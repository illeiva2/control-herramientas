"""Chequeo y aplicacion de actualizaciones desde GitHub Releases.

La app consulta una vez por dia (y al arrancar) el ultimo release de
https://github.com/illeiva2/control-herramientas . Si hay una version mas
nueva, la UI muestra un aviso; "Actualizar ahora" descarga el ZIP, lo
extrae y un .bat reemplaza los archivos del programa (nunca la carpeta
data/) y lo reinicia.
"""
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path

from version import VERSION

REPO = "illeiva2/control-herramientas"
URL_API = os.environ.get("CH_UPDATE_URL",
                         f"https://api.github.com/repos/{REPO}/releases/latest")

estado = {"actual": VERSION, "ultima": None, "hay_update": False,
          "url_zip": None, "error": None}
_lock = threading.Lock()


def _contexto_ssl():
    # en Windows 7 el almacen de certificados suele estar desactualizado:
    # usar el paquete de certificados de certifi si esta disponible
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _abrir(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "ControlHerramientas"})
    if url.startswith("https:"):
        return urllib.request.urlopen(req, timeout=timeout, context=_contexto_ssl())
    return urllib.request.urlopen(req, timeout=timeout)


def _numeros(version):
    return tuple(int(x) for x in re.findall(r"\d+", version or "")[:3]) or (0,)


def chequear():
    """Consulta el ultimo release. Actualiza `estado`. Nunca lanza excepciones."""
    try:
        with _abrir(URL_API) as r:
            data = json.load(r)
        tag = data.get("tag_name", "")
        asset = next((a for a in data.get("assets", [])
                      if a.get("name", "").lower().endswith(".zip")), None)
        with _lock:
            estado["ultima"] = tag.lstrip("v")
            estado["hay_update"] = _numeros(tag) > _numeros(VERSION) and asset is not None
            estado["url_zip"] = asset["browser_download_url"] if asset else None
            estado["error"] = None
    except Exception as e:  # sin red, timeout, API caida: la app sigue normal
        with _lock:
            estado["error"] = str(e)


def iniciar():
    """Lanza el chequeo al arrancar y despues una vez por dia."""
    def bucle():
        while True:
            chequear()
            threading.Event().wait(24 * 3600)
    threading.Thread(target=bucle, daemon=True).start()


def aplicar():
    """Descarga la nueva version y deja un .bat que reemplaza los archivos
    y reinicia el programa. Devuelve (ok, mensaje). Si ok, el proceso se
    cierra solo un segundo despues de responder."""
    if not getattr(sys, "frozen", False):
        return False, "La actualización automática solo funciona en la versión instalada."
    with _lock:
        url = estado["url_zip"]
        if not estado["hay_update"] or not url:
            return False, "No hay ninguna actualización para aplicar."

    destino = Path(sys.executable).parent
    tmp = Path(tempfile.mkdtemp(prefix="ch_update_"))
    zip_path = tmp / "update.zip"
    nueva = tmp / "nueva"
    try:
        with _abrir(url, timeout=300) as r, open(zip_path, "wb") as f:
            shutil.copyfileobj(r, f)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(nueva)
        if not (nueva / "ControlHerramientas.exe").exists():
            return False, "El paquete descargado no es válido (falta el ejecutable)."
    except Exception as e:
        return False, f"No se pudo descargar la actualización: {e}"

    with _lock:
        version_nueva = estado["ultima"] or ""
    # si el programa se instalo con el Setup, mantener actualizado el numero
    # de version que muestra "Agregar o quitar programas"
    clave_arp = (r"HKCU\Software\Microsoft\Windows\CurrentVersion"
                 r"\Uninstall\ControlHerramientas_is1")
    # el .bat corre oculto y deja un log en %TEMP% por si algo falla.
    # - espera con tope: si el programa no cierra solo en ~20 s, lo fuerza
    # - robocopy con reintentos acotados (/R:3 /W:2): sin eso, un archivo
    #   trabado lo deja reintentando durante horas
    # comandos con ruta absoluta: el bat no depende del PATH de la maquina
    bat = tmp / "aplicar.bat"
    bat.write_text(f"""@echo off
set S32=%SystemRoot%\\System32
set LOG=%TEMP%\\control-herramientas-update.log
echo [%date% %time%] actualizando a v{version_nueva} > "%LOG%"
set INTENTOS=0
:espera
"%S32%\\ping.exe" -n 3 127.0.0.1 >nul 2>nul
"%S32%\\tasklist.exe" /FI "IMAGENAME eq ControlHerramientas.exe" 2>nul | "%S32%\\find.exe" /I "ControlHerramientas.exe" >nul || goto copiar
set /a INTENTOS+=1
if %INTENTOS% LSS 10 goto espera
echo el programa no cerro solo: forzando cierre >> "%LOG%"
"%S32%\\taskkill.exe" /F /IM ControlHerramientas.exe >nul 2>nul
"%S32%\\ping.exe" -n 3 127.0.0.1 >nul 2>nul
:copiar
"%S32%\\robocopy.exe" "{nueva}" "{destino}" /MIR /XD data /R:3 /W:2 >> "%LOG%" 2>&1
if errorlevel 8 echo ERROR: robocopy no pudo copiar todo >> "%LOG%"
"%S32%\\reg.exe" query "{clave_arp}" >nul 2>nul && "%S32%\\reg.exe" add "{clave_arp}" /v DisplayVersion /t REG_SZ /d "{version_nueva}" /f >nul
echo [%date% %time%] relanzando >> "%LOG%"
start "" "{destino}\\ControlHerramientas.exe"
""", encoding="ascii")
    subprocess.Popen(["cmd", "/c", str(bat)],
                     creationflags=0x08000000)  # CREATE_NO_WINDOW: sin ventana de cmd
    threading.Timer(1.0, os._exit, args=(0,)).start()
    return True, "Actualizando: el programa se reinicia solo en unos segundos."
