@echo off
REM ============================================================
REM  start_backend.bat  —  Fast startup script
REM  Loads FAISS indexes from disk cache (< 5 seconds)
REM ============================================================
echo.
echo  =====================================================
echo   Industrial Diagnostic AI  ^|  Backend Startup
echo  =====================================================
echo.
echo  [INFO] FAISS indexes will be loaded from disk cache.
echo  [INFO] Startup should take less than 30 seconds.
echo.

cd /d "%~dp0"

REM Activate virtual environment if it exists
if exist ".venv\Scripts\activate.bat" (
    echo  [INFO] Activating virtual environment...
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    echo  [INFO] Activating virtual environment...
    call venv\Scripts\activate.bat
)

REM Start uvicorn
echo  [START] Launching FastAPI server on http://localhost:8000
echo  [TIP]   API Docs: http://localhost:8000/docs
echo.
uvicorn main:app --host 0.0.0.0 --port 8000 --reload --log-level info
