from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, after_this_request, jsonify, render_template, request, send_file
import yt_dlp


app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

MAX_DURATION_SECONDS = int(os.getenv("MAX_DURATION_SECONDS", "7200"))
MAX_FORMATS_RETURNED = int(os.getenv("MAX_FORMATS_RETURNED", "60"))

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}


def is_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return parsed.scheme in {"http", "https"} and (
            host in YOUTUBE_HOSTS or host.endswith(".youtube.com")
        )
    except Exception:
        return False


def base_ydl_options() -> dict:
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "cachedir": False,
        "socket_timeout": 20,
        # Use the local BgUtils PO-token provider. This helps yt-dlp
        # satisfy YouTube's current proof-of-origin checks.
        "extractor_args": {
            "youtubepot-bgutilhttp": {
                "base_url": "http://127.0.0.1:4416"
            }
        },
    }


def extract_video_info(url: str) -> dict:
    with yt_dlp.YoutubeDL(base_ydl_options()) as ydl:
        info = ydl.extract_info(url, download=False)

    if not isinstance(info, dict):
        raise ValueError("Unable to read this video.")

    # Ensure a single video, never a whole playlist.
    if info.get("_type") in {"playlist", "multi_video"}:
        entries = info.get("entries") or []
        info = next((x for x in entries if isinstance(x, dict)), None)
        if not info:
            raise ValueError("No downloadable video was found.")

    duration = info.get("duration")
    if duration and duration > MAX_DURATION_SECONDS:
        minutes = MAX_DURATION_SECONDS // 60
        raise ValueError(f"This server is limited to videos up to {minutes} minutes.")

    return info


def filesize_for(fmt: dict):
    return fmt.get("filesize") or fmt.get("filesize_approx")


def format_kind(fmt: dict) -> str:
    has_video = fmt.get("vcodec") not in (None, "none")
    has_audio = fmt.get("acodec") not in (None, "none")
    if has_video and has_audio:
        return "Video + Audio"
    if has_video:
        return "Video"
    if has_audio:
        return "Audio"
    return "Other"


def build_format_list(info: dict) -> list[dict]:
    raw_formats = info.get("formats") or []
    candidates = []

    for fmt in raw_formats:
        fmt_id = str(fmt.get("format_id") or "")
        if not fmt_id or not re.fullmatch(r"[A-Za-z0-9._-]+", fmt_id):
            continue

        has_video = fmt.get("vcodec") not in (None, "none")
        has_audio = fmt.get("acodec") not in (None, "none")
        if not has_video and not has_audio:
            continue

        ext = (fmt.get("ext") or "unknown").lower()
        height = fmt.get("height")
        width = fmt.get("width")
        fps = fmt.get("fps")
        abr = fmt.get("abr")
        tbr = fmt.get("tbr")
        kind = format_kind(fmt)

        if has_video:
            resolution = f"{height}p" if height else (
                f"{width}x{height}" if width and height else "Video"
            )
        else:
            resolution = f"{round(abr)} kbps" if abr else "Audio"

        candidates.append({
            "id": fmt_id,
            "ext": ext,
            "kind": kind,
            "resolution": resolution,
            "height": height or 0,
            "fps": fps,
            "abr": abr,
            "tbr": tbr or 0,
            "filesize": filesize_for(fmt),
            "needs_merge": bool(has_video and not has_audio),
            "has_video": has_video,
            "has_audio": has_audio,
            "vcodec": fmt.get("vcodec"),
            "acodec": fmt.get("acodec"),
        })

    # Reduce near-duplicates while preserving genuinely different file types.
    best_by_key = {}
    for item in candidates:
        if item["has_video"]:
            key = (
                "video",
                item["ext"],
                item["height"],
                bool(item["has_audio"]),
                round(item["fps"] or 0),
            )
        else:
            # Keep one strong audio option per extension.
            key = ("audio", item["ext"])

        existing = best_by_key.get(key)
        if existing is None:
            best_by_key[key] = item
        else:
            current_score = (
                item["tbr"],
                item["filesize"] or 0,
                item["abr"] or 0,
            )
            existing_score = (
                existing["tbr"],
                existing["filesize"] or 0,
                existing["abr"] or 0,
            )
            if current_score > existing_score:
                best_by_key[key] = item

    result = list(best_by_key.values())
    result.sort(
        key=lambda x: (
            1 if x["has_video"] else 0,
            x["height"],
            1 if x["has_audio"] else 0,
            x["tbr"],
        ),
        reverse=True,
    )

    return result[:MAX_FORMATS_RETURNED]


