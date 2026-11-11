"""URL configuration for tickets-datak-backend project."""

from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.companies.views import CustomTokenObtainPairView
from apps.core.views import HealthCheckView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Health check
    path("api/v1/health/", HealthCheckView.as_view(), name="health-check"),
    # SimpleJWT Authentication
    path("api/v1/auth/token/", CustomTokenObtainPairView.as_view(), name="token-obtain-pair"),
    path("api/v1/auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("api/v1/auth/login/", CustomTokenObtainPairView.as_view(), name="auth-login"),
    path("api/v1/auth/refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    # Modular apps API routes
    path("api/v1/", include("apps.companies.urls")),
    path("api/v1/", include("apps.tickets.urls")),
]
