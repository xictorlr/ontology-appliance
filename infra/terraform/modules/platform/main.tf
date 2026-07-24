locals {
  name_prefix       = "${var.resource_prefix}-${var.environment}"
  apphosting_domain = "${var.apphosting_backend_id}--${var.project_id}.${var.region}.hosted.app"
  apphosting_origin = "https://${local.apphosting_domain}"
  common_labels = merge(
    {
      application = "ontology-appliance"
      environment = var.environment
      managed_by  = "terraform"
    },
    var.labels,
  )

  required_apis = setunion(toset([
    "artifactregistry.googleapis.com",
    "billingbudgets.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudbilling.googleapis.com",
    "cloudfunctions.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "cloudscheduler.googleapis.com",
    "cloudtasks.googleapis.com",
    "compute.googleapis.com",
    "developerconnect.googleapis.com",
    "eventarc.googleapis.com",
    "firebase.googleapis.com",
    "firebaseapphosting.googleapis.com",
    "firebaserules.googleapis.com",
    "firebasestorage.googleapis.com",
    "firestore.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "identitytoolkit.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "pubsub.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "serviceusage.googleapis.com",
    "storage.googleapis.com",
    "sts.googleapis.com",
  ]), var.enable_vertex_ai ? toset(["aiplatform.googleapis.com"]) : toset([]))

  runtime_service_accounts = {
    apphosting = "App Hosting BFF runtime"
    functions  = "Firebase Functions control plane"
    publisher  = "Ontology artifact publisher"
    semantic   = "Semantic Gateway runtime"
    ci         = "GitHub Actions deployment identity"
  }

  secret_ids = toset([
    "openai-api-key",
    "semantic-gateway-url",
  ])

  github_wif_enabled  = var.enabled && trimspace(var.github_repository) != ""
  organization_scoped = var.folder_id != null || var.organization_id != null
}

resource "google_project" "this" {
  provider = google.no_user_project_override
  count    = var.enabled ? 1 : 0

  project_id      = var.project_id
  name            = var.project_name
  billing_account = var.billing_account_id
  folder_id       = var.folder_id
  org_id          = var.folder_id == null ? var.organization_id : null
  labels          = local.common_labels

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_project_service" "required" {
  provider = google.no_user_project_override
  for_each = var.enabled ? local.required_apis : toset([])

  project            = google_project.this[0].project_id
  service            = each.value
  disable_on_destroy = false
}

# Keep the Firebase Extensions control API independent from the core API
# for_each. Adding a key to that collection defers default-service-account data
# sources during planning and would otherwise cause unnecessary IAM
# remove/recreate operations. Firebase CLI requires this API to analyze
# parameterized Functions even when no extension is installed.
resource "google_project_service" "firebase_extensions_control" {
  provider = google.no_user_project_override
  count    = var.enabled ? 1 : 0

  project            = google_project.this[0].project_id
  service            = "firebaseextensions.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "org_policy" {
  provider = google.no_user_project_override
  count    = var.enabled ? 1 : 0

  project            = google_project.this[0].project_id
  service            = "orgpolicy.googleapis.com"
  disable_on_destroy = false
}

resource "google_firebase_project" "this" {
  provider = google-beta
  count    = var.enabled ? 1 : 0

  project = google_project.this[0].project_id

  depends_on = [google_project_service.required]
}

resource "google_org_policy_policy" "disable_default_sa_auto_grants" {
  provider = google.quota_project
  # Creating a project policy still requires a permission whose lowest grant
  # level is the organization. Standalone projects cannot receive that
  # permission, including through a project custom role.
  count = var.enabled && local.organization_scoped ? 1 : 0

  name   = "projects/${google_project.this[0].number}/policies/iam.automaticIamGrantsForDefaultServiceAccounts"
  parent = "projects/${google_project.this[0].number}"

  spec {
    rules {
      enforce = "TRUE"
    }
  }

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.org_policy]
}