def find_selected_format(info: dict, fmt_id: str) -> dict | None:
    for fmt in info.get("formats") or []:
        if str(fmt.get("format_id")) == fmt_id:
            return fmt
    return None


def choose_selector(fmt_id: str, fmt: dict) -> tuple[str, str | None]:
    ext = (fmt.get("ext") or "").lower()
    has_video = fmt.get("vcodec") not in (None, "none")
    has_audio = fmt.get("acodec") not in (None, "none")

    if has_video and not has_audio:
        if ext == "mp4":
            selector = f"({fmt_id}+bestaudio[ext=m4a])/({fmt_id}+bestaudio)"
            return selector, "mp4"
        if ext == "webm":
            selector = f"({fmt_id}+bestaudio[ext=webm])/({fmt_id}+bestaudio)"
            return selector, "webm"
        return f"{fmt_id}+bestaudio", None

    return fmt_id, None


def newest_media_file(folder: Path) -> Path | None:
    ignored = {".part", ".ytdl", ".json", ".jpg", ".jpeg", ".png", ".webp"}
    files = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() not in ignored
    ]
    if not files:
        return None
    return max(files, key=lambda p: (p.stat().st_mtime, p.stat().st_size))


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.post("/api/info")
def api_info():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url") or "").strip()
    permission = data.get("permission") is True

    if not permission:
        return jsonify({"error": "Confirm that you have permission to save this video."}), 400

    if not is_youtube_url(url):
        return jsonify({"error": "Please enter a valid YouTube video URL."}), 400

    try:
        info = extract_video_info(url)
        formats = build_format_list(info)

        if not formats:
            return jsonify({"error": "No downloadable formats were returned for this video."}), 404

        return jsonify({
            "title": info.get("title") or "YouTube video",
            "channel": info.get("channel") or info.get("uploader") or "YouTube",
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "webpage_url": info.get("webpage_url") or url,
            "formats": formats,
            "mp3_available": True,
        })
    except yt_dlp.utils.DownloadError as exc:
        return jsonify({"error": f"Could not read that YouTube video: {str(exc)}"}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/download")
def api_download():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url") or "").strip()
    fmt_id = str(data.get("format_id") or "").strip()
    mode = str(data.get("mode") or "format").strip()
    permission = data.get("permission") is True

    if not permission:
        return jsonify({"error": "Confirm that you have permission to save this video."}), 400

    if not is_youtube_url(url):
        return jsonify({"error": "Please enter a valid YouTube video URL."}), 400

    if mode not in {"format", "mp3"}:
        return jsonify({"error": "Invalid download mode."}), 400

    if mode == "format" and not re.fullmatch(r"[A-Za-z0-9._-]+", fmt_id):
        return jsonify({"error": "Invalid format ID."}), 400

    temp_dir = Path(tempfile.mkdtemp(prefix="videodrop_"))

    @after_this_request
    def cleanup(response):
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        finally:
            return response

    try:
        info = extract_video_info(url)

        opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "cachedir": False,
            "socket_timeout": 20,
            "extractor_args": {
                "youtubepot-bgutilhttp": {
                    "base_url": "http://127.0.0.1:4416"
                }
            },
            "paths": {"home": str(temp_dir)},
            "outtmpl": {
                "default": str(temp_dir / "%(title).120B [%(id)s].%(ext)s")
            },
            "overwrites": True,
            "windowsfilenames": True,
        }

        if mode == "mp3":
            opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })
        else:
            selected = find_selected_format(info, fmt_id)
            if not selected:
                return jsonify({"error": "That format is no longer available. Analyze the link again."}), 400

            selector, merge_ext = choose_selector(fmt_id, selected)
            opts["format"] = selector
            if merge_ext:
                opts["merge_output_format"] = merge_ext

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        output = newest_media_file(temp_dir)
        if not output or not output.exists():
            return jsonify({"error": "The download finished, but the output file could not be found."}), 500

        return send_file(
            output,
            as_attachment=True,
            download_name=output.name,
            conditional=True,
            max_age=0,
        )

    except yt_dlp.utils.DownloadError as exc:
        return jsonify({"error": f"Download failed: {str(exc)}"}), 400
    except Exception as exc:
        return jsonify({"error": f"Download failed: {str(exc)}"}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG") == "1")
