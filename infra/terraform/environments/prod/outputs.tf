output "production_enabled" {
  value = var.enable_production
}

output "project_id" {
  value = module.platform.project_id
}
