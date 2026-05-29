@echo off
title Casa Sergio - Servidor Facturas
echo.
echo  =========================================
echo   CASA SERGIO - Sistema de Facturas
echo  =========================================
echo.
echo  Iniciando servidor...
echo  Acceso local   : http://localhost:8501
echo  Acceso red     : http://192.168.68.107:8501
echo.
echo  Para cerrar el servidor: Ctrl+C o cerrar esta ventana.
echo.

cd /d "%~dp0"
py -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true

pause
