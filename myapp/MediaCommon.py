import datetime
import json
import os
import shutil
import subprocess
import threading
import time
import uuid

from django.conf import settings
from django.http import JsonResponse


_delete_timers = {}
_cleanup_worker_started = False

VIDEO_MIME_TYPES = {
    "mp4": "video/mp4",
    "avi": "video/x-msvideo",
    "mov": "video/quicktime",
    "wmv": "video/x-ms-wmv",
    "flv": "video/x-flv",
    "mkv": "video/x-matroska",
    "webm": "video/webm",
    "m4v": "video/mp4",
    "3gp": "video/3gpp",
    "gif": "image/gif",
}

AUDIO_MIME_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
    "m4a": "audio/mp4",
    "aac": "audio/aac",
}

MEDIA_MIME_TYPES = {**VIDEO_MIME_TYPES, **AUDIO_MIME_TYPES}

VIDEO_CODEC_SETTINGS = {
    "mp4": {"vcodec": "libx264", "acodec": "aac"},
    "m4v": {"vcodec": "libx264", "acodec": "aac"},
    "mov": {"vcodec": "libx264", "acodec": "aac"},
    "webm": {"vcodec": "libvpx-vp9", "acodec": "libopus"},
    "avi": {"vcodec": "mpeg4", "acodec": "mp3"},
    "wmv": {"vcodec": "wmv2", "acodec": "wmav2"},
    "flv": {"vcodec": "flv", "acodec": "mp3"},
    "mkv": {"vcodec": "libx264", "acodec": "aac"},
    "3gp": {"vcodec": "h263", "acodec": "aac"},
}

AUDIO_CODEC_SETTINGS = {
    "mp3": {"acodec": "libmp3lame"},
    "wav": {"acodec": "pcm_s16le"},
    "ogg": {"acodec": "libvorbis"},
    "flac": {"acodec": "flac"},
    "m4a": {"acodec": "aac"},
    "aac": {"acodec": "aac"},
}

MEDIA_FILE_TTL_SECONDS = 180
MEDIA_CLEANUP_INTERVAL_SECONDS = 30


def _output_dir():
    base_dir = getattr(settings, "MEDIA_ROOT", None)
    if not base_dir:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        base_dir = os.path.join(project_root, "media")
    output_dir = os.path.join(base_dir, "media_tools")
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def _safe_name(name):
    return os.path.basename(name).replace(" ", "_")


def _normalize_ext(value, fallback=None):
    if not value:
        return fallback
    value = str(value).strip().lower()
    if value.startswith("."):
        value = value[1:]
    if "/" in value:
        value = value.split("/")[-1]
    alias_map = {
        "x-matroska": "mkv",
        "x-msvideo": "avi",
        "quicktime": "mov",
        "x-ms-wmv": "wmv",
        "x-flv": "flv",
        "3gpp": "3gp",
    }
    value = alias_map.get(value, value)
    return value


