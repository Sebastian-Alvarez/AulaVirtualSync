#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
moodle_connector.py - Robust Moodle connector for any Moodle instance

Authenticates via Microsoft OAuth2/MFA, fetches courses/grades/assignments/
announcements/materials, caches aggressively, and outputs structured Markdown.

Usage (CLI):
    python moodle_connector.py login
    python moodle_connector.py courses
    python moodle_connector.py grades
    python moodle_connector.py assignments
    python moodle_connector.py announcements
    python moodle_connector.py materials [--course-id ID]
    python moodle_connector.py download <url> [--output path]
    python moodle_connector.py summary          # Full markdown summary
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode, urljoin

import requests
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("moodle_connector")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "config.json"
CREDENTIALS_FILE = SCRIPT_DIR / "credentials.enc"
CACHE_DIR = SCRIPT_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Credential encryption helpers
# ---------------------------------------------------------------------------

def _derive_key(password: str, salt: bytes) -> bytes:
    """Derive a Fernet key from a password + salt via PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


def encrypt_credentials(data: dict, password: str) -> bytes:
    """Encrypt a dict to bytes using a password-derived key."""
    salt = os.urandom(16)
    key = _derive_key(password, salt)
    f = Fernet(key)
    payload = json.dumps(data).encode()
    return salt + f.encrypt(payload)


def decrypt_credentials(raw: bytes, password: str) -> dict:
    """Decrypt bytes back to a dict."""
    salt, token = raw[:16], raw[16:]
    key = _derive_key(password, salt)
    f = Fernet(key)
    return json.loads(f.decrypt(token).decode())


# ---------------------------------------------------------------------------
# Simple disk cache
# ---------------------------------------------------------------------------

class DiskCache:
    """Key-value cache backed by JSON files on disk."""

    def __init__(self, directory: Path, default_ttl: int = 300):
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self.default_ttl = default_ttl

    def _path(self, key: str) -> Path:
        safe = hashlib.sha256(key.encode()).hexdigest()
        return self.dir / f"{safe}.json"

    def get(self, key: str) -> Optional[Any]:
        p = self._path(key)
        if not p.exists():
            return None
        try:
            entry = json.loads(p.read_text(encoding="utf-8"))
            if time.time() < entry["expires"]:
                return entry["value"]
            p.unlink(missing_ok=True)
        except Exception:
            pass
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        p = self._path(key)
        entry = {"expires": time.time() + (ttl or self.default_ttl), "value": value}
        p.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")

    def invalidate(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Moodle authentication (browser-based SSO via Mobile Launch Flow)
# ---------------------------------------------------------------------------

class MicrosoftAuthenticator:
    """
    Handles Moodle authentication via SSO.

    Strategy:
    1. Stored username/password, if any (direct Moodle login).
    2. Interactive browser login (Playwright) via Moodle's Mobile Launch Flow —
       works with any SSO provider (Microsoft, Google, SAML, ...), not just Microsoft.
    3. Manual token entry fallback.
    """

    def __init__(self, config: dict, cred_file: Path, password: str):
        self.config = config
        self.cred_file = cred_file
        self.password = password
        self._token: Optional[str] = None
        self._moodle_token: Optional[str] = None

    # ------------------------------------------------------------------
    # Credential persistence
    # ------------------------------------------------------------------

    def _load_credentials(self) -> dict:
        if self.cred_file.exists():
            try:
                raw = self.cred_file.read_bytes()
                return decrypt_credentials(raw, self.password)
            except Exception as exc:
                log.warning("Could not decrypt credentials: %s", exc)
        return {}

    def _save_credentials(self, data: dict) -> None:
        raw = encrypt_credentials(data, self.password)
        self.cred_file.write_bytes(raw)
        log.debug("Credentials saved to %s", self.cred_file)

    # ------------------------------------------------------------------
    # Token acquisition
    # ------------------------------------------------------------------

    def _is_token_valid(self, base_url: str, token: str) -> bool:
        """Check with the server whether a token is still accepted."""
        url = f"{base_url.rstrip('/')}/webservice/rest/server.php"
        try:
            resp = requests.post(url, data={
                "wstoken": token,
                "wsfunction": "core_webservice_get_site_info",
                "moodlewsrestformat": "json",
            }, timeout=10)
            data = resp.json()
            return "sitename" in data
        except Exception:
            return False

    def get_moodle_token(self, base_url: str) -> str:
        """Return a valid Moodle web-service token, refreshing if needed."""
        # First, check if token is in config
        if hasattr(self, 'config') and self.config.get("moodle", {}).get("token"):
            token = self.config["moodle"]["token"]
            if token:
                log.debug("Using Moodle token from config.")
                return token

        creds = self._load_credentials()
        token = creds.get("moodle_token")

        if token:
            if self._is_token_valid(base_url, token):
                log.debug("Cached Moodle token validated by server.")
                return token
            log.info("Moodle token rejected by server — re-authenticating...")

        # Need to (re)authenticate
        token = self._authenticate_moodle(base_url, creds)
        creds["moodle_token"] = token
        self._save_credentials(creds)
        return token

    def _authenticate_moodle(self, base_url: str, creds: dict) -> str:
        """
        Attempt Moodle authentication via multiple strategies:
        1. Existing username/password stored in encrypted creds
        2. Interactive browser login (Playwright) for Microsoft SSO/MFA
        3. Manual token entry fallback
        """
        # Strategy 1: Try username/password if stored (Moodle local login)
        username = creds.get("username")
        password = creds.get("password")
        if username and password:
            token = self._try_moodle_login_token(base_url, username, password)
            if token:
                log.info("Authenticated via stored credentials.")
                return token

        # Strategy 2: Interactive browser SSO (Microsoft MFA)
        log.info("Attempting browser-based Microsoft SSO login...")
        try:
            token = self._playwright_sso_login(base_url, creds)
            if token:
                return token
        except ImportError:
            log.warning("Playwright not installed — skipping browser login.")
        except Exception as exc:
            log.warning("Browser login failed: %s", exc)

        # Strategy 3: Manual fallback
        return self._manual_token_entry(base_url, creds)

    def _try_moodle_login_token(self, base_url: str, username: str, password: str) -> Optional[str]:
        """Try Moodle's /login/token.php endpoint (works for local accounts)."""
        url = f"{base_url.rstrip('/')}/login/token.php"
        try:
            resp = requests.post(url, data={
                "username": username,
                "password": password,
                "service": "moodle_mobile_app",
            }, timeout=30)
            data = resp.json()
            if "token" in data:
                return data["token"]
            log.warning("Token login failed: %s", data.get("error", "unknown"))
        except Exception as exc:
            log.warning("Token login request failed: %s", exc)
        return None

    def _playwright_sso_login(self, base_url: str, creds: dict) -> Optional[str]:
        """
        Obtain a Moodle web-service token via the Mobile Launch Flow.

        This is the same flow used by the official Moodle mobile app and works
        with any SSO provider (Microsoft, Google, SAML, etc.).

        Flow:
        1. Navigate to /admin/tool/mobile/launch.php — Moodle redirects to SSO
           if no session exists, or immediately to moodlemobile:// if already
           logged in.
        2. The user completes SSO + MFA interactively in the browser window.
        3. Moodle issues an HTTP 302 to moodlemobile://token=<base64>.
        4. We intercept that redirect (before the browser fails on the unknown
           scheme), decode the base64 payload and extract the ws token.

        Token payload format: SITE_ID:::WS_TOKEN[:::PRIVATE_TOKEN]
        """
        import base64 as _base64
        from playwright.sync_api import sync_playwright

        base_url = base_url.rstrip("/")
        passport = str(int(time.time()))
        launch_url = (
            f"{base_url}/admin/tool/mobile/launch.php"
            f"?service=moodle_mobile_app&passport={passport}&urlscheme=moodlemobile"
        )

        token: Optional[str] = None

        def _extract_from_location(location: str) -> Optional[str]:
            """Decode the base64 payload from a moodlemobile:// redirect URL."""
            if not location.startswith("moodlemobile://token="):
                return None
            try:
                b64 = location.split("token=", 1)[1]
                # Add padding if needed
                b64 += "=" * (-len(b64) % 4)
                decoded = _base64.b64decode(b64).decode("utf-8")
                parts = decoded.split(":::")
                if len(parts) >= 2:
                    return parts[1]
            except Exception as exc:
                log.warning("Failed to decode mobile launch token: %s", exc)
            return None

        # Detect headless environments (no display available).
        # In that case the interactive browser cannot be shown; the caller will
        # fall through to _manual_token_entry which explains what to do.
        headless_env = not sys.stdin.isatty() or os.environ.get("DISPLAY") == "" or (
            sys.platform != "win32"
            and sys.platform != "darwin"
            and not os.environ.get("DISPLAY")
            and not os.environ.get("WAYLAND_DISPLAY")
        )
        if headless_env:
            log.warning(
                "No display detected — cannot open browser for SSO login. "
                "Run 'python moodle_connector.py login' on a machine with a display "
                "to cache the token, or set 'token' in config.json manually."
            )
            return None

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            ctx = browser.new_context()
            page = ctx.new_page()

            # Strategy A: HTTP 302 — intercept Location header in the response.
            def _on_response(response) -> None:
                nonlocal token
                if token:
                    return
                location = response.headers.get("location", "")
                extracted = _extract_from_location(location)
                if extracted:
                    token = extracted
                    log.debug("Token captured via HTTP 302 Location header.")

            page.on("response", _on_response)

            # Strategy B: JS/meta redirect — inject a script on every page load
            # that intercepts window.location assignments and open() calls before
            # the browser tries (and fails) to open the moodlemobile:// scheme.
            page.add_init_script("""
                (function () {
                    function _capture(url) {
                        if (url && url.indexOf('moodlemobile://token=') === 0) {
                            window.__moodleTokenUrl = url;
                        }
                    }
                    // Override window.location.href setter
                    try {
                        const desc = Object.getOwnPropertyDescriptor(Location.prototype, 'href');
                        Object.defineProperty(Location.prototype, 'href', {
                            set: function (url) { _capture(url); desc.set.call(this, url); },
                            get: desc.get,
                            configurable: true,
                        });
                    } catch (e) {}
                    // Override window.location.replace / assign
                    const _replace = Location.prototype.replace;
                    Location.prototype.replace = function (url) { _capture(url); return _replace.call(this, url); };
                    const _assign = Location.prototype.assign;
                    Location.prototype.assign = function (url) { _capture(url); return _assign.call(this, url); };
                    // Override window.open
                    const _open = window.open;
                    window.open = function (url) { _capture(url); return _open.apply(this, arguments); };
                })();
            """)

            log.info(
                "Browser opened — complete Microsoft SSO / MFA in the window. "
                "The window will close automatically once the token is captured."
            )

            # Pre-fill username when the Microsoft login page loads
            username = creds.get("username") or creds.get("email", "")

            def _prefill_username(frame) -> None:
                if "login.microsoftonline.com" not in frame.url or not username:
                    return
                try:
                    frame.fill(
                        'input[type="email"], input[name="loginfmt"]',
                        username,
                        timeout=3000,
                    )
                    frame.press(
                        'input[type="email"], input[name="loginfmt"]',
                        "Enter",
                        timeout=3000,
                    )
                except Exception:
                    pass

            page.on("framenavigated", _prefill_username)

            try:
                page.goto(launch_url, wait_until="commit", timeout=10_000)
            except Exception:
                pass  # Expected if browser immediately hits moodlemobile://

            # Poll until token is captured or 3-minute timeout is reached.
            # Each iteration:
            # 1. Checks the JS-injected window.__moodleTokenUrl (client-side redirects).
            # 2. Tracks whether the browser visited the SSO provider, then detects
            #    when it returns to Moodle and re-triggers launch.php so Moodle issues
            #    the moodlemobile:// redirect with the token.
            deadline = time.time() + 180
            _saw_sso = False
            _relaunched = False
            while not token and time.time() < deadline:
                page.wait_for_timeout(1_000)
                if token:
                    break

                try:
                    js_url = page.evaluate("window.__moodleTokenUrl || ''")
                    if js_url:
                        token = _extract_from_location(js_url)
                        if token:
                            log.debug("Token captured via JS redirect interception.")
                            break
                except Exception:
                    pass

                if not _relaunched:
                    try:
                        current = page.url
                        log.debug("Polling URL: %s", current)
                        on_sso = any(h in current for h in (
                            "microsoftonline.com", "login.live.com", "login.microsoft.com"
                        ))
                        if on_sso:
                            _saw_sso = True

                        # Only relaunch after we have confirmed the SSO page was visited,
                        # meaning the user has actually gone through (or is finishing) login.
                        if _saw_sso and not on_sso:
                            on_moodle = base_url in current
                            on_launch = "launch.php" in current
                            if on_moodle and not on_launch:
                                log.info("SSO complete — re-triggering launch.php via JS navigation.")
                                _relaunched = True
                                page.evaluate(f"window.location.href = '{launch_url}'")
                    except Exception as exc:
                        log.debug("Relaunch check error: %s", exc)

            browser.close()

        if token:
            log.info("Mobile launch flow succeeded — token captured.")
        return token

    def _manual_token_entry(self, base_url: str, creds: dict) -> str:
        """
        Fallback: instruct the user to get their token manually.
        For automated agents, this will raise an error.
        """
        print("\n" + "="*60)
        print("MANUAL AUTHENTICATION REQUIRED")
        print("="*60)
        print("Please obtain your Moodle web-service token:")
        print(f"1. Log in to {base_url}")
        print("2. Go to: User menu → Preferences → Security keys")
        print("   OR navigate to: /user/managetoken.php")
        print("3. Copy your Mobile App token")
        print("="*60)

        if sys.stdin.isatty():
            token = input("Paste token here: ").strip()
            if token:
                return token

        raise RuntimeError(
            "No token available and cannot authenticate interactively.\n"
            "Options:\n"
            "  1. Run 'python moodle_connector.py login' on a machine with a display "
            "to cache the token in credentials.enc, then copy it to this environment.\n"
            "  2. Set 'token' in config.json with a valid token."
        )

    def store_credentials(self, username: str = "", password: str = "", email: str = "") -> None:
        """Store (encrypted) username/password for future logins."""
        creds = self._load_credentials()
        if username:
            creds["username"] = username
        if password:
            creds["password"] = password
        if email:
            creds["email"] = email
        self._save_credentials(creds)


