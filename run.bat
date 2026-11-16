@echo off
title Node Searcher
cd /d "%~dp0"

rem IMPORTANT: keep this file ASCII-only with CRLF line endings and no BOM.
rem CMD parses .bat with the system ANSI code page (936 on Chinese Windows),
rem so non-ASCII text, LF-only newlines or a UTF-8 BOM can break commands.
rem Do NOT call chcp here: switching the code page mid-script plus Python's
rem own stdout encoding makes Chinese console output garbled. All console
rem messages (here and in node_searcher.py) are plain ASCII for this reason.
rem Chinese text lives in the HTML page, the Tk window and README.md.
set "PYCMD="

python -c "import sys" >nul 2>&1
if not errorlevel 1 set "PYCMD=python"

if not defined PYCMD (
  py -3 -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PYCMD=py -3"
)
if not defined PYCMD if exist "D:\Python\python.exe" set "PYCMD=D:\Python\python.exe"
if not defined PYCMD if exist "C:\Program Files\Python310\python.exe" set PYCMD="C:\Program Files\Python310\python.exe"
if not defined PYCMD if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set PYCMD="%LOCALAPPDATA%\Programs\Python\Python313\python.exe"

if not defined PYCMD (
  echo.
  echo ERROR: No usable Python 3.8+ found.
  echo Install it from python.org and check "Add Python to PATH".
  echo.
  pause
  exit /b 1
)

echo Starting with: %PYCMD%
echo If tkinter is missing, the app restarts on another Python or opens browser UI.
echo.
%PYCMD% node_searcher.py
if errorlevel 1 (
  echo.
  echo The program exited with an error. Details are shown above.
  echo Manual run: %PYCMD% node_searcher.py
  echo.
  pause
)
exit /b 0
