# HireLens API — production image.
#
# 3.12, the version CI tests against. This read 3.11, so production ran an
# interpreter no test had ever run on.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# No compiler toolchain. Every pinned dependency publishes a prebuilt
# manylinux wheel for CPython 3.12 (checked against constraints.txt), so the
# gcc/g++/libffi-dev/libssl-dev layer this image used to install was ~200MB
# that nothing used. `--only-binary=:all:` keeps it that way: a future
# dependency without a wheel fails the build loudly here, instead of trying to
# compile and failing obscurely.
COPY requirements.txt constraints.txt ./
RUN pip install --upgrade pip && \
    pip install --only-binary=:all: -r requirements.txt -c constraints.txt

COPY . .

# Non-root user. /app/data is where the local SQLite fallback writes.
RUN useradd -m -u 1000 -s /bin/bash hirelens && \
    mkdir -p /app/data && \
    chown -R hirelens:hirelens /app
USER hirelens

# Render (and most platforms) tell the container which port to bind through
# $PORT. 8000 is the fallback for running the image by hand.
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK \
    --interval=30s \
    --timeout=10s \
    --start-period=20s \
    --retries=3 \
    CMD python3 -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/v1/health' % os.environ.get('PORT', '8000'), timeout=5)" || exit 1

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
#
# `exec` makes uvicorn PID 1, so the platform's SIGTERM on a deploy reaches it
# directly and in-flight requests get the graceful-shutdown window, rather
# than the shell absorbing the signal and the process being killed outright.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --log-level info --access-log --timeout-graceful-shutdown 20 --no-proxy-headers"]
