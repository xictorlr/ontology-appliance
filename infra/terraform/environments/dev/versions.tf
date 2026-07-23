terraform {
  required_version = ">= 1.7.0, < 2.0.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 7.0"
    }
  }

  backend "gcs" {}
}

provider "google" {
  user_project_override = true
}

provider "google" {
  alias                 = "no_user_project_override"
  user_project_override = false
}

provider "google" {
  alias                 = "quota_project"
  billing_project       = var.project_id
  user_project_override = true
}

provider "google-beta" {
  user_project_override = true
}
