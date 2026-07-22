---
name: deploy-firebase-semantic-platform
description: Provision, configure, release, and verify the Ontology Appliance on Firebase and Google Cloud. Use for Firebase App Hosting, Next.js, Cloud Run, Functions v2, Cloud Tasks, Firestore, Cloud Storage, Secret Manager, IAM, Workload Identity Federation, Terraform, GitHub CI/CD, European-region setup, budget controls, emulator configuration, deployment smoke tests, or rollback planning.
---

# Deploy Firebase Semantic Platform

Release a least-privilege development platform in Europe while keeping production defined but unprovisioned.

## Workflow

1. Read `references/platform-deployment.md` before provisioning or changing cloud ownership.
2. Run the local preflight:

   `python3 .agents/skills/deploy-firebase-semantic-platform/scripts/preflight.py`

3. Pin Node 22 for App Hosting and Functions compatibility. Pin provider, CLI, package-manager, and runtime versions in source control.
4. Create a unique development Firebase/GCP project in `europe-west4`, attach Blaze billing, and enable only required APIs. If more than one billing account is available, require the operator to select the exact account before creating the project. Use `scripts/bootstrap_dev_project.sh` so an existing unrelated project cannot be adopted accidentally.
5. Apply reviewed Terraform for base APIs, IAM/service accounts, Firestore, Storage, Artifact Registry, empty secret resources, and the EUR 50 monthly alert policy.
6. Configure Firebase Auth, Functions v2, tasks, and emulator ports. Use port 5002 for App Hosting when 5000 is occupied.
7. Establish the private GitHub `GitRepositoryLink`, then use the guarded REST scripts to create a `REGIONAL_STRICT` App Hosting backend and prove the exact active commit on protected `main`. Use Workload Identity Federation in CI; never create downloadable service-account keys.
8. Deploy the private Semantic Gateway with zero minimum instances and bounded maximum scale. Run bounded profiling, verification, and drift orchestration through Functions v2 and Cloud Tasks. Grant invocation only to approved service identities.
9. Configure Gemini through Vertex ADC. Keep the OpenAI adapter disabled and use deterministic verifier mock mode until a real key is stored in Secret Manager and evaluation passes.
10. Run emulator, contract, security, and local end-to-end tests. After an actual development deployment, run the checked-in cloud smoke and rollback scripts and record real resource revisions; never report those cloud checks as passed from local fixtures.

## Guardrails

- Deploy development; define production variables and pipelines but do not provision production.
- Keep Terraform, Firebase CLI, and the guarded App Hosting REST scripts' ownership disjoint to prevent drift.
- Treat budget notifications as alerts, not a hard spend stop; enforce scale, task, token, and concurrency caps too.
- Keep secrets out of Git, Terraform state, build logs, browser bundles, and Firebase client configuration beyond public identifiers.
- Preserve tenant isolation and deny browser Firestore/Storage access unless a narrow rule explicitly grants it.

## Required outputs

Produce reviewed Terraform configuration and plans, Firebase/App Hosting configuration, WIF-based CI, deployment manifests, IAM bindings, budget alerts at 50/80/100 percent, emulator configuration, and local validation evidence. Produce cloud smoke and rollback evidence only after deployment. Cloud Run Jobs and measured cloud SLOs are roadmap capabilities; bounded Functions v2 and Cloud Tasks are the MVP orchestration path. Use resource prefix `oa-dev-` and project display name `Ontology Appliance Dev`.