# Remove only the exact automatic Editor grants. The provider's broader
# google_project_default_service_accounts DEPRIVILEGE action removes every
# project-level role from the default identities, including the explicit
# Cloud Build role below, so it is intentionally not used here.
resource "google_project_iam_member_remove" "compute_default_editor" {
  count = var.enabled ? 1 : 0

  project = google_project.this[0].project_id
  role    = "roles/editor"
  member  = "serviceAccount:${google_project.this[0].number}-compute@developer.gserviceaccount.com"

  lifecycle {
    prevent_destroy = true
  }

  # Organization-scoped projects first block future automatic grants.
  # Standalone projects have no policy instance and enforce exact absence on
  # each Terraform apply through this negative IAM resource.
  depends_on = [google_org_policy_policy.disable_default_sa_auto_grants]
}

resource "google_project_iam_member_remove" "app_engine_default_editor" {
  count = var.enabled ? 1 : 0

  project = google_project.this[0].project_id
  role    = "roles/editor"
  member  = "serviceAccount:${google_project.this[0].project_id}@appspot.gserviceaccount.com"

  lifecycle {
    prevent_destroy = true
  }

  # Serialize project IAM writes to avoid etag races.
  depends_on = [google_project_iam_member_remove.compute_default_editor]
}

resource "google_firebase_web_app" "web" {
  provider = google-beta
  count    = var.enabled ? 1 : 0

  project         = google_firebase_project.this[0].project
  display_name    = "${local.name_prefix} App Hosting web app"
  deletion_policy = "ABANDON"

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [google_project_service.required]
}

resource "google_firestore_database" "default" {
  provider = google-beta
  count    = var.enabled ? 1 : 0

  project                     = google_project.this[0].project_id
  name                        = "(default)"
  location_id                 = var.region
  type                        = "FIRESTORE_NATIVE"
  concurrency_mode            = "OPTIMISTIC"
  app_engine_integration_mode = "DISABLED"
  delete_protection_state     = "DELETE_PROTECTION_ENABLED"

  depends_on = [google_firebase_project.this]
}

resource "google_firestore_document" "demo_tenant" {
  count = var.enabled ? 1 : 0

  project         = google_project.this[0].project_id
  database        = google_firestore_database.default[0].name
  collection      = "tenants"
  document_id     = "demo-bank"
  deletion_policy = "PREVENT"
  fields = jsonencode({
    tenantId           = { stringValue = "demo-bank" }
    displayName        = { stringValue = "Synthetic Demo Bank" }
    status             = { stringValue = "ACTIVE" }
    environment        = { stringValue = var.environment }
    dataClassification = { stringValue = "SYNTHETIC_ONLY" }
    managedBy          = { stringValue = "terraform" }
    schemaVersion      = { integerValue = "1" }
  })
}

resource "google_firestore_document" "demo_tenant_bootstrap_audit" {
  count = var.enabled ? 1 : 0

  project         = google_project.this[0].project_id
  database        = google_firestore_database.default[0].name
  collection      = "tenants/demo-bank/auditEvents"
  document_id     = "terraform-bootstrap-v1"
  deletion_policy = "PREVENT"
  fields = jsonencode({
    eventType          = { stringValue = "TENANT_BOOTSTRAPPED" }
    tenantId           = { stringValue = "demo-bank" }
    actorType          = { stringValue = "INFRASTRUCTURE" }
    actorId            = { stringValue = "terraform" }
    status             = { stringValue = "SUCCEEDED" }
    dataClassification = { stringValue = "SYNTHETIC_ONLY" }
    schemaVersion      = { integerValue = "1" }
  })

  depends_on = [google_firestore_document.demo_tenant]
}

