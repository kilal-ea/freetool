from datetime import datetime, timedelta
from typing import Optional
import shutil

from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncHour
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import BlockedIP, ContactMessage, ErrorLog, FileProcess, IPUsage, SystemMetric, ToolUsage, VisitEvent

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    psutil = None


def _parse_date(value: Optional[str], end_of_day: bool = False):
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
        if end_of_day:
            parsed = parsed.replace(hour=23, minute=59, second=59)
        return timezone.make_aware(parsed)
    except ValueError:
        return None


class IsStaffUser(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)


class AdminMeView(APIView):
    permission_classes = [IsStaffUser]

    def get(self, request):
        return Response(
            {
                "id": request.user.id,
                "username": request.user.username,
                "is_staff": request.user.is_staff,
                "is_superuser": request.user.is_superuser,
            },
            status=status.HTTP_200_OK,
        )


class AdminDashboardView(APIView):
    permission_classes = [IsStaffUser]

    def get(self, request):
        now = timezone.now()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = day_start - timedelta(days=day_start.weekday())
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        today_tool_usage = ToolUsage.objects.filter(created_at__gte=day_start)
        month_tool_usage = ToolUsage.objects.filter(created_at__gte=month_start)
        today_files = FileProcess.objects.filter(upload_timestamp__gte=day_start)
        today_failed_ops = today_tool_usage.filter(success=False).aggregate(total=Count("id"))["total"] or 0

        most_used = (
            month_tool_usage.values("tool_name")
            .annotate(total=Sum("operation_count"))
            .order_by("-total")
            .first()
        )

        usage_hourly = (
            today_tool_usage.annotate(hour=TruncHour("created_at"))
            .values("hour")
            .annotate(total=Sum("operation_count"))
            .order_by("hour")
        )

        usage_by_category = (
            month_tool_usage.values("tool_category")
            .annotate(total=Sum("operation_count"))
            .order_by("-total")
        )

        latest_metric = SystemMetric.objects.first()
        if latest_metric:
            cpu_usage = latest_metric.cpu_usage
            ram_usage = latest_metric.ram_usage
            disk_usage = latest_metric.disk_usage
            active_jobs = latest_metric.active_jobs
            queue_length = latest_metric.queue_length
        else:
            cpu_usage = float(psutil.cpu_percent(interval=0.1)) if psutil else 0.0
            ram_usage = float(psutil.virtual_memory().percent) if psutil else 0.0
            total, used, _ = shutil.disk_usage("/")
            disk_usage = round((used / total) * 100, 2) if total else 0.0
            active_jobs = FileProcess.objects.filter(status="processing").count()
            queue_length = active_jobs

        data = {
            "total_operations_today": today_tool_usage.aggregate(total=Sum("operation_count"))["total"] or 0,
            "total_operations_this_week": ToolUsage.objects.filter(created_at__gte=week_start).aggregate(
                total=Sum("operation_count")
            )["total"]
            or 0,
            "total_operations_this_month": month_tool_usage.aggregate(total=Sum("operation_count"))["total"] or 0,
            "most_used_tool": most_used["tool_name"] if most_used else None,
            "total_files_processed_today": today_files.count(),
            "total_data_processed_today": today_files.aggregate(total=Sum("file_size"))["total"] or 0,
            "failed_operations_today": today_failed_ops + today_files.filter(status="failed").count(),
            "average_processing_time": month_tool_usage.aggregate(avg=Avg("processing_time_ms"))["avg"] or 0,
            "active_jobs": active_jobs,
            "queue_length": queue_length,
            "server_cpu_usage": cpu_usage,
            "server_ram_usage": ram_usage,
            "disk_usage": disk_usage,
            "unique_visitors_today": VisitEvent.objects.filter(created_at__gte=day_start)
            .exclude(ip_address__isnull=True)
            .values("ip_address")
            .distinct()
            .count(),
            "unique_visitors_this_week": VisitEvent.objects.filter(created_at__gte=week_start)
            .exclude(ip_address__isnull=True)
            .values("ip_address")
            .distinct()
            .count(),
            "unique_visitors_this_month": VisitEvent.objects.filter(created_at__gte=month_start)
            .exclude(ip_address__isnull=True)
            .values("ip_address")
            .distinct()
            .count(),
            "total_visits_today": VisitEvent.objects.filter(created_at__gte=day_start).count(),
            "total_visits_this_week": VisitEvent.objects.filter(created_at__gte=week_start).count(),
            "total_visits_this_month": VisitEvent.objects.filter(created_at__gte=month_start).count(),
            "active_visitors_last_5_minutes": VisitEvent.objects.filter(
                created_at__gte=(now - timedelta(minutes=5))
            )
            .exclude(ip_address__isnull=True)
            .values("ip_address")
            .distinct()
            .count(),
            "operations_per_hour": [
                {
                    "hour": item["hour"].isoformat() if item["hour"] else None,
                    "total": item["total"] or 0,
                }
                for item in usage_hourly
            ],
            "usage_by_category": [
                {"category": item["tool_category"], "total": item["total"] or 0}
                for item in usage_by_category
            ],
        }
        return Response(data, status=status.HTTP_200_OK)


