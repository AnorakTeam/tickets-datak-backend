"""Views for authentication and companies management."""

from rest_framework_simplejwt.views import TokenObtainPairView

from apps.companies.serializers import CustomTokenObtainPairSerializer


class CustomTokenObtainPairView(TokenObtainPairView):
    """Custom login view returning JWT tokens and user/company details."""

    serializer_class = CustomTokenObtainPairSerializer
