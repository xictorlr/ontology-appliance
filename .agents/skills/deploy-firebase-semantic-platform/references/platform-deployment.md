# Firebase semantic platform deployment

## Target architecture

- Firebase App Hosting: pinned Next.js 15.5.21 English UI and server-side BFF
- Firebase Auth: email-link pilot login; Google remains disabled until its OAuth provider is configured
- Firestore Standard: tenant-scoped operational state, proposals, reviews, jobs, and projections
- Cloud Storage: synthetic inputs and immutable ontology packages
- Cloud Run: private Python Semantic Gateway
- Functions v2: object/document triggers plus bounded profiling and workflow handlers
- Cloud Tasks and Scheduler: idempotent ingestion, verification, and daily drift
- Secret Manager: external provider credentials and the private gateway URL
- Cloud Logging/Monitoring: runtime logs, audit signals, and configured alerts; measured SLOs follow after a deployed workload has real telemetry

Co-locate supported resources in `europe-west4`. Use regional Firestore there for the pilot.

## Resource ownership

Terraform owns API enablement, service accounts, IAM, Firestore, Storage, Artifact Registry, empty secrets, and budgets. Firebase CLI owns Functions and Firebase policy; the guarded REST scripts own App Hosting backend, traffic, build, and rollout resources after a one-time Developer Connect link. Cloud Run application revisions are owned by the release pipeline. Do not manage the same field with two systems.

Pin Terraform and Google provider versions because Firebase Terraform support may include preview resources. Review every plan before apply.

## Identity and tenancy

Use tenant `demo-bank` initially and roles `admin`, `steward`, and `auditor`. Store operational records below `tenants/{tenantId}`. Derive tenant and role from verified claims and recheck them in server services. Use distinct service accounts for App Hosting/BFF, gateway, Functions, Publisher, and CI.

Use Workload Identity Federation from the private GitHub repository. Grant minimal deploy permissions to the repository/branch subject and minimal runtime permissions to separate App Hosting, gateway, Functions, Publisher, and CI service accounts.

## Cost controls

Configure an EUR 50 monthly budget with alerts at 50, 80, and 100 percent. Set minimum instances to zero, bounded maximum instances, task dispatch and Function concurrency limits, request deadlines, query limits, and model token ceilings. A billing budget alert does not automatically disable spend.

Cloud Run Jobs and measured availability or latency SLOs are not part of the MVP. Consider them only after production-like volume and telemetry justify a separate batch runtime and service objectives.

## Release order

1. Verify local tools, project identifiers, billing choice, and region.
2. Create project and attach billing.
3. Bootstrap remote state safely if used.
4. Apply base infrastructure after plan review.
5. Store secret values out of band; leave OpenAI empty in the initial development release.
6. Deploy the gateway, then Functions and task queues.
7. Connect the private repository once, then provision `REGIONAL_STRICT` App Hosting from an exact protected-`main` SHA and verify the active build, rollout, and 100% traffic split.
8. Seed only synthetic data and the demo tenant.
9. Run cloud smoke, IAM denial, tenant-isolation, and rollback tests.
10. Record revisions, endpoints, manifest hashes, and unresolved alerts.

## Rollback

Roll back App Hosting and Cloud Run to known-good revisions. Activate the last valid immutable ontology version instead of editing artifacts. Disable task queues if a workflow is unsafe. Keep migrations backward compatible until rollback windows close.