class TrackVisitView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        path = request.data.get("path", "/")
        if not isinstance(path, str):
            path = "/"

        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded_for:
            ip_address = forwarded_for.split(",")[0].strip()
        else:
            ip_address = request.META.get("REMOTE_ADDR")

        user_agent = request.META.get("HTTP_USER_AGENT", "")[:512]
        session_key = request.META.get("HTTP_X_SESSION_KEY", "")[:64]

        # Throttle duplicates for same IP+path over short window.
        recent_cutoff = timezone.now() - timedelta(minutes=10)
        exists_recent = VisitEvent.objects.filter(
            ip_address=ip_address,
            path=path,
            created_at__gte=recent_cutoff,
        ).exists()
        if not exists_recent:
            VisitEvent.objects.create(
                path=path[:255],
                ip_address=ip_address,
                user_agent=user_agent,
                session_key=session_key,
            )
        return Response({"ok": True}, status=status.HTTP_200_OK)


class TrackToolUsageView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        tool_name = str(request.data.get("tool_name", "Frontend Tool")).strip()[:120]
        tool_category = str(request.data.get("tool_category", "utility")).strip()[:64]
        success = bool(request.data.get("success", True))
        operation_count = int(request.data.get("operation_count", 1) or 1)
        processing_time_ms = int(request.data.get("processing_time_ms", 0) or 0)
        file_size_bytes = int(request.data.get("file_size_bytes", 0) or 0)
        conversion_from = str(request.data.get("conversion_from", "")).strip()[:32]
        conversion_to = str(request.data.get("conversion_to", "")).strip()[:32]

        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded_for:
            ip_address = forwarded_for.split(",")[0].strip()
        else:
            ip_address = request.META.get("REMOTE_ADDR")

        ToolUsage.objects.create(
            tool_name=tool_name,
            tool_category=tool_category or "utility",
            operation_count=max(operation_count, 1),
            success=success,
            processing_time_ms=max(processing_time_ms, 0),
            file_size_bytes=max(file_size_bytes, 0),
            conversion_from=conversion_from,
            conversion_to=conversion_to,
            ip_address=ip_address,
        )

        usage, _ = IPUsage.objects.get_or_create(
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
        usage.last_request = timezone.now()
        usage.save(update_fields=["total_requests", "requests_today", "last_request"])
        return Response({"ok": True}, status=status.HTTP_200_OK)


class AdminToolsAnalyticsView(APIView):
    permission_classes = [IsStaffUser]

    def get(self, request):
        start_date = _parse_date(request.query_params.get("start_date"))
        end_date = _parse_date(request.query_params.get("end_date"), end_of_day=True)
        category = request.query_params.get("category")

        queryset = ToolUsage.objects.all()
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)
        if category:
            queryset = queryset.filter(tool_category__iexact=category)

        grouped = (
            queryset.values("tool_name")
            .annotate(
                total_usage=Sum("operation_count"),
                avg_processing_time=Avg("processing_time_ms"),
                avg_file_size=Avg("file_size_bytes"),
            )
            .order_by("-total_usage")
        )

        # Build success/failure counts explicitly per tool to keep compatibility.
        results = []
        for item in grouped:
            tool_name = item["tool_name"]
            per_tool = queryset.filter(tool_name=tool_name)
            success_count = per_tool.filter(success=True).count()
            failure_count = per_tool.filter(success=False).count()
            total = (item["total_usage"] or 0)

            pair = (
                per_tool.exclude(conversion_from="", conversion_to="")
                .values("conversion_from", "conversion_to")
                .annotate(total_count=Count("id"))
                .order_by("-total_count")
                .first()
            )
            results.append(
                {
                    "tool_name": tool_name,
                    "total_usage": total,
                    "success_count": success_count,
                    "failure_count": failure_count,
                    "success_rate": round((success_count / (success_count + failure_count) * 100), 2)
                    if (success_count + failure_count)
                    else 0.0,
                    "avg_processing_time": item["avg_processing_time"] or 0,
                    "avg_file_size": item["avg_file_size"] or 0,
                    "most_common_conversion_pair": (
                        f"{pair['conversion_from']}->{pair['conversion_to']}" if pair else None
                    ),
                }
            )

        return Response({"results": results}, status=status.HTTP_200_OK)


