variable "enabled" {
  description = "Master provisioning guard. Production keeps this false until explicitly approved."
  type        = bool
  default     = true
}

variable "enable_vertex_ai" {
  description = "Explicit paid-provider opt-in. Disabled by default; deployment also requires GENERATOR_PROVIDER=vertex-ai."
  type        = bool
  default     = false
}

variable "project_id" {
  description = "Globally unique GCP project ID."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid 6-30 character GCP project ID."
  }
}

variable "project_name" {
  description = "Human-readable GCP project display name."
  type        = string
}

variable "billing_account_id" {
  description = "Billing account ID required for Firebase Blaze/App Hosting."
  type        = string
  sensitive   = true

  validation {
    condition = !var.enabled || can(regex(
      "^[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}$",
      var.billing_account_id,
    ))
    error_message = "An enabled environment requires a billing account ID like 000000-000000-000000."
  }
}

variable "folder_id" {
  description = "Optional GCP folder in which to create the project."
  type        = string
  default     = null
  nullable    = true
}

variable "organization_id" {
  description = "Optional GCP organization used when no folder is supplied."
  type        = string
  default     = null
  nullable    = true
}

variable "environment" {
  description = "Short environment name used in labels and resource names."
  type        = string

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod."
  }
}

variable "region" {
  description = "Primary co-located Firebase/GCP region. App Hosting EU currently uses europe-west4."
  type        = string
  default     = "europe-west4"

  validation {
    condition     = var.region == "europe-west4"
    error_message = "This platform baseline intentionally pins the pilot to europe-west4."
  }
}

variable "resource_prefix" {
  description = "Prefix for named cloud resources."
  type        = string
  default     = "oa"
}

variable "apphosting_backend_id" {
  description = "Firebase App Hosting backend ID used to derive its default authorized domain."
  type        = string
  default     = "ontology-appliance-web"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,28}[a-z0-9]$", var.apphosting_backend_id))
    error_message = "apphosting_backend_id must be a valid 2-30 character backend ID."
  }
}

variable "labels" {
  description = "Additional labels merged into every resource that supports labels."
  type        = map(string)
  default     = {}
}

variable "monthly_budget_eur" {
  description = "Monthly budget amount in whole EUR. Alerts do not hard-stop billing."
  type        = number
  default     = 50

  validation {
    condition     = var.monthly_budget_eur > 0
    error_message = "monthly_budget_eur must be positive."
  }
}

variable "budget_notification_emails" {
  description = "Optional email channels in addition to default billing-account recipients."
  type        = set(string)
  default     = []
}

variable "storage_cors_origins" {
  description = "Origins allowed to perform the narrowly-scoped direct upload flow."
  type        = set(string)
  default     = ["http://127.0.0.1:5002", "http://localhost:5002"]
}

variable "github_repository" {
  description = "Optional owner/repository allowed to impersonate the CI service account."
  type        = string
  default     = ""

  validation {
    condition     = var.github_repository == "" || can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must use owner/repository form."
  }
}

variable "github_branch" {
  description = "Only this GitHub branch may use Workload Identity Federation."
  type        = string
  default     = "main"
}
