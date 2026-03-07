# في ملف urls.py، أضف هذه المسارات

from django.urls import path, re_path

from . import AudioCompressor
from . import AudioConverter
from . import AudioExtractor
from . import MediaMaintenance
from . import VideoCompressor
from . import VideoConverter
from . import VideoToGif
from . import admin_api
from . import contact
from . import image_services
from . import libreoffice
from . import libreoffice_services
from . import views
from . import wordtopdf


urlpatterns = [
    path("", views.home, name="home"),

    path("test-word-to-pdf/", libreoffice_services.test_word_to_pdf_page, name="test_word_to_pdf"),

    path("api/analytics/visit/", admin_api.TrackVisitView.as_view(), name="analytics_visit"),
    path("api/analytics/tool-usage/", admin_api.TrackToolUsageView.as_view(), name="analytics_tool_usage"),
    path("api/admin/me/", admin_api.AdminMeView.as_view(), name="admin_me"),
    path("api/admin/dashboard/", admin_api.AdminDashboardView.as_view(), name="admin_dashboard"),
    path("api/admin/tools-analytics/", admin_api.AdminToolsAnalyticsView.as_view(), name="admin_tools_analytics"),
    path("api/admin/files/", admin_api.AdminFilesView.as_view(), name="admin_files"),
    path("api/admin/files/<int:file_id>/", admin_api.AdminFileDeleteView.as_view(), name="admin_file_delete"),
    path("api/admin/files/cleanup/", admin_api.AdminFilesCleanupView.as_view(), name="admin_files_cleanup"),
    path("api/admin/errors/", admin_api.AdminErrorsView.as_view(), name="admin_errors"),
    path("api/admin/errors/<int:error_id>/", admin_api.AdminErrorDetailView.as_view(), name="admin_error_detail"),
    path("api/admin/ip-usage/", admin_api.AdminIPUsageView.as_view(), name="admin_ip_usage"),
    path("api/admin/block-ip/", admin_api.AdminBlockIPView.as_view(), name="admin_block_ip"),
    path("api/admin/unblock-ip/", admin_api.AdminUnblockIPView.as_view(), name="admin_unblock_ip"),
    path("api/admin/contact-messages/", admin_api.AdminContactMessagesView.as_view(), name="admin_contact_messages"),
    path("api/admin/contact-messages/bulk-delete/", admin_api.AdminContactMessagesBulkDeleteView.as_view(), name="admin_contact_messages_bulk_delete"),
    path("api/admin/contact-messages/<int:message_id>/", admin_api.AdminContactMessageDetailView.as_view(), name="admin_contact_message_detail"),
    path("api/get-machine-token/", views.AutomaticTokenObtainView.as_view(), name="get_machine_token"),
    path("api/remove-background/", views.remove_background, name="remove_background"),
    path("api/health/", views.health_check, name="health_check"),
    path("api/protected/", views.protected_test_view, name="protected_test_view"),
    path("api/contact/", contact.submit_contact_message, name="submit_contact_message"),
    path("test", views.test_download, name="test_download"),
    path("back", views.test_download, name="back_test"),
    path(
        "api/convert/word-to-pdf/",
        libreoffice_services.convert_word_to_pdf_libreoffice,
        name="convert_word_to_pdf_libreoffice",
    ),
    path(
        "api/convert/excel-to-pdf/",
        libreoffice_services.convert_excel_to_pdf_libreoffice,
        name="convert_excel_to_pdf_libreoffice",
    ),
    path(
        "api/convert/powerpoint-to-pdf/",
        libreoffice_services.convert_powerpoint_to_pdf_libreoffice,
        name="convert_powerpoint_to_pdf_libreoffice",
    ),
    path(
        "api/convert/pdf-to-word/",
        libreoffice_services.convert_pdf_to_word_libreoffice,
        name="convert_pdf_to_word_libreoffice",
    ),
    path(
        "api/convert/pdf-to-excel/",
        libreoffice_services.convert_pdf_to_excel_libreoffice,
        name="convert_pdf_to_excel_libreoffice",
    ),
    path(
        "api/convert/pdf-to-powerpoint/",
        libreoffice_services.convert_pdf_to_powerpoint_libreoffice,
        name="convert_pdf_to_powerpoint_libreoffice",
    ),
    path(
        "api/convert/download/<str:file_id>/",
        libreoffice_services.download_converted_file_once,
        name="download_converted_file_once",
    ),
    path(
        "api/image/convert/",
        image_services.convert_image_with_imagemagick,
        name="convert_image_with_imagemagick",
    ),
    path(
        "api/image/compress/",
        image_services.compress_image_with_pillow,
        name="compress_image_with_pillow",
    ),
    path(
        "api/image/download/<str:file_id>/",
        image_services.download_image_file_once,
        name="download_image_file_once",
    ),
    
    # مسارات Word to PDF المحسنة
    path("api/word-to-pdf/", wordtopdf.convert_word_to_pdf, name="word_to_pdf"),
    
    # المسار الدائم للتحميل (لا يحذف الملف)
    re_path(
        r"^api/word-to-pdf/download/(?P<filename>.+)$",
        wordtopdf.download_converted_file_persistent,
        name="download_converted_file_persistent",
    ),
    
    # مسار للتحقق من وجود الملف
    re_path(
        r"^api/word-to-pdf/check/(?P<filename>.+)$",
        wordtopdf.check_file_exists,
        name="check_file_exists",
    ),
    
    # مسار لعرض جميع الملفات (للتشخيص)
    path("api/word-to-pdf/files/", wordtopdf.list_converted_files, name="list_files"),
    
    # الاحتفاظ بالمسار القديم للتوافق
    re_path(
        r"^api/word-to-pdf/download-legacy/(?P<filename>.+)$",
        wordtopdf.download_converted_file,
        name="download_converted_file",
    ),
    
    path("api/check/libreoffice/", libreoffice.check_libreoffice, name="check_libreoffice"),
    path("api/convert/video/", VideoConverter.convert_video, name="convert_video"),
    path("api/convert/video/download/<str:file_id>/", VideoConverter.download_media_file, name="convert_video_download"),
    path("api/convert/video/remove/<str:file_id>/", VideoConverter.remove_media_file, name="convert_video_remove"),
    path("api/convert/video-to-gif/", VideoToGif.convert_video_to_gif, name="convert_video_to_gif"),
    path(
        "api/convert/video-to-gif/download/<str:file_id>/",
        VideoToGif.download_media_file,
        name="convert_video_to_gif_download",
    ),
    path(
        "api/convert/video-to-gif/remove/<str:file_id>/",
        VideoToGif.remove_media_file,
        name="convert_video_to_gif_remove",
    ),
    path("api/compress/video/", VideoCompressor.compress_video, name="compress_video"),
    path("api/compress/video/download/<str:file_id>/", VideoCompressor.download_media_file, name="compress_video_download"),
    path("api/compress/video/remove/<str:file_id>/", VideoCompressor.remove_media_file, name="compress_video_remove"),
    path("api/convert/audio/", AudioConverter.convert_audio, name="convert_audio"),
    path("api/convert/audio/download/<str:file_id>/", AudioConverter.download_media_file, name="convert_audio_download"),
    path("api/convert/audio/remove/<str:file_id>/", AudioConverter.remove_media_file, name="convert_audio_remove"),
    path("api/compress/audio/", AudioCompressor.compress_audio, name="compress_audio"),
    path("api/compress/audio/download/<str:file_id>/", AudioCompressor.download_media_file, name="compress_audio_download"),
    path("api/compress/audio/remove/<str:file_id>/", AudioCompressor.remove_media_file, name="compress_audio_remove"),
    path("api/extract/audio/", AudioExtractor.extract_audio_from_video, name="extract_audio"),
    path("api/extract/audio/download/<str:file_id>/", AudioExtractor.download_media_file, name="extract_audio_download"),
    path("api/extract/audio/remove/<str:file_id>/", AudioExtractor.remove_media_file, name="extract_audio_remove"),
    path("api/media/cleanup/", MediaMaintenance.cleanup_media_files, name="cleanup_media"),
    path("api/media/check/<str:file_id>/", MediaMaintenance.check_file_validity, name="check_file_validity"),

    path('api/page/save/', views.save_page, name='save_page'),
    path('api/pages/save-multiple/', views.save_multiple_pages, name='save_multiple_pages'),
    path('api/page/get/', views.get_page_by_url, name='get_page'),
    path('api/pages/all/', views.get_all_pages, name='get_all_pages'),
    path('api/admin/pages/', views.admin_get_pages, name='admin_get_pages'),
    path('api/admin/pages/<int:page_id>/', views.admin_page_detail, name='admin_page_detail'),
    path('api/admin/pages/bulk-update/', views.admin_bulk_update, name='admin_bulk_update'),
    path('api/admin/pages/bulk-delete/', views.admin_bulk_delete, name='admin_bulk_delete'),
    path('api/admin/pages/stats/', views.admin_get_stats, name='admin_get_stats'),
]
