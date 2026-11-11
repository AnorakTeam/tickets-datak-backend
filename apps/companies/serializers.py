"""Serializers for companies and authentication."""

from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.companies.models import Empresa, Usuario


class EmpresaSerializer(serializers.ModelSerializer):
    """Serializer for Empresa tenant model."""

    class Meta:
        model = Empresa
        fields = ["id", "nombre", "identificacion", "activa", "fecha_creacion"]
        read_only_fields = ["id", "fecha_creacion"]


class UsuarioSerializer(serializers.ModelSerializer):
    """Serializer for Usuario public profile."""

    empresa = EmpresaSerializer(read_only=True)

    class Meta:
        model = Usuario
        fields = ["id", "email", "nombre", "rol", "empresa", "activo"]
        read_only_fields = ["id"]


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """SimpleJWT serializer injecting role and company details into token and response."""

    @classmethod
    def get_token(cls, user: Usuario):
        token = super().get_token(user)

        # Custom claims embedded in the JWT payload
        token["email"] = user.email
        token["nombre"] = user.nombre
        token["rol"] = user.rol
        token["empresa_id"] = user.empresa_id
        token["empresa_nombre"] = user.empresa.nombre if user.empresa else None

        return token

    def validate(self, attrs):
        data = super().validate(attrs)

        # Include user profile object in response body for immediate frontend consumption
        data["user"] = {
            "id": self.user.id,
            "email": self.user.email,
            "correo": self.user.email,
            "nombre": self.user.nombre,
            "rol": self.user.rol,
            "empresa": (
                {
                    "id": self.user.empresa.id,
                    "nombre": self.user.empresa.nombre,
                    "identificacion": self.user.empresa.identificacion,
                }
                if self.user.empresa
                else None
            ),
        }
        return data
