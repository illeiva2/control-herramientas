"""Punto de entrada para IIS (módulo HttpPlatformHandler).

IIS levanta este proceso y le pasa el puerto por la variable HTTP_PLATFORM_PORT;
waitress sirve la app de Flask en ese puerto y IIS le reenvía las peticiones.

A diferencia de run.py (app de escritorio), acá NO se abre el navegador ni corre
el auto-updater: es un servidor.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Cargar el .env que está junto a este archivo, ANTES de importar la app
# (bajo IIS el directorio de trabajo puede no ser el de la app).
load_dotenv(Path(__file__).with_name(".env"))

from waitress import serve   # noqa: E402
from app import app          # noqa: E402

if __name__ == "__main__":
    port = int(os.environ.get("HTTP_PLATFORM_PORT", "8177"))
    serve(app, host="127.0.0.1", port=port, threads=8)
