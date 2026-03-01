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


def _classify_ffmpeg_extract_error(message):
    text = (message or "").lower()
    if not text:
        return 500, "Audio extraction failed."
    if "does not contain any stream" in text or "stream map '0:a'" in text:
        return 400, "This video does not contain an audio stream."
    if "invalid data found when processing input" in text:
        return 400, "Invalid or corrupted video file."
    if "moov atom not found" in text:
        return 400, "Invalid MP4 file (moov atom not found)."
    if "permission denied" in text:
        return 500, "Server could not read or write temporary media files."
    return 500, message


def _load_video_for_audio_extract(video_file, temp_dir):
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
        name = f"audio_{file_id[:8]}"
    return f"{name}{ext}"


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def extract_audio_from_video(request):
    print("1️⃣ بدء استخراج الصوت من الفيديو")
    try:
        print("2️⃣ التحقق من وجود FFmpeg...")
        ffmpeg, error = MediaCommon._ensure_ffmpeg()
        if error:
            print("❌ FFmpeg غير موجود")
            return error
        print("✅ FFmpeg موجود")

        print("3️⃣ استلام ملف الفيديو...")
        video_file = request.FILES.get("video_file") or request.FILES.get("file")
        if not video_file:
            print("❌ لا يوجد ملف فيديو")
            return JsonResponse({"success": False, "error": "No video file provided."}, status=400)
        print(f"✅ تم استلام ملف: {video_file.name}, الحجم: {video_file.size} بايت")

        print("4️⃣ قراءة إعدادات الاستخراج...")
        try:
            settings = json.loads(request.POST.get("extraction_settings", "{}"))
            print(f"✅ الإعدادات: {settings}")
        except Exception as e:
            print(f"⚠️ خطأ في قراءة الإعدادات: {e}")
            settings = {}

        print("5️⃣ التحقق من صيغة الإخراج...")
        output_ext = MediaCommon._normalize_ext(settings.get("target_format"), "mp3")
        if output_ext not in MediaCommon.AUDIO_CODEC_SETTINGS:
            print(f"❌ صيغة غير مدعومة: {output_ext}")
            return JsonResponse(
                {"success": False, "error": "Unsupported output audio format."},
                status=400,
            )
        print(f"✅ صيغة الإخراج: {output_ext}")

        original_size = video_file.size
        bitrate = str(settings.get("bitrate", "192")).strip()
        sample_rate = str(settings.get("sample_rate", "44100")).strip()
        preserve_metadata = bool(settings.get("preserve_metadata", True))
        normalize_audio = bool(settings.get("normalize_audio", False))
        mono_channel = bool(settings.get("mono_channel", False))
        remove_silence = bool(settings.get("remove_silence", False))
        
        print(f"📊 الإعدادات المستخرجة: bitrate={bitrate}, sample_rate={sample_rate}, preserve_metadata={preserve_metadata}, normalize={normalize_audio}, mono={mono_channel}, remove_silence={remove_silence}")

        print("6️⃣ إنشاء مجلد مؤقت...")
        with tempfile.TemporaryDirectory() as temp_dir:
            print(f"✅ المجلد المؤقت: {temp_dir}")
            
            print("7️⃣ تحميل ملف الفيديو إلى المجلد المؤقت...")
            base_name, input_path = _load_video_for_audio_extract(video_file, temp_dir)
            print(f"✅ تم التحميل: {input_path}")
            print(f"   اسم القاعدة: {base_name}")
            
            output_path = os.path.join(temp_dir, f"{base_name}.{output_ext}")
            print(f"📤 مسار الإخراج: {output_path}")

            print("8️⃣ تحديد برنامج الترميز...")
            codec = MediaCommon.AUDIO_CODEC_SETTINGS[output_ext]["acodec"]
            print(f"✅ برنامج الترميز: {codec}")

            print("9️⃣ بناء أمر FFmpeg...")
            cmd = [ffmpeg, "-y", "-i", input_path, "-vn", "-c:a", codec]
            print(f"   الأمر الأساسي: {' '.join(cmd)}")

            if bitrate.isdigit():
                cmd.extend(["-b:a", f"{bitrate}k"])
                print(f"   ➕ إضافة معدل البت: {bitrate}k")
            if sample_rate.isdigit():
                cmd.extend(["-ar", sample_rate])
                print(f"   ➕ إضافة معدل العينة: {sample_rate}Hz")
            if mono_channel:
                cmd.extend(["-ac", "1"])
                print("   ➕ تحويل إلى أحادي")

            print("🔟 إعداد فلاتر الصوت...")
            af = MediaCommon._audio_filter(remove_silence=remove_silence, normalize=normalize_audio)
            if af:
                cmd.extend(["-af", af])
                print(f"   ➕ إضافة فلتر: {af}")
            else:
                print("   ➖ لا توجد فلاتر")

            if not preserve_metadata:
                cmd.extend(["-map_metadata", "-1"])
                print("   ➕ إزالة البيانات الوصفية")
            else:
                print("   ➖ الاحتفاظ بالبيانات الوصفية")

            cmd.append(output_path)
            print(f"📋 الأمر النهائي: {' '.join(cmd)}")

            print("1️⃣1️⃣ تنفيذ أمر FFmpeg...")
            ffmpeg_error = MediaCommon._run_command(cmd)
            if ffmpeg_error:
                print(f"❌ خطأ FFmpeg: {ffmpeg_error}")
                status, error_message = _classify_ffmpeg_extract_error(ffmpeg_error)
                print(f"   تصنيف الخطأ: {status} - {error_message}")
                return JsonResponse({"success": False, "error": error_message}, status=status)
            print("✅ تم تنفيذ FFmpeg بنجاح")

            print("1️⃣2️⃣ التحقق من وجود ملف الإخراج...")
            if not os.path.exists(output_path):
                print("❌ ملف الإخراج غير موجود")
                return JsonResponse({"success": False, "error": "Audio output not generated."}, status=500)
            
            file_size = os.path.getsize(output_path)
            print(f"✅ ملف الإخراج موجود، الحجم: {file_size} بايت")

            print("1️⃣3️⃣ استخراج مدة الصوت...")
            converted_size = os.path.getsize(output_path)
            duration = MediaCommon._probe_duration_seconds(output_path) or 0
            print(f"✅ مدة الصوت: {duration} ثانية")

            print("1️⃣4️⃣ حفظ الملف في المخزن...")
            file_id, _ = MediaCommon._store_output_file(output_path, output_ext, video_file.name)
            print(f"✅ تم الحفظ بمعرف: {file_id}")

        filename = f"{base_name}_{file_id[:8]}.{output_ext}"
        print("1️⃣5️⃣ إنشاء رابط التحميل...")
        download_url = request.build_absolute_uri(f"/api/extract/audio/download/{file_id}/")
        print(f"✅ رابط التحميل: {download_url}")

        print("1️⃣6️⃣ إعداد استجابة JSON...")
        response_data = {
            "success": True,
            "file_id": file_id,
            "filename": filename,
            "original_name": video_file.name,
            "original_size": original_size,
            "converted_size": converted_size,
            "compressed_size": converted_size,
            "saved_bytes": max(0, original_size - converted_size),
            "duration_seconds": duration,
            "download_url": download_url,
            "expires_in_minutes": 3,
        }
        print("✅ تمت العملية بنجاح!")
        print(f"📊 النتيجة: حجم الملف الأصلي={original_size}, حجم الملف المحول={converted_size}, التوفير={max(0, original_size - converted_size)} بايت")
        
        return JsonResponse(response_data)
        
    except Exception as exc:
        print(f"💥 خطأ غير متوقع: {str(exc)}")
        import traceback
        print(traceback.format_exc())
        logger.exception("Unexpected error in extract_audio_from_video")
        return JsonResponse({"success": False, "error": f"Audio extraction failed: {str(exc)}"}, status=500)


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
