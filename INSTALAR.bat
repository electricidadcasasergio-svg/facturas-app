@echo off
title Casa Sergio - Instalacion inicial
echo.
echo  =========================================
echo   CASA SERGIO - Instalacion inicial
echo  =========================================
echo.

cd /d "%~dp0"

echo  Verificando Python...
py --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [!] Python no esta instalado.
    echo      Instalar desde: https://python.org
    echo      Asegurate de tildar "Add Python to PATH" al instalar.
    pause
    exit /b 1
)
py --version

echo.
echo  Instalando dependencias...
py -m pip install -r requirements.txt

echo.
echo  Creando carpeta de datos...
if not exist "data" mkdir data

echo.
echo  =========================================
echo   Instalacion completada!
echo   Ahora podes usar INICIAR_SERVIDOR.bat
echo  =========================================
echo.
pause
