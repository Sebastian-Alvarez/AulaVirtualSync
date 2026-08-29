#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auto-discovery course sync: mirrors new Moodle course files to a local folder.

Asks Moodle for the contents of every enrolled course and figures out what's
downloadable on its own — no manual file list to maintain. Run it again any
time — files that already exist locally are skipped.

Usage:
    python course_sync.py                  # sync every enrolled course
    python course_sync.py --dry-run        # preview what would be synced
    python course_sync.py --course hd      # sync only one course (by folder key)
    python course_sync.py --list-courses   # show detected courses and exit
    python course_sync.py --password mypass
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import logging
import os
import re
import sys
import io
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import requests

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

from moodle_connector import MoodleConnector

log = logging.getLogger("course_sync")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "config.json"

# Characters not allowed in Windows/OneDrive paths.
_INVALID_CHARS = r'\/:*?"<>|'

# Domains that are (almost) never directly downloadable — always saved as a
# .url shortcut instead of probed with a HEAD request. Extend via
# descargas.dominios_acceso_directo in config.json.
_DEFAULT_SHORTCUT_DOMAINS = (
    "sharepoint.com",
    "onedrive.live.com",
    "drive.google.com",
    "docs.google.com",
    "forms.gle",
    "youtube.com",
    "youtu.be",
    "github.com",
    "gitlab.com",
    "notion.so",
    "figma.com",
    "miro.com",
    "canva.com",
    "trello.com",
)

