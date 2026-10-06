# Adopt existing production resources; never recreate them during migration.
import {
  for_each = local.jobs
  to       = google_cloud_run_v2_job.pipeline[each.key]
  id       = "projects/${var.project}/locations/${var.region}/jobs/air-quality-${each.key}"
}
import {
  to = google_cloud_run_v2_service.dashboard
  id = "projects/${var.project}/locations/${var.region}/services/air-quality-dashboard"
}
import {
  for_each = local.schedules
  to       = google_cloud_scheduler_job.pipeline[each.key]
  id       = "projects/${var.project}/locations/${var.region}/jobs/air-quality-${each.key}"
}