resource "google_identity_platform_config" "auth" {
  provider = google-beta
  count    = var.enabled ? 1 : 0

  project = google_project.this[0].project_id

  # Email-link redirects must use an explicitly authorized HTTPS domain. New
  # Firebase projects no longer authorize localhost by default, and the pilot
  # intentionally does not add it to the cloud project.
  authorized_domains = [
    "${google_project.this[0].project_id}.firebaseapp.com",
    "${google_project.this[0].project_id}.web.app",
    local.apphosting_domain,
  ]

  autodelete_anonymous_users = true
  sign_in {
    anonymous {
      enabled = false
    }
    email {
      enabled           = true
      password_required = false
    }
    phone_number {
      enabled = false
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket" "input" {
  provider = google-beta
  count    = var.enabled ? 1 : 0

  project                     = google_project.this[0].project_id
  name                        = "${google_project.this[0].project_id}-oa-input"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = local.common_labels

  versioning {
    enabled = true
  }

  dynamic "cors" {
    for_each = [1]
    content {
      origin          = sort(tolist(setunion(var.storage_cors_origins, toset([local.apphosting_origin]))))
      method          = ["GET", "HEAD", "POST", "PUT", "OPTIONS"]
      response_header = ["Content-Type", "Authorization", "x-goog-resumable"]
      max_age_seconds = 3600
    }
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age                = 30
      num_newer_versions = 2
      with_state         = "ARCHIVED"
    }
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age            = 2
      matches_prefix = ["tenants/demo-bank/uploads/smoke-"]
      with_state     = "ANY"
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket" "artifacts" {
  provider = google-beta
  count    = var.enabled ? 1 : 0

  project                     = google_project.this[0].project_id
  name                        = "${google_project.this[0].project_id}-oa-artifacts"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = local.common_labels

  versioning {
    enabled = true
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age                = 90
      num_newer_versions = 5
      with_state         = "ARCHIVED"
    }
  }

  depends_on = [google_project_service.required]
}

# The App Hosting compute identity needs Firebase's project-level Compute Runner
# role for its own build and runtime buckets. Tag the governed artifact bucket so
# its allow binding can exclude that bucket. Organization-scoped projects also
# add a Deny policy as defense in depth.
resource "google_tags_tag_key" "artifact_access_boundary" {
  count = var.enabled ? 1 : 0

  parent          = "projects/${google_project.this[0].project_id}"
  short_name      = "oa-artifact-access"
  description     = "Access boundary for governed Ontology Appliance artifacts."
  deletion_policy = "PREVENT"

  depends_on = [google_project_service.required]
}

resource "google_tags_tag_value" "publisher_only" {
  count = var.enabled ? 1 : 0

  parent          = google_tags_tag_key.artifact_access_boundary[0].id
  short_name      = "publisher-only"
  description     = "Only the Publisher boundary may mutate canonical artifacts."
  deletion_policy = "PREVENT"
}

resource "google_tags_location_tag_binding" "artifact_publisher_only" {
  count = var.enabled ? 1 : 0

  parent          = "//storage.googleapis.com/projects/_/buckets/${google_storage_bucket.artifacts[0].name}"
  tag_value       = google_tags_tag_value.publisher_only[0].id
  location        = var.region
  deletion_policy = "PREVENT"
}

resource "google_firebase_storage_bucket" "input" {
  provider = google-beta
  count    = var.enabled ? 1 : 0

  project   = google_firebase_project.this[0].project
  bucket_id = google_storage_bucket.input[0].name
}

resource "google_firebase_storage_bucket" "artifacts" {
  provider = google-beta
  count    = var.enabled ? 1 : 0

  project   = google_firebase_project.this[0].project
  bucket_id = google_storage_bucket.artifacts[0].name
}

resource "google_artifact_registry_repository" "containers" {
  count = var.enabled ? 1 : 0

  project       = google_project.this[0].project_id
  location      = var.region
  repository_id = "${local.name_prefix}-containers"
  description   = "Ontology Appliance service images"
  format        = "DOCKER"
  labels        = local.common_labels

  cleanup_policy_dry_run = false
  cleanup_policies {
    id     = "delete-untagged-after-seven-days"
    action = "DELETE"
    condition {
      tag_state  = "UNTAGGED"
      older_than = "604800s"
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_service_account" "runtime" {
  for_each = var.enabled ? local.runtime_service_accounts : {}

  project      = google_project.this[0].project_id
  account_id   = "${local.name_prefix}-${each.key}"
  display_name = each.value
  description  = "Least-privilege identity managed by Terraform for ${each.key}."
}

data "google_compute_default_service_account" "functions_build" {
  count = var.enabled ? 1 : 0

  project = google_project.this[0].project_id

  depends_on = [google_project_service.required["compute.googleapis.com"]]
}

resource "google_project_iam_member" "functions_build_builder" {
  count = var.enabled ? 1 : 0

  project = google_project.this[0].project_id
  role    = "roles/cloudbuild.builds.builder"
  member  = "serviceAccount:${data.google_compute_default_service_account.functions_build[0].email}"
}

resource "google_service_account_iam_member" "ci_functions_build_act_as" {
  count = var.enabled ? 1 : 0

  service_account_id = data.google_compute_default_service_account.functions_build[0].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.runtime["ci"].email}"
}

# Firebase CLI validates the legacy App Engine default identity before a
# Functions v2 deploy even when every function declares the dedicated runtime
# service account. Limit ActAs to the CI deployer on this one service account;
# the default identity intentionally retains no project-level Editor role.
resource "google_service_account_iam_member" "ci_app_engine_default_act_as" {
  count = var.enabled ? 1 : 0

  service_account_id = "projects/${google_project.this[0].project_id}/serviceAccounts/${google_project.this[0].project_id}@appspot.gserviceaccount.com"
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.runtime["ci"].email}"

  depends_on = [google_firebase_project.this]
}

resource "google_project_iam_member" "firestore_runtime" {
  for_each = var.enabled ? toset(["functions"]) : toset([])

  project = google_project.this[0].project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.runtime[each.value].email}"
}

