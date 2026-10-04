@echo off
setlocal EnableExtensions
set "FAILED="

call :check "Web" "http://localhost:3000/login"
if errorlevel 1 set "FAILED=1"

call :check "API" "http://localhost:8000/health"
if errorlevel 1 set "FAILED=1"

if defined FAILED set "RESULT=1"
if not defined FAILED set "RESULT=0"
echo Presione una tecla para cerrar...
pause >nul
exit /b %RESULT%

:check
set "NAME=%~1"
set "URL=%~2"
set "CODE="
for /f "usebackq delims=" %%C in (`curl.exe --noproxy "*" --silent --output NUL --write-out "%%{http_code}" --connect-timeout 3 --max-time 10 "%URL%" 2^>nul`) do set "CODE=%%C"
if "%CODE%"=="200" (
    echo PASS %NAME% HTTP 200
    exit /b 0
)
echo FAIL %NAME% HTTP %CODE%
exit /b 1
