@echo off
rem Recompila el ejecutable para Windows 7+ (32 bits).
rem Requiere Python 3.8.10 x86 instalado en %USERPROFILE%\Python38-32
rem (ultima version de Python compatible con Windows 7) con:
rem   pip install flask waitress "pyinstaller==5.13.2"
cd /d "%~dp0"

"%USERPROFILE%\Python38-32\Scripts\pyinstaller.exe" --noconfirm --clean --onedir ^
  --name ControlHerramientas ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --add-data "schema.sql;." ^
  run.py

if errorlevel 1 ( echo FALLO LA COMPILACION & pause & exit /b 1 )

rem copia la base actual como semilla del instalador y actualiza el paquete
xcopy /E /I /Y data dist\ControlHerramientas\data >nul
robocopy dist\ControlHerramientas instalador\ControlHerramientas /MIR >nul
echo Listo: instalador\ControlHerramientas actualizado.
pause
