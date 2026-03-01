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


def _load_audio_for_compress(audio_file, temp_dir):
    input_name = MediaCommon._safe_name(audio_file.name)
    base_name = os.path.splitext(input_name)[0]
    input_path = os.path.join(temp_dir, input_name)
    with open(input_path, "wb") as f:
        for chunk in audio_file.chunks():
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
        name = f"audio_{file_id[:8]}"
    return f"{name}{ext}"


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def compress_audio(request):
    ffmpeg, error = MediaCommon._ensure_ffmpeg()
    if error:
        return error

    audio_file = request.FILES.get("audio_file") or request.FILES.get("file")
    if not audio_file:
        return JsonResponse({"success": False, "error": "No audio file provided."}, status=400)

    try:
        settings = json.loads(request.POST.get("compression_settings", "{}"))
    except Exception:
        settings = {}

    # التحقق من حجم الملف
    if audio_file.size > 100 * 1024 * 1024:  # 100MB
        return JsonResponse({
            "success": False, 
            "error": "File size exceeds 100MB limit. Please upload a smaller file."
        }, status=400)

    level = str(settings.get("compression_level", "medium")).lower()
    bitrate_map = {"high": "96", "medium": "128", "low": "192"}
    bitrate = settings.get("custom_bitrate", "128") if level == "custom" else bitrate_map.get(level, "128")
    sample_rate = str(settings.get("custom_sample_rate", "44100"))

    keep_original_format = bool(settings.get("keep_original_format", True))
    normalize_audio = bool(settings.get("normalize", False))
    remove_silence = bool(settings.get("remove_silence", False))
    remove_metadata = bool(settings.get("remove_metadata", False))

    original_size = audio_file.size

    with tempfile.TemporaryDirectory() as temp_dir:
        input_name, base_name, input_path = _load_audio_for_compress(audio_file, temp_dir)
        
        # التحقق من أن الملف ليس تالفاً
        if not MediaCommon._probe_duration_seconds(input_path):
            return JsonResponse({
                "success": False,
                "error": "The audio file appears to be corrupted or invalid. Please try another file."
            }, status=400)
        
        input_ext = MediaCommon._normalize_ext(os.path.splitext(input_name)[1], "mp3")
        output_ext = input_ext if keep_original_format else "mp3"
        
        # استخدام اسم مؤقت للإخراج لتجنب مشكلة الكتابة على نفس الملف
        temp_output = os.path.join(temp_dir, f"temp_compressed_{base_name}.{output_ext}")
        output_path = os.path.join(temp_dir, f"{base_name}_compressed.{output_ext}")

        if output_ext not in MediaCommon.AUDIO_CODEC_SETTINGS:
            return JsonResponse(
                {"success": False, "error": f"Unsupported output audio format: {output_ext}"},
                status=400,
            )

        codec = MediaCommon.AUDIO_CODEC_SETTINGS[output_ext]["acodec"]
        cmd = [ffmpeg, "-y", "-i", input_path, "-c:a", codec]

        if str(bitrate).isdigit():
            cmd.extend(["-b:a", f"{bitrate}k"])
        if sample_rate.isdigit():
            cmd.extend(["-ar", sample_rate])

        af = MediaCommon._audio_filter(remove_silence=remove_silence, normalize=normalize_audio)
        if af:
            cmd.extend(["-af", af])

        if remove_metadata:
            cmd.extend(["-map_metadata", "-1"])

        cmd.append(temp_output)  # استخدام الملف المؤقت أولاً

        ffmpeg_error = MediaCommon._run_command(cmd)
        if ffmpeg_error:
            # تحليل الخطأ وإرجاع رسالة مفهومة
            return _handle_compression_error(ffmpeg_error)

        if not os.path.exists(temp_output):
            return JsonResponse({
                "success": False, 
                "error": "Compression failed. The output file was not generated."
            }, status=500)

        # إعادة تسمية الملف المؤقت إلى الاسم النهائي
        os.rename(temp_output, output_path)

        converted_size = os.path.getsize(output_path)
        duration = MediaCommon._probe_duration_seconds(output_path) or 0
        
        # حساب نسبة التوفير
        saved_bytes = max(0, original_size - converted_size)
        saved_percentage = round((saved_bytes / original_size) * 100) if original_size > 0 else 0
        
        file_id, _ = MediaCommon._store_output_file(output_path, output_ext, audio_file.name)

    filename = f"{base_name}_compressed_{file_id[:8]}.{output_ext}"
    
    # رسالة نجاح مع معلومات مفيدة
    return JsonResponse({
        "success": True,
        "file_id": file_id,
        "filename": filename,
        "original_name": audio_file.name,
        "original_size": original_size,
        "converted_size": converted_size,
        "compressed_size": converted_size,
        "saved_bytes": saved_bytes,
        "saved_percentage": saved_percentage,
        "compression_ratio": round(converted_size / original_size, 2) if original_size > 0 else 1,
        "duration_seconds": duration,
        "bitrate_used": bitrate,
        "sample_rate_used": sample_rate,
        "format_used": output_ext.upper(),
        "download_url": request.build_absolute_uri(f"/api/compress/audio/download/{file_id}/"),
        "expires_in_minutes": 3,
    })


def _handle_compression_error(error_message):
    """معالجة أخطاء الضغط وإرجاع رسائل مفهومة"""
    error_text = str(error_message).lower()
    
    if "invalid data found" in error_text:
        return JsonResponse({
            "success": False,
            "error": "The audio file is corrupted or invalid. Please try another file."
        }, status=400)
    
    if "does not contain any stream" in error_text:
        return JsonResponse({
            "success": False,
            "error": "No audio stream found in the file. Please ensure it's a valid audio file."
        }, status=400)
    
    if "permission denied" in error_text:
        return JsonResponse({
            "success": False,
            "error": "Server error: Unable to process the file. Please try again later."
        }, status=500)
    
    if "bitrate" in error_text and "not supported" in error_text:
        return JsonResponse({
            "success": False,
            "error": "The selected bitrate is not supported for this audio format. Try a different bitrate."
        }, status=400)
    
    # خطأ عام مع تفاصيل مفيدة
    return JsonResponse({
        "success": False,
        "error": f"Compression failed: {error_message[:200]}"
    }, status=500)


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
