locals {
  jobs = {
    bootstrap = { cpu = "2", memory = "4Gi", timeout = "3600s", args = ["bootstrap", "--history-bucket", "${var.project}-historical", "--models-bucket", "${var.project}-models", "--operational-bucket", "${var.project}-operational"] }
    weekly    = { cpu = "1", memory = "2Gi", timeout = "1800s", args = ["weekly", "--models-bucket", "${var.project}-models", "--operational-bucket", "${var.project}-operational"] }
    cleanup   = { cpu = "1", memory = "512Mi", timeout = "600s", args = ["cleanup", "--operational-bucket", "${var.project}-operational"] }
  }
  schedules = { weekly = "0 8 * * 1", cleanup = "0 5 * * *" }
}
resource "google_cloud_run_v2_job" "pipeline" {
  for_each            = local.jobs
  name                = "air-quality-${each.key}"
  location            = var.region
  deletion_protection = true
  template {
    task_count  = 1
    parallelism = 1
    template {
      service_account       = "air-quality-${each.key}@${var.project}.iam.gserviceaccount.com"
      timeout               = each.value.timeout
      max_retries           = 0
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2"
      containers {
        image   = var.pipeline_image
        command = ["air-quality-cloud"]
        args    = each.value.args
        resources { limits = { cpu = each.value.cpu, memory = each.value.memory } }
        dynamic "env" {
          for_each = each.key == "bootstrap" ? [var.revision] : []
          content {
            name  = "GIT_COMMIT"
            value = env.value
          }
        }
      }
    }
  }
  lifecycle { prevent_destroy = true }
}
resource "google_cloud_run_v2_service" "dashboard" {
  name                = "air-quality-dashboard"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = true
  template {
    service_account                  = "air-quality-dashboard@${var.project}.iam.gserviceaccount.com"
    timeout                          = "3600s"
    max_instance_request_concurrency = 20
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    containers {
      image = var.dashboard_image
      ports { container_port = 8080 }
      resources {
        limits            = { cpu = "1", memory = "1Gi" }
        cpu_idle          = true
        startup_cpu_boost = true
      }
      env {
        name  = "MODELS_BUCKET"
        value = "${var.project}-models"
      }
      env {
        name  = "OPERATIONAL_BUCKET"
        value = "${var.project}-operational"
      }
      startup_probe {
        failure_threshold = 1
        period_seconds    = 240
        timeout_seconds   = 240
        tcp_socket { port = 8080 }
      }
    }
  }
  lifecycle { prevent_destroy = true }
}
resource "google_cloud_scheduler_job" "pipeline" {
  for_each         = local.schedules
  name             = "air-quality-${each.key}"
  region           = var.region
  schedule         = each.value
  time_zone        = "America/New_York"
  attempt_deadline = "180s"
  retry_config { retry_count = 0 }
  http_target {
    uri         = "https://run.googleapis.com/v2/projects/${var.project}/locations/${var.region}/jobs/${google_cloud_run_v2_job.pipeline[each.key].name}:run"
    http_method = "POST"
    body        = base64encode("{}")
    # Scheduler owns User-Agent and omits it from reads; declaring it causes drift.
    headers = { "Content-Type" = "application/json" }
    oauth_token {
      service_account_email = "air-quality-scheduler@${var.project}.iam.gserviceaccount.com"
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }
  lifecycle { prevent_destroy = true }
}
output "dashboard_url" { value = google_cloud_run_v2_service.dashboard.uri }
