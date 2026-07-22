output "project_id" {
  value = module.platform.project_id
}

output "region" {
  value = module.platform.region
}

output "apphosting_url" {
  value = module.platform.apphosting_url
}

output "firebase_web_app_id" {
  value = module.platform.firebase_web_app_id
}

output "input_bucket_name" {
  value = module.platform.input_bucket_name
}

output "artifact_bucket_name" {
  value = module.platform.artifact_bucket_name
}

output "artifact_registry_repository" {
  value = module.platform.artifact_registry_repository
}

output "artifact_registry_image" {
  value = module.platform.artifact_registry_image
}

output "runtime_service_accounts" {
  value = module.platform.runtime_service_accounts
}

output "empty_secret_ids" {
  value = module.platform.empty_secret_ids
}

output "github_workload_identity_provider" {
  value = module.platform.github_workload_identity_provider
}

output "github_publisher_workload_identity_provider" {
  value = module.platform.github_publisher_workload_identity_provider
}

output "github_rollback_workload_identity_provider" {
  value = module.platform.github_rollback_workload_identity_provider
}

output "github_semantic_rollout_workload_identity_provider" {
  value = module.platform.github_semantic_rollout_workload_identity_provider
}