resource "google_project_iam_custom_role" "apphosting_firestore_review" {
  count = var.enabled ? 1 : 0

  project     = google_project.this[0].project_id
  role_id     = "oa_${var.environment}_reviewWriter"
  title       = "Ontology Appliance review writer"
  description = "Read proposals and create/update governed review records without delete access."
  permissions = [
    "datastore.databases.get",
    "datastore.entities.create",
    "datastore.entities.get",
    "datastore.entities.list",
    "datastore.entities.update",
  ]
}

resource "google_project_iam_member" "apphosting_firestore_review" {
  count = var.enabled ? 1 : 0

  project = google_project.this[0].project_id
  role    = google_project_iam_custom_role.apphosting_firestore_review[0].name
  member  = "serviceAccount:${google_service_account.runtime["apphosting"].email}"
}

resource "google_project_iam_custom_role" "firebase_session_issuer" {
  count = var.enabled ? 1 : 0

  project     = google_project.this[0].project_id
  role_id     = "oa_${var.environment}_sessionIssuer"
  title       = "Ontology Appliance session issuer"
  description = "Issue and revoke-check Firebase session cookies without user administration."
  permissions = [
    "firebaseauth.users.createSession",
    "firebaseauth.users.get",
  ]
}

resource "google_project_iam_member" "apphosting_session_issuer" {
  count = var.enabled ? 1 : 0

  project = google_project.this[0].project_id
  role    = google_project_iam_custom_role.firebase_session_issuer[0].name
  member  = "serviceAccount:${google_service_account.runtime["apphosting"].email}"
}

# App Hosting uses the backend service account for both Cloud Build and the
# managed Cloud Run runtime. This is the Firebase-defined minimum role for a
# user-supplied compute identity; application permissions stay separate below.
# The conditional binding excludes the tagged canonical artifact bucket from
# this otherwise project-level role. Organization-scoped projects add a Deny
# policy as defense in depth; standalone projects cannot grant Deny Admin
# because Google only exposes that role at organization level.
resource "google_project_iam_member" "apphosting_compute_runner" {
  count = var.enabled ? 1 : 0

  project = google_project.this[0].project_id
  role    = "roles/firebaseapphosting.computeRunner"
  member  = "serviceAccount:${google_service_account.runtime["apphosting"].email}"

  condition {
    title       = "exclude_governed_artifact_bucket"
    description = "App Hosting may use its managed build buckets but never the canonical ontology artifact bucket."
    expression  = "!resource.matchTagId('${google_tags_tag_key.artifact_access_boundary[0].id}', '${google_tags_tag_value.publisher_only[0].id}')"
  }

  depends_on = [
    google_iam_deny_policy.apphosting_artifact_mutation,
    google_tags_location_tag_binding.artifact_publisher_only,
  ]
}

