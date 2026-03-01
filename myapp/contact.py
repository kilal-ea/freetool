from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import ContactMessage


def _client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@api_view(["POST"])
def submit_contact_message(request):
    username = str(request.data.get("username", "")).strip()
    last_name = str(request.data.get("last_name", "")).strip()
    email = str(request.data.get("email", "")).strip()
    message = str(request.data.get("message", "")).strip()

    if not username:
        return Response({"error": "Username is required."}, status=status.HTTP_400_BAD_REQUEST)
    if not last_name:
        return Response({"error": "Last name is required."}, status=status.HTTP_400_BAD_REQUEST)
    if not message:
        return Response({"error": "Message is required."}, status=status.HTTP_400_BAD_REQUEST)

    ContactMessage.objects.create(
        username=username[:120],
        last_name=last_name[:120],
        email=email,
        message=message[:5000],
        ip_address=_client_ip(request),
    )

    return Response({"success": True, "message": "Message received successfully."}, status=status.HTTP_201_CREATED)