# ---------------------------------------------------------------------------
# Moodle REST API client
# ---------------------------------------------------------------------------

class MoodleAPI:
    """
    Thin wrapper around Moodle's External Functions (REST) API.
    All responses are cached; cache is invalidated selectively.
    """

    def __init__(self, base_url: str, token: str, cache: DiskCache):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.cache = cache
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "MoodleConnector/1.0"

    def _ws(self, function: str, params: Optional[dict] = None, ttl: Optional[int] = None) -> Any:
        """Call a Moodle web-service function, with caching."""
        params = params or {}
        cache_key = f"ws:{function}:{json.dumps(params, sort_keys=True)}"

        cached = self.cache.get(cache_key)
        if cached is not None:
            log.debug("Cache hit: %s", function)
            return cached

        url = f"{self.base_url}/webservice/rest/server.php"
        payload = {
            "wstoken": self.token,
            "moodlewsrestformat": "json",
            "wsfunction": function,
            **params,
        }

        log.debug("API call: %s", function)
        try:
            resp = self.session.post(url, data=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"Moodle API request failed: {exc}") from exc

        if isinstance(data, dict) and "exception" in data:
            raise RuntimeError(f"Moodle API error [{function}]: {data.get('message', data)}")

        self.cache.set(cache_key, data, ttl=ttl)
        return data

    # ------------------------------------------------------------------
    # Site info
    # ------------------------------------------------------------------

    def get_site_info(self) -> dict:
        return self._ws("core_webservice_get_site_info", ttl=3600)

    # ------------------------------------------------------------------
    # Courses
    # ------------------------------------------------------------------

    def get_enrolled_courses(self) -> list[dict]:
        info = self.get_site_info()
        user_id = info["userid"]
        return self._ws(
            "core_enrol_get_users_courses",
            {"userid": user_id},
            ttl=300,
        )

    def get_course_contents(self, course_id: int) -> list[dict]:
        return self._ws(
            "core_course_get_contents",
            {"courseid": course_id},
            ttl=600,
        )

    # ------------------------------------------------------------------
    # Grades
    # ------------------------------------------------------------------

    def get_grades(self, course_id: int) -> dict:
        info = self.get_site_info()
        return self._ws(
            "gradereport_user_get_grade_items",
            {"courseid": course_id, "userid": info["userid"]},
            ttl=300,
        )

    def get_grades_overview(self) -> list[dict]:
        info = self.get_site_info()
        return self._ws(
            "gradereport_overview_get_course_grades",
            {"userid": info["userid"]},
            ttl=300,
        )

    # ------------------------------------------------------------------
    # Assignments
    # ------------------------------------------------------------------

    def get_assignments(self, course_ids: Optional[list[int]] = None) -> dict:
        params: dict = {}
        if course_ids:
            for i, cid in enumerate(course_ids):
                params[f"courseids[{i}]"] = cid
        return self._ws("mod_assign_get_assignments", params, ttl=300)

    def get_submission_status(self, assignment_id: int) -> dict:
        return self._ws(
            "mod_assign_get_submission_status",
            {"assignid": assignment_id},
            ttl=120,
        )

    # ------------------------------------------------------------------
    # Forums / Announcements
    # ------------------------------------------------------------------

    def get_forums_by_course(self, course_id: int) -> list[dict]:
        return self._ws(
            "mod_forum_get_forums_by_courses",
            {"courseids[0]": course_id},
            ttl=300,
        )

    def get_forum_discussions(self, forum_id: int, page: int = 0, per_page: int = 10) -> dict:
        return self._ws(
            "mod_forum_get_forum_discussions",
            {"forumid": forum_id, "page": page, "perpage": per_page},
            ttl=300,
        )

    def get_discussion_posts(self, discussion_id: int) -> dict:
        return self._ws(
            "mod_forum_get_discussion_posts",
            {"discussionid": discussion_id},
            ttl=300,
        )

    # ------------------------------------------------------------------
    # Calendar / Events
    # ------------------------------------------------------------------

    def get_calendar_events(self, course_ids: Optional[list[int]] = None) -> dict:
        now = int(time.time())
        params: dict = {
            "events[timestart]": now,
            "options[userevents]": 1,
            "options[siteevents]": 0,
        }
        if course_ids:
            for i, cid in enumerate(course_ids):
                params[f"events[courseids][{i}]"] = cid
        return self._ws("core_calendar_get_calendar_events", params, ttl=300)

    # ------------------------------------------------------------------
    # File download with caching
    # ------------------------------------------------------------------

    def download_file(self, file_url: str, dest: Optional[Path] = None) -> Path:
        """
        Download a Moodle file (PDF, doc, etc.) with local caching.
        Returns the local path.
        """
        # Build a stable filename from the URL
        url_hash = hashlib.sha256(file_url.encode()).hexdigest()[:16]
        # Try to get a meaningful name from the URL
        url_name = file_url.split("/")[-1].split("?")[0] or "file"
        filename = f"{url_hash}_{url_name}"
        if dest is None:
            dest = CACHE_DIR / "files" / filename
        dest.parent.mkdir(parents=True, exist_ok=True)

        if dest.exists():
            log.debug("File already cached: %s", dest)
            return dest

        # Append token if not already present
        sep = "&" if "?" in file_url else "?"
        url_with_token = f"{file_url}{sep}token={self.token}"

        log.debug("Downloading: %s → %s", file_url, dest.name)
        try:
            with self.session.get(url_with_token, stream=True, timeout=60) as r:
                r.raise_for_status()
                with dest.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        f.write(chunk)
        except requests.RequestException as exc:
            raise RuntimeError(f"File download failed: {exc}") from exc

        return dest


