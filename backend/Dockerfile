FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies needed for pdfminer and cryptography
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libffi-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user for security
RUN useradd -m -u 1000 -s /bin/bash hirelens && \
    chown -R hirelens:hirelens /app
USER hirelens

# Expose port
EXPOSE 8000

# Health check — Render uses this
HEALTHCHECK \
    --interval=30s \
    --timeout=10s \
    --start-period=20s \
    --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health', timeout=5)" || exit 1

# Start server
#
# IMPORTANT: this must stay at 1 worker unless REDIS_URL is configured.
# The job/report tracking in app/services/queue/job_store.py falls back to
# a plain in-process dict when Redis isn't set. With >1 uvicorn worker,
# requests load-balance across processes that don't share that dict —
# uploads land on worker A, but status polls and report reads that hit
# worker B get a false "not found", even though the analysis succeeded.
# (See job_store.py's module docstring for the full explanation.)
#
# To scale beyond 1 worker: set REDIS_URL in the environment first, then
# raise --workers here. Do not raise this number without Redis configured.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--log-level", "info", \
     "--access-log"]
