# Aula Virtual Sync

## Índice

[Primeros pasos](#primeros-pasos) • [Configuración](#configuración) • [Usos Alternativos](#usos-alternativos) • [Autenticación](#cómo-funciona-la-autenticación) • [Integración MCP](#integración-mcp-claude-code--opencode--openclaw) • [Notas de seguridad](#notas-de-seguridad) • [Solución de problemas](#solución-de-problemas)

## Primeros pasos

> [!IMPORTANT]
>PREVIAMENTE: Instalar Python
> Si nunca lo has instalado en tu computador:
> https://www.python.org/downloads/ <br>
> Al instalarlo, **marca la casilla "Add Python to PATH"** antes de hacer clic en `Install Now`

### Paso 1: Descargar este proyecto
1. Haz click [aquí](https://github.com/Sebastian-Alvarez/AulaVirtualSync/archive/refs/tags/v1.1.0.zip) para descargar la última versión.
   * o en [**Releases**](https://github.com/Sebastian-Alvarez/AulaVirtualSync/releases/latest) puedes ver y descarga la última versión en el archivo `.zip` .
    <img width="400" alt="AulaVirtualSync_Asset-Download" src="https://github.com/user-attachments/assets/c7ccc64f-b67f-4d26-991f-1eaf0ff9df67" />

2. Extrae el zip y entra a la carpeta.

### Paso 2: Ejecutar el programa

1. Haz doble clic en `sync_files.bat`.
2. Se abrirá una ventana negra (la terminal) 
    > La primera vez tarda unos minutos, porque instala automáticamente todo lo que necesita.
3. Se le pedirá una **contraseña de cifrado**, esta contraseña no es tu clave del Aula. Sirve para proteger la sesión guardada. El programa la guarda de forma segura (usando el gestor de credenciales de tu Sistema Operativo).
4. Se abrirá automáticamente una ventana del navegador, inicia sesión ahí como lo haces normalmente en la web (usuario, contraseña, doble factor si te lo pide). La ventana se cierra sola cuando termina.
    > Si obtienes fallos en esta parte, puedes probar el [método alternativo para obtener el token](#método-alternativo-al-token).
5. El programa empieza a descargar los archivos nuevos de tus cursos a la carpeta definida.

### Y para la próxima vez

Solo repite el **Paso 2**: Doble clic en `sync_files.bat`. <br>
Como ya quedó todo instalado y configurado, va a ser mucho más rápido, y solo descarga los archivos que sean nuevos.

---

## Configuración

Toda configuración/personalización se hace en [`config.json`](config.json).

<details>
<summary><h3>Cambiar sitio web del Aula Virtual</h3></summary>

Cambia el valor del `url`:
```json
    "url": "https://tu-sitio.com",
```
    
</details>

<details>
<summary><h3> Para cambiar el carpeta de destino </h3></summary>

Cambia el valor de `directorio_descargas`, ejemplo:

```json
        "directorio_descargas": "C:/Users/icapaz/Downloads"
```

> **Tip:** Puedes dejarlo en tu Onedrive si tienes la app de escritorio descargada.<br>
> Para esto solo cambia el valor a "%OneDrive%/*Tu carpeta*"
    
</details>

<details>
<summary><h3> Para cambiar nombre de carpetas por Curso </h3></summary>

Agrega el nombre del ramo seguido de el nombre que quieres que quede (abreviación o lo que sea).<br>
"Ramo": "nombre que quieras"

```json
    "carpetas_por_curso": {
      "GESTION DEL EMPRENDIMIENTO": "GE",
      "INGENIERIA DE SOFTWARE": "IS"
    }
```
    
</details>

<details>
<summary><h3> Archivos Ignorados</h3> </summary>

Muchas veces el Aula hay archivos basura, estos se pueden ignorar agregandolos a `archivos_ignorados` de la siguiente forma:

```json
    "archivos_ignorados": ["Programa-de-estudio.pdf", "CREACIÓN DE CUESTIONARIO.docx", "Presentación_DEO_05-08.pdf"],
```
    
</details>

<details>
<summary><h3> Filtro por Semestre</h3> </summary>

Para no descargar todo el contenido de ramos antiguos se puede filtrar por semestre.<br>
Esto funciona ya que los ramos en aula suelen tener el año o semestre en el nombre. 
Por lo que este filtro depende de la configuración que le da tu universidad al nombre de los ramos.

```json
    "semestre": "2026-2",
```
    
</details>

---

## Usos Alternativos

Si prefieres usar la terminal directamente en vez del `.bat`, o quieres explorar otras opciones (consultar notas desde la línea de comandos, usarlo como librería de Python, integrarlo con Claude Code), sigue leyendo:

- **[Sincronización automática por curso](#sincronización-automática-por-curso)** — lo mismo que hace `sync_files.bat`, pero a mano
- **[CLI](#cli)** — consulta cursos, notas, tareas, fechas límite desde la terminal
- **[Librería Python](#librería-python)** — úsalo dentro de tus propios scripts
- **[Integración MCP](#integración-mcp-claude-code--opencode--openclaw)** — úsalo como herramienta desde Claude Code / OpenCode

### Sincronización automática por curso

`course_sync.py` le pregunta a Moodle el contenido de cada curso inscrito y detecta solo lo nuevo. Puedes correrlo las veces que quieras — solo descarga archivos nuevos.

```bash
python course_sync.py --list-courses    # ver qué cursos detectó
python course_sync.py --dry-run         # previsualizar sin descargar
python course_sync.py                   # sincronizar todo
python course_sync.py --course mi-clave # sincronizar solo un curso
```

Se configura en la sección [Configuración](#configuración).

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
---

## Cómo funciona la autenticación

Este conector usa el **Mobile Launch Flow** de Moodle, el mismo mecanismo que usa la app oficial de Moodle. Funciona con cualquier proveedor SSO sin necesitar credenciales de API ni configuración especial en el servidor.

**Flujo:**
1. El navegador navega a `/admin/tool/mobile/launch.php`
2. Si no hay sesión activa, Moodle redirige al proveedor SSO (ej: Microsoft)
3. El usuario completa el login + MFA de forma interactiva
4. El SSO devuelve a Moodle, que emite un redirect `moodlemobile://token=<base64>`
5. El conector intercepta este redirect, decodifica el token y cierra el navegador

El token se guarda en un archivo cifrado (`credentials.enc`) y se reutiliza hasta que el servidor lo rechaza.

<a id="método-alternativo-al-token"></a>
<details>
<summary><h3>Método alternativo a obtención del token</h3></summary>

**Tampermonkey Token Helper**<br>
Si el método anterior no funciona o si quieres usarlo en un entorno headless (sin monitor)

1. Instala [Tampermonkey](https://www.tampermonkey.net/) en tu navegador
2. Abre Tampermonkey - Crear nuevo script - pega el contenido de [`moodle_token_helper.user.js`](moodle_token_helper.user.js)
3. Navega a tu sitio Moodle con sesion activa
4. Haz click en el boton **"Get Token"** (esquina inferior derecha)
5. Copia el token y pegalo en `config.json` bajo `token`

El script usa `GM_xmlhttpRequest` para llamar al endpoint Mobile Launch con tus cookies de sesion activas e intercepta el redirect `moodlemobile://` sin salir de la pagina.

Para agregar otras instancias Moodle, agrega lineas `@match` y `@connect` en el header del script.
</details>

---

## Integración MCP (Claude Code / OpenCode / OpenClaw)

> [!CAUTION]
> Esta funcionalidad viene del fork original — las funciones agregadas en este repositorio no están integradas en el funcionamiento del MCP.

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

---

## Instancias de Moodle compatibles

Probado con:
- Taylor's University (mytimes.taylors.edu.my)
- Universidad Técnica Federico Santa María (aula.usm.cl)
- Debería funcionar con cualquier instancia Moodle 3.x+

---

## Notas de seguridad

- Sin valores por defecto hardcodeados para la contraseña de cifrado
- **Sanitización de errores:** El servidor MCP sanitiza los errores, sin filtración de detalles internos
- **Credenciales cifradas:** PBKDF2 (480K iteraciones) + cifrado Fernet
- **Contraseña guardada de forma segura:** se pide una sola vez y se guarda en el gestor de credenciales nativo del sistema (Windows Credential Manager / macOS Keychain / Linux Secret Service vía `keyring`) — no en texto plano
- **Apto para headless:** Usar la variable de entorno `MOODLE_CRED_PASSWORD` para automatización (tiene prioridad sobre la contraseña guardada)
- **Seguro para git:** Nunca hacer commit de `config.json` con tokens reales
- **Sin telemetría:** Sin transmisión de datos externos ni de logs

---

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

---

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
