print("=" * 50)
print("Loading admin.py for myapp")
print("=" * 50)

from django.contrib import admin
from .models import (
    BlockedIP, ContactMessage, ErrorLog, FileProcess, 
    IPUsage, SystemMetric, ToolUsage, VisitEvent, PageStatus
)

print(f"PageStatus imported: {PageStatus}")
print(f"All models imported: {[m.__name__ for m in [BlockedIP, ContactMessage, ErrorLog, FileProcess, IPUsage, SystemMetric, ToolUsage, VisitEvent, PageStatus]]}")
print("=" * 50)


@admin.register(ToolUsage)
class ToolUsageAdmin(admin.ModelAdmin):
    list_display = ('tool_name', 'tool_category', 'operation_count', 'success', 'processing_time_ms', 'created_at')
    list_filter = ('tool_category', 'success', 'created_at')
    search_fields = ('tool_name', 'tool_category', 'conversion_from', 'conversion_to', 'ip_address')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at',)


@admin.register(FileProcess)
class FileProcessAdmin(admin.ModelAdmin):
    list_display = ('tool_name', 'original_filename', 'file_size', 'status', 'upload_timestamp')
    list_filter = ('status', 'tool_name', 'auto_delete', 'upload_timestamp')
    search_fields = ('tool_name', 'original_filename', 'status')
    date_hierarchy = 'upload_timestamp'
    readonly_fields = ('upload_timestamp',)


@admin.register(SystemMetric)
class SystemMetricAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'cpu_usage', 'ram_usage', 'disk_usage', 'active_jobs', 'queue_length')
    list_filter = ('timestamp',)
    search_fields = ('timestamp',)
    date_hierarchy = 'timestamp'
    readonly_fields = ('timestamp',)


@admin.register(ErrorLog)
class ErrorLogAdmin(admin.ModelAdmin):
    list_display = ('tool_name', 'error_type', 'error_message', 'timestamp', 'ip_address')
    list_filter = ('tool_name', 'error_type', 'timestamp')
    search_fields = ('tool_name', 'error_type', 'error_message', 'related_file', 'ip_address', 'stack_trace')
    date_hierarchy = 'timestamp'
    readonly_fields = ('timestamp',)


@admin.register(BlockedIP)
class BlockedIPAdmin(admin.ModelAdmin):
    list_display = ('ip_address', 'reason', 'blocked_at', 'expires_at', 'is_active')
    list_filter = ('is_active', 'blocked_at')
    search_fields = ('ip_address', 'reason')
    date_hierarchy = 'blocked_at'
    readonly_fields = ('blocked_at',)


@admin.register(IPUsage)
class IPUsageAdmin(admin.ModelAdmin):
    list_display = ('ip_address', 'total_requests', 'total_files_uploaded', 'last_request', 'requests_today')
    list_filter = ('last_request',)
    search_fields = ('ip_address',)
    date_hierarchy = 'last_request'
    readonly_fields = ('last_request',)


@admin.register(VisitEvent)
class VisitEventAdmin(admin.ModelAdmin):
    list_display = ('path', 'ip_address', 'session_key', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('path', 'ip_address', 'user_agent', 'session_key')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at',)


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('username', 'last_name', 'email', 'ip_address', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('username', 'last_name', 'email', 'message', 'ip_address')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at',)


@admin.register(PageStatus)
class PageStatusAdmin(admin.ModelAdmin):
    list_display = ('path', 'name', 'category', 'status', 'last_checked', 'http_status', 'check_count')
    list_filter = ('status', 'category', 'is_dynamic', 'last_checked', 'created_at')
    search_fields = ('url', 'path', 'name', 'category', 'title', 'meta_description', 'error_message')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Page Information', {
            'fields': ('url', 'path', 'name', 'category')
        }),
        ('Page Status', {
            'fields': ('status', 'last_checked', 'response_time', 'http_status', 'error_message')
        }),
        ('Additional Information', {
            'fields': ('title', 'meta_description', 'content_hash')
        }),
        ('Statistics', {
            'fields': ('check_count', 'failure_count')
        }),
        ('Dynamic Pages', {
            'fields': ('is_dynamic', 'parameter_pattern'),
            'classes': ('collapse',)
        }),
        ('Dates', {
            'fields': ('created_at', 'updated_at')
        }),
    )

# Add debug at the end to confirm registration
print("=" * 50)
print("ADMIN REGISTRATION SUMMARY")
print("=" * 50)
for model in [ToolUsage, FileProcess, SystemMetric, ErrorLog, BlockedIP, 
              IPUsage, VisitEvent, ContactMessage, PageStatus]:
    is_registered = admin.site.is_registered(model)
    status = "✅ Registered" if is_registered else "❌ NOT REGISTERED"
    print(f"{model.__name__:20}: {status}")
print("=" * 50)