# ---------------------------------------------------------------------------
# Markdown formatters
# ---------------------------------------------------------------------------

def _ts(unix: Optional[int]) -> str:
    if not unix:
        return "No deadline"
    dt = datetime.fromtimestamp(unix, tz=timezone.utc).astimezone()
    return dt.strftime("%a %d %b %Y %H:%M")


def fmt_courses(courses: list[dict]) -> str:
    if not courses:
        return "_No enrolled courses found._"
    lines = ["# Enrolled Courses\n"]
    for c in courses:
        prog = c.get("progress", None)
        prog_str = f" — {prog:.0f}% complete" if prog is not None else ""
        lines.append(f"## {c['fullname']}{prog_str}")
        lines.append(f"- **ID:** {c['id']}")
        lines.append(f"- **Short name:** {c.get('shortname', '')}")
        if c.get("enddate"):
            lines.append(f"- **End date:** {_ts(c['enddate'])}")
        lines.append("")
    return "\n".join(lines)


def fmt_grades(grades_overview: list[dict], courses: list[dict]) -> str:
    course_map = {c["id"]: c["fullname"] for c in courses}
    if not grades_overview:
        return "_No grade data available._"
    lines = ["# Grades Overview\n"]
    for item in grades_overview:
        cid = item.get("courseid")
        name = course_map.get(cid, f"Course {cid}")
        grade = item.get("grade", "N/A")
        lines.append(f"- **{name}:** {grade}")
    return "\n".join(lines)


