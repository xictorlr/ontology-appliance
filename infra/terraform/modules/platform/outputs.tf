output "project_id" {
  description = "Created Firebase/GCP project ID."
  value       = var.enabled ? google_project.this[0].project_id : null
}

output "project_number" {
  description = "Created project number used by service agents."
  value       = var.enabled ? google_project.this[0].number : null
}

output "region" {
  value = var.region
}

output "apphosting_url" {
  description = "Deterministic default App Hosting URL and Firebase Auth authorized domain."
  value       = var.enabled ? local.apphosting_origin : null
}

output "firebase_web_app_id" {
  description = "Terraform-managed Firebase Web App ID bound to App Hosting."
  value       = var.enabled ? google_firebase_web_app.web[0].app_id : null
}

output "input_bucket_name" {
  description = "Set SOURCE_BUCKET to this value before deploying Functions."
  value       = var.enabled ? google_storage_bucket.input[0].name : null
}

output "artifact_bucket_name" {
  value = var.enabled ? google_storage_bucket.artifacts[0].name : null
}

output "artifact_registry_repository" {
  value = var.enabled ? google_artifact_registry_repository.containers[0].name : null
}

output "artifact_registry_image" {
  description = "Untagged Semantic Gateway image URI consumed by GitHub Actions."
  value = var.enabled ? format(
    "%s-docker.pkg.dev/%s/%s/semantic-gateway",
    var.region,
    google_project.this[0].project_id,
    google_artifact_registry_repository.containers[0].repository_id,
  ) : null
}

output "runtime_service_accounts" {
  value = var.enabled ? {
    for key, account in google_service_account.runtime : key => account.email
  } : {}
}

output "empty_secret_ids" {
  description = "Secret containers only; add versions out-of-band and never in tfvars/state."
  value = var.enabled ? {
    for key, secret in google_secret_manager_secret.empty : key => secret.secret_id
  } : {}
}

output "github_workload_identity_provider" {
  value = local.github_wif_enabled ? google_iam_workload_identity_pool_provider.github[0].name : null
}

output "github_publisher_workload_identity_provider" {
  value = local.github_wif_enabled ? google_iam_workload_identity_pool_provider.github_publisher[0].name : null
}

output "github_rollback_workload_identity_provider" {
  value = local.github_wif_enabled ? google_iam_workload_identity_pool_provider.github_rollback[0].name : null
}

output "github_semantic_rollout_workload_identity_provider" {
  value = local.github_wif_enabled ? google_iam_workload_identity_pool_provider.github_semantic_rollout[0].name : null
}
