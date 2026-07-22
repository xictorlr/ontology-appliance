variable "enable_production" {
  description = "Safety switch. Keep false until a separately approved production rollout."
  type        = bool
  default     = false
}

variable "project_id" {
  type        = string
  description = "Reserved production project ID."
  default     = "ontology-appliance-prod-reserved"
}

variable "billing_account_id" {
  type        = string
  description = "Required only when production is explicitly enabled."
  sensitive   = true
  default     = ""
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

variable "github_repository" {
  type    = string
  default = ""
}
