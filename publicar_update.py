"""Compila y publica una nueva version en GitHub Releases.

Pasos para publicar una actualizacion:
  1. Hacer los cambios en el codigo.
  2. Subir el numero en version.py (ej. "1.2.0").
  3. Correr:  python publicar_update.py
     (compila el exe, arma el ZIP de update SIN la base de datos y crea
      el release v<version> en GitHub; las PCs instaladas van a mostrar
      el aviso de actualizacion dentro de las 24 hs, o al reiniciar la app)

Requiere: gh CLI autenticado y Python 3.8 x86 en %USERPROFILE%/Python38-32.
"""
import subprocess
import sys
import zipfile
from pathlib import Path

from version import VERSION

BASE = Path(__file__).parent
PYINSTALLER = Path.home() / "Python38-32" / "Scripts" / "pyinstaller.exe"
DIST = BASE / "dist" / "ControlHerramientas"
REPO = "illeiva2/control-herramientas"


def correr(cmd):
    print(">", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, cwd=BASE)


def main():
    tag = f"v{VERSION}"
    ya = subprocess.run(["gh", "release", "view", tag, "-R", REPO],
                        capture_output=True, cwd=BASE)
    if ya.returncode == 0:
        sys.exit(f"ERROR: el release {tag} ya existe en GitHub. Subí el número en version.py.")

    correr([PYINSTALLER, "--noconfirm", "--clean", "--onedir",
            "--name", "ControlHerramientas",
            "--add-data", "templates;templates",
            "--add-data", "static;static",
            "--add-data", "schema.sql;.",
            "run.py"])

    # ZIP de update: todo el build MENOS data/ (la base de cada PC no se toca
    # y jamas se sube a GitHub porque contiene datos del personal)
    zip_path = BASE / f"ControlHerramientas-{tag}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in DIST.rglob("*"):
            rel = f.relative_to(DIST)
            if rel.parts[0] == "data":
                continue
            z.write(f, rel)
    print(f"ZIP de update: {zip_path.name} ({zip_path.stat().st_size // 1_000_000} MB)")

    correr(["gh", "release", "create", tag, str(zip_path), "-R", REPO,
            "--title", f"Control de Herramientas {tag}",
            "--notes", f"Actualización {tag}. Se instala desde el aviso dentro de la app."])

    # ademas del ZIP de update, publicar el Setup.exe para instalaciones nuevas
    iscc = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")
    if iscc.exists():
        correr([str(iscc), "/Qp", f"/DMyAppVersion={VERSION}", "setup.iss"])
        setup = BASE / "Output" / f"ControlHerramientas-Setup-{VERSION}.exe"
        correr(["gh", "release", "upload", tag, str(setup), "-R", REPO])
        print(f"Setup publicado: {setup.name}")
    else:
        print("AVISO: Inno Setup no está instalado; no se generó el Setup.exe.")

    print(f"\nListo: {tag} publicado. Las apps instaladas van a avisar solas.")


if __name__ == "__main__":
    main()
