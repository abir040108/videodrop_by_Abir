# VideoDrop — YouTube Link Downloader

Developed by **Ashikul Islam Abir**.

This is the complete version: a frontend plus a server backend. A plain HTML page alone cannot reliably inspect and download YouTube media streams.

## Features

- Paste a YouTube video URL
- Read the video's title, channel, thumbnail and duration
- List currently available video/audio formats
- Download a selected format
- Automatically merge separate video + audio streams when required
- Export audio as MP3 (192 kbps)
- Reject playlists and non-YouTube URLs
- Developer credit and supplied photo included
- Permission confirmation built into the UI

Use it only for videos you own or have permission/right to save.

## Requirements

- Python 3.10+
- FFmpeg
- Internet connection

## Run locally

### 1. Install FFmpeg

Windows:
Install FFmpeg and make sure `ffmpeg` is available in PATH.

Ubuntu/Debian:
```bash
sudo apt update
sudo apt install ffmpeg
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Windows:
```bash
.venv\Scripts\activate
```

macOS/Linux:
```bash
source .venv/bin/activate
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Start the site

```bash
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

## Docker

```bash
docker build -t videodrop .
docker run --rm -p 5000:5000 videodrop
```

Then open:

```text
http://127.0.0.1:5000
```

## Deployment

The included Dockerfile is the easiest deployment route because it installs FFmpeg.

For a public deployment, add production protections such as:
- HTTPS
- rate limiting
- authentication or quotas if needed
- maximum file/duration limits appropriate for your server
- sufficient disk/RAM/bandwidth
- abuse monitoring

The default maximum duration is 2 hours. Change it with:

```text
MAX_DURATION_SECONDS=3600
```

## Updating the extractor

YouTube changes often. Keep yt-dlp updated:

```bash
pip install -U yt-dlp
```
