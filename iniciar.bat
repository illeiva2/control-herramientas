@echo off
rem Inicia el sistema de Control de Herramientas.
rem La primera vez crea el entorno e instala dependencias (necesita internet solo esa vez).
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo No se encontro Python. Instalalo desde https://www.python.org/downloads/
    echo IMPORTANTE: marcar "Add python.exe to PATH" durante la instalacion.
    pause
    exit /b 1
)

if not exist .venv (
    echo Preparando el sistema por primera vez...
    py -3 -m venv .venv
    .venv\Scripts\pip install -r requirements.txt
)

.venv\Scripts\python run.py
pause