resource "google_iam_deny_policy" "apphosting_artifact_mutation" {
  provider = google-beta
  count    = var.enabled && local.organization_scoped ? 1 : 0

  parent          = urlencode("cloudresourcemanager.googleapis.com/projects/${google_project.this[0].project_id}")
  name            = "${local.name_prefix}-apphosting-artifact-mutation"
  display_name    = "Block App Hosting writes to governed artifacts"
  deletion_policy = "PREVENT"

  rules {
    description = "The App Hosting compute identity may read but never mutate the publisher-only artifact bucket."
    deny_rule {
      denied_principals = [
        "principal://iam.googleapis.com/projects/-/serviceAccounts/${google_service_account.runtime["apphosting"].email}",
      ]
      denied_permissions = [
        "storage.googleapis.com/folders.create",
        "storage.googleapis.com/folders.delete",
        "storage.googleapis.com/folders.rename",
        "storage.googleapis.com/managedFolders.create",
        "storage.googleapis.com/managedFolders.delete",
        "storage.googleapis.com/multipartUploads.abort",
        "storage.googleapis.com/multipartUploads.create",
        "storage.googleapis.com/objects.create",
        "storage.googleapis.com/objects.createContext",
        "storage.googleapis.com/objects.delete",
        "storage.googleapis.com/objects.deleteContext",
        "storage.googleapis.com/objects.move",
        "storage.googleapis.com/objects.overrideUnlockedRetention",
        "storage.googleapis.com/objects.restore",
        "storage.googleapis.com/objects.setIamPolicy",
        "storage.googleapis.com/objects.setRetention",
        "storage.googleapis.com/objects.update",
        "storage.googleapis.com/objects.updateContext",
      ]

      denial_condition {
        title       = "publisher_only_artifact_bucket"
        description = "Apply only to the canonical bucket and its descendants; App Hosting-managed buckets remain writable."
        expression  = "resource.matchTagId('${google_tags_tag_key.artifact_access_boundary[0].id}', '${google_tags_tag_value.publisher_only[0].id}')"
      }
    }
  }

  depends_on = [google_tags_location_tag_binding.artifact_publisher_only]
}

resource "google_project_iam_custom_role" "firebase_session_verifier" {
  count = var.enabled ? 1 : 0

  project     = google_project.this[0].project_id
  role_id     = "oa_${var.environment}_sessionVerifier"
  title       = "Ontology Appliance session verifier"
  description = "Read Firebase user state for revoked-session checks."
  permissions = ["firebaseauth.users.get"]
}

resource "google_project_iam_member" "semantic_session_verifier" {
  count = var.enabled ? 1 : 0

  project = google_project.this[0].project_id
  role    = google_project_iam_custom_role.firebase_session_verifier[0].name
  member  = "serviceAccount:${google_service_account.runtime["semantic"].email}"
}

resource "google_storage_bucket_iam_member" "input_functions_reader" {
  count = var.enabled ? 1 : 0

  bucket = google_storage_bucket.input[0].name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.runtime["functions"].email}"
}

resource "google_storage_bucket_iam_member" "input_ci_smoke_creator" {
  count = var.enabled ? 1 : 0

  bucket = google_storage_bucket.input[0].name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.runtime["ci"].email}"

  condition {
    title       = "create_demo_bank_smoke_uploads_only"
    description = "Deployment smoke tests may create only unique synthetic demo-bank upload objects."
    expression  = "resource.name.startsWith('projects/_/buckets/${google_storage_bucket.input[0].name}/objects/tenants/demo-bank/uploads/smoke-')"
  }
}

resource "google_storage_bucket_iam_member" "artifact_semantic_reader" {
  count = var.enabled ? 1 : 0

  bucket = google_storage_bucket.artifacts[0].name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.runtime["semantic"].email}"
}

resource "google_storage_bucket_iam_member" "artifact_ci_reader" {
  count = var.enabled ? 1 : 0

  bucket = google_storage_bucket.artifacts[0].name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.runtime["ci"].email}"
}

