# Guía de Conexión a PostgreSQL (Supabase) — Tickets Datak Backend

Esta guía documenta la arquitectura, configuración y puesta en marcha de la base de datos relacional **PostgreSQL** para el backend Django de **Tickets Datak**, con enfoque específico en **Supabase**.

---

## 1. Arquitectura y Tecnologías

El backend utiliza las siguientes librerías estándar en el ecosistema Python/Django para la persistencia relacional:

- **`psycopg2-binary`**: Adaptador nativo de PostgreSQL para Python.
- **`dj-database-url`**: Parser estándar de URLs de conexión a bases de datos (`DATABASE_URL`).
- **`django.db.backends.postgresql`**: Motor ORM oficial de Django para PostgreSQL.

### Selección de Supabase
Para entornos de demostración, pruebas y producción eficiente sin incurrir en los costos fijos elevados de instancias gestionadas completas (como Google Cloud SQL), se emplea **Supabase PostgreSQL**. Supabase provee:
1. Una instancia completa de PostgreSQL 15+ administrada.
2. Modo SSL obligatorio para conexiones en tránsito.
3. Connection Pooler integrado (PgBouncer/Supavisor) para manejar conexiones concurrentes sin saturar el motor.

---

## 2. Obtención de Credenciales en Supabase

1. Inicia sesión en la consola de [Supabase](https://supabase.com/dashboard).
2. Crea un nuevo proyecto o selecciona el proyecto existente (ej. `ikqcgdyxeduffbmrskdf`).
3. Ve a **Project Settings** (icono de engranaje) > **Database**.
4. En la sección **Connection parameters**, encontrarás:
   - **Host**: `db.<PROJECT-REF>.supabase.co`
   - **Database name**: `postgres`
   - **Port**: `5432`
   - **User**: `postgres`
   - **Password**: La contraseña asignada durante la creación del proyecto.
5. En la sección **Connection string**, selecciona el tab **URI**:
   ```text
   postgresql://postgres:[TU-PASSWORD]@db.<PROJECT-REF>.supabase.co:5432/postgres
   ```

### Direct Connection vs Connection Pooler
- **Conexión Directa (`port 5432`)**:
  - `postgresql://postgres:[TU-PASSWORD]@db.<PROJECT-REF>.supabase.co:5432/postgres`
  - Recomendada cuando la plataforma de ejecución (ej. Cloud Run) soporta resolución directa IPv4/IPv6.
- **Connection Pooler (`port 6543` modo Transaction o `port 5432` modo Session)**:
  - Formato del usuario: `postgres.<PROJECT-REF>`
  - Host: `aws-0-[region].pooler.supabase.com`
  - `postgresql://postgres.<PROJECT-REF>:[TU-PASSWORD]@aws-0-[region].pooler.supabase.com:6543/postgres`
  - Recomendada si se supera el límite de conexiones concurrentes o en redes con restricciones IPv6.

---

## 3. Configuración en Django (`config/settings.py`)

El backend detecta automáticamente la configuración mediante variables de entorno:

```python
# config/settings.py
USE_SQLITE = os.getenv("USE_SQLITE", "False").lower() in ("true", "1", "yes")

if USE_SQLITE:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        DATABASES = {
            "default": dj_database_url.parse(
                database_url,
                conn_max_age=600,
                conn_health_checks=True,
            )
        }
        # Forzar SSL obligatorio para Supabase
        DATABASES["default"].setdefault("OPTIONS", {})
        DATABASES["default"]["OPTIONS"]["sslmode"] = os.getenv("DB_SSLMODE", "require")
```

---

## 4. Configuración Local (`.env`)

Para desarrollo local conectado a la base de datos de Supabase, crea un archivo `.env` en la raíz de `tickets-datak-backend/` (ignorado por Git):

```bash
# .env
DEBUG=True
SECRET_KEY=clave-local-desarrollo-django-123456
USE_SQLITE=False
DATABASE_URL=postgresql://postgres:[TU-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres
DB_SSLMODE=require
```

Una vez configurado, aplica las migraciones y carga los datos de prueba:
```bash
# Activar entorno virtual
source .venv/bin/activate

# Ejecutar migraciones contra Supabase
python manage.py migrate

# Cargar datos semilla idempotentes (empresas, usuarios, roles, tickets)
python manage.py seed_data

# Iniciar servidor local
python manage.py runserver
```

---

## 5. Despliegue en Producción (Cloud Run)

En producción, la variable `DATABASE_URL` se inyecta de forma segura a través de **Terraform**:

1. En `infra/terraform.tfvars`:
   ```hcl
   project_id             = "tu-proyecto-gcp"
   region                 = "us-central1"
   database_url           = "postgresql://postgres:[TU-PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres"
   use_sqlite             = false
   ```
2. Durante el arranque del contenedor Cloud Run, el script de entrada `docker-entrypoint.sh` ejecuta de forma automática e idempotente:
   - `python manage.py migrate --noinput`
   - `python manage.py seed_data`
   - `python manage.py collectstatic --noinput`
   - `exec gunicorn config.wsgi:application ...`

---

## 6. Usuarios y Credenciales Semilla (Seed Data)

Tras ejecutar `seed_data`, se generan las siguientes cuentas de prueba:

| Rol | Correo | Contraseña | Empresa |
|---|---|---|---|
| **Administrador** | `admin@datak.com` | `admin123456` | Datak Support |
| **Ingeniero Soporte** | `soporte@datak.com` | `soporte123456` | Datak Support |
| **Cliente** | `cliente@acme.com` | `test123456` | Acme Industrial S.A.S. |

---

## 7. Resolución de Problemas Frecuentes

### Error: `OperationalError: connection to server at "db....supabase.co" failed: SSL connection has been closed unexpectedly`
- **Causa**: Falta el parámetro SSL o timeout en el handshake inicial.
- **Solución**: Asegúrate de que `DB_SSLMODE=require` esté configurado y que el puerto sea `5432` o `6543`.

### Error: `Network is unreachable (IPv6)`
- **Causa**: La dirección `db.<REF>.supabase.co` resuelve por defecto a una dirección IPv6 (`AAAA`). Si la red local o el host no tiene ruta saliente IPv6, fallará la resolución.
- **Solución**:
  - En Google Cloud Run, el soporte de red incluye egress compatible.
  - Para entornos locales sin IPv6, utiliza la URL del Connection Pooler de Supabase (`aws-0-[region].pooler.supabase.com:6543`) que dispone de endpoints IPv4 nativos.

### Buenas Prácticas de Seguridad
- **NUNCA** subas contraseñas reales ni cadenas de conexión a repositorios Git.
- El archivo `.gitignore` debe excluir siempre `.env`, `.env.*` (excepto `.env.example`) y archivos de estado de Terraform (`*.tfstate`, `*.tfvars`).
