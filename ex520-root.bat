@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"

call :ensure_requirements
if errorlevel 1 goto :failed

where py >nul 2>nul
if errorlevel 1 (
  echo HATA: Python 3 hazirlanamadi.
  goto :failed
)

if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if errorlevel 1 goto :failed

".venv\Scripts\python.exe" -c "import websocket" >nul 2>nul
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet --no-index --find-links "%CD%\vendor" -r requirements.txt
  if errorlevel 1 goto :failed
)

set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=oneclick"
if "%ACTION:~0,2%"=="--" set "ACTION=%ACTION:~2%"
".venv\Scripts\python.exe" ex520_oneclick.py "%ACTION%"
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%

:failed
echo HATA: Calisma ortami hazirlanamadi.
pause
exit /b 1

:ensure_requirements
where winget >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 exit /b 1
  call :openssh_ready
  if errorlevel 1 exit /b 1
  call :chrome_ready
  if errorlevel 1 exit /b 1
  exit /b 0
)

where py >nul 2>nul
if errorlevel 1 (
  echo [HAZIRLIK] Python 3 kuruluyor...
  winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
  if errorlevel 1 exit /b 1
  set "PATH=%LocalAppData%\Programs\Python\Launcher;%LocalAppData%\Programs\Python\Python312;%LocalAppData%\Programs\Python\Python312\Scripts;%PATH%"
)

call :openssh_ready
if errorlevel 1 (
  echo [HAZIRLIK] Windows OpenSSH Client kuruluyor...
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$p=Start-Process powershell -Verb RunAs -Wait -PassThru -ArgumentList '-NoProfile -Command Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0'; exit $p.ExitCode"
  if errorlevel 1 exit /b 1
  set "PATH=%SystemRoot%\System32\OpenSSH;%PATH%"
)

call :chrome_ready
if errorlevel 1 (
  echo [HAZIRLIK] Google Chrome kuruluyor...
  winget install --id Google.Chrome -e --accept-package-agreements --accept-source-agreements
  if errorlevel 1 exit /b 1
)

where py >nul 2>nul || exit /b 1
call :openssh_ready
if errorlevel 1 exit /b 1
call :chrome_ready
exit /b %ERRORLEVEL%

:openssh_ready
where ssh >nul 2>nul || exit /b 1
where ssh-keygen >nul 2>nul || exit /b 1
where ssh-keyscan >nul 2>nul || exit /b 1
exit /b 0

:chrome_ready
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" exit /b 0
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" exit /b 0
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" exit /b 0
if exist "%ProgramFiles%\Chromium\Application\chrome.exe" exit /b 0
if exist "%LocalAppData%\Chromium\Application\chrome.exe" exit /b 0
exit /b 1