resource "google_storage_bucket_iam_member" "artifact_publisher_creator" {
  count = var.enabled ? 1 : 0

  bucket = google_storage_bucket.artifacts[0].name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.runtime["publisher"].email}"

  condition {
    title       = "create_demo_bank_governed_semantic_objects_only"
    description = "Publisher may create immutable releases, rollback audits, and the stable active pointer only."
    expression  = "resource.name.startsWith('projects/_/buckets/${google_storage_bucket.artifacts[0].name}/objects/tenants/demo-bank/ontology/releases/') || resource.name.startsWith('projects/_/buckets/${google_storage_bucket.artifacts[0].name}/objects/tenants/demo-bank/ontology/rollbacks/') || resource.name == 'projects/_/buckets/${google_storage_bucket.artifacts[0].name}/objects/tenants/demo-bank/ontology/active.json'"
  }
}

resource "google_storage_bucket_iam_member" "artifact_publisher_reader" {
  count = var.enabled ? 1 : 0

  bucket = google_storage_bucket.artifacts[0].name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.runtime["publisher"].email}"
}

resource "google_project_iam_custom_role" "artifact_pointer_activator" {
  count = var.enabled ? 1 : 0

  project     = google_project.this[0].project_id
  role_id     = "oa_${var.environment}_artifactPointerActivator"
  title       = "Ontology active pointer activator"
  description = "Replace only the stable ontology active pointer; immutable releases remain undeletable."
  permissions = ["storage.objects.delete"]
}

resource "google_storage_bucket_iam_member" "artifact_pointer_activator" {
  count = var.enabled ? 1 : 0

  bucket = google_storage_bucket.artifacts[0].name
  role   = google_project_iam_custom_role.artifact_pointer_activator[0].name
  member = "serviceAccount:${google_service_account.runtime["publisher"].email}"

  condition {
    title       = "replace_demo_bank_active_pointer_only"
    description = "Publisher may replace the recoverable active pointer but not immutable release objects."
    expression  = "resource.name == 'projects/_/buckets/${google_storage_bucket.artifacts[0].name}/objects/tenants/demo-bank/ontology/active.json'"
  }
}

resource "google_project_iam_member" "functions_control_plane_roles" {
  for_each = var.enabled ? toset([
    "roles/cloudtasks.enqueuer",
    "roles/eventarc.eventReceiver",
  ]) : toset([])

  project = google_project.this[0].project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.runtime["functions"].email}"
}

resource "google_service_account_iam_member" "functions_self_act_as" {
  count = var.enabled ? 1 : 0

  service_account_id = google_service_account.runtime["functions"].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.runtime["functions"].email}"
}

data "google_storage_project_service_account" "gcs" {
  count = var.enabled ? 1 : 0

  project = google_project.this[0].project_id

  depends_on = [google_project_service.required["storage.googleapis.com"]]
}

resource "google_project_iam_member" "storage_event_publisher" {
  count = var.enabled ? 1 : 0

  project = google_project.this[0].project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${data.google_storage_project_service_account.gcs[0].email_address}"
}

resource "google_project_iam_member" "semantic_vertex_user" {
  count = var.enabled && var.enable_vertex_ai ? 1 : 0

  project = google_project.this[0].project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.runtime["semantic"].email}"
}

resource "google_secret_manager_secret" "empty" {
  for_each = var.enabled ? local.secret_ids : toset([])

  project   = google_project.this[0].project_id
  secret_id = "${local.name_prefix}-${each.value}"
  labels    = local.common_labels

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_iam_member" "openai_semantic_accessor" {
  count = var.enabled ? 1 : 0

  project   = google_project.this[0].project_id
  secret_id = google_secret_manager_secret.empty["openai-api-key"].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime["semantic"].email}"
}

resource "google_secret_manager_secret_iam_member" "gateway_url_apphosting_accessor" {
  count = var.enabled ? 1 : 0

  project   = google_project.this[0].project_id
  secret_id = google_secret_manager_secret.empty["semantic-gateway-url"].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime["apphosting"].email}"
}

