@echo off
REM ============================================================
REM  rebuild_index.bat  —  Force re-embed all FAISS indexes
REM  Run this ONLY when your source data files change.
REM  WARNING: This will take ~45 minutes.
REM ============================================================
echo.
echo  =====================================================
echo   FAISS Index Rebuild (SLOW - source data changed)
echo  =====================================================
echo.
echo  [WARNING] This deletes the cached FAISS indexes and
echo            rebuilds them from scratch by re-embedding
echo            all documents. This may take 30-45 minutes.
echo.
set /p CONFIRM="  Type YES to continue: "
if /i not "%CONFIRM%"=="YES" (
    echo  [CANCELLED] Rebuild aborted.
    exit /b 0
)

echo.
echo  [INFO] Deleting cached FAISS index files...
del /f /q "faiss_indexes\failure_iq.faiss" 2>nul
del /f /q "faiss_indexes\failure_iq_docs.pkl" 2>nul
del /f /q "faiss_indexes\afrb.faiss" 2>nul
del /f /q "faiss_indexes\afrb_docs.pkl" 2>nul
del /f /q "faiss_indexes\afrb_synthetic.faiss" 2>nul
del /f /q "faiss_indexes\afrb_synthetic_docs.pkl" 2>nul
del /f /q "faiss_indexes\*_meta.json" 2>nul
echo  [OK] Cache cleared.
echo.
echo  [START] Starting backend — indexes will be rebuilt now...
echo          Check the console for progress logs.
echo.

cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

uvicorn main:app --host 0.0.0.0 --port 8000 --log-level info
