@echo off
rem Despliega la app al servidor on-premise (srv-datos, IIS puerto 44050).
rem Requiere la clave SSH %USERPROFILE%\.ssh\id_ed25519_srv87 autorizada en el servidor.
cd /d "%~dp0"
set SRV=Administrador@192.168.100.87
set KEY=%USERPROFILE%\.ssh\id_ed25519_srv87

echo Copiando archivos...
scp -i "%KEY%" -q app.py serve_iis.py updater.py version.py requirements.txt web.config %SRV%:C:/panol/
scp -i "%KEY%" -q -r templates static %SRV%:C:/panol/

echo Actualizando dependencias y reiniciando el sitio...
ssh -i "%KEY%" %SRV% "C:\panol\.venv\Scripts\pip install -q -r C:\panol\requirements.txt && %%windir%%\System32\inetsrv\appcmd stop site panol"
rem detener el sitio no siempre mata el proceso python: matar solo los de C:\panol
ssh -i "%KEY%" %SRV% "powershell -NoProfile -Command \"Get-CimInstance Win32_Process -Filter \\\"Name='python.exe'\\\" | Where-Object { $_.ExecutablePath -like 'C:\panol\*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }\""
ssh -i "%KEY%" %SRV% "%%windir%%\System32\inetsrv\appcmd start site panol"

echo Verificando...
curl -s -o nul -w "http://192.168.100.87:44050/ -> %%{http_code}\n" http://192.168.100.87:44050/
pause
