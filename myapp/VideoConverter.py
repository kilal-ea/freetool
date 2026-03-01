import json
import os
import re
import tempfile
import urllib.parse
import logging
import hashlib
import shutil
import subprocess
import threading
from pathlib import Path
from datetime import datetime

from django.http import FileResponse, JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, MultiPartParser

from . import MediaCommon

# إعداد التسجيل
logger = logging.getLogger(__name__)

# قائمة صيغ الفيديو المدعومة
SUPPORTED_VIDEO_FORMATS = {"mp4", "avi", "mov", "wmv", "mkv", "webm", "flv", "m4v", "3gp"}

# أنواع MIME للفيديو
VIDEO_MIME_TYPES = {
    "mp4": "video/mp4",
    "avi": "video/x-msvideo",
    "mov": "video/quicktime",
    "wmv": "video/x-ms-wmv",
    "mkv": "video/x-matroska",
    "webm": "video/webm",
    "flv": "video/x-flv",
    "m4v": "video/mp4",
    "3gp": "video/3gpp",
}

def _load_video_for_convert(video_file, temp_dir):
    """حفظ الفيديو المرفوع في مجلد مؤقت"""
    try:
        # تنظيف اسم الملف
        input_name = MediaCommon._safe_name(video_file.name)
        base_name = os.path.splitext(input_name)[0]
        input_path = os.path.join(temp_dir, input_name)
        
        # حفظ الملف
        with open(input_path, "wb") as f:
            for chunk in video_file.chunks(chunk_size=8192):
                f.write(chunk)
        
        # التحقق من وجود الملف
        if not os.path.exists(input_path):
            raise Exception("Failed to save uploaded file")
            
        # التحقق من حجم الملف
        file_size = os.path.getsize(input_path)
        if file_size == 0:
            raise Exception("Uploaded file is empty")
            
        logger.info(f"File saved successfully: {input_path} ({file_size} bytes)")
        return base_name, input_path
        
    except Exception as e:
        logger.error(f"Error saving file: {str(e)}")
        raise

def _find_media_file(file_id):
    """البحث عن ملف الفيديو - يدعم صيغ الفيديو فقط"""
    storage_dir = MediaCommon._output_dir()
    target_path = None
    target_ext = None
    info_path = None
    
    try:
        for name in os.listdir(storage_dir):
            path = os.path.join(storage_dir, name)
            if not os.path.isfile(path):
                continue
            base, ext = os.path.splitext(name)
            ext = ext.lower().lstrip('.')
            
            if base == file_id:
                if ext == "json":
                    info_path = path
                elif ext in SUPPORTED_VIDEO_FORMATS:
                    target_path = path
                    target_ext = ext
                    
        if target_path and target_ext:
            logger.info(f"Found video file: {os.path.basename(target_path)} (Format: {target_ext})")
        else:
            logger.warning(f"No video file found for ID: {file_id}")
            
    except Exception as e:
        logger.error(f"Error finding media file: {str(e)}")
        
    return target_path, target_ext, info_path

