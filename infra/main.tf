# Google Cloud APIs required for Cloud Run and Artifact Registry
resource "google_project_service" "run_api" {
  service                    = "run.googleapis.com"
  disable_dependent_services = false
  disable_on_destroy         = false
}

resource "google_project_service" "artifactregistry_api" {
  service                    = "artifactregistry.googleapis.com"
  disable_dependent_services = false
  disable_on_destroy         = false
}

resource "google_project_service" "iam_api" {
  service                    = "iam.googleapis.com"
  disable_dependent_services = false
  disable_on_destroy         = false
}

# Artifact Registry Repository for Docker container images
resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = var.artifact_registry_repo
  description   = "Docker repository for Tickets Datak services"
  format        = "DOCKER"

  depends_on = [google_project_service.artifactregistry_api]
}

# Dedicated Service Account for the backend Cloud Run service
resource "google_service_account" "backend_sa" {
  account_id   = "tickets-backend-sa"
  display_name = "Tickets Datak Backend Cloud Run Service Account"

  depends_on = [google_project_service.iam_api]
}
