@echo off
setlocal
cd /d "%~dp0"
echo Belay Purchase Simulator
echo Open http://127.0.0.1:8777/ in your browser after the server starts.
echo Leave this window open while using the simulator. Press Ctrl+C to stop.
echo All money, services, credentials and signatures are fictional.

set "BELAY_DEMO_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%BELAY_DEMO_PYTHON%" goto bundled
where py >nul 2>nul
if not errorlevel 1 goto launcher
where python >nul 2>nul
if not errorlevel 1 goto standard
echo Python 3.10 or newer is required. No other packages are needed.
goto finished

:bundled
"%BELAY_DEMO_PYTHON%" -m purchase_simulator.server --port 8777 --data-dir .belay-purchase-simulator/demo-v4
goto finished

:launcher
py -3 -m purchase_simulator.server --port 8777 --data-dir .belay-purchase-simulator/demo-v4
goto finished

:standard
python -m purchase_simulator.server --port 8777 --data-dir .belay-purchase-simulator/demo-v4

:finished
echo The server has stopped. If the port was already in use, open the existing simulator in your browser.
pause
