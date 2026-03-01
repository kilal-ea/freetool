import json
import os
import re
import tempfile
import urllib.parse

from django.http import FileResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, MultiPartParser

from . import MediaCommon


def _load_video_for_gif(video_file, temp_dir):
    input_name = MediaCommon._safe_name(video_file.name)
    base_name = os.path.splitext(input_name)[0]
    input_path = os.path.join(temp_dir, input_name)
    with open(input_path, "wb") as f:
        for chunk in video_file.chunks():
            f.write(chunk)
    return base_name, input_path


def _find_media_file(file_id):
    storage_dir = MediaCommon._output_dir()
    target_path = None
    target_ext = None
    info_path = None
    for name in os.listdir(storage_dir):
        path = os.path.join(storage_dir, name)
        if not os.path.isfile(path):
            continue
        base, ext = os.path.splitext(name)
        if base == file_id and ext != ".json":
            target_path = path
            target_ext = ext.lower().lstrip(".")
        elif base == file_id and ext == ".json":
            info_path = path
    return target_path, target_ext, info_path


def _build_download_name(file_id, target_path, target_ext, info_path):
    original_filename = None
    if info_path and os.path.exists(info_path):
        try:
            with open(info_path, "r", encoding="utf-8") as f:
                info = json.load(f)
                original_filename = info.get("original_name")
                if original_filename:
                    base = os.path.splitext(original_filename)[0]
                    original_filename = f"{base}.{target_ext}"
        except Exception:
            pass
    filename = original_filename or os.path.basename(target_path)
    name, ext = os.path.splitext(filename)
    name = re.sub(r"\s*\(\d+\)\s*", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        name = f"video_{file_id[:8]}"
    return f"{name}{ext}"


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def convert_video_to_gif(request):
    print("============================gif request received============================")
    ffmpeg, error = MediaCommon._ensure_ffmpeg()
    if error:
        return error

    video_file = request.FILES.get("video_file") or request.FILES.get("file")
    if not video_file:
        return JsonResponse({"success": False, "error": "No video file provided."}, status=400)

    try:
        gif_settings = json.loads(request.POST.get("gif_settings", "{}"))
    except Exception:
        gif_settings = {}

    fps = max(1, int(gif_settings.get("frameRate", 10)))
    width = max(100, int(gif_settings.get("width", 480)))
    quality = max(1, min(100, int(gif_settings.get("quality", 85))))
    start_time = max(0.0, float(gif_settings.get("startTime", 0)))
    end_time = float(gif_settings.get("endTime", 0))
    loop_forever = bool(gif_settings.get("loop", True))
    duration = max(0.1, float(gif_settings.get("duration", 5)))

    if end_time <= start_time:
        end_time = start_time + duration

    original_size = video_file.size

    with tempfile.TemporaryDirectory() as temp_dir:
        base_name, input_path = _load_video_for_gif(video_file, temp_dir)
        output_path = os.path.join(temp_dir, f"{base_name}.gif")

        vf = f"fps={fps},scale={width}:-1:flags=lanczos"
        cmd = [
            ffmpeg,
            "-y",
            "-ss",
            str(start_time),
            "-to",
            str(end_time),
            "-i",
            input_path,
            "-vf",
            vf,
            "-an",
            "-loop",
            "0" if loop_forever else "1",
        ]

        if quality < 60:
            cmd.extend(["-fs", "25M"])

        cmd.append(output_path)

        ffmpeg_error = MediaCommon._run_command(cmd, timeout=600)
        if ffmpeg_error:
            return MediaCommon._ffmpeg_error_response(ffmpeg_error)

        if not os.path.exists(output_path):
            return MediaCommon._ffmpeg_error_response("GIF output not generated.")

        converted_size = os.path.getsize(output_path)
        file_id, _ = MediaCommon._store_output_file(output_path, "gif", video_file.name)

    filename = f"{base_name}_{file_id[:8]}.gif"
    return JsonResponse(
        {
            "success": True,
            "file_id": file_id,
            "filename": filename,
            "original_name": video_file.name,
            "original_size": original_size,
            "converted_size": converted_size,
            "saved_bytes": max(0, original_size - converted_size),
            "download_url": request.build_absolute_uri(f"/api/convert/video-to-gif/download/{file_id}/"),
            "expires_in_minutes": 3,
        }
    )


@api_view(["GET"])
def download_media_file(request, file_id):
    target_path, target_ext, info_path = _find_media_file(file_id)
    if not target_path or not target_ext:
        return JsonResponse({"success": False, "error": "File not found or already expired."}, status=404)

    if target_ext == "gif":
        mime = "image/gif"
    elif target_ext in MediaCommon.VIDEO_MIME_TYPES:
        mime = "video/avi" if target_ext == "avi" else MediaCommon.VIDEO_MIME_TYPES[target_ext]
    elif target_ext in MediaCommon.AUDIO_MIME_TYPES:
        mime = MediaCommon.AUDIO_MIME_TYPES[target_ext]
    else:
        mime = "application/octet-stream"

    filename = _build_download_name(file_id, target_path, target_ext, info_path)
    try:
        file_handle = open(target_path, "rb")
        file_size = os.path.getsize(target_path)
    except Exception as e:
        return JsonResponse({"success": False, "error": f"Could not open file: {str(e)}"}, status=500)

    response = FileResponse(file_handle, as_attachment=True, filename=filename, content_type=mime)
    response["Access-Control-Expose-Headers"] = "Content-Disposition, Content-Type, Content-Length, Accept-Ranges"
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response["Access-Control-Allow-Headers"] = "*"
    response["Content-Length"] = str(file_size)
    response["Content-Type"] = mime
    if target_ext in ["avi", "mp4", "mov", "wmv"]:
        response["Accept-Ranges"] = "bytes"
        response["Cache-Control"] = "public, max-age=3600"
        response["Content-Disposition"] = (
            f"attachment; filename=\"{filename}\"; filename*=UTF-8''{urllib.parse.quote(filename)}"
        )
    else:
        response["Content-Disposition"] = f"attachment; filename=\"{filename}\""
        response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


@api_view(["POST", "DELETE"])
def remove_media_file(request, file_id):
    storage_dir = MediaCommon._output_dir()
    removed = []
    for filename in os.listdir(storage_dir):
        path = os.path.join(storage_dir, filename)
        if not os.path.isfile(path):
            continue
        base, _ext = os.path.splitext(filename)
        if base == file_id:
            os.remove(path)
            removed.append(filename)
    if file_id in MediaCommon._delete_timers:
        MediaCommon._delete_timers[file_id].cancel()
        del MediaCommon._delete_timers[file_id]
    if not removed:
        return JsonResponse({"success": False, "error": "File not found or already removed."}, status=404)
    return JsonResponse({"success": True, "file_id": file_id, "removed_files": removed})