def _find_ffmpeg():
    """البحث عن مسار FFmpeg في النظام"""
    # 1. التحقق من متغير البيئة المخصص
    custom = os.environ.get("FFMPEG_PATH")
    if custom and os.path.exists(custom):
        return custom
    
    # 2. البحث في PATH باستخدام which
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    
    # 3. مسارات افتراضية لأنظمة Unix/Linux
    if os.name != "nt":  # Linux/Unix/Mac
        unix_paths = [
            "/usr/bin/ffmpeg",
            "/usr/local/bin/ffmpeg",
            "/opt/bin/ffmpeg",
            "/snap/bin/ffmpeg",
        ]
        for path in unix_paths:
            if os.path.exists(path):
                return path
    
    # 4. مسارات افتراضية لنظام Windows
    else:  # Windows
        common_paths = [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path
    
    # 5. إذا لم يتم العثور على FFmpeg
    return None

def _find_ffprobe():
    custom = os.environ.get("FFPROBE_PATH")
    if custom and os.path.exists(custom):
        return custom
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        return ffprobe
    if os.name == "nt":
        common_paths = [
            r"C:\ffmpeg\bin\ffprobe.exe",
            r"C:\Program Files\ffmpeg\bin\ffprobe.exe",
            r"C:\Program Files (x86)\ffmpeg\bin\ffprobe.exe",
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path
    return None


def _ensure_ffmpeg():
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return None, JsonResponse(
            {"success": False, "error": "FFmpeg is not installed or not in PATH."},
            status=500,
        )
    return ffmpeg, None


def _run_command(args, timeout=900):
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            err = result.stderr or result.stdout or "Unknown FFmpeg error"
            return err.strip()
        return None
    except subprocess.TimeoutExpired:
        return "FFmpeg process timed out"
    except Exception as e:
        return str(e)


def _probe_duration_seconds(path):
    ffprobe = _find_ffprobe()
    if not ffprobe:
        return None
    args = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=20)
        if result.returncode != 0:
            return None
        return float(result.stdout.strip())
    except Exception:
        return None


def _schedule_deletion(file_id, delay_minutes=3):
    def delete_files():
        storage_dir = _output_dir()
        try:
            for filename in os.listdir(storage_dir):
                filepath = os.path.join(storage_dir, filename)
                if not os.path.isfile(filepath):
                    continue
                base, _ext = os.path.splitext(filename)
                if base == file_id:
                    os.remove(filepath)
                    print(
                        f"[Backend] Auto-deleted file after {delay_minutes} minutes: {filename}"
                    )
            if file_id in _delete_timers:
                del _delete_timers[file_id]
        except Exception as e:
            print(f"[Backend] Error in auto-delete: {e}")

    if file_id in _delete_timers:
        _delete_timers[file_id].cancel()

    timer = threading.Timer(delay_minutes * 60, delete_files)
    timer.daemon = True
    timer.start()
    _delete_timers[file_id] = timer

    print(f"[Backend] Scheduled deletion for {file_id} in {delay_minutes} minutes")
    return timer


def _store_output_file(path, output_ext, original_name=None):
    file_id = uuid.uuid4().hex
    output_ext = _normalize_ext(output_ext)
    stored_path = os.path.join(_output_dir(), f"{file_id}.{output_ext}")
    shutil.copy2(path, stored_path)

    info_path = os.path.join(_output_dir(), f"{file_id}.json")
    file_info = {
        "file_id": file_id,
        "original_name": original_name or os.path.basename(path),
        "stored_path": stored_path,
        "created_at": datetime.datetime.now().isoformat(),
        "expires_at": (
            datetime.datetime.now() + datetime.timedelta(minutes=3)
        ).isoformat(),
        "file_size": os.path.getsize(stored_path),
        "file_ext": output_ext,
        "auto_delete_after_minutes": 3,
    }

    try:
        with open(info_path, "w", encoding="utf-8") as f:
            json.dump(file_info, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Warning: Could not save file info: {e}")

    _schedule_deletion(file_id, 3)
    print(f"[Backend] File stored: {stored_path} (will be auto-deleted in 3 minutes)")
    return file_id, stored_path


def remove_stored_file(file_id):
    storage_dir = _output_dir()
    removed = []
    for filename in os.listdir(storage_dir):
        path = os.path.join(storage_dir, filename)
        if not os.path.isfile(path):
            continue
        base, _ext = os.path.splitext(filename)
        if base == file_id:
            os.remove(path)
            removed.append(filename)
    if file_id in _delete_timers:
        _delete_timers[file_id].cancel()
        del _delete_timers[file_id]
    return removed


def _audio_filter(remove_silence=False, normalize=False):
    filters = []
    if remove_silence:
        filters.append("silenceremove=1:0:-50dB")
    if normalize:
        filters.append("loudnorm")
    return ",".join(filters) if filters else None


def _resolution_scale(value):
    table = {
        "4k": "3840:2160",
        "1440p": "2560:1440",
        "1080p": "1920:1080",
        "720p": "1280:720",
        "480p": "854:480",
        "360p": "640:360",
    }
    return table.get(str(value).lower())


def _ffmpeg_error_response(message):
    return JsonResponse({"success": False, "error": message}, status=500)


def _append_video_quality_args(cmd, vcodec, quality, video_bitrate):
    crf_map = {"lossless": "16", "high": "22", "medium": "28", "low": "34"}

    if video_bitrate and str(video_bitrate).isdigit():
        cmd.extend(["-b:v", f"{video_bitrate}k"])
        return

    if vcodec in {"libx264", "libx265", "libvpx-vp9", "libvpx"}:
        cmd.extend(["-crf", crf_map.get(str(quality).lower(), "22")])
        if vcodec in {"libvpx-vp9", "libvpx"}:
            cmd.extend(["-b:v", "0"])
    elif vcodec in {"mpeg4", "wmv2", "flv", "h263"}:
        qscale_map = {"lossless": "2", "high": "4", "medium": "6", "low": "9"}
        cmd.extend(["-q:v", qscale_map.get(str(quality).lower(), "6")])
    else:
        cmd.extend(["-crf", "24"])


def cleanup_old_files():
    storage_dir = _output_dir()
    now = time.time()
    cutoff = MEDIA_FILE_TTL_SECONDS
    deleted_count = 0

    for filename in os.listdir(storage_dir):
        filepath = os.path.join(storage_dir, filename)
        if os.path.isfile(filepath):
            file_age = now - os.path.getmtime(filepath)
            if file_age > cutoff:
                try:
                    os.remove(filepath)
                    deleted_count += 1
                    print(f"[Backend] Cleaned up old file: {filename}")
                except Exception as e:
                    print(f"[Backend] Could not delete {filename}: {e}")

    if deleted_count > 0:
        print(f"[Backend] Cleaned up {deleted_count} old files")

    return deleted_count


def cleanup_media_root_files(ttl_seconds=MEDIA_FILE_TTL_SECONDS):
    media_root = getattr(settings, "MEDIA_ROOT", None)
    if not media_root:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        media_root = os.path.join(project_root, "media")

    now = time.time()
    deleted_count = 0

    if not os.path.exists(media_root):
        return 0

    for root, _dirs, files in os.walk(media_root):
        for filename in files:
            if filename == ".gitkeep":
                continue
            filepath = os.path.join(root, filename)
            try:
                if not os.path.isfile(filepath):
                    continue
                age_seconds = now - os.path.getmtime(filepath)
                if age_seconds > ttl_seconds:
                    os.remove(filepath)
                    deleted_count += 1
                    print(f"[Backend] Auto-cleaned media file: {filepath}")
            except Exception as exc:
                print(f"[Backend] Could not auto-clean media file {filepath}: {exc}")

    return deleted_count


def start_media_cleanup_worker(
    interval_seconds=MEDIA_CLEANUP_INTERVAL_SECONDS,
    ttl_seconds=MEDIA_FILE_TTL_SECONDS,
):
    global _cleanup_worker_started
    if _cleanup_worker_started:
        return
    _cleanup_worker_started = True

    def _loop():
        while True:
            try:
                cleanup_media_root_files(ttl_seconds=ttl_seconds)
            except Exception as exc:
                print(f"[Backend] Media cleanup worker error: {exc}")
            time.sleep(interval_seconds)

    thread = threading.Thread(target=_loop, daemon=True, name="media-cleanup-worker")
    thread.start()
    print(
        "[Backend] Media cleanup worker started "
        f"(ttl={ttl_seconds}s, interval={interval_seconds}s)"
    )


try:
    cleanup_old_files()
except Exception as e:
    print(f"[Backend] Startup cleanup skipped: {e}")
