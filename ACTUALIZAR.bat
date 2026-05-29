@echo off
title Casa Sergio - Actualizando programa
echo.
echo  =========================================
echo   CASA SERGIO - Actualizando programa
echo  =========================================
echo.

cd /d "%~dp0"

:: Verificar si git está instalado
git --version >nul 2>&1
if errorlevel 1 (
    echo  [!] Git no esta instalado.
    echo      Instalar desde: https://git-scm.com
    echo      Despues volver a ejecutar este archivo.
    pause
    exit /b 1
)

:: Verificar si esta carpeta es un repositorio git
git rev-parse --git-dir >nul 2>&1
if errorlevel 1 (
    echo  Primera vez: inicializando repositorio git...
    git init
    git remote add origin https://github.com/electricidadcasasergio-svg/facturas-app.git
    git fetch origin main
    git checkout -b main --track origin/main
    if errorlevel 1 (
        echo.
        echo  [!] No se pudo inicializar. Verifica tu conexion a internet.
        pause
        exit /b 1
    )
    echo  Repositorio inicializado correctamente.
) else (
    echo  Bajando cambios de GitHub...
    git pull origin main
    if errorlevel 1 (
        echo.
        echo  [!] Error al conectar con GitHub.
        echo      Verifica que tengas internet y volvé a intentar.
        pause
        exit /b 1
    )
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
