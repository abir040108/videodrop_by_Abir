FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl git xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Node.js 20 is used by the BgUtils PO-token provider and by yt-dlp's
# JavaScript challenge solver.
RUN curl -fsSL https://nodejs.org/dist/v20.20.0/node-v20.20.0-linux-x64.tar.xz \
    | tar -xJ -C /usr/local --strip-components=1

# Install the BgUtils PO-token HTTP provider.
RUN git clone --depth 1 --branch 1.3.1 \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil-ytdlp-pot-provider \
    && cd /opt/bgutil-ytdlp-pot-provider/server \
    && npm ci \
    && npx tsc

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=10000
EXPOSE 10000

# Start the local PO-token provider, then the Flask app.
CMD ["sh", "-c", "node /opt/bgutil-ytdlp-pot-provider/server/build/main.js & exec gunicorn --workers 2 --threads 4 --timeout 300 --bind 0.0.0.0:${PORT} app:app"]
