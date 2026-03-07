from django.contrib import admin

from .models import BlockedIP, ContactMessage, ErrorLog, FileProcess, IPUsage, SystemMetric, ToolUsage, VisitEvent , PageStatus


admin.site.register(ToolUsage)
admin.site.register(FileProcess)
admin.site.register(SystemMetric)
admin.site.register(ErrorLog)
admin.site.register(BlockedIP)
admin.site.register(IPUsage)
admin.site.register(VisitEvent)
admin.site.register(ContactMessage)
admin.site.register(PageStatus)
