from rest_framework import serializers

class FileConversionSerializer(serializers.Serializer):
    file = serializers.FileField(required=True)
    format = serializers.CharField(required=False, default='pdf')
    quality = serializers.IntegerField(required=False, default=85, min_value=1, max_value=100)
    page_size = serializers.CharField(required=False, default='A4')
    orientation = serializers.CharField(required=False, default='portrait')
    margin = serializers.IntegerField(required=False, default=10)
    resize = serializers.IntegerField(required=False, default=100, min_value=10, max_value=100)

class MultipleFilesSerializer(serializers.Serializer):
    files = serializers.ListField(
        child=serializers.FileField(),
        required=True
    )
    output_format = serializers.CharField(required=False, default='pdf')
    merge = serializers.BooleanField(required=False, default=True)