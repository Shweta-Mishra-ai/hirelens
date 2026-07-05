#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# HireLens — One-Command Deploy Script
# Run this on YOUR machine (not in Claude's environment)
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh
#
# What it does:
#   1. Checks prerequisites
#   2. Collects your API keys interactively
#   3. Pushes to GitHub
#   4. Guides you through Render + Vercel deployment
# ─────────────────────────────────────────────────────────────────────────────

set -e
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║           HireLens — Deploy Script v1.0                 ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 1: Check prerequisites ──────────────────────────────────────────────
echo -e "${YELLOW}[1/6] Checking prerequisites...${NC}"

check_cmd() {
  if ! command -v "$1" &>/dev/null; then
    echo -e "${RED}✗ $1 not found. Please install it first.${NC}"
    exit 1
  fi
  echo -e "${GREEN}✓ $1 found${NC}"
}

check_cmd git
check_cmd node
check_cmd npm
check_cmd python3

echo ""
echo -e "${YELLOW}[2/6] GitHub repository setup...${NC}"
echo ""
echo "Make sure you have created a GitHub repo named 'hirelens'"
echo "at: https://github.com/new"
echo ""
read -p "Enter your GitHub username: " GH_USER
read -p "Enter repo name (default: hirelens): " GH_REPO
GH_REPO=${GH_REPO:-hirelens}
REPO_URL="https://github.com/${GH_USER}/${GH_REPO}.git"
echo -e "${GREEN}→ Will push to: ${REPO_URL}${NC}"

# ── Step 3: Collect API keys ──────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[3/6] Collecting configuration...${NC}"
echo ""
echo "You need:"
echo "  • Gemini API key → https://aistudio.google.com (free)"
echo "  • Supabase project → https://supabase.com (free)"
echo "  • Upstash Redis → https://upstash.com (free, optional)"
echo ""

read -p "Gemini API key (REQUIRED): " GEMINI_KEY
read -p "Groq API key (optional fallback, press Enter to skip): " GROQ_KEY
read -p "Supabase URL (e.g. https://xyz.supabase.co): " SUPA_URL
read -p "Supabase Service Role key: " SUPA_SERVICE
read -p "Supabase Anon key: " SUPA_ANON
read -p "Database URL (postgresql://...): " DB_URL
read -p "Upstash Redis URL (optional, press Enter to skip): " REDIS_URL
read -p "Upstash Redis password (optional): " REDIS_PASS
read -p "Your Vercel app URL (leave blank for now, fill later): " VERCEL_URL

# Generate secret key
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
echo -e "${GREEN}✓ Generated SECRET_KEY${NC}"

# Write backend .env
cat > backend/.env << ENVEOF
APP_ENV=production
SECRET_KEY=${SECRET_KEY}
ALLOWED_ORIGINS=http://localhost:3000${VERCEL_URL:+,${VERCEL_URL}}

DATABASE_URL=${DB_URL}
SUPABASE_URL=${SUPA_URL}
SUPABASE_SERVICE_KEY=${SUPA_SERVICE}
SUPABASE_ANON_KEY=${SUPA_ANON}

GEMINI_API_KEY=${GEMINI_KEY}
GROQ_API_KEY=${GROQ_KEY}

REDIS_URL=${REDIS_URL}
REDIS_PASSWORD=${REDIS_PASS}

MAX_FILE_SIZE_MB=10
RATE_LIMIT_PER_MINUTE=20
ANALYSIS_TIMEOUT_SECONDS=120
ENVEOF

echo -e "${GREEN}✓ backend/.env created (not committed to git)${NC}"

# Write frontend .env.local
cat > frontend/.env.local << ENVEOF
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=${SUPA_URL}
NEXT_PUBLIC_SUPABASE_ANON_KEY=${SUPA_ANON}
ENVEOF

echo -e "${GREEN}✓ frontend/.env.local created${NC}"

# ── Step 4: Install & test locally ───────────────────────────────────────────
echo ""
echo -e "${YELLOW}[4/6] Installing dependencies...${NC}"

echo "→ Installing backend dependencies..."
cd backend
python3 -m pip install -r requirements.txt -q
echo -e "${GREEN}✓ Backend deps installed${NC}"

echo "→ Installing frontend dependencies..."
cd ../frontend
npm install --silent
echo -e "${GREEN}✓ Frontend deps installed${NC}"
cd ..

# ── Step 5: Git push ──────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[5/6] Pushing to GitHub...${NC}"

if [ ! -d ".git" ]; then
  git init
  echo -e "${GREEN}✓ Git initialized${NC}"