def fmt_course_grades(course_name: str, grade_items: list[dict]) -> str:
    lines = [f"# Grades — {course_name}\n"]
    for item in grade_items:
        name = item.get("itemname") or item.get("itemmodule", "Unknown")
        grade = item.get("gradeformatted", item.get("graderaw", "N/A"))
        max_grade = item.get("grademax", "")
        feedback = item.get("feedback", "")
        line = f"- **{name}:** {grade}"
        if max_grade:
            line += f" / {max_grade}"
        if feedback:
            line += f"  _{feedback}_"
        lines.append(line)
    return "\n".join(lines)


def fmt_assignments(courses_assignments: dict) -> str:
    lines = ["# Assignments & Deadlines\n"]
    now = time.time()
    all_assignments = []

    for course_data in courses_assignments.get("courses", []):
        course_name = course_data.get("fullname", f"Course {course_data.get('id')}")
        for a in course_data.get("assignments", []):
            all_assignments.append((course_name, a))

    # Sort by due date
    all_assignments.sort(key=lambda x: x[1].get("duedate") or 0)

    if not all_assignments:
        return "_No assignments found._"

    for course_name, a in all_assignments:
        due = a.get("duedate", 0)
        overdue = due and due < now
        status = " ⚠️ OVERDUE" if overdue else (" 🕐 UPCOMING" if due else "")
        lines.append(f"## {a['name']}{status}")
        lines.append(f"- **Course:** {course_name}")
        lines.append(f"- **Due:** {_ts(due)}")
        if a.get("allowsubmissionsfromdate"):
            lines.append(f"- **Opens:** {_ts(a['allowsubmissionsfromdate'])}")
        if a.get("cutoffdate"):
            lines.append(f"- **Cutoff:** {_ts(a['cutoffdate'])}")
        if a.get("intro"):
            # Strip HTML tags simply
            import re
            intro = re.sub(r"<[^>]+>", "", a["intro"]).strip()
            if intro:
                lines.append(f"- **Description:** {intro[:300]}")
        lines.append("")
    return "\n".join(lines)


