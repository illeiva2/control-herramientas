"""Arranca el servidor local y abre el navegador."""
import socket
import sys
import threading
import webbrowser

from waitress import serve

import updater
from app import app
from version import VERSION

PUERTO = 8177


def ya_corriendo():
    """True si otra instancia ya esta atendiendo el puerto."""
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", PUERTO))
        return True
    except OSError:
        return False
    finally:
        s.close()


if __name__ == "__main__":
    if ya_corriendo():
        # instancia unica: si ya esta abierto, solo mostrar la pagina.
        # (dos servidores a la vez rompen el puerto y traban el auto-update)
        webbrowser.open(f"http://127.0.0.1:{PUERTO}")
        sys.exit(0)
    updater.iniciar()
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PUERTO}")).start()
    print(f"Control de Herramientas v{VERSION} corriendo en http://127.0.0.1:{PUERTO}")
    print("Dejá esta ventana abierta mientras uses el sistema. Para cerrar: Ctrl+C o cerrar la ventana.")
    serve(app, host="127.0.0.1", port=PUERTO, threads=4)
