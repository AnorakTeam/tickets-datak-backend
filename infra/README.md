# Infraestructura como Código (Terraform) - Backend Cloud Run

Este directorio contiene la definición modular y reproducible en **Terraform** para aprovisionar y desplegar el backend Django (`tickets-backend`) en **Google Cloud Run** y **Artifact Registry**.

---

## Arquitectura

- **Google Cloud Run (v2)**: Servicio contenedor serverless para Django + Gunicorn con escalabilidad automática (0 a N instancias).
- **Google Artifact Registry**: Registro Docker privado para alojar las imágenes de producción.
- **Service Account dedicada**: `tickets-backend-sa` con el principio de mínimo privilegio.
- **Base de Datos Externa**: Conexión a PostgreSQL (Supabase o Cloud SQL) mediante la variable sensible `DATABASE_URL` con SSL obligatorio (`DB_SSLMODE=require`).

---

## Prerrequisitos

1. **Google Cloud SDK (`gcloud`)**: Autenticado con una cuenta con permisos de administrador en el proyecto de GCP.
   ```bash
   gcloud auth login
   gcloud auth application-default login
   gcloud config set project TU_PROJECT_ID
   ```
2. **Terraform**: `>= 1.5.0` instalado localmente o en Cloud Shell.
3. **Docker / Cloud Build**: Para compilar y subir la imagen de contenedor.

---

## Paso a Paso para el Despliegue

### 1. Construir y Subir la Imagen Docker
Antes de aplicar Terraform por primera vez, crea el repositorio en Artifact Registry (o deja que Terraform lo cree) y compila la imagen con Cloud Build:

```bash
# Desde la raíz del repositorio tickets-datak-backend
gcloud builds submit . \
  --tag us-central1-docker.pkg.dev/TU_PROJECT_ID/tickets-datak-repo/backend:latest
```

### 2. Configurar Variables de Terraform
Copia el archivo de ejemplo `terraform.tfvars.example` a `terraform.tfvars` (este archivo está ignorado en `.gitignore` para no exponer secretos):

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars
```

Edita `terraform.tfvars` con tus credenciales y proyecto:
```hcl
project_id        = "mi-proyecto-gcp"
region            = "us-central1"
service_name      = "tickets-backend"
django_secret_key = "clave-super-secreta-para-django"
database_url      = "postgresql://postgres:MI_PASSWORD@db.MI_PROJECT_REF.supabase.co:5432/postgres"
use_sqlite        = false
```

> **Importante**: Para una guía detallada sobre cómo obtener y configurar las credenciales de Supabase PostgreSQL, consulta [docs/POSTGRES_SUPABASE_SETUP.md](../docs/POSTGRES_SUPABASE_SETUP.md).

### 3. Inicializar y Aplicar Terraform

```bash
# Inicializar los proveedores de Terraform
terraform init

# Validar la sintaxis y plan de ejecución
terraform plan

# Aplicar los cambios
terraform apply
```

Al finalizar, Terraform mostrará la URL pública asignada por Cloud Run:
```bash
Outputs:
backend_url = "https://tickets-backend-XXXXX-uc.a.run.app"
```

---

## Verificación de Salud

El contenedor ejecuta automáticamente migraciones (`python manage.py migrate`), inyección de datos semilla (`python manage.py seed_data`) y recolección de estáticos (`collectstatic`) en el arranque (`docker-entrypoint.sh`).

Para verificar el estado del servicio:
```bash
# Health check básico
curl https://tickets-backend-XXXXX-uc.a.run.app/api/v1/health/

# Verificar autenticación SimpleJWT
curl -X POST https://tickets-backend-XXXXX-uc.a.run.app/api/v1/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"correo": "cliente@acme.com", "password": "test123456"}'
```
