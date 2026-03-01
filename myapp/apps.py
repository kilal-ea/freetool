from django.apps import AppConfig


class MyappConfig(AppConfig):
    name = 'myapp'

    def ready(self):
        # Start background cleanup for all files under MEDIA_ROOT.
        from . import MediaCommon

        MediaCommon.start_media_cleanup_worker()
