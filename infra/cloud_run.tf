locals {
  backend_image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.repository_id}/backend:${var.backend_image_tag}"
}

resource "google_cloud_run_v2_service" "backend" {
  name     = var.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.backend_sa.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = local.backend_image

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      env {
        name  = "DEBUG"
        value = "False"
      }

      env {
        name  = "SECRET_KEY"
        value = var.django_secret_key
      }

      env {
        name  = "DATABASE_URL"
        value = var.database_url
      }

      env {
        name  = "DB_SSLMODE"
        value = "require"
      }

      env {
        name  = "USE_SQLITE"
        value = var.use_sqlite ? "True" : "False"
      }

      env {
        name  = "AUTO_SEED"
        value = "True"
      }

      env {
        name  = "CORS_ALLOW_ALL_ORIGINS"
        value = "True"
      }

      env {
        name  = "CSRF_TRUSTED_ORIGINS"
        value = "https://*.a.run.app,https://*.run.app"
      }
    }
  }

  depends_on = [
    google_project_service.run_api,
    google_artifact_registry_repository.repo,
    google_service_account.backend_sa,
  ]
}

# Allow unauthenticated public invocations (API backend secured with SimpleJWT)
resource "google_cloud_run_v2_service_iam_member" "backend_public" {
  project  = var.project_id
  location = google_cloud_run_v2_service.backend.location
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
