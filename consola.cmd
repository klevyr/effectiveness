
@echo off
echo [Iniciando] por favor espera.
setlocal enabledelayedexpansion

rem Buscar el nombre del proceso padre utilizando wmic o powershell de fondo
for /f "tokens=1" %%a in ('powershell -Command "(Get-Process -Id (Get-CimInstance WMIC_Process -Filter \"ProcessId=$PID\").ParentProcessId).Name"') do (
    set "PARENT_PROCESS=%%a"
)

rem Normalizar a minúsculas
set "PARENT_PROCESS=!PARENT_PROCESS:~0!"

if /i "!PARENT_PROCESS!"=="powershell" (
    echo [Entorno] PowerShell.
    powershell -NoExit -ExecutionPolicy Bypass -Command "& .venv\Scripts\Activate.ps1 && efectividad --help"
    exit /b
)

if /i "!PARENT_PROCESS!"=="pwsh" (
    echo [Entorno] PowerShell Core.
    pwsh -NoExit -ExecutionPolicy Bypass -Command "& .venv\Scripts\Activate.ps1 && efectividad --help"
    exit /b
)

rem Si no es ninguno de los anteriores, se asume Command Prompt (cmd)
echo [Entorno] Command Prompt (CMD).
call .venv\Scripts\activate.bat && efectividad --help
cmd /k
