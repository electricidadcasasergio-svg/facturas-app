@echo off
title Casa Sergio - Servidor Facturas

:: Obtener IP local automaticamente
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do (
    set IP=%%a
    goto :found
)
:found
set IP=%IP: =%

echo.
echo  =========================================
echo   CASA SERGIO - Sistema de Facturas
echo  =========================================
echo.
echo  Iniciando servidor...
echo  Acceso esta PC  : http://localhost:8501
echo  Acceso red LAN  : http://%IP%:8501
echo.
echo  Para cerrar el servidor: Ctrl+C o cerrar esta ventana.
echo.

cd /d "%~dp0"
py -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true

pause
