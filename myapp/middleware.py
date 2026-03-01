import time
from datetime import timedelta

from django.http import JsonResponse
from django.utils import timezone

from .models import BlockedIP, ErrorLog, FileProcess, IPUsage, ToolUsage


def _client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _tool_name_from_path(path: str) -> str:
    mapping = {
        "/api/remove-background/": "Background Remover",
        "/api/image/convert/": "Image Converter",
        "/api/image/compress/": "Image Compressor",
        "/api/word-to-pdf/": "Word to PDF",
        "/api/convert/word-to-pdf/": "Word to PDF",
        "/api/convert/excel-to-pdf/": "Excel to PDF",
        "/api/convert/powerpoint-to-pdf/": "PowerPoint to PDF",
        "/api/convert/pdf-to-word/": "PDF to Word",
        "/api/convert/pdf-to-excel/": "PDF to Excel",
        "/api/convert/pdf-to-powerpoint/": "PDF to PowerPoint",
        "/api/convert/video/": "Video Converter",
        "/api/convert/video-to-gif/": "Video to GIF",
        "/api/compress/video/": "Video Compressor",
        "/api/convert/audio/": "Audio Converter",
        "/api/compress/audio/": "Audio Compressor",
        "/api/extract/audio/": "Audio Extractor",
    }
    if path in mapping:
        return mapping[path]
    if path.startswith("/api/convert/"):
        return "File Converter"
    if path.startswith("/api/image/"):
        return "Image Tools"
    if path.startswith("/api/compress/"):
        return "Compressor"
    if path.startswith("/api/extract/"):
        return "Extractor"
    return "API Operation"


def _category_from_tool(tool_name: str) -> str:
    lowered = tool_name.lower()
    if "pdf" in lowered or "office" in lowered or "file" in lowered:
        return "pdf"
    if "image" in lowered or "background" in lowered:
        return "image"
    if "video" in lowered:
        return "video"
    if "audio" in lowered:
        return "audio"
    if "calculator" in lowered or "converter" in lowered:
        return "utility"
    return "general"


def _is_trackable_path(path: str) -> bool:
    if not path.startswith("/api/"):
        return False
    ignored_prefixes = (
        "/api/admin/",
        "/api/analytics/",
        "/api/token/",
        "/api/get-machine-token/",
        "/api/health/",
        "/api/protected/",
    )
    return not any(path.startswith(prefix) for prefix in ignored_prefixes)


class TransactionLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request._txn_start = time.perf_counter()
        request._txn_ip = _client_ip(request)

        if _is_trackable_path(request.path):
            blocked = BlockedIP.objects.filter(ip_address=request._txn_ip, is_active=True).first()
            if blocked:
                if blocked.expires_at and blocked.expires_at < timezone.now():
                    blocked.is_active = False
                    blocked.save(update_fields=["is_active"])
                else:
                    return JsonResponse({"detail": "This IP is blocked."}, status=403)

        response = self.get_response(request)

        if not _is_trackable_path(request.path):
            return response

        try:
            duration_ms = int((time.perf_counter() - getattr(request, "_txn_start", time.perf_counter())) * 1000)
            ip_address = getattr(request, "_txn_ip", None)
            success = response.status_code < 400
            tool_name = _tool_name_from_path(request.path)
            if tool_name == "API Operation":
                return response
            category = _category_from_tool(tool_name)

            files = []
            try:
                files = list(request.FILES.values())
            except Exception:
                files = []

            total_file_size = sum(getattr(file_obj, "size", 0) for file_obj in files)

            ToolUsage.objects.create(
                tool_name=tool_name,
                tool_category=category,
                operation_count=1,
                success=success,
                processing_time_ms=max(duration_ms, 0),
                file_size_bytes=total_file_size,
                ip_address=ip_address,
            )

            if request.method in ("POST", "PUT", "PATCH") and files:
                for file_obj in files:
                    FileProcess.objects.create(
                        tool_name=tool_name,
                        original_filename=getattr(file_obj, "name", "uploaded-file"),
                        file_size=getattr(file_obj, "size", 0),
                        status="success" if success else "failed",
                        auto_delete=True,
                    )

            usage, created = IPUsage.objects.get_or_create(
                ip_address=ip_address or "0.0.0.0",
                defaults={
                    "total_requests": 0,
                    "total_files_uploaded": 0,
                    "requests_today": 0,
                    "last_request": timezone.now(),
                },
            )
            today = timezone.now().date()
            if usage.last_request and usage.last_request.date() != today:
                usage.requests_today = 0
            usage.total_requests += 1
            usage.requests_today += 1
            usage.total_files_uploaded += len(files)
            usage.last_request = timezone.now()
            usage.save(
                update_fields=[
                    "total_requests",
                    "requests_today",
                    "total_files_uploaded",
                    "last_request",
                ]
            )

            if not success:
                try:
                    message = response.content.decode("utf-8", errors="ignore")[:1000]
                except Exception:
                    message = "Unhandled API error"
                ErrorLog.objects.create(
                    tool_name=tool_name,
                    error_type=f"HTTP_{response.status_code}",
                    error_message=message or "Request failed",
                    stack_trace="",
                    related_file=files[0].name if files else "",
                    ip_address=ip_address,
                )
        except Exception:
            # Logging must never break user requests.
            pass

        return response