fi

# Set remote
if git remote get-url origin &>/dev/null; then
  git remote set-url origin "$REPO_URL"
else
  git remote add origin "$REPO_URL"
fi

git add .
git commit -m "feat: HireLens MVP — AI recruiter intelligence with Gemini 2.5 Flash" 2>/dev/null || git commit --allow-empty -m "chore: update"
git branch -M main
git push -u origin main

echo -e "${GREEN}✓ Pushed to GitHub: ${REPO_URL}${NC}"

# ── Step 6: Deployment instructions ──────────────────────────────────────────
echo ""
echo -e "${YELLOW}[6/6] Deployment steps...${NC}"
echo ""
echo -e "${BLUE}══════════════════════════════════════════${NC}"
echo -e "${BLUE}  BACKEND → Render (Free)                ${NC}"
echo -e "${BLUE}══════════════════════════════════════════${NC}"
echo ""
echo "1. Go to https://render.com → New → Web Service"
echo "2. Connect your GitHub repo: ${GH_USER}/${GH_REPO}"
echo "3. Root directory: backend"
echo "4. Runtime: Docker"
echo "5. Add these Environment Variables in Render dashboard:"
echo ""
echo "   APP_ENV = production"
echo "   SECRET_KEY = ${SECRET_KEY}"
echo "   GEMINI_API_KEY = ${GEMINI_KEY}"
echo "   SUPABASE_URL = ${SUPA_URL}"
echo "   SUPABASE_SERVICE_KEY = ${SUPA_SERVICE}"
echo "   DATABASE_URL = ${DB_URL}"
echo "   REDIS_URL = ${REDIS_URL}"
if [ -n "$GROQ_KEY" ]; then
echo "   GROQ_API_KEY = ${GROQ_KEY}"
fi
echo ""
echo "6. Click Deploy → wait ~3 mins"
echo "7. Copy your Render URL (e.g. https://hirelens-api.onrender.com)"
echo ""
echo -e "${BLUE}══════════════════════════════════════════${NC}"
echo -e "${BLUE}  FRONTEND → Vercel (Free)               ${NC}"
echo -e "${BLUE}══════════════════════════════════════════${NC}"
echo ""
echo "1. Go to https://vercel.com → Add New → Project"
echo "2. Import: ${GH_USER}/${GH_REPO}"
echo "3. Root Directory: frontend"
echo "4. Framework: Next.js"
echo "5. Environment Variables:"
echo ""
echo "   NEXT_PUBLIC_API_URL = https://your-app.onrender.com  ← Render URL from above"
echo "   NEXT_PUBLIC_SUPABASE_URL = ${SUPA_URL}"
echo "   NEXT_PUBLIC_SUPABASE_ANON_KEY = ${SUPA_ANON}"
echo ""
echo "6. Click Deploy → wait ~2 mins"
echo ""
echo -e "${BLUE}══════════════════════════════════════════${NC}"
echo -e "${BLUE}  SUPABASE — Run this SQL once            ${NC}"
echo -e "${BLUE}══════════════════════════════════════════${NC}"
echo ""
echo "Go to https://supabase.com → SQL Editor → paste & run:"
echo ""
cat << 'SQLEOF'
-- Run once in Supabase SQL Editor

CREATE TABLE IF NOT EXISTS public.reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  job_id UUID,
  file_name TEXT NOT NULL,
  candidate_name TEXT,
  overall_score INTEGER CHECK (overall_score BETWEEN 0 AND 100),
  recommendation TEXT CHECK (recommendation IN ('recommended','manual_review','high_risk')),
  report_data JSONB NOT NULL DEFAULT '{}',
  recruiter_decision TEXT CHECK (recruiter_decision IN ('advance','schedule_followup','reject')),
  decision_notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.reports ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users own their reports"
  ON public.reports FOR ALL USING (auth.uid() = user_id);

CREATE INDEX IF NOT EXISTS idx_reports_user_id ON public.reports(user_id);
CREATE INDEX IF NOT EXISTS idx_reports_created_at ON public.reports(created_at DESC);
SQLEOF

echo ""
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✓ SETUP COMPLETE                        ${NC}"
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo ""
echo -e "GitHub: ${BLUE}https://github.com/${GH_USER}/${GH_REPO}${NC}"
echo -e "Render docs: ${BLUE}https://render.com/docs${NC}"
echo -e "Vercel docs: ${BLUE}https://vercel.com/docs${NC}"
echo ""
echo "After both deployments, update ALLOWED_ORIGINS in Render to include your Vercel URL."
echo ""