def fmt_announcements(forums_data: list[tuple[str, list[dict]]]) -> str:
    lines = ["# Announcements\n"]
    if not forums_data:
        return "_No announcements found._"
    for course_name, discussions in forums_data:
        if not discussions:
            continue
        lines.append(f"## {course_name}")
        for d in discussions[:5]:  # limit per course
            lines.append(f"### {d.get('name', 'Untitled')}")
            lines.append(f"- **Posted:** {_ts(d.get('timemodified'))}")
            lines.append(f"- **By:** {d.get('userfullname', 'Unknown')}")
            msg = d.get("message", "")
            if msg:
                import re
                msg = re.sub(r"<[^>]+>", "", msg).strip()
                lines.append(f"\n{msg[:500]}")
            lines.append("")
    return "\n".join(lines)


def fmt_materials(course_name: str, contents: list[dict]) -> str:
    lines = [f"# Materials — {course_name}\n"]
    for section in contents:
        section_name = section.get("name", "Unnamed section")
        modules = section.get("modules", [])
        if not modules:
            continue
        lines.append(f"## {section_name}")
        for mod in modules:
            mod_name = mod.get("name", "Unknown")
            mod_type = mod.get("modname", "")
            lines.append(f"### {mod_name} `[{mod_type}]`")
            for f_item in mod.get("contents", []):
                fname = f_item.get("filename", "")
                furl = f_item.get("fileurl", "")
                fsize = f_item.get("filesize", 0)
                size_str = f" ({fsize // 1024} KB)" if fsize else ""
                if furl:
                    lines.append(f"- [{fname}{size_str}]({furl})")
            lines.append("")
    return "\n".join(lines)


