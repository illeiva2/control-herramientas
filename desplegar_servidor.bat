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
ssh -i "%KEY%" %SRV% "C:\panol\.venv\Scripts\pip install -q -r C:\panol\requirements.txt && %%windir%%\System32\inetsrv\appcmd stop site panol && %%windir%%\System32\inetsrv\appcmd start site panol"

echo Verificando...
curl -s -o nul -w "http://192.168.100.87:44050/ -> %%{http_code}\n" http://192.168.100.87:44050/
pause