resource "google_secret_manager_secret_iam_member" "gateway_url_ci_version_adder" {
  count = var.enabled ? 1 : 0

  project   = google_project.this[0].project_id
  secret_id = google_secret_manager_secret.empty["semantic-gateway-url"].secret_id
  role      = "roles/secretmanager.secretVersionAdder"
  member    = "serviceAccount:${google_service_account.runtime["ci"].email}"
}

resource "google_monitoring_notification_channel" "budget_email" {
  for_each = var.enabled ? var.budget_notification_emails : toset([])

  project      = google_project.this[0].project_id
  display_name = "Ontology Appliance budget: ${each.value}"
  type         = "email"
  labels = {
    email_address = each.value
  }

  depends_on = [google_project_service.required]
}

resource "google_billing_budget" "monthly" {
  provider = google.quota_project
  count    = var.enabled ? 1 : 0

  billing_account = var.billing_account_id
  display_name    = "${var.project_name} monthly guardrail"

  budget_filter {
    projects = ["projects/${google_project.this[0].number}"]
  }

  amount {
    specified_amount {
      currency_code = "EUR"
      units         = tostring(var.monthly_budget_eur)
    }
  }

  threshold_rules {
    threshold_percent = 0.50
    spend_basis       = "CURRENT_SPEND"
  }
  threshold_rules {
    threshold_percent = 0.80
    spend_basis       = "CURRENT_SPEND"
  }
  threshold_rules {
    threshold_percent = 1.00
    spend_basis       = "CURRENT_SPEND"
  }

  all_updates_rule {
    monitoring_notification_channels = [
      for channel in google_monitoring_notification_channel.budget_email : channel.id
    ]
    disable_default_iam_recipients = false
  }

  depends_on = [google_project_service.required]
}

resource "google_iam_workload_identity_pool" "github" {
  count = local.github_wif_enabled ? 1 : 0

  project                   = google_project.this[0].project_id
  workload_identity_pool_id = "${local.name_prefix}-github"
  display_name              = "Ontology Appliance GitHub"
  description               = "Keyless deployment identities restricted to one reviewed workflow and environment."

  depends_on = [google_project_service.required]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  count = local.github_wif_enabled ? 1 : 0

  project                            = google_project.this[0].project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub Actions OIDC"
  attribute_condition                = "assertion.repository == '${var.github_repository}' && assertion.ref == 'refs/heads/${var.github_branch}' && assertion.environment == 'development' && assertion.workflow_ref == '${var.github_repository}/.github/workflows/deploy-dev.yml@refs/heads/${var.github_branch}'"
  attribute_mapping = {
    "google.subject"        = "assertion.sub"
    "attribute.environment" = "assertion.environment"
    "attribute.identity"    = "'deployment'"
    "attribute.repository"  = "assertion.repository"
    "attribute.ref"         = "assertion.ref"
    "attribute.workflow"    = "assertion.workflow_ref"
  }
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_iam_workload_identity_pool_provider" "github_publisher" {
  count = local.github_wif_enabled ? 1 : 0

  project                            = google_project.this[0].project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "github-publisher"
  display_name                       = "GitHub semantic Publisher"
  attribute_condition                = "assertion.repository == '${var.github_repository}' && assertion.ref == 'refs/heads/${var.github_branch}' && assertion.environment == 'semantic-publication' && assertion.workflow_ref == '${var.github_repository}/.github/workflows/publish-semantics.yml@refs/heads/${var.github_branch}'"
  attribute_mapping = {
    "google.subject"        = "assertion.sub"
    "attribute.environment" = "assertion.environment"
    "attribute.identity"    = "'semantic-publisher'"
    "attribute.repository"  = "assertion.repository"
    "attribute.ref"         = "assertion.ref"
    "attribute.workflow"    = "assertion.workflow_ref"
  }
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_iam_workload_identity_pool_provider" "github_rollback" {
  count = local.github_wif_enabled ? 1 : 0

  project                            = google_project.this[0].project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "github-rollback"
  display_name                       = "GitHub semantic rollback"
  attribute_condition                = "assertion.repository == '${var.github_repository}' && assertion.ref == 'refs/heads/${var.github_branch}' && assertion.environment == 'semantic-rollback' && assertion.workflow_ref == '${var.github_repository}/.github/workflows/rollback-semantics.yml@refs/heads/${var.github_branch}'"
  attribute_mapping = {
    "google.subject"        = "assertion.sub"
    "attribute.environment" = "assertion.environment"
    "attribute.identity"    = "'semantic-rollback-publisher'"
    "attribute.repository"  = "assertion.repository"
    "attribute.ref"         = "assertion.ref"
    "attribute.workflow"    = "assertion.workflow_ref"
  }
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_iam_workload_identity_pool_provider" "github_semantic_rollout" {
  count = local.github_wif_enabled ? 1 : 0

  project                            = google_project.this[0].project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "github-semantic-rollout"
  display_name                       = "GitHub semantic rollout"
  attribute_condition                = "assertion.repository == '${var.github_repository}' && assertion.ref == 'refs/heads/${var.github_branch}' && ((assertion.environment == 'semantic-publication' && assertion.workflow_ref == '${var.github_repository}/.github/workflows/publish-semantics.yml@refs/heads/${var.github_branch}') || (assertion.environment == 'semantic-rollback' && assertion.workflow_ref == '${var.github_repository}/.github/workflows/rollback-semantics.yml@refs/heads/${var.github_branch}'))"
  attribute_mapping = {
    "google.subject"        = "assertion.sub"
    "attribute.environment" = "assertion.environment"
    "attribute.identity"    = "'semantic-rollout'"
    "attribute.repository"  = "assertion.repository"
    "attribute.ref"         = "assertion.ref"
    "attribute.workflow"    = "assertion.workflow_ref"
  }
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github_ci_impersonation" {
  count = local.github_wif_enabled ? 1 : 0

  service_account_id = google_service_account.runtime["ci"].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github[0].name}/attribute.identity/deployment"
}