class AdminFilesView(APIView):
    permission_classes = [IsStaffUser]

    def get(self, request):
        status_filter = request.query_params.get("status")
        queryset = FileProcess.objects.all()
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        files_data = [
            {
                "id": fp.id,
                "tool_name": fp.tool_name,
                "original_filename": fp.original_filename,
                "file_size": fp.file_size,
                "status": fp.status,
                "upload_timestamp": fp.upload_timestamp,
                "deletion_timestamp": fp.deletion_timestamp,
                "auto_delete": fp.auto_delete,
            }
            for fp in queryset[:500]
        ]
        return Response(
            {
                "results": files_data,
                "total_storage_usage": queryset.aggregate(total=Sum("file_size"))["total"] or 0,
            },
            status=status.HTTP_200_OK,
        )


class AdminFileDeleteView(APIView):
    permission_classes = [IsStaffUser]

    def delete(self, request, file_id):
        try:
            fp = FileProcess.objects.get(pk=file_id)
        except FileProcess.DoesNotExist:
            return Response({"detail": "File process not found."}, status=status.HTTP_404_NOT_FOUND)

        fp.status = "deleted"
        fp.deletion_timestamp = timezone.now()
        fp.save(update_fields=["status", "deletion_timestamp"])
        return Response({"detail": "File marked as deleted."}, status=status.HTTP_200_OK)


class AdminFilesCleanupView(APIView):
    permission_classes = [IsStaffUser]

    def post(self, request):
        threshold_hours = int(request.data.get("hours", 24))
        cutoff = timezone.now() - timedelta(hours=threshold_hours)
        queryset = FileProcess.objects.filter(auto_delete=True, upload_timestamp__lt=cutoff).exclude(status="deleted")
        updated = queryset.update(status="deleted", deletion_timestamp=timezone.now())
        return Response({"deleted_records": updated}, status=status.HTTP_200_OK)


class AdminErrorsView(APIView):
    permission_classes = [IsStaffUser]

    def get(self, request):
        tool = request.query_params.get("tool")
        error_type = request.query_params.get("error_type")
        start_date = _parse_date(request.query_params.get("start_date"))
        end_date = _parse_date(request.query_params.get("end_date"), end_of_day=True)

        queryset = ErrorLog.objects.all()
        if tool:
            queryset = queryset.filter(tool_name__iexact=tool)
        if error_type:
            queryset = queryset.filter(error_type__iexact=error_type)
        if start_date:
            queryset = queryset.filter(timestamp__gte=start_date)
        if end_date:
            queryset = queryset.filter(timestamp__lte=end_date)

        data = [
            {
                "id": log.id,
                "tool_name": log.tool_name,
                "error_type": log.error_type,
                "error_message": log.error_message,
                "timestamp": log.timestamp,
            }
            for log in queryset[:500]
        ]
        return Response({"results": data}, status=status.HTTP_200_OK)


