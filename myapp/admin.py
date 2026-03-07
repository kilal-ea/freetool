from django.contrib import admin
from .models import (
    BlockedIP, ContactMessage, ErrorLog, FileProcess, 
    IPUsage, SystemMetric, ToolUsage, VisitEvent, PageStatus
)


@admin.register(ToolUsage)
class ToolUsageAdmin(admin.ModelAdmin):
    list_display = ('tool_name', 'tool_category', 'operation_count', 'success', 'processing_time_ms', 'created_at')
    list_filter = ('tool_category', 'success', 'created_at')
    search_fields = ('tool_name', 'tool_category', 'conversion_from', 'conversion_to', 'ip_address')
    date_hierarchy = 'created_at'
    readonly_fields = ('created_at',)