def _build_download_name(file_id, target_path, target_ext, info_path):
    """بناء اسم التحميل"""
    original_filename = None
    if info_path and os.path.exists(info_path):
        try:
            with open(info_path, "r", encoding="utf-8") as f:
                info = json.load(f)
                original_filename = info.get("original_name")
                if original_filename:
                    base = os.path.splitext(original_filename)[0]
                    original_filename = f"{base}.{target_ext}"
        except Exception as e:
            logger.warning(f"Error loading info file: {str(e)}")
            
    filename = original_filename or os.path.basename(target_path)
    name, ext = os.path.splitext(filename)
    name = re.sub(r"\s*\(\d+\)\s*", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        name = f"video_{file_id[:8]}"
    return f"{name}{ext}"

def _store_output_file(file_path, extension, original_name):
    """تخزين الملف المحول - يدعم صيغ الفيديو فقط"""
    try:
        # التحقق من أن الصيغة مدعومة
        if extension not in SUPPORTED_VIDEO_FORMATS:
            raise ValueError(f"Unsupported format: {extension}. Only video formats are supported.")
        
        # إنشاء معرف فريد للملف
        timestamp = str(int(datetime.now().timestamp()))
        file_hash = hashlib.md5(f"{original_name}{timestamp}".encode()).hexdigest()[:12]
        file_id = f"{file_hash}"
        
        # إنشاء مجلد التخزين
        storage_dir = MediaCommon._output_dir()
        
        # نسخ الملف إلى مجلد التخزين
        new_filename = f"{file_id}.{extension}"
        new_path = os.path.join(storage_dir, new_filename)
        shutil.copy2(file_path, new_path)
        
        # حفظ معلومات الملف
        info = {
            "original_name": original_name,
            "extension": extension,
            "format_type": "video",
            "created_at": datetime.now().isoformat(),
            "file_size": os.path.getsize(new_path),
            "mime_type": VIDEO_MIME_TYPES.get(extension, "application/octet-stream")
        }
        
        info_path = os.path.join(storage_dir, f"{file_id}.json")
        with open(info_path, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Video file stored: {new_filename} (Format: {extension})")
        
        # جدولة حذف الملف بعد 3 دقائق
        _schedule_deletion(file_id, 180)
        
        return file_id, new_path
        
    except Exception as e:
        logger.error(f"Error storing file: {str(e)}")
        raise

def _schedule_deletion(file_id, delay_seconds=180):
    """جدولة حذف الملف بعد فترة"""
    
    def delete_files():
        try:
            import time
            time.sleep(delay_seconds)
            storage_dir = MediaCommon._output_dir()
            
            # حذف جميع الملفات المرتبطة بالمعرف
            for filename in os.listdir(storage_dir):
                path = os.path.join(storage_dir, filename)
                if not os.path.isfile(path):
                    continue
                base, _ext = os.path.splitext(filename)
                if base == file_id:
                    os.remove(path)
                    logger.info(f"Auto-deleted: {filename}")
            
            # إزالة المؤقت من القاموس
            if file_id in MediaCommon._delete_timers:
                del MediaCommon._delete_timers[file_id]
                
        except Exception as e:
            logger.error(f"Error in scheduled deletion: {str(e)}")
    
    # إنشاء وتشغيل مؤقت الحذف
    timer = threading.Timer(delay_seconds, delete_files)
    timer.daemon = True
    timer.start()
    
    # تخزين المؤقت للإلغاء المحتمل
    MediaCommon._delete_timers[file_id] = timer
    logger.info(f"Scheduled deletion for {file_id} in {delay_seconds} seconds")

@api_view(["POST", "OPTIONS"])
@parser_classes([MultiPartParser, FormParser])
@require_http_methods(["POST", "OPTIONS"])
def convert_video(request):
    """تحويل الفيديو - يدعم صيغ الفيديو فقط"""
    
    # معالجة طلبات OPTIONS لـ CORS
    if request.method == "OPTIONS":
        response = HttpResponse()
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "*"
        response["Access-Control-Max-Age"] = "3600"
        return response
    
    logger.info("Received video conversion request")
    
    # التحقق من FFmpeg
    ffmpeg, error = MediaCommon._ensure_ffmpeg()
    if error:
        logger.error(f"FFmpeg error: {error}")
        return error

    # الحصول على الملف المرفوع
    video_file = request.FILES.get("video_file") or request.FILES.get("file")
    if not video_file:
        logger.warning("No video file provided")
        return JsonResponse(
            {"success": False, "error": "No video file provided."}, 
            status=400
        )

    # التحقق من حجم الملف
    if video_file.size > 500 * 1024 * 1024:  # 500MB
        return JsonResponse(
            {"success": False, "error": "File too large. Maximum size is 500MB."},
            status=400
        )

    # التحقق من نوع الملف
    allowed_types = ['video/mp4', 'video/avi', 'video/quicktime', 'video/x-msvideo', 
                     'video/x-matroska', 'video/webm', 'video/x-flv', 'video/3gpp']
    if video_file.content_type not in allowed_types:
        logger.warning(f"Invalid file type: {video_file.content_type}")
        return JsonResponse(
            {"success": False, "error": f"Unsupported file type: {video_file.content_type}"},
            status=400
        )

    try:
        # تحميل إعدادات التحويل
        settings_data = {}
        if request.POST.get("conversion_settings"):
            try:
                settings_data = json.loads(request.POST.get("conversion_settings", "{}"))
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON in conversion_settings: {e}")

        # إعدادات التحويل
        target_ext = MediaCommon._normalize_ext(settings_data.get("target_format"), "mp4")
        
        # التحقق من أن الصيغة المستهدفة مدعومة
        if target_ext not in SUPPORTED_VIDEO_FORMATS:
            return JsonResponse(
                {"success": False, "error": f"Unsupported output format: {target_ext}. Supported formats: {', '.join(SUPPORTED_VIDEO_FORMATS)}"},
                status=400,
            )
        
        if target_ext not in MediaCommon.VIDEO_CODEC_SETTINGS:
            return JsonResponse(
                {"success": False, "error": "Unsupported output video format."},
                status=400,
            )

        quality = str(settings_data.get("quality", "high")).lower()
        resolution = settings_data.get("resolution", "original")
        framerate = settings_data.get("framerate", "original")
        audio_bitrate = str(settings_data.get("audio_bitrate", "128")).strip()
        video_bitrate = str(settings_data.get("video_bitrate", "")).strip()
        remove_audio = bool(settings_data.get("remove_audio", False))
        preserve_metadata = bool(settings_data.get("preserve_metadata", True))
        fast_start = bool(settings_data.get("fast_start", True))

        original_size = video_file.size
        logger.info(f"Converting file: {video_file.name}, size: {original_size}, to: {target_ext}")

        # إنشاء مجلد مؤقت
        with tempfile.TemporaryDirectory() as temp_dir:
            # حفظ الملف المرفوع
            base_name, input_path = _load_video_for_convert(video_file, temp_dir)
            
            # ✅ الحل: إنشاء اسم فريد لملف الإخراج لمنع الكتابة على ملف الإدخال
            timestamp = int(datetime.now().timestamp())
            unique_suffix = f"_{timestamp}"
            output_filename = f"{base_name}{unique_suffix}.{target_ext}"
            output_path = os.path.join(temp_dir, output_filename)

            # بناء أمر FFmpeg
            codecs = MediaCommon.VIDEO_CODEC_SETTINGS[target_ext]
            cmd = [ffmpeg, "-y", "-i", input_path, "-c:v", codecs["vcodec"]]

            # إعدادات الجودة
            MediaCommon._append_video_quality_args(cmd, codecs["vcodec"], quality, video_bitrate)

            # معدل الإطارات
            if framerate and str(framerate).lower() != "original":
                cmd.extend(["-r", str(framerate)])

            # الدقة
            scale = MediaCommon._resolution_scale(resolution)
            if scale:
                cmd.extend(["-vf", f"scale={scale}:force_original_aspect_ratio=decrease"])

            # إعدادات الصوت
            if remove_audio:
                cmd.append("-an")
            else:
                cmd.extend(["-c:a", codecs["acodec"]])
                if audio_bitrate.isdigit():
                    cmd.extend(["-b:a", f"{audio_bitrate}k"])

            # البيانات الوصفية
            if not preserve_metadata:
                cmd.extend(["-map_metadata", "-1"])

            # Fast Start لـ MP4
            if fast_start and target_ext in {"mp4", "m4v"}:
                cmd.extend(["-movflags", "+faststart"])

            cmd.append(output_path)

            # تنفيذ الأمر
            logger.info(f"Running FFmpeg command: {' '.join(cmd)}")
            ffmpeg_error = MediaCommon._run_command(cmd)
            
            if ffmpeg_error:
                logger.error(f"FFmpeg error: {ffmpeg_error}")
                return MediaCommon._ffmpeg_error_response(ffmpeg_error)

            # التحقق من وجود الملف المحول
            if not os.path.exists(output_path):
                logger.error("Converted output not generated")
                return MediaCommon._ffmpeg_error_response("Converted output not generated.")

            # التحقق من حجم الملف المحول
            converted_size = os.path.getsize(output_path)
            if converted_size == 0:
                logger.error("Converted file is empty")
                return JsonResponse(
                    {"success": False, "error": "Conversion resulted in empty file."},
                    status=500
                )

            # حفظ الملف المحول
            file_id, _ = _store_output_file(output_path, target_ext, video_file.name)
            logger.info(f"File saved with ID: {file_id}")

        # إعداد اسم الملف للتحميل
        filename = f"{base_name}_{file_id[:8]}.{target_ext}"
        
        # إنشاء رابط التحميل
        download_url = request.build_absolute_uri(f"/api/convert/video/download/{file_id}/")
        
        # حساب المساحة المحفوظة
        saved_bytes = max(0, original_size - converted_size)
        
        response_data = {
            "success": True,
            "file_id": file_id,
            "filename": filename,
            "original_name": video_file.name,
            "original_size": original_size,
            "converted_size": converted_size,
            "saved_bytes": saved_bytes,
            "compression_ratio": f"{(converted_size/original_size*100):.1f}%" if original_size > 0 else "0%",
            "download_url": download_url,
            "expires_in_minutes": 3,
            "format": target_ext,
            "supported_formats": list(SUPPORTED_VIDEO_FORMATS)
        }
        
        logger.info(f"Conversion successful: {response_data}")
        
        # إضافة رؤوس CORS
        response = JsonResponse(response_data)
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "*"
        
        return response

    except Exception as e:
        logger.error(f"Unexpected error during conversion: {str(e)}", exc_info=True)
        return JsonResponse(
            {"success": False, "error": f"Conversion failed: {str(e)}"},
            status=500
        )


@api_view(["GET", "OPTIONS"])
@require_http_methods(["GET", "OPTIONS"])
def download_media_file(request, file_id):
    """تحميل الملف المحول - يدعم صيغ الفيديو فقط"""
    
    # معالجة طلبات OPTIONS لـ CORS
    if request.method == "OPTIONS":
        response = HttpResponse()
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response["Access-Control-Allow-Headers"] = "*"
        response["Access-Control-Max-Age"] = "3600"
        return response
    
    logger.info(f"Download request for file ID: {file_id}")
    
    # البحث عن الملف
    target_path, target_ext, info_path = _find_media_file(file_id)
    
    if not target_path or not os.path.exists(target_path):
        logger.warning(f"File not found: {file_id}")
        return JsonResponse(
            {"success": False, "error": "File not found or already expired."}, 
            status=404
        )

    # التحقق من أن الصيغة مدعومة
    if target_ext not in SUPPORTED_VIDEO_FORMATS:
        logger.warning(f"Unsupported format for download: {target_ext}")
        return JsonResponse(
            {"success": False, "error": f"Unsupported format: {target_ext}. Only video formats are supported."},
            status=400
        )

    # تحديد نوع MIME للفيديو
    mime = VIDEO_MIME_TYPES.get(target_ext, "application/octet-stream")

    # بناء اسم الملف
    filename = _build_download_name(file_id, target_path, target_ext, info_path)
    
    try:
        # فتح الملف
        file_handle = open(target_path, "rb")
        file_size = os.path.getsize(target_path)
        
        # إنشاء الاستجابة
        response = FileResponse(
            file_handle,
            as_attachment=True,
            filename=filename,
            content_type=mime
        )
        
        # إضافة رؤوس CORS
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Expose-Headers"] = "Content-Disposition, Content-Type, Content-Length, Accept-Ranges"
        response["Content-Length"] = str(file_size)
        
        # إضافة رؤوس إضافية للملفات الكبيرة
        response["Accept-Ranges"] = "bytes"
        response["Cache-Control"] = "public, max-age=3600"
        response["Content-Disposition"] = (
            f"attachment; filename=\"{filename}\"; filename*=UTF-8''{urllib.parse.quote(filename)}"
        )
        
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"
        
        logger.info(f"Video file download initiated: {filename} ({file_size} bytes) - Format: {target_ext}")
        
        return response
        
    except Exception as e:
        logger.error(f"Error opening file for download: {str(e)}")
        return JsonResponse(
            {"success": False, "error": f"Could not open file: {str(e)}"}, 
            status=500
        )

@api_view(["POST", "DELETE", "OPTIONS"])
@require_http_methods(["POST", "DELETE", "OPTIONS"])
def remove_media_file(request, file_id):
    """حذف الملف المحول"""
    
    # معالجة طلبات OPTIONS لـ CORS
    if request.method == "OPTIONS":
        response = HttpResponse()
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "POST, DELETE, OPTIONS"
        response["Access-Control-Allow-Headers"] = "*"
        return response
    
    logger.info(f"Remove request for file ID: {file_id}")
    
    storage_dir = MediaCommon._output_dir()
    removed = []
    
    try:
        for filename in os.listdir(storage_dir):
            path = os.path.join(storage_dir, filename)
            if not os.path.isfile(path):
                continue
            base, _ext = os.path.splitext(filename)
            if base == file_id:
                os.remove(path)
                removed.append(filename)
                logger.info(f"Removed file: {filename}")
        
        # إلغاء المؤقت إذا كان موجوداً
        if file_id in MediaCommon._delete_timers:
            MediaCommon._delete_timers[file_id].cancel()
            del MediaCommon._delete_timers[file_id]
            
    except Exception as e:
        logger.error(f"Error removing files: {str(e)}")
        return JsonResponse(
            {"success": False, "error": f"Error removing files: {str(e)}"},
            status=500
        )
    
    if not removed:
        logger.warning(f"No files found to remove for ID: {file_id}")
        return JsonResponse(
            {"success": False, "error": "File not found or already removed."}, 
            status=404
        )
    
    response = JsonResponse({
        "success": True, 
        "file_id": file_id, 
        "removed_files": removed
    })
    response["Access-Control-Allow-Origin"] = "*"
    return response

@api_view(["GET", "OPTIONS"])
@require_http_methods(["GET", "OPTIONS"])
def check_file_validity(request, file_id):
    """التحقق من صلاحية الملف - يدعم صيغ الفيديو فقط"""
    
    if request.method == "OPTIONS":
        response = HttpResponse()
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response["Access-Control-Allow-Headers"] = "*"
        return response
    
    try:
        storage_dir = MediaCommon._output_dir()
        file_found = False
        file_size = 0
        filename = None
        file_ext = None
        file_info = None
        
        # البحث عن الملف ومعلوماته
        for name in os.listdir(storage_dir):
            path = os.path.join(storage_dir, name)
            if not os.path.isfile(path):
                continue
                
            base, ext = os.path.splitext(name)
            ext = ext.lower().lstrip('.')
            
            if base == file_id:
                if ext == "json":
                    # قراءة ملف المعلومات
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            file_info = json.load(f)
                    except:
                        pass
                elif ext in SUPPORTED_VIDEO_FORMATS:
                    # هذا ملف فيديو مدعوم
                    file_found = True
                    file_size = os.path.getsize(path)
                    filename = name
                    file_ext = ext
        
        if not file_found:
            return JsonResponse({
                "success": True,
                "valid": False,
                "message": "File not found or expired"
            })
        
        # حساب الوقت المتبقي (3 دقائق كحد أقصى)
        expires_in_minutes = 3
        if file_info and "created_at" in file_info:
            try:
                created_at = datetime.fromisoformat(file_info["created_at"])
                now = datetime.now()
                elapsed = (now - created_at).total_seconds() / 60
                expires_in_minutes = max(0, 3 - elapsed)
            except:
                pass
        
        return JsonResponse({
            "success": True,
            "valid": True,
            "file_id": file_id,
            "filename": filename,
            "file_size": file_size,
            "file_format": file_ext,
            "expires_in_minutes": round(expires_in_minutes, 1),
            "supported_formats": list(SUPPORTED_VIDEO_FORMATS)
        })
        
    except Exception as e:
        logger.error(f"Error checking file validity: {str(e)}")
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=500)
