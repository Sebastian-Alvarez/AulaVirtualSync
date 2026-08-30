# Moodle Connector

## Primeros pasos

Esta guía asume que no sabes programar — solo necesitas seguir los pasos en orden.

#### Previamente: Instalar Python (solo la primera vez)

Si nunca has instalado Python en tu computador:

Ve a [python.org/downloads](https://www.python.org/downloads/) y descarga la versión para Windows.
* Al instalarlo, **marca la casilla "Add Python to PATH"** antes de hacer clic en "Install Now"

### Paso 1: Descargar este proyecto

1. Ve a la sección [**Releases**](https://github.com/Sebastian-Alvarez/AulaVirtualSync/releases/latest) de este repositorio.
2. Baja hasta **"Assets"** y descarga el archivo `.zip` .
<img width="238" height="127" alt="Releases-Assets-download_source_code" src="https://github.com/user-attachments/assets/883871f6-21c6-4bb5-a10e-0fca17779f5e" />
3. Extrae el zip y entra a la carpeta.

### Paso 2: Configurar

1. Abre `config.json` con el Bloc de notas (o cualquier IDE).
2. Busca la línea `"url": "https://aula.usm.cl",` y reemplaza esa dirección por la de tu Aula <span style="color: grey; font-size: 0.9em;">(por defecto ya viene con la de la USM)</span>
3. Guarda el archivo (Ctrl+S).


### Paso 3: Ejecutar el programa

1. Haz doble clic en `sync_files.bat`.
2. Se abrirá una ventana negra (la terminal) la primera vez tarda unos minutos, porque instala automáticamente todo lo que necesita.
3. En algún momento te va a pedir una **contraseña de cifrado** — esta contraseña **te la inventas tú**, no es tu clave del Aula. Sirve para proteger, en tu propio computador, la sesión guardada. **Anótala en algún lado**.
4. Se abrirá automáticamente una ventana del navegador, inicia sesión ahí como lo haces normalmente en tu universidad (usuario, contraseña, doble factor si te lo pide). La ventana se cierra sola cuando termina.
5. El programa empieza a descargar los archivos nuevos de tus cursos a la carpeta definida.

### Y para la próxima vez

Solo repite el **Paso 3** 
Doble clic en `sync_files.bat`. Como ya quedó todo instalado y configurado, va a ser mucho más rápido, y solo descarga los archivos que sean nuevos.

---

Si prefieres usar la terminal directamente en vez del `.bat`, o quieres explorar otras opciones (consultar notas desde la línea de comandos, usarlo como librería de Python, integrarlo con Claude Code), sigue leyendo:

- **[Sincronización automática por curso](#sincronización-automática-por-curso)** — lo mismo que hace `sync_files.bat`, pero a mano
- **[CLI](#cli)** — consulta cursos, notas, tareas, fechas límite desde la terminal
- **[Librería Python](#librería-python)** — úsalo dentro de tus propios scripts
- **[Integración MCP](#integración-mcp-claude-code--opencode--openclaw)** — úsalo como herramienta desde Claude Code / OpenCode

## Uso

### Sincronización automática por curso

`course_sync.py` le pregunta a Moodle el contenido de cada curso inscrito y detecta solo lo nuevo. Puedes correrlo las veces que quieras — solo descarga archivos nuevos.

```bash
python course_sync.py --list-courses    # ver qué cursos detectó
python course_sync.py --dry-run         # previsualizar sin descargar
python course_sync.py                   # sincronizar todo
python course_sync.py --course mi-clave # sincronizar solo un curso
```

Se configura bajo `descargas` en `config.json` (todos estos campos son opcionales):
- `directorio_descargas` — carpeta local de destino. Soporta rutas con `%OneDrive%` si la escribes tú; si se deja vacío, usa `./downloads` dentro del proyecto.
- `semestre` — ej. `"2026-2"`. Si se define, solo sincroniza cursos cuyo nombre en Moodle contenga el código `AAAANN` correspondiente. Si se omite, sincroniza todos los cursos inscritos.
- `carpetas_por_curso` — palabra clave del nombre del curso → carpeta local.
- `archivos_ignorados` — patrones glob para ignorar archivos por nombre.
- `dominios_acceso_directo` — dominios adicionales (además de SharePoint/Drive/YouTube/etc.) que siempre se guardan como acceso directo `.url`.

Los links externos que parecen archivos reales (según su `Content-Type`) se descargan directo; el resto se guarda como acceso directo `.url`.

En Windows, `sync_files.bat` es un wrapper de un clic (crea/activa `.venv`, instala dependencias, instala Chromium, corre `course_sync.py`). `sync_files.sh` hace lo mismo en Linux/macOS.

### CLI

```bash
python moodle_connector.py courses        # Listar todos los cursos
python moodle_connector.py grades         # Consultar notas
python moodle_connector.py assignments    # Ver tareas con fechas límite
python moodle_connector.py announcements  # Anuncios de los cursos
python moodle_connector.py materials --course-id 12345
python moodle_connector.py deadlines      # Eventos próximos del calendario
python moodle_connector.py download "https://tu-moodle.ejemplo.com/..." --output archivo.pdf
python moodle_connector.py summary        # Exportación completa en markdown
```

### Librería Python

```python
from moodle_connector import MoodleConnector
from pathlib import Path

connector = MoodleConnector(
    config_path=Path('config.json'),
    password='contraseña-de-cifrado'
)

courses = connector.courses()
grades = connector.grades()
assignments = connector.assignments()
materials = connector.materials()
deadlines = connector.deadlines()
announcements = connector.announcements()
content = connector.summary()

# Descarga con caché
file_content = connector.download("https://...")
```

## Características

**Acceso completo a la API de Moodle**
- Listar cursos, consultar notas, seguir tareas
- Obtener materiales, fechas límite, anuncios
- Descargar archivos con caché agresiva

**Soporte SSO / MFA**
- Mobile Launch Flow automatizado (el mismo que usa la app oficial de Moodle)
- Compatible con cualquier proveedor SSO: Microsoft Azure AD, Google, SAML, etc.
- El navegador se abre para el login interactivo y se cierra automáticamente al capturar el token

**Múltiples modos de integración**
- **CLI:** `python moodle_connector.py courses`
- **Librería Python:** `from moodle_connector import MoodleConnector`
- **Protocolo MCP:** Integración nativa con Claude Code, OpenCode y OpenClaw

**Descarga automática**
- `course_sync.py` auto-descubre archivos por curso inscrito, cero mantenimiento manual de listas

**Seguridad**
- Credenciales cifradas (PBKDF2 + Fernet)
- Gestión de tokens integrada
- Sin secretos en el historial de git
- Licencia MIT

## Tampermonkey Token Helper

Si el conector corre en un servidor headless (sin pantalla), obtén el token desde un PC o Mac con navegador y copialo al servidor. Instala el userscript incluido en esa máquina:

1. Instala [Tampermonkey](https://www.tampermonkey.net/) en tu navegador
2. Abre Tampermonkey - Crear nuevo script - pega el contenido de [`moodle_token_helper.user.js`](moodle_token_helper.user.js)
3. Navega a tu sitio Moodle con sesion activa
4. Haz click en el boton **"Get Token"** (esquina inferior derecha)
5. Copia el token y pegalo en `config.json` bajo `token`

El script usa `GM_xmlhttpRequest` para llamar al endpoint Mobile Launch con tus cookies de sesion activas e intercepta el redirect `moodlemobile://` sin salir de la pagina.

Para agregar otras instancias Moodle, agrega lineas `@match` y `@connect` en el header del script.

## Cómo funciona la autenticación

Este conector usa el **Mobile Launch Flow** de Moodle, el mismo mecanismo que usa la app oficial de Moodle. Funciona con cualquier proveedor SSO sin necesitar credenciales de API ni configuración especial en el servidor.

**Flujo:**
1. El navegador navega a `/admin/tool/mobile/launch.php`
2. Si no hay sesión activa, Moodle redirige al proveedor SSO (ej: Microsoft)
3. El usuario completa el login + MFA de forma interactiva
4. El SSO devuelve a Moodle, que emite un redirect `moodlemobile://token=<base64>`
5. El conector intercepta este redirect, decodifica el token y cierra el navegador

El token se guarda en un archivo cifrado (`credentials.enc`) y se reutiliza hasta que el servidor lo rechaza.

## Integración MCP (Claude Code / OpenCode / OpenClaw)

**REQUERIDO:** Configurar la variable de entorno `MOODLE_CRED_PASSWORD` antes de iniciar Claude Code.

Agregar a tu `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "moodle-connector": {
      "command": "python",
      "args": ["/ruta/a/AulaVirtualSync/mcp_server.py"],
      "env": {
        "MOODLE_CRED_PASSWORD": "tu-contraseña-de-cifrado"
      }
    }
  }
}
```

**Importante:** Reemplazar `tu-contraseña-de-cifrado` con la misma contraseña usada al correr `login`.

Reiniciar Claude Code. Las 8 funciones de Moodle estarán disponibles como herramientas MCP nativas:
- `courses()` - Listar cursos inscritos
- `grades()` - Obtener notas
- `assignments()` - Obtener tareas
- `materials()` - Obtener materiales del curso
- `deadlines()` - Obtener próximas fechas límite
- `announcements()` - Obtener novedades del curso
- `download(url, output?)` - Descargar archivos
- `summary()` - Exportación completa de datos

## Referencia de configuración

### Token de Moodle (`config.json`)
```json
{
  "moodle": {
    "url": "https://tu-moodle.ejemplo.com",
    "token": ""
  }
}
```

Dejar `token` vacío para usar el flujo SSO automatizado. Completarlo manualmente solo si ya tienes un token.

## Requisitos

- Python 3.10+
- requests ≥2.31.0
- cryptography ≥41.0.0
- playwright ≥1.40.0
- mcp ≥0.1.0 (para el servidor MCP)

## Instancias de Moodle compatibles

Probado con:
- Taylor's University (mytimes.taylors.edu.my)
- Universidad Técnica Federico Santa María (aula.usm.cl)
- Debería funcionar con cualquier instancia Moodle 3.x+

## Notas de seguridad

- `MOODLE_CRED_PASSWORD` es **obligatorio** - sin valores por defecto hardcodeados
- **Sanitización de errores:** El servidor MCP sanitiza los errores, sin filtración de detalles internos
- **Credenciales cifradas:** PBKDF2 (480K iteraciones) + cifrado Fernet
- **Apto para headless:** Usar la variable de entorno `MOODLE_CRED_PASSWORD` para automatización
- **Seguro para git:** Nunca hacer commit de `config.json` con tokens reales
- **Sin telemetría:** Sin transmisión de datos externos ni de logs

## Solución de problemas

### El navegador se abre pero nunca se cierra
El redirect del token no fue capturado. Verifica que tu universidad o institución educativa tenga activada la aplicación movil

### "BrowserType.launch: Executable doesn't exist"
El binario del navegador de Playwright no está instalado — corre `python -m playwright install chromium`. `sync_files.bat`/`sync_files.sh` lo hacen automáticamente.

### "Invalid parameter value detected" en la API de calendario
Usar `assignments()` en su lugar, obtiene la misma información de fechas límite.

### Token expirado / se pide login de nuevo
Eliminar `credentials.enc` y ejecutar `python moodle_connector.py login` nuevamente.

### Descarga de archivo detenida
Verifica tu conexión a internet. Aumentar el timeout en el código o limpiar la caché: `rm -rf cache/`

## Licencia

MIT - Ver el archivo LICENSE para más detalles. Eres libre de usar, modificar y distribuir este software.

## Contribuir

¡Las contribuciones son bienvenidas! Por favor:
1. Haz un fork del repositorio
2. Crea una rama para tu funcionalidad
3. Envía un pull request
4. Acepta licenciar tu trabajo bajo MIT (la misma licencia del resto del proyecto)

## Autores

**Jabir Iliyas Suraj-Deen** - autor original
- GitHub: https://github.com/Jabir-Srj
- Email: jabirsrj8@protonmail.com
- Taylor's University, Kuala Lumpur, Malaysia

**Sebastian Guevara M.** - SSO Mobile Launch Flow, soporte multi-instancia
- GitHub: https://github.com/SebaG20xx
- Email: contacto@sebag20xx.cl
- Universidad Técnica Federico Santa María, Viña del Mar, Chile

**Sebastian Alvarez Avendaño** - Sincronización automática de archivos, configuración simplificada
- GitHub: https://github.com/Sebastian-Alvarez
- Email: sebastian.alvarezav@usm.cl
- Universidad Técnica Federico Santa María, Viña del Mar, Chile
---

**GitHub:** https://github.com/Sebastian-Alvarez/AulaVirtualSync
**Upstream:** https://github.com/Jabir-Srj/moodle-connector