_DOWNLOADABLE_MIME_PREFIXES = (
    "application/", "image/", "audio/", "video/",
    "text/plain", "text/csv", "text/xml",
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_app_config() -> dict:
    if not CONFIG_FILE.exists():
        print("ERROR: config.json not found. See the README's 'Primeros pasos' section.")
        sys.exit(1)
    with CONFIG_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def resolve_base_dir(cfg: dict) -> Path:
    """
    Resolve the local download root from config.json's descargas.directorio_descargas.
    Supports Windows env-var expansion (%OneDrive%, %OneDriveCommercial%, ...)
    if you set base_dir yourself. Falls back to ./downloads if base_dir is
    empty or its env var can't be resolved.
    """
    base_dir = cfg.get("descargas", {}).get("directorio_descargas", "")
    if base_dir:
        expanded = Path(os.path.expandvars(base_dir))
        if "%" not in str(expanded) and "$" not in str(expanded):
            return expanded
        print(f"Warning: unresolved environment variable in base_dir: {base_dir!r}")

    print("Using local './downloads'.")
    return SCRIPT_DIR / "downloads"


def build_course_map(cfg: dict) -> list[tuple[list[str], str]]:
    """
    Builds the course map from descargas.carpetas_por_curso in config.json.
    Returns a list of ([keywords], folder), grouping keywords that map to
    the same folder.
    """
    course_folders: dict = cfg.get("descargas", {}).get("carpetas_por_curso", {})
    grouped: dict[str, list[str]] = {}
    for keyword, folder in course_folders.items():
        if keyword.startswith("_"):
            continue
        grouped.setdefault(folder, []).append(keyword)
    return [(keywords, folder) for folder, keywords in grouped.items()]


def semester_code(semester: str) -> str:
    """'2026-1' -> '202601'. Falls back to stripping dashes for other formats."""
    try:
        year, num = semester.split("-")
        return f"{year}{num.zfill(2)}"
    except ValueError:
        return semester.replace("-", "")


def match_course(course_name: str, course_map: list, code: str | None) -> str | None:
    """
    Returns the local folder name for a course, or None to skip it.

    If `code` is set (descargas.semestre is configured), only courses whose
    name contains a matching 6-digit semester code (e.g. "202602") are
    synced — this matches the naming convention some Moodle instances use
    for course codes. If `code` is None, every enrolled course is synced.
    """
    upper = course_name.upper()

    if code is not None:
        found_codes = re.findall(r'\b(20\d{4})\b', upper)
        if not found_codes or code not in found_codes:
            return None

    for keywords, folder in course_map:
        if any(kw.upper() in upper for kw in keywords):
            return folder

    return sanitize(course_name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanitize(name: str) -> str:
    """Strips characters that aren't allowed in Windows/OneDrive paths."""
    for ch in _INVALID_CHARS:
        name = name.replace(ch, "_")
    return name.strip(" .")


def shortcut_domains(cfg: dict) -> tuple[str, ...]:
    extra = cfg.get("descargas", {}).get("dominios_acceso_directo", [])
    return _DEFAULT_SHORTCUT_DOMAINS + tuple(extra)


def is_shortcut_domain(url: str, domains: tuple[str, ...]) -> bool:
    """True if the URL's host is a domain that's always saved as a shortcut."""
    try:
        host = urlparse(url).hostname or ""
        return any(host == d or host.endswith("." + d) for d in domains)
    except Exception:
        return False


def is_direct_download(url: str) -> bool:
    """
    HEAD-requests a URL to guess whether it points at a downloadable file.
    Only called for domains not in the shortcut-domains list.
    """
    try:
        resp = requests.head(url, allow_redirects=True, timeout=8)
        content_type = resp.headers.get("Content-Type", "")
        if content_type.startswith("text/html") or not content_type:
            return False
        return any(content_type.startswith(p) for p in _DOWNLOADABLE_MIME_PREFIXES)
    except Exception:
        return False


def fmt_size(size_bytes: int) -> str:
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / 1024 ** 3:.1f} GB"
    elif size_bytes >= 1024 ** 2:
        return f"{size_bytes / 1024 ** 2:.1f} MB"
    else:
        return f"{size_bytes // 1024} KB"


def _is_ignored(filename: str, patterns: list[str]) -> bool:
    name = unicodedata.normalize("NFC", filename).lower()
    return any(fnmatch.fnmatch(name, unicodedata.normalize("NFC", p).lower()) for p in patterns)


def save_url_shortcut(dest: Path, url: str) -> None:
    """Writes a Windows .url shortcut that opens the link in a browser."""
    dest.write_text(f"[InternetShortcut]\nURL={url}\n", encoding="utf-8")


def get_course_files(connector: MoodleConnector, course_id: int, ignore_patterns: list[str] | None = None) -> list[dict]:
    """
    Returns a flat list of resources for a course.
    Each entry: {section, filename, url, kind}
      kind = "file" -> direct Moodle file (download with the auth token)
      kind = "link" -> external link (probe if downloadable, else shortcut)
    """
    files: list[dict] = []
    patterns = ignore_patterns or []
    try:
        sections = connector.api.get_course_contents(course_id)
    except Exception as exc:
        log.warning("Could not fetch contents for course %d: %s", course_id, exc)
        return files

    for section in sections:
        section_name = sanitize(section.get("name", "General"))
        for module in section.get("modules", []):
            modname = module.get("modname", "")

            if modname in ("resource", "folder"):
                for content in module.get("contents", []):
                    if content.get("type") != "file":
                        continue
                    filename = sanitize(content.get("filename", "file"))
                    url = content.get("fileurl", "")
                    if url and filename and not _is_ignored(filename, patterns):
                        files.append({
                            "section": section_name,
                            "filename": filename,
                            "url": url,
                            "kind": "file",
                        })

            elif modname == "url":
                name = sanitize(module.get("name", "link"))
                contents = module.get("contents", [])
                url = ""
                if contents:
                    url = contents[0].get("fileurl", "")
                if not url:
                    url = module.get("url", "")
                if url and not _is_ignored(name, patterns):
                    files.append({
                        "section": section_name,
                        "filename": name,
                        "url": url,
                        "kind": "link",
                    })

    return files


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

def sync_course(
    course: dict,
    folder_name: str,
    connector: MoodleConnector,
    base_dir: Path,
    dry_run: bool,
    domains: tuple[str, ...],
    ignore_patterns: list[str] | None = None,
) -> tuple[int, int, int]:
    """Syncs one course. Returns (total, synced, skipped)."""
    course_id = course["id"]
    course_name = course.get("fullname", f"Course {course_id}")
    course_dir = base_dir / folder_name

    files = get_course_files(connector, course_id, ignore_patterns)
    n_files = sum(1 for f in files if f["kind"] == "file")
    n_links = sum(1 for f in files if f["kind"] == "link")
    print(f"\nCourse: {course_name}")
    print(f"    {len(files)} resource(s): {n_files} file(s), {n_links} link(s)")

    if not files:
        return 0, 0, 0

    total = len(files)
    synced = 0
    skipped = 0

    for file_info in files:
        section_dir = course_dir / file_info["section"]
        kind = file_info["kind"]

        if kind == "file":
            dest = section_dir / file_info["filename"]
            if dest.exists():
                log.debug("  [skip] %s", file_info["filename"])
                skipped += 1
                continue

            if dry_run:
                print(f"    [new] {file_info['section']}/{file_info['filename']}")
                synced += 1
                continue

            section_dir.mkdir(parents=True, exist_ok=True)
            try:
                connector.api.download_file(file_info["url"], dest)
                print(f"    {file_info['section']}/{file_info['filename']} - [{fmt_size(dest.stat().st_size)}]")
                synced += 1
            except Exception as exc:
                print(f"    FAILED: {exc}")
            continue

        # kind == "link"
        url = file_info["url"]
        label = f"{file_info['section']}/{file_info['filename']}"

        if is_shortcut_domain(url, domains):
            dest = section_dir / f"{file_info['filename']}.url"
            if dest.exists():
                skipped += 1
                continue
            if dry_run:
                print(f"    [shortcut] {label}")
                synced += 1
                continue
            section_dir.mkdir(parents=True, exist_ok=True)
            save_url_shortcut(dest, url)
            print(f"    [shortcut] {label}")
            synced += 1
            continue

        print(f"    checking {label}...", end=" ", flush=True)
        if is_direct_download(url):
            dest = section_dir / file_info["filename"]
            if dest.exists():
                print("already exists")
                skipped += 1
                continue
            if dry_run:
                print("downloadable")
                synced += 1
                continue
            section_dir.mkdir(parents=True, exist_ok=True)
            try:
                resp = requests.get(url, stream=True, timeout=60)
                resp.raise_for_status()
                with dest.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        f.write(chunk)
                print(f"downloaded [{fmt_size(dest.stat().st_size)}]")
                synced += 1
            except Exception as exc:
                print(f"FAILED: {exc}")
        else:
            dest = section_dir / f"{file_info['filename']}.url"
            if dest.exists():
                print("already exists")
                skipped += 1
                continue
            if dry_run:
                print("saving as shortcut")
                synced += 1
                continue
            section_dir.mkdir(parents=True, exist_ok=True)
            save_url_shortcut(dest, url)
            print("saved as shortcut")
            synced += 1

    return total, synced, skipped


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Auto-discover and sync new Moodle course files to a local folder."
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be synced without downloading anything.")
    parser.add_argument("--course", metavar="FOLDER", help="Only sync the course mapped to this folder name.")
    parser.add_argument("--list-courses", action="store_true", help="List detected courses and exit.")
    parser.add_argument(
        "--password",
        default=os.getenv("MOODLE_CRED_PASSWORD"),
        help="Encryption password for credentials.enc (env: MOODLE_CRED_PASSWORD).",
    )
    args = parser.parse_args()

    if args.dry_run:
        print("[DRY RUN: nothing will be downloaded]")

    cfg = load_app_config()
    base_dir = resolve_base_dir(cfg)
    course_map = build_course_map(cfg)
    domains = shortcut_domains(cfg)
    sem_folder = cfg.get("descargas", {}).get("semestre")
    sem_code = semester_code(sem_folder) if sem_folder else None

    connector = MoodleConnector(config_path=CONFIG_FILE, password=args.password)
    all_courses = connector.api.get_enrolled_courses()

    matched_courses: list[tuple[dict, str]] = []
    for c in all_courses:
        folder = match_course(c.get("fullname", ""), course_map, sem_code)
        if folder:
            matched_courses.append((c, folder))

    if args.list_courses:
        print("\nDetected courses:")
        for c, folder in sorted(matched_courses, key=lambda x: x[1]):
            print(f"  [{c['id']:>8}] {c['fullname']}  ->  {base_dir.name}/{folder}/")
        return

    if not matched_courses:
        print("\nERROR: no enrolled course matched the configured filters.")
        print("Run with --list-courses to see the exact names Moodle reports.")
        sys.exit(1)

    if args.course:
        matched_courses = [(c, f) for c, f in matched_courses if f == args.course]
        if not matched_courses:
            print(f"\nERROR: no course found for folder '{args.course}'.")
            sys.exit(1)

    print(f"\nCourses to sync: {len(matched_courses)}")
    for c, folder in matched_courses:
        print(f"  {c['fullname']}  ->  {folder}/")
    print("\n" + "-" * 70)

    grand_total = grand_synced = grand_skipped = 0
    ignore_patterns: list[str] = cfg.get("descargas", {}).get("archivos_ignorados", [])

    for course, folder_name in matched_courses:
        total, synced, skipped = sync_course(
            course=course,
            folder_name=folder_name,
            connector=connector,
            base_dir=base_dir,
            dry_run=args.dry_run,
            domains=domains,
            ignore_patterns=ignore_patterns,
        )
        grand_total += total
        grand_synced += synced
        grand_skipped += skipped

    failed = grand_total - grand_synced - grand_skipped

    print("\n" + "-" * 70)
    if args.dry_run:
        print("SUMMARY (DRY RUN — nothing was downloaded)")
        print(f"  New files that would be synced: {grand_synced}")
        print(f"  Already present (would be skipped): {grand_skipped}")
    else:
        print(f"Files found : {grand_total}")
        print(f"    Synced : {grand_synced}")
        print(f"    Skipped: {grand_skipped}")
        if failed:
            print(f"    Failed : {failed}")
    print("-" * 70)


if __name__ == "__main__":
    main()
