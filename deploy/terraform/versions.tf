terraform {
  required_version = "= 1.14.3"
  backend "gcs" {}
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "= 7.21.0"
    }
  }
}
provider "google" {
  project = var.project
  region  = var.region
}
