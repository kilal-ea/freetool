import json
import logging
import os
import re
import tempfile
import urllib.parse

from django.http import FileResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, MultiPartParser

from . import MediaCommon

logger = logging.getLogger(__name__)


def _classify_ffmpeg_compress_error(message):
    text = (message or "").lower()
    if not text:
        return 500, "Video compression failed."
    if "invalid data found when processing input" in text:
        return 400, "Invalid or corrupted video file."
    if "moov atom not found" in text:
        return 400, "Invalid MP4 file (moov atom not found)."
    if "permission denied" in text:
        return 500, "Server could not read or write temporary media files."
    if "unknown encoder" in text:
        return 500, "Server encoder is unavailable for this format."
    return 500, message


def _build_scale_filter(target_resolution):
    scale = MediaCommon._resolution_scale(target_resolution)
    if not scale:
        return None
    # Ensure even dimensions for codecs like H.264 while preserving aspect ratio.
    return f"scale={scale}:force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2"


def _load_video_for_compress(video_file, temp_dir):
    input_name = MediaCommon._safe_name(video_file.name)
    base_name = os.path.splitext(input_name)[0]
    input_path = os.path.join(temp_dir, input_name)
    with open(input_path, "wb") as f:
        for chunk in video_file.chunks():
            f.write(chunk)
    return input_name, base_name, input_path


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
def compress_video(request):
    try:
        ffmpeg, error = MediaCommon._ensure_ffmpeg()
        if error:
            return error

        video_file = request.FILES.get("video_file") or request.FILES.get("file")
        if not video_file:
            return JsonResponse({"success": False, "error": "No video file provided."}, status=400)

        try:
            settings_data = json.loads(request.POST.get("compression_settings", "{}"))
        except Exception:
            settings_data = {}

        try:
            compression_level = max(1, min(100, int(settings_data.get("compression_level", 70))))
        except (TypeError, ValueError):
            compression_level = 70
        reduce_resolution = bool(settings_data.get("reduce_resolution", False))
        target_resolution = settings_data.get("target_resolution", "1080p")
        reduce_framerate = bool(settings_data.get("reduce_framerate", False))
        target_framerate = settings_data.get("target_framerate", "30")
        remove_audio = bool(settings_data.get("remove_audio", False))
        optimize_for_web = bool(settings_data.get("optimize_for_web", True))
        output_format = MediaCommon._normalize_ext(settings_data.get("output_format"))

        input_name = MediaCommon._safe_name(video_file.name)
        input_ext = MediaCommon._normalize_ext(os.path.splitext(input_name)[1], "mp4")

        if output_format in {None, "", "same"}:
            output_format = input_ext
        if output_format not in MediaCommon.VIDEO_CODEC_SETTINGS:
            output_format = "mp4"

        original_size = video_file.size
        base_name = os.path.splitext(input_name)[0]

        with tempfile.TemporaryDirectory() as temp_dir:
            _input_name, base_name, input_path = _load_video_for_compress(video_file, temp_dir)
            output_path = os.path.join(temp_dir, f"{base_name}.{output_format}")

            codecs = MediaCommon.VIDEO_CODEC_SETTINGS[output_format]
            quality = "low" if compression_level >= 75 else "medium" if compression_level >= 45 else "high"

            cmd = [ffmpeg, "-y", "-i", input_path, "-c:v", codecs["vcodec"]]
            MediaCommon._append_video_quality_args(cmd, codecs["vcodec"], quality, "")

            if reduce_resolution:
                scale_filter = _build_scale_filter(target_resolution)
                if scale_filter:
                    cmd.extend(["-vf", scale_filter])

            if reduce_framerate and str(target_framerate).strip().isdigit():
                cmd.extend(["-r", str(target_framerate)])

            if remove_audio:
                cmd.append("-an")
            else:
                cmd.extend(["-c:a", codecs["acodec"], "-b:a", "96k"])

            if optimize_for_web and output_format in {"mp4", "m4v"}:
                cmd.extend(["-movflags", "+faststart"])

            cmd.append(output_path)

            ffmpeg_error = MediaCommon._run_command(cmd)
            if ffmpeg_error:
                fallback_format = "mp4"
                fallback_output_path = os.path.join(temp_dir, f"{base_name}.{fallback_format}")
                fallback_codecs = MediaCommon.VIDEO_CODEC_SETTINGS[fallback_format]
                fallback_cmd = [
                    ffmpeg,
                    "-y",
                    "-i",
                    input_path,
                    "-c:v",
                    fallback_codecs["vcodec"],
                    "-pix_fmt",
                    "yuv420p",
                ]
                MediaCommon._append_video_quality_args(fallback_cmd, fallback_codecs["vcodec"], quality, "")

                if reduce_resolution:
                    scale_filter = _build_scale_filter(target_resolution)
                    if scale_filter:
                        fallback_cmd.extend(["-vf", scale_filter])

                if reduce_framerate and str(target_framerate).strip().isdigit():
                    fallback_cmd.extend(["-r", str(target_framerate)])

                if remove_audio:
                    fallback_cmd.append("-an")
                else:
                    fallback_cmd.extend(["-c:a", fallback_codecs["acodec"], "-b:a", "96k"])

                if optimize_for_web:
                    fallback_cmd.extend(["-movflags", "+faststart"])

                fallback_cmd.append(fallback_output_path)
                fallback_error = MediaCommon._run_command(fallback_cmd)
                if fallback_error:
                    status, error_message = _classify_ffmpeg_compress_error(
                        f"Primary compression failed: {ffmpeg_error}. Fallback MP4 failed: {fallback_error}"
                    )
                    return JsonResponse({"success": False, "error": error_message}, status=status)

                output_format = fallback_format
                output_path = fallback_output_path

            if not os.path.exists(output_path):
                return JsonResponse({"success": False, "error": "Compressed output not generated."}, status=500)

            compressed_size = os.path.getsize(output_path)
            duration = MediaCommon._probe_duration_seconds(output_path) or 0
            bitrate = int((compressed_size * 8) / duration) if duration > 0 else 0

            file_id, _ = MediaCommon._store_output_file(output_path, output_format, video_file.name)

        filename = f"{base_name}_{file_id[:8]}.{output_format}"
        return JsonResponse(
            {
                "success": True,
                "file_id": file_id,
                "filename": filename,
                "original_name": video_file.name,
                "original_size": original_size,
                "compressed_size": compressed_size,
                "saved_bytes": max(0, original_size - compressed_size),
                "bitrate": bitrate,
                "download_url": request.build_absolute_uri(f"/api/compress/video/download/{file_id}/"),
                "expires_in_minutes": 3,
            }
        )
    except Exception as exc:
        logger.exception("Unexpected error in compress_video")
        return JsonResponse({"success": False, "error": f"Compression failed: {str(exc)}"}, status=500)


@api_view(["GET"])
def download_media_file(request, file_id):
    print(f"[Backend] Download request for file_id: {file_id}")
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
