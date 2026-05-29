@echo off
title Casa Sergio - Actualizando programa
echo.
echo  =========================================
echo   CASA SERGIO - Actualizando programa
echo  =========================================
echo.

cd /d "%~dp0"

echo  Bajando cambios de GitHub...
git pull origin main
if errorlevel 1 (
    echo.
    echo  [!] Error al conectar con GitHub.
    echo      Verifica que tengas internet y volvé a intentar.
    pause
    exit /b 1
)

echo.
echo  Actualizando dependencias...
py -m pip install -r requirements.txt --quiet

echo.
echo  =========================================
echo   Programa actualizado correctamente!
echo  =========================================
echo.
pause
