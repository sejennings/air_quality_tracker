variable "project" {
  type    = string
  default = "air-quality-tracker-510721"
}
variable "region" {
  type    = string
  default = "us-east1"
}
variable "pipeline_image" {
  type = string
  validation {
    condition     = can(regex("^us-east1-docker.pkg.dev/air-quality-tracker-510721/air-quality/pipeline@sha256:[a-f0-9]{64}$", var.pipeline_image))
    error_message = "Use the tested private pipeline image digest."
  }
}
variable "dashboard_image" {
  type = string
  validation {
    condition     = can(regex("^us-east1-docker.pkg.dev/air-quality-tracker-510721/air-quality/dashboard@sha256:[a-f0-9]{64}$", var.dashboard_image))
    error_message = "Use the tested private dashboard image digest."
  }
}
variable "revision" {
  type = string
  validation {
    condition     = can(regex("^[a-f0-9]{40}$", var.revision))
    error_message = "Use the full tested commit SHA."
  }
}
