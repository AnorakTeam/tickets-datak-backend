from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthCheckView(APIView):
    """Simple unauthenticated health check endpoint."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok", "service": "tickets-datak-backend", "version": "1.0.0"})
