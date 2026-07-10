"""Arranca el servidor local y abre el navegador."""
import threading
import webbrowser

from waitress import serve

import updater
from app import app
from version import VERSION

PUERTO = 8177

if __name__ == "__main__":
    updater.iniciar()
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PUERTO}")).start()
    print(f"Control de Herramientas v{VERSION} corriendo en http://127.0.0.1:{PUERTO}")
    print("Dejá esta ventana abierta mientras uses el sistema. Para cerrar: Ctrl+C o cerrar la ventana.")
    serve(app, host="127.0.0.1", port=PUERTO, threads=4)
