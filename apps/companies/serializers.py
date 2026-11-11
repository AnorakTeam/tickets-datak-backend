"""Serializers de la app `companies`.

Un serializer convierte objetos de Python/Django en JSON (y valida el JSON que
llega). Aquí está el serializer del inicio de sesión con JWT (tarea BE-03).
"""

from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


class LoginTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Login: recibe correo y contraseña y devuelve los tokens JWT y los datos del usuario.

    Lo usa el endpoint `POST /api/v1/auth/token/` (definido por José en
    config/urls.py). Se activa con la opción `TOKEN_OBTAIN_SERIALIZER` de
    SIMPLE_JWT en config/settings.py, así que no hubo que cambiar las URLs.

    Petición:  {"correo": "cliente@acme.com", "password": "..."}
    Respuesta: {"access": "...", "refresh": "...", "user": {...}}
    (formato de la sección 5.1 de ARCHITECTURE_AND_DATA_MODEL_REFERENCE.md).
    """

    # Mensaje en español cuando el correo o la contraseña no son válidos, o la
    # cuenta está inactiva. Es un mensaje general a propósito: no le dice a un
    # atacante si el correo existe o no.
    default_error_messages = {
        "no_active_account": "Correo o contraseña incorrectos, o la cuenta está inactiva.",
    }

    @classmethod
    def get_token(cls, user):
        """Crea el token y le agrega "claims" (datos) propios del proyecto.

        Los claims viajan dentro del token y el frontend puede leerlos sin pedir
        nada más al servidor:
        - rol: "cliente", "agente_soporte" o "responsable_atencion".
        - empresa_id: id de la empresa del usuario (None si es personal interno).

        Se agregan al token de refresh y SimpleJWT los copia al token de acceso,
        así que también siguen presentes cuando se renueva el acceso.
        """
        token = super().get_token(user)
        token["rol"] = user.rol
        token["empresa_id"] = user.empresa_id
        return token

    def validate(self, attrs):
        """Valida las credenciales y arma la respuesta del login.

        `super().validate()` autentica al usuario (correo + contraseña) y devuelve
        {"access": ..., "refresh": ...}. Aquí se le añade la clave "user" con los
        datos que necesita el store de Pinia del frontend (app/stores/auth.ts).
        """
        data = super().validate(attrs)
        # self.user lo deja guardado super().validate() tras autenticar.
        empresa = self.user.empresa
        data["user"] = {
            "id": self.user.id,
            "correo": self.user.correo,
            "nombre": self.user.nombre,
            "rol": self.user.rol,
            # La empresa va como objeto pequeño o null si el usuario no tiene.
            "empresa": (
                {
                    "id": empresa.id,
                    "nombre": empresa.nombre,
                    "identificacion": empresa.identificacion,
                }
                if empresa is not None
                else None
            ),
        }
        return data
