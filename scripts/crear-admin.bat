@echo off
setlocal EnableExtensions

for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
set "ENV_FILE=%PROJECT_ROOT%\.env"
set "COMPOSE_FILE=%PROJECT_ROOT%\infra\compose.dev.yml"

for %%V in (POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD DATABASE_URL DATABASE_HOST DATABASE_PORT DATABASE_NAME DATABASE_USER DATABASE_PASSWORD APP_ENVIRONMENT APP_PUBLIC_URL SESSION_COOKIE_NAME SESSION_DURATION_MINUTES ACTIVACION_REENVIO_COOLDOWN_SEGUNDOS CORREO_TRANSPORTE SMTP_HOST SMTP_PORT SMTP_USERNAME SMTP_PASSWORD SMTP_FROM_EMAIL SMTP_FROM_NAME SMTP_SECURITY SMTP_TIMEOUT_SECONDS NUXT_API_INTERNAL_BASE_URL) do set "%%V="

if not exist "%COMPOSE_FILE%" (
    echo Error: no se encontro infra\compose.dev.yml en el proyecto.
    exit /b 1
)

if not exist "%ENV_FILE%" (
    echo Error: no se encontro .env en la raiz del proyecto; copia .env.example.
    exit /b 1
)

rem SMART_PARKING_PODMAN_BIN permite ejecutar pruebas aisladas con un stub.
set "PODMAN_CALL="
if defined SMART_PARKING_PODMAN_BIN goto :usar_ejecutable_podman
where podman >nul 2>&1
if errorlevel 1 (
    echo Error: Podman no esta disponible en PATH.
    exit /b 127
)
set "PODMAN=podman"
goto :ejecutable_podman_seleccionado

:usar_ejecutable_podman
set "PODMAN=%SMART_PARKING_PODMAN_BIN%"
if not exist "%PODMAN%" (
    echo Error: el ejecutable configurado para Podman no esta disponible.
    exit /b 127
)
for %%I in ("%PODMAN%") do set "PODMAN_EXTENSION=%%~xI"
if /I "%PODMAN_EXTENSION%"==".bat" set "PODMAN_CALL=call"
if /I "%PODMAN_EXTENSION%"==".cmd" set "PODMAN_CALL=call"

:ejecutable_podman_seleccionado

%PODMAN_CALL% "%PODMAN%" version >nul 2>&1
if errorlevel 1 (
    echo Error: Podman no puede conectarse al motor local.
    exit /b 125
)

%PODMAN_CALL% "%PODMAN%" compose version >nul 2>&1
if errorlevel 1 (
    echo Error: no hay un proveedor Compose disponible para Podman.
    exit /b 126
)

echo Preparando Smart Parking...
%PODMAN_CALL% "%PODMAN%" compose --env-file "%ENV_FILE%" --project-directory "%PROJECT_ROOT%" -f "%COMPOSE_FILE%" up --detach --wait --wait-timeout 60 postgres api-dev
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo Error: no fue posible iniciar postgres/api-dev.
    exit /b %EXIT_CODE%
)

echo postgres/api-dev disponibles.
echo Abriendo la creacion interactiva de ADMIN...
%PODMAN_CALL% "%PODMAN%" compose --env-file "%ENV_FILE%" --project-directory "%PROJECT_ROOT%" -f "%COMPOSE_FILE%" exec api-dev uv run python -m app.cli.crear_admin
set "CLI_EXIT=%ERRORLEVEL%"
if "%CLI_EXIT%"=="0" (
    echo.
    echo Presiona una tecla para cerrar...
    pause >nul
) else (
    echo Error: la creacion interactiva de ADMIN termino con codigo %CLI_EXIT%.
)
exit /b %CLI_EXIT%
