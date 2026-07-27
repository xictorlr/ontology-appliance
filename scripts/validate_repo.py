#!/usr/bin/env python3
"""Fast, dependency-free structural validation for the monorepo."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(path: str) -> Path:
    candidate = ROOT / path
    if not candidate.exists():
        raise SystemExit(f"missing required path: {path}")
    return candidate


def main() -> None:
    required = [
        "apps/web/package.json",
        "contracts/openapi.yaml",
        "contracts/schemas/proposal.schema.json",
        "services/semantic-gateway/pyproject.toml",
        "firebase.json",
        "firestore.rules",
        "storage.rules",
        "scripts/create_apphosting_backend.sh",
        "scripts/verify_apphosting_rollout.sh",
        "infra",
        "semantic",
        "data",
    ]
    for item in required:
        require(item)

    package = json.loads(require("package.json").read_text())
    if package.get("engines", {}).get("node") != "22.x":
        raise SystemExit("root package must pin Node 22.x")

    apphosting_config = require("apps/web/apphosting.yaml").read_text()
    google_sign_in_block = (
        '  - variable: NEXT_PUBLIC_GOOGLE_SIGN_IN_ENABLED\n'
        '    value: "true"\n'
    )
    if google_sign_in_block not in apphosting_config:
        raise SystemExit(
            "App Hosting must expose Google sign-in only after the Firebase provider is configured"
        )

    proposal_schema = json.loads(
        require("contracts/schemas/proposal.schema.json").read_text()
    )
    if proposal_schema.get("additionalProperties") is not False:
        raise SystemExit("proposal schema must reject unknown properties")

    openapi = require("contracts/openapi.yaml").read_text()
    for endpoint in (
        "/v1/resolve",
        "/v1/context",
        "/v1/query",
        "/v1/explain",
        "/v1/validate",
        "/v1/sparql",
    ):
        if endpoint not in openapi:
            raise SystemExit(f"OpenAPI is missing {endpoint}")

    env_example = require(".env.example").read_text()
    if (
        "GENERATOR_PROVIDER=mock" not in env_example
        or "VERIFIER_PROVIDER=mock" not in env_example
        or "OPENAI_VERIFIER_MODE=mock" not in env_example
    ):
        raise SystemExit("example environment must keep paid model providers disabled")

    gitignore = require(".gitignore").read_text()
    if ".env.*" not in gitignore or "!.env.example" not in gitignore:
        raise SystemExit("local env files must stay ignored while .env.example remains tracked")

    deploy_workflow = require(".github/workflows/deploy-dev.yml").read_text()
    if (
        "GENERATOR_PROVIDER=vertex-ai" in deploy_workflow
        or "OPENAI_VERIFIER_MODE=openai" in deploy_workflow
        or "VERIFIER_PROVIDER=openai" in deploy_workflow
        or "VERIFIER_PROVIDER=anthropic" in deploy_workflow
    ):
        raise SystemExit("baseline deployment must not activate paid model providers")
    if deploy_workflow.count("GENERATOR_PROVIDER=mock") < 2:
        raise SystemExit(
            "every semantic gateway deployment mode must pin the mock generator"
        )
    if deploy_workflow.count("VERIFIER_PROVIDER=mock") < 2:
        raise SystemExit(
            "every semantic gateway deployment mode must pin the mock verifier"
        )

    platform_tf = require("infra/terraform/modules/platform/main.tf").read_text()
    required_iam_boundaries = (
        'resource "google_tags_tag_key" "artifact_access_boundary"',
        'resource "google_tags_tag_value" "publisher_only"',
        'resource "google_tags_location_tag_binding" "artifact_publisher_only"',
        "//storage.googleapis.com/projects/_/buckets/${google_storage_bucket.artifacts[0].name}",
        "location        = var.region",
        'resource "google_iam_deny_policy" "apphosting_artifact_mutation"',
        'provider = google-beta',
        "count    = var.enabled && local.organization_scoped ? 1 : 0",
        '"principal://iam.googleapis.com/projects/-/serviceAccounts/${google_service_account.runtime["apphosting"].email}"',
        "expression  = \"resource.matchTagId('${google_tags_tag_key.artifact_access_boundary[0].id}', '${google_tags_tag_value.publisher_only[0].id}')\"",
        "expression  = \"!resource.matchTagId('${google_tags_tag_key.artifact_access_boundary[0].id}', '${google_tags_tag_value.publisher_only[0].id}')\"",
        '"storage.googleapis.com/objects.create"',
        '"storage.googleapis.com/objects.delete"',
        '"storage.googleapis.com/objects.move"',
        '"storage.googleapis.com/objects.restore"',
        '"storage.googleapis.com/objects.setRetention"',
        '"storage.googleapis.com/objects.update"',
        'role    = "roles/firebaseapphosting.computeRunner"',
        "google_iam_deny_policy.apphosting_artifact_mutation,",
        "google_tags_location_tag_binding.artifact_publisher_only,",
        'title       = "exclude_governed_artifact_bucket"',
    )
    for boundary in required_iam_boundaries:
        if boundary not in platform_tf:
            raise SystemExit(
                f"App Hosting canonical-artifact IAM boundary is missing: {boundary}"
            )
    for forbidden_read_deny in (
        '"storage.googleapis.com/objects.get"',
        '"storage.googleapis.com/objects.list"',
    ):
        if forbidden_read_deny in platform_tf:
            raise SystemExit(
                "App Hosting artifact deny must block mutation without removing read access"
            )

    for default_sa_boundary in (
        '"orgpolicy.googleapis.com"',
        'resource "google_project_service" "org_policy"',
        'resource "google_org_policy_policy" "disable_default_sa_auto_grants"',
        "iam.automaticIamGrantsForDefaultServiceAccounts",
        'resource "google_project_iam_member_remove" "compute_default_editor"',
        'resource "google_project_iam_member_remove" "app_engine_default_editor"',
        'role    = "roles/editor"',
        'member  = "serviceAccount:${google_project.this[0].number}-compute@developer.gserviceaccount.com"',
        'member  = "serviceAccount:${google_project.this[0].project_id}@appspot.gserviceaccount.com"',
        "depends_on = [google_org_policy_policy.disable_default_sa_auto_grants]",
        "depends_on = [google_project_iam_member_remove.compute_default_editor]",
        'depends_on = [google_project_service.required["compute.googleapis.com"]]',
        'depends_on = [google_project_service.required["storage.googleapis.com"]]',
    ):
        if default_sa_boundary not in platform_tf:
            raise SystemExit(
                f"Default service-account privilege boundary is missing: {default_sa_boundary}"
            )
    org_policy_start = platform_tf.index(
        'resource "google_org_policy_policy" "disable_default_sa_auto_grants"'
    )
    org_policy_end = platform_tf.index("\n}\n", org_policy_start)
    org_policy_resource = platform_tf[org_policy_start:org_policy_end]
    if "provider = google.quota_project" not in org_policy_resource:
        raise SystemExit("Organization Policy must use the environment quota project")
    if (
        "count = var.enabled && local.organization_scoped ? 1 : 0"
        not in org_policy_resource
    ):
        raise SystemExit(
            "Organization Policy must be limited to projects with an organization parent"
        )
    if 'resource "google_project_default_service_accounts"' in platform_tf:
        raise SystemExit(
            "Default service-account DEPRIVILEGE would also strip explicit project roles"
        )
    if 'resource "google_project_iam_binding" "default_service_accounts_no_editor"' in platform_tf:
        raise SystemExit(
            "Default service-account Editor removal must target exact memberships"
        )

    apphosting_create = require("scripts/create_apphosting_backend.sh").read_text()
    for guardrail in (
        'APPHOSTING_REGION:-europe-west4',
        '[[ "$region" == "europe-west4" ]]',
        "APPHOSTING_REPOSITORY_RESOURCE",
        "APPHOSTING_GIT_SHA",
        "APPHOSTING_SERVICE_ACCOUNT",
        "APPHOSTING_WEB_APP_ID",
        "APPHOSTING_APPLY",
        "CONFIRM_GCP_PROJECT_ID",
        "CONFIRM_APPHOSTING_GIT_SHA",
        'servingLocality: "GLOBAL_ACCESS"',
        "source: {codebase: {commit: $commit}}",
        "apphosting:secrets:grantaccess",
        "--non-interactive",
        "/v1beta/",
        "verify_apphosting_rollout.sh",
    ):
        if guardrail not in apphosting_create:
            raise SystemExit(f"App Hosting provisioning guardrail is missing: {guardrail}")
    if "firebase apphosting:backends:create" in apphosting_create:
        raise SystemExit("App Hosting provisioning must use the reproducible REST flow")

    apphosting_verify = require("scripts/verify_apphosting_rollout.sh").read_text()
    for exact_proof in (
        ".current.splits",
        '"$split_count" == "1"',
        '"$active_percent" == "100"',
        '"$build_state" == "READY"',
        '"$resolved_sha" == "$expected_sha"',
        '"$rollout_state" == "SUCCEEDED"',
        '"$canonical_rollout_build" == "$canonical_active_build"',
        '"$locality" == "GLOBAL_ACCESS"',
    ):
        if exact_proof not in apphosting_verify:
            raise SystemExit(f"App Hosting exact-rollout proof is missing: {exact_proof}")

    ci_workflow = require(".github/workflows/ci.yml").read_text()
    if "bash scripts/tests/verify_apphosting_rollout_test.sh" not in ci_workflow:
        raise SystemExit("CI must run the App Hosting exact-rollout verifier tests")

    skills = require(".agents/skills")
    expected = {
        "model-kyc-semantics",
        "build-evidence-connectors",
        "run-semantic-discovery",
        "verify-semantic-proposals",
        "serve-semantic-gateway",
        "deploy-firebase-semantic-platform",
    }
    found = {path.name for path in skills.iterdir() if path.is_dir()}
    missing = expected - found
    if missing:
        raise SystemExit(f"missing repository skills: {', '.join(sorted(missing))}")
    for skill_name in expected:
        skill_root = skills / skill_name
        skill_text = require(str(skill_root.relative_to(ROOT) / "SKILL.md")).read_text()
        if (
            not skill_text.startswith("---\n")
            or f"name: {skill_name}" not in skill_text
        ):
            raise SystemExit(f"invalid SKILL.md metadata: {skill_name}")
        require(str(skill_root.relative_to(ROOT) / "agents" / "openai.yaml"))

    print("repository structure: valid")


if __name__ == "__main__":
    main()
