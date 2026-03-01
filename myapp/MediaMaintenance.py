import json
import math
import os
import time

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view

from . import MediaCommon


def _format_file_size(bytes_size):
    if bytes_size == 0:
        return "0 Bytes"
    k = 1024
    sizes = ["Bytes", "KB", "MB", "GB"]
    i = int(math.floor(math.log(bytes_size) / math.log(k)))
    return f"{round(bytes_size / (k ** i), 2)} {sizes[i]}"


@api_view(["GET"])
def check_file_validity(request, file_id):
    storage_dir = MediaCommon._output_dir()
    target_path = None
    target_ext = None
    info_path = None
    file_info = {}

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
            try:
                with open(info_path, "r", encoding="utf-8") as f:
                    file_info = json.load(f)
            except Exception as e:
                print(f"Could not read info file: {e}")

    if not target_path or not target_ext:
        return JsonResponse(
            {
                "success": False,
                "valid": False,
                "error": "File not found or already expired.",
                "message": "الملف غير موجود أو انتهت صلاحيته",
            },
            status=404,
        )

    file_modified_time = os.path.getmtime(target_path)
    current_time = time.time()
    age_minutes = (current_time - file_modified_time) / 60
    expires_in_minutes = max(0, 3 - age_minutes)
    is_valid = expires_in_minutes > 0
    file_size = os.path.getsize(target_path) if target_path else 0

    response_data = {
        "success": True,
        "valid": is_valid,
        "file_id": file_id,
        "filename": file_info.get("original_name", os.path.basename(target_path)),
        "file_size": file_size,
        "file_size_formatted": _format_file_size(file_size),
        "file_ext": target_ext,
        "created_at": file_info.get("created_at"),
        "expires_at": file_info.get("expires_at"),
        "age_minutes": round(age_minutes, 1),
        "expires_in_minutes": round(expires_in_minutes, 1),
        "is_expired": not is_valid,
        "message": (
            f"الملف صالح للتحميل لمدة {round(expires_in_minutes, 1)} دقيقة"
            if is_valid
            else "انتهت صلاحية الملف"
        ),
        "download_url": None,
    }
    return JsonResponse(response_data)


@api_view(["POST"])
def cleanup_media_files(request):
    try:
        deleted_count = MediaCommon.cleanup_old_files()
        return JsonResponse(
            {
                "success": True,
                "message": f"Cleaned up {deleted_count} old files",
                "deleted_count": deleted_count,
            }
        )
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)