class AdminErrorDetailView(APIView):
    permission_classes = [IsStaffUser]

    def get(self, request, error_id):
        try:
            log = ErrorLog.objects.get(pk=error_id)
        except ErrorLog.DoesNotExist:
            return Response({"detail": "Error log not found."}, status=status.HTTP_404_NOT_FOUND)

        data = {
            "id": log.id,
            "tool_name": log.tool_name,
            "error_type": log.error_type,
            "error_message": log.error_message,
            "stack_trace": log.stack_trace,
            "related_file": log.related_file,
            "timestamp": log.timestamp,
            "ip_address": log.ip_address,
        }
        return Response(data, status=status.HTTP_200_OK)

    def delete(self, request, error_id):
        deleted, _ = ErrorLog.objects.filter(pk=error_id).delete()
        if not deleted:
            return Response({"detail": "Error log not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"detail": "Error log deleted."}, status=status.HTTP_200_OK)


class AdminIPUsageView(APIView):
    permission_classes = [IsStaffUser]

    def get(self, request):
        usage_data = [
            {
                "ip_address": ip.ip_address,
                "total_requests": ip.total_requests,
                "total_files_uploaded": ip.total_files_uploaded,
                "last_request": ip.last_request,
                "requests_today": ip.requests_today,
            }
            for ip in IPUsage.objects.all()[:500]
        ]
        blocked = [
            {
                "ip_address": item.ip_address,
                "reason": item.reason,
                "blocked_at": item.blocked_at,
                "expires_at": item.expires_at,
                "is_active": item.is_active,
            }
            for item in BlockedIP.objects.filter(is_active=True)
        ]
        return Response({"usage": usage_data, "blocked": blocked}, status=status.HTTP_200_OK)


class AdminBlockIPView(APIView):
    permission_classes = [IsStaffUser]

    def post(self, request):
        ip_address = request.data.get("ip_address")
        if not ip_address:
            return Response({"detail": "ip_address is required."}, status=status.HTTP_400_BAD_REQUEST)

        reason = request.data.get("reason", "")
        expires_at = _parse_date(request.data.get("expires_at"), end_of_day=True)

        obj, _ = BlockedIP.objects.update_or_create(
            ip_address=ip_address,
            defaults={
                "reason": reason,
                "expires_at": expires_at,
                "is_active": True,
            },
        )
        return Response(
            {
                "ip_address": obj.ip_address,
                "reason": obj.reason,
                "expires_at": obj.expires_at,
                "is_active": obj.is_active,
            },
            status=status.HTTP_200_OK,
        )


class AdminUnblockIPView(APIView):
    permission_classes = [IsStaffUser]

    def post(self, request):
        ip_address = request.data.get("ip_address")
        if not ip_address:
            return Response({"detail": "ip_address is required."}, status=status.HTTP_400_BAD_REQUEST)

        updated = BlockedIP.objects.filter(ip_address=ip_address).update(is_active=False)
        if not updated:
            return Response({"detail": "IP not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"detail": "IP unblocked."}, status=status.HTTP_200_OK)


class AdminContactMessagesView(APIView):
    permission_classes = [IsStaffUser]

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        has_email = (request.query_params.get("has_email") or "").strip().lower()
        start_date = _parse_date(request.query_params.get("start_date"))
        end_date = _parse_date(request.query_params.get("end_date"), end_of_day=True)

        queryset = ContactMessage.objects.all()
        if q:
            queryset = queryset.filter(
                Q(username__icontains=q)
                | Q(last_name__icontains=q)
                | Q(email__icontains=q)
                | Q(message__icontains=q)
                | Q(ip_address__icontains=q)
            )
        if has_email == "yes":
            queryset = queryset.exclude(email="")
        elif has_email == "no":
            queryset = queryset.filter(email="")
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)

        messages = [
            {
                "id": item.id,
                "username": item.username,
                "last_name": item.last_name,
                "email": item.email,
                "message": item.message,
                "ip_address": item.ip_address,
                "created_at": item.created_at,
            }
            for item in queryset[:500]
        ]
        return Response(
            {
                "results": messages,
                "total": queryset.count(),
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request):
        deleted_count, _ = ContactMessage.objects.all().delete()
        return Response({"deleted_count": deleted_count}, status=status.HTTP_200_OK)


class AdminContactMessagesBulkDeleteView(APIView):
    permission_classes = [IsStaffUser]

    def post(self, request):
        ids = request.data.get("ids", [])
        if not isinstance(ids, list) or not ids:
            return Response({"detail": "ids must be a non-empty list."}, status=status.HTTP_400_BAD_REQUEST)

        safe_ids = []
        for item in ids:
            try:
                safe_ids.append(int(item))
            except (TypeError, ValueError):
                continue
        if not safe_ids:
            return Response({"detail": "No valid message ids provided."}, status=status.HTTP_400_BAD_REQUEST)

        deleted_count, _ = ContactMessage.objects.filter(pk__in=safe_ids).delete()
        return Response({"deleted_count": deleted_count}, status=status.HTTP_200_OK)


class AdminContactMessageDetailView(APIView):
    permission_classes = [IsStaffUser]

    def get(self, request, message_id):
        try:
            item = ContactMessage.objects.get(pk=message_id)
        except ContactMessage.DoesNotExist:
            return Response({"detail": "Contact message not found."}, status=status.HTTP_404_NOT_FOUND)

        data = {
            "id": item.id,
            "username": item.username,
            "last_name": item.last_name,
            "email": item.email,
            "message": item.message,
            "ip_address": item.ip_address,
            "created_at": item.created_at,
        }
        return Response(data, status=status.HTTP_200_OK)

    def delete(self, request, message_id):
        deleted, _ = ContactMessage.objects.filter(pk=message_id).delete()
        if not deleted:
            return Response({"detail": "Contact message not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"detail": "Contact message deleted."}, status=status.HTTP_200_OK)