resource "google_service_account_iam_member" "github_publisher_impersonation" {
  count = local.github_wif_enabled ? 1 : 0

  service_account_id = google_service_account.runtime["publisher"].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github[0].name}/attribute.identity/semantic-publisher"
}

resource "google_service_account_iam_member" "github_rollback_impersonation" {
  count = local.github_wif_enabled ? 1 : 0

  service_account_id = google_service_account.runtime["publisher"].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github[0].name}/attribute.identity/semantic-rollback-publisher"
}

resource "google_service_account_iam_member" "github_semantic_rollout_impersonation" {
  count = local.github_wif_enabled ? 1 : 0

  service_account_id = google_service_account.runtime["ci"].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github[0].name}/attribute.identity/semantic-rollout"
}

resource "google_project_iam_member" "ci_roles" {
  for_each = var.enabled ? toset([
    "roles/artifactregistry.writer",
    "roles/cloudtasks.enqueuer",
    "roles/cloudfunctions.developer",
    # Firebase CLI reconciles the queues declared by onTaskDispatched functions.
    # Queue Admin is intentionally narrower than Cloud Tasks Admin: it does not
    # grant access to inspect, create, run, or delete task payloads.
    "roles/cloudtasks.queueAdmin",
    # Firebase CLI also reconciles the jobs declared by onSchedule functions.
    # Scheduler has no narrower predefined deployer role with create, update,
    # and delete permissions, so this role is limited to the CI identity.
    "roles/cloudscheduler.admin",
    "roles/datastore.indexAdmin",
    "roles/datastore.viewer",
    "roles/firebase.viewer",
    "roles/firebaserules.admin",
    "roles/run.admin",
    "roles/serviceusage.apiKeysViewer",
    "roles/serviceusage.serviceUsageConsumer",
  ]) : toset([])

  project = google_project.this[0].project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.runtime["ci"].email}"
}

resource "google_service_account_iam_member" "ci_runtime_user" {
  for_each = var.enabled ? toset(["functions", "semantic"]) : toset([])

  service_account_id = google_service_account.runtime[each.value].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.runtime["ci"].email}"
}
