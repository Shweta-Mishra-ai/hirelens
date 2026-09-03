#!/usr/bin/env bash
# HireLens — One-Click Development Launcher (macOS / Linux)

echo "======================================================="
echo "         HireLens — One-Click App Launcher"
echo "======================================================="

# 1. Setup Backend Environment if missing
if [ ! -f "backend/.env" ]; then
    echo "[*] Creating backend/.env from .env.example..."
    cp backend/.env.example backend/.env
fi

# 2. Setup Frontend Environment if missing
if [ ! -f "frontend/.env.local" ]; then
    echo "[*] Creating frontend/.env.local from .env.local.example..."
    cp frontend/.env.local.example frontend/.env.local
fi

# 3. Start Backend
echo "[*] Starting FastAPI Backend on http://localhost:8000..."
(cd backend && python3 -m uvicorn app.main:app --reload --port 8000) &
BACKEND_PID=$!

# 4. Start Frontend
echo "[*] Starting Next.js Frontend on http://localhost:3000..."
(cd frontend && npm run dev) &
FRONTEND_PID=$!

trap "kill $BACKEND_PID $FRONTEND_PID" EXIT

echo "Services running. Press Ctrl+C to stop."
wait