def fmt_deadlines(events: list[dict]) -> str:
    lines = ["# Upcoming Deadlines (Calendar)\n"]
    if not events:
        return "_No upcoming deadlines found._"
    events_sorted = sorted(events, key=lambda e: e.get("timestart", 0))
    for ev in events_sorted[:20]:
        lines.append(f"- **{ev.get('name', 'Event')}** — {_ts(ev.get('timestart'))}")
        if ev.get("course"):
            lines.append(f"  Course: {ev['course'].get('fullname', '')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MoodleConnector — main facade
# ---------------------------------------------------------------------------

class MoodleConnector:
    """
    High-level facade combining authentication, API, caching, and formatting.
    """

    def __init__(self, config_path: Path = CONFIG_FILE, password: Optional[str] = None):
        self.config = self._load_config(config_path)
        self.base_url = self.config["moodle"]["url"]
        self.password = password or self._load_stored_password() or self._prompt_password()
        self.cache = DiskCache(CACHE_DIR / "api")

        self.auth = MicrosoftAuthenticator(
            config=self.config,
            cred_file=CREDENTIALS_FILE,
            password=self.password,
        )
        self._api: Optional[MoodleAPI] = None

    def _load_config(self, path: Path) -> dict:
        if not path.exists():
            raise FileNotFoundError(
                f"Config file not found: {path}\n"
                "Edit config.json (see the README's 'Primeros pasos' section)."
            )
        with path.open(encoding="utf-8") as f:
            return json.load(f)

    _KEYRING_SERVICE = "moodle-connector"
    _KEYRING_USERNAME = "credentials-password"

    def _prompt_password(self) -> str:
        """Prompt for encryption password (hidden input)."""
        import getpass
        password = getpass.getpass("Encryption password (protects stored credentials): ")
        self._remember_password(password)
        return password

    def _load_stored_password(self) -> Optional[str]:
        """
        Best-effort: look up a previously-saved password in the OS's native
        credential store (Windows Credential Manager / macOS Keychain /
        Linux Secret Service via the 'keyring' package). Returns None if
        unavailable or nothing is stored — never raises.
        """
        try:
            import keyring
            return keyring.get_password(self._KEYRING_SERVICE, self._KEYRING_USERNAME)
        except Exception:
            return None

    def _remember_password(self, password: str) -> None:
        """
        Best-effort: save the password in the OS's native credential store
        (encrypted at rest, tied to your login — not a plaintext file or env
        var) so future runs find it via _load_stored_password() and never
        prompt again. Silently does nothing if that's not possible.
        """
        try:
            import keyring
            keyring.set_password(self._KEYRING_SERVICE, self._KEYRING_USERNAME, password)
        except Exception:
            pass

    @property
    def api(self) -> MoodleAPI:
        if self._api is None:
            token = self.auth.get_moodle_token(self.base_url)
            self._api = MoodleAPI(self.base_url, token, self.cache)
        return self._api

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def login(self, username: str = "", password: str = "") -> str:
        """Authenticate and store credentials. Returns markdown status."""
        if username or password:
            self.auth.store_credentials(username=username, password=password)
        token = self.auth.get_moodle_token(self.base_url)
        info = MoodleAPI(self.base_url, token, self.cache).get_site_info()
        return (
            f"# ✅ Authentication Successful\n\n"
            f"- **User:** {info.get('fullname', 'Unknown')}\n"
            f"- **Site:** {info.get('sitename', self.base_url)}\n"
            f"- **Moodle version:** {info.get('release', 'N/A')}\n"
        )

    def courses(self) -> str:
        return fmt_courses(self.api.get_enrolled_courses())

    def grades(self, course_id: Optional[int] = None) -> str:
        if course_id:
            courses = self.api.get_enrolled_courses()
            name = next((c["fullname"] for c in courses if c["id"] == course_id), f"Course {course_id}")
            data = self.api.get_grades(course_id)
            items = data.get("usergrades", [{}])[0].get("gradeitems", [])
            return fmt_course_grades(name, items)
        courses = self.api.get_enrolled_courses()
        overview_data = self.api.get_grades_overview()
        # Extract grades list from the dict response
        grades_list = overview_data.get("grades", []) if isinstance(overview_data, dict) else overview_data
        return fmt_grades(grades_list, courses)

    def assignments(self, course_id: Optional[int] = None) -> str:
        courses = self.api.get_enrolled_courses()
        ids = [course_id] if course_id else [c["id"] for c in courses]
        data = self.api.get_assignments(ids)
        return fmt_assignments(data)

    def announcements(self, course_id: Optional[int] = None) -> str:
        courses = self.api.get_enrolled_courses()
        if course_id:
            courses = [c for c in courses if c["id"] == course_id]

        results: list[tuple[str, list[dict]]] = []
        for c in courses:
            forums = self.api.get_forums_by_course(c["id"])
            # Only news/announcements forums
            for forum in forums:
                if forum.get("type") in ("news", "announcements"):
                    disc_data = self.api.get_forum_discussions(forum["id"])
                    discussions = disc_data.get("discussions", [])
                    if discussions:
                        results.append((c["fullname"], discussions))
        return fmt_announcements(results)

    def materials(self, course_id: Optional[int] = None) -> str:
        courses = self.api.get_enrolled_courses()
        if course_id:
            courses = [c for c in courses if c["id"] == course_id]

        parts: list[str] = []
        for c in courses:
            contents = self.api.get_course_contents(c["id"])
            parts.append(fmt_materials(c["fullname"], contents))
        return "\n\n---\n\n".join(parts) if parts else "_No materials found._"

    def deadlines(self, course_id: Optional[int] = None) -> str:
        courses = self.api.get_enrolled_courses()
        ids = [course_id] if course_id else [c["id"] for c in courses]
        data = self.api.get_calendar_events(ids)
        return fmt_deadlines(data.get("events", []))

    def download(self, url: str, output: Optional[str] = None) -> str:
        dest = Path(output) if output else None
        path = self.api.download_file(url, dest)
        return f"# ✅ Downloaded\n\n- **File:** `{path}`\n- **Size:** {path.stat().st_size // 1024} KB\n"

    def summary(self) -> str:
        """Full markdown dump of all data for AI consumption."""
        parts: list[str] = []

        try:
            parts.append(self.courses())
        except Exception as e:
            parts.append(f"_Error fetching courses: {e}_")

        try:
            parts.append(self.grades())
        except Exception as e:
            parts.append(f"_Error fetching grades: {e}_")

        try:
            parts.append(self.assignments())
        except Exception as e:
            parts.append(f"_Error fetching assignments: {e}_")

        try:
            parts.append(self.deadlines())
        except Exception as e:
            parts.append(f"_Error fetching deadlines: {e}_")

        try:
            parts.append(self.announcements())
        except Exception as e:
            parts.append(f"_Error fetching announcements: {e}_")

        return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Moodle connector — configure base_url in config.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--config", default=str(CONFIG_FILE), help="Path to config.json")
    p.add_argument("--password", default=None, help="Encryption password (or set MOODLE_CRED_PASSWORD env var)")
    p.add_argument("--course-id", type=int, default=None, help="Filter by course ID")

    sub = p.add_subparsers(dest="command", required=True)

    login_p = sub.add_parser("login", help="Authenticate and store credentials")
    login_p.add_argument("--username", default="", help="Moodle/Microsoft username or email")
    login_p.add_argument("--user-password", default="", help="Password (stored encrypted)")

    sub.add_parser("courses", help="List enrolled courses")
    sub.add_parser("grades", help="Show grades (all courses or --course-id)")
    sub.add_parser("assignments", help="List assignments with deadlines")
    sub.add_parser("announcements", help="Show course announcements")
    sub.add_parser("materials", help="List course materials/files")
    sub.add_parser("deadlines", help="Upcoming deadlines from calendar")

    dl_p = sub.add_parser("download", help="Download a file by URL")
    dl_p.add_argument("url", help="File URL")
    dl_p.add_argument("--output", default=None, help="Output path")

    sub.add_parser("summary", help="Full markdown summary (all data)")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    password = (
        args.password
        or os.environ.get("MOODLE_CRED_PASSWORD")
        or None
    )

    connector = MoodleConnector(
        config_path=Path(args.config),
        password=password,
    )

    cmd = args.command
    course_id = getattr(args, "course_id", None)

    if cmd == "login":
        result = connector.login(
            username=getattr(args, "username", ""),
            password=getattr(args, "user_password", ""),
        )
    elif cmd == "courses":
        result = connector.courses()
    elif cmd == "grades":
        result = connector.grades(course_id)
    elif cmd == "assignments":
        result = connector.assignments(course_id)
    elif cmd == "announcements":
        result = connector.announcements(course_id)
    elif cmd == "materials":
        result = connector.materials(course_id)
    elif cmd == "deadlines":
        result = connector.deadlines(course_id)
    elif cmd == "download":
        result = connector.download(args.url, getattr(args, "output", None))
    elif cmd == "summary":
        result = connector.summary()
    else:
        result = f"Unknown command: {cmd}"

    print(result)


if __name__ == "__main__":
    main()
