variable "project_id" {
  description = "Google Cloud Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region for Cloud Run and Artifact Registry"
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Name of the Cloud Run service"
  type        = string
  default     = "tickets-backend"
}

variable "artifact_registry_repo" {
  description = "Artifact Registry repository ID"
  type        = string
  default     = "tickets-datak-repo"
}

variable "backend_image_tag" {
  description = "Docker image tag for backend"
  type        = string
  default     = "latest"
}

variable "django_secret_key" {
  description = "Django SECRET_KEY"
  type        = string
  sensitive   = true
}

variable "database_url" {
  description = "PostgreSQL Database URL (e.g. Supabase connection string)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "use_sqlite" {
  description = "Whether to use local SQLite instead of PostgreSQL"
  type        = bool
  default     = false
}

variable "min_instances" {
  description = "Minimum number of Cloud Run instances (0 allows scale to zero)"
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Maximum number of Cloud Run instances"
  type        = number
  default     = 3
}
