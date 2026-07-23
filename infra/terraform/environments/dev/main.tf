module "platform" {
  source = "../../modules/platform"

  providers = {
    google                          = google
    google.no_user_project_override = google.no_user_project_override
    google.quota_project            = google.quota_project
    google-beta                     = google-beta
  }

  enabled            = true
  project_id         = var.project_id
  project_name       = "Ontology Appliance Dev"
  billing_account_id = var.billing_account_id
  folder_id          = var.folder_id
  organization_id    = var.organization_id
  environment        = "dev"
  region             = "europe-west4"
  resource_prefix    = "oa"

  monthly_budget_eur         = 50
  budget_notification_emails = var.budget_notification_emails
  github_repository          = var.github_repository
  github_branch              = "main"

  labels = {
    cost_center = "ontology-appliance-pilot"
  }
}
