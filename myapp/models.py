from django.db import models


class ToolUsage(models.Model):
    tool_name = models.CharField(max_length=120, db_index=True)
    tool_category = models.CharField(max_length=64, db_index=True)
    operation_count = models.PositiveIntegerField(default=1)
    success = models.BooleanField(default=True, db_index=True)
    processing_time_ms = models.PositiveIntegerField(default=0)
    file_size_bytes = models.BigIntegerField(default=0)
    conversion_from = models.CharField(max_length=32, blank=True, default="")
    conversion_to = models.CharField(max_length=32, blank=True, default="")
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class FileProcess(models.Model):
    STATUS_CHOICES = [
        ("processing", "Processing"),
        ("success", "Success"),
        ("failed", "Failed"),
        ("deleted", "Deleted"),
    ]

    tool_name = models.CharField(max_length=120, db_index=True)
    original_filename = models.CharField(max_length=255)
    file_size = models.BigIntegerField(default=0)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="processing", db_index=True)
    upload_timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    deletion_timestamp = models.DateTimeField(null=True, blank=True)
    auto_delete = models.BooleanField(default=True)

    class Meta:
        ordering = ["-upload_timestamp"]


class SystemMetric(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    cpu_usage = models.FloatField(default=0.0)
    ram_usage = models.FloatField(default=0.0)
    disk_usage = models.FloatField(default=0.0)
    active_jobs = models.PositiveIntegerField(default=0)
    queue_length = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-timestamp"]


class ErrorLog(models.Model):
    tool_name = models.CharField(max_length=120, db_index=True)
    error_type = models.CharField(max_length=120, db_index=True)
    error_message = models.TextField()
    stack_trace = models.TextField(blank=True, default="")
    related_file = models.CharField(max_length=255, blank=True, default="")
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-timestamp"]


class BlockedIP(models.Model):
    ip_address = models.GenericIPAddressField(unique=True, db_index=True)
    reason = models.CharField(max_length=255, blank=True, default="")
    blocked_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["-blocked_at"]


class IPUsage(models.Model):
    ip_address = models.GenericIPAddressField(unique=True, db_index=True)
    total_requests = models.PositiveIntegerField(default=0)
    total_files_uploaded = models.PositiveIntegerField(default=0)
    last_request = models.DateTimeField(null=True, blank=True, db_index=True)
    requests_today = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-total_requests"]


class VisitEvent(models.Model):
    path = models.CharField(max_length=255, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    user_agent = models.CharField(max_length=512, blank=True, default="")
    session_key = models.CharField(max_length=64, blank=True, default="", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class ContactMessage(models.Model):
    username = models.CharField(max_length=120)
    last_name = models.CharField(max_length=120)
    email = models.EmailField(blank=True, default="")
    message = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

class PageStatus(models.Model):
    """نموذج لتتبع حالة صفحات الموقع"""
    
    STATUS_CHOICES = [
        ('working', 'Working'),        # يعمل ✅
        ('not_working', 'Not Working'), # لا يعمل ❌
        ('pending', 'Pending'),         # لم يعالج ⏳
        ('reprocess', 'Reprocess'),     # طلب إعادة المعالجة 🔄
    ]
    
    # معلومات الصفحة الأساسية
    url = models.URLField(max_length=500, unique=True, db_index=True)
    path = models.CharField(max_length=255, db_index=True)  # المسار النسبي
    name = models.CharField(max_length=255, blank=True, default="")  # اسم الصفحة
    category = models.CharField(max_length=100, blank=True, default="")  # تصنيف الصفحة
    
    # حالة الصفحة
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    
    # معلومات الفحص (يمكن تركها فارغة)
    last_checked = models.DateTimeField(null=True, blank=True)
    response_time = models.FloatField(null=True, blank=True)
    http_status = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")
    
    # معلومات إضافية
    title = models.CharField(max_length=500, blank=True, default="")
    meta_description = models.TextField(blank=True, default="")
    content_hash = models.CharField(max_length=64, blank=True, default="")
    
    # إحصائيات
    check_count = models.PositiveIntegerField(default=0)
    failure_count = models.PositiveIntegerField(default=0)
    
    # تواريخ
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # للصفحات الديناميكية
    is_dynamic = models.BooleanField(default=False)
    parameter_pattern = models.CharField(max_length=255, blank=True, default="")
    
    class Meta:
    ordering = ['-created_at']
    verbose_name = "Page Status"
    verbose_name_plural = "Page Statuses"
    indexes = [
        models.Index(fields=['status', 'last_checked']),
        models.Index(fields=['category', 'status']),
    ]
    
    def __str__(self):
        return f"{self.path} - {self.get_status_display()}"

   
