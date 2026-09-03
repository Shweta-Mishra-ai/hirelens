@echo off
title HireLens Development Server Launcher
echo =======================================================
echo          HireLens - One-Click App Launcher
echo =======================================================
echo.

REM 1. Setup Backend Environment if missing
if not exist "backend\.env" (
    echo [*] Creating backend\.env from .env.example...
    copy "backend\.env.example" "backend\.env" >nul
)

REM 2. Setup Frontend Environment if missing
if not exist "frontend\.env.local" (
    echo [*] Creating frontend\.env.local from .env.local.example...
    copy "frontend\.env.local.example" "frontend\.env.local" >nul
)

REM 3. Launch Backend in a separate window
echo [*] Starting FastAPI Backend on http://localhost:8000...
start "HireLens Backend (Port 8000)" cmd /k "cd backend && python -m uvicorn app.main:app --reload --port 8000"

REM 4. Launch Frontend in a separate window
echo [*] Starting Next.js Frontend on http://localhost:3000...
start "HireLens Frontend (Port 3000)" cmd /k "cd frontend && npm run dev"

REM 5. Wait a moment and launch browser
echo [*] Waiting for services to initialize...
timeout /t 5 /nobreak >nul
echo [*] Opening HireLens in your default browser...
start http://localhost:3000

echo.
echo =======================================================
echo  App is running!
echo  - Frontend: http://localhost:3000
echo  - Backend API: http://localhost:8000/docs
echo =======================================================
echo.
pause
