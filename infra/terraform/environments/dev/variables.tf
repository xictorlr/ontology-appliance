variable "project_id" {
  type        = string
  description = "Globally unique development project ID."
}

variable "billing_account_id" {
  type        = string
  description = "Billing account linked to the new development project."
  sensitive   = true
}

variable "folder_id" {
  type     = string
  default  = null
  nullable = true
}

variable "organization_id" {
  type     = string
  default  = null
  nullable = true
}

variable "budget_notification_emails" {
  type    = set(string)
  default = []
}

variable "github_repository" {
  type    = string
  default = ""
}
