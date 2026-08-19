FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=5000
EXPOSE 5000

# Pull the newest yt-dlp every time the CONTAINER STARTS (not just when
# Docker decides to rebuild this image). Render (and most hosts) reuse the
# Docker build cache between deploys, so a build-time "pip install -U
# yt-dlp" can silently stay stale for months even though it looks like it
# should always fetch latest. Doing the upgrade in the start command means
# every deploy and every restart gets a fresh yt-dlp — which matters a lot
# since YouTube changes its site often and breaks older extractor versions.
CMD ["sh", "-c", "pip install --no-cache-dir -U yt-dlp && gunicorn --workers 2 --threads 4 --timeout 300 --bind 0.0.0.0:${PORT} app:app"]

