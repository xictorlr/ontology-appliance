# Ontology Appliance

Ontology Appliance turns fragmented enterprise metadata into governed semantic context for agents. This repository contains a functional KYC/AML pilot over `Party → LegalEntity → Account → Payment`, with evidence-first discovery, atomic review, immutable publishing, and a read-only semantic gateway.

## What is implemented

- Next.js control plane prepared for Firebase App Hosting.
- Firebase Authentication with passwordless email, Google sign-in enabled in App Hosting after OAuth setup, and a synthetic local demo session.
- Private FastAPI semantic gateway with RDF/OWL/SKOS, SHACL validation, provenance, read-only SPARQL, and five golden competency questions.
- Live tenant source onboarding for bounded CSV, JSONL, PDF, and OpenAPI 3 JSON uploads, plus synthetic connector fixtures for reproducible evaluation.
- Firestore/Storage rules, Functions v2 triggers, task queue orchestration, and drift scheduling.
- Terraform modules for an EU dev environment with least-privilege identities and €50 budget alerts.
- Six repo-local Codex skills under `.agents/skills/`.
- OpenAPI 3.1 and JSON Schema contracts.

All model providers are disabled by default: the generator is deterministic and
the provider-neutral independent verifier is a fail-closed mock. Optional OpenAI
and Anthropic adapters require an explicit provider selection and their own
server-only key; no paid model call is required by local verification or the
checked-in cloud workflow. In mock mode `modelAgreement` is `null`; high-risk or
model-dependent proposals route to `HUMAN_REVIEW` or `ABSTAINED`.

The bundled semantic pilot is likewise explicit: it is a non-published
`CANDIDATE` / `DEMO_ONLY` graph. Gateway responses expose that state and a warning.
The normal cloud-development rollout may serve this labeled candidate without assuming
Publisher or writing an active pointer. The separate manual Publisher promotion gate
currently fails by design because all 100 mappings remain `HUMAN_REVIEW`; no approval
or publication status is synthesized for the demo.

## Architecture

```text
Browser
  │ Firebase Auth → HTTP-only session
  ▼
Next.js on Firebase App Hosting (BFF)
  ├─ private OIDC call → FastAPI Semantic Gateway on Cloud Functions v2
  └─ bounded source upload → versioned Firebase Storage object
                            └─ Functions v2 → SHA-256 profile → immutable snapshot

Cloud data plane
  ├─ immutable RDF/SHACL bundles in Cloud Storage
  ├─ workflow, proposals and projections in Firestore
  ├─ Cloud Tasks + Functions v2 for evidence profiling, drift and idempotent orchestration
  └─ bounded RDF/SHACL/OWL-RL execution plus typed model adapters
```

The Cloud Run-backed Function loads a validated RDF snapshot into memory and
never accepts SPARQL Update. Published revisions are pinned to the exact
Publisher-approved Storage generation of `active.json`, so cold starts do not
follow a later broken `latest` pointer. The local `/tmp` cache accelerates warm
recovery but is not treated as durable storage.

## Local quick start

Prerequisites: Node.js 22, pnpm 9, Python 3.12 with `uv`, Java 21 for Firebase emulators, and optionally Docker.

```bash
cp .env.example .env.local
corepack enable
pnpm install
cd services/semantic-gateway && uv sync --dev --extra firebase --extra cloud-function && cd ../..
```

Run the gateway and web app in separate terminals:

```bash
pnpm dev:gateway
pnpm dev
```

Open `http://localhost:3000`. With no Firebase public configuration, the app offers a governed `demo-bank` session. Emulator ports are defined in `firebase.json`; App Hosting uses `5002` because `5000` was occupied during project setup.

Verified users without existing membership claims can self-enroll into the configured
pilot tenant as read-only auditors. Source onboarding requires an explicit `admin`
or `steward` role. An administrator must name and repeat the exact target project
before granting that elevated role:

```bash
pnpm --filter @ontology-appliance/web claims:set -- --project PROJECT_ID --confirm-project PROJECT_ID --email user@example.com --roles steward,auditor
```

The user then signs in again to refresh the token. The tenant is always derived
from the verified token/session, never accepted from a browser request body.

## Connecting sources

Open **Sources** in the deployed control plane and choose an available connector:

| Connector | Current production behavior |
|---|---|
| CSV | Validates a unique UTF-8 header, profiles bounded records, and creates an immutable snapshot. |
| JSONL | Validates every bounded object record and preserves deterministic line-level evidence coordinates. |
| PDF | Verifies the PDF signature and creates a content-addressed document snapshot. |
| OpenAPI 3 | Accepts a JSON contract and inventories its paths; live remote API calls are deliberately disabled. |
| PostgreSQL, MySQL, SQL Server, Oracle | Planned: read-only adapter, Secret Manager reference, network boundary, allowlists, and ephemeral integration tests are required. |
| Amazon S3, Azure Blob Storage, Google Cloud Storage | Planned: federated read-only identity, prefix allowlist, version-pinned evidence, and integration tests are required. |
| Databricks, BigQuery, Snowflake | Planned: catalog-scoped access, bounded query/compute policy, server-side credentials, and integration tests are required. |

Uploads are limited to 20 MiB. The BFF derives the tenant and uploader from the
HTTP-only Firebase session, records a Firestore audit event, and can only create
new objects under the governed input bucket. It cannot read, replace, or delete
those objects. Storage finalization invokes the existing serverless profiling,
snapshot, proposal, and independent verification workflow. No database password,
API token, or service credential is accepted by the browser form.

The complete activation contract for these options is documented in
[`docs/enterprise-connectors.md`](./docs/enterprise-connectors.md). A catalog
entry is not a claim that the adapter exists: only CSV, JSONL, PDF, and OpenAPI
3 JSON are active in this release.

## Industry semantic packs

The platform now exposes a cross-industry pack catalog. **Financial Crime ·
KYC/AML** remains the only implemented pack and is still a labeled,
non-published candidate. The roadmap includes **Oil & Gas**, Energy & Utilities,
Insurance, Manufacturing, Healthcare & Life Sciences, Retail & CPG,
Telecommunications, and Public Sector.

Each planned pack stays inactive until it includes a versioned RDF bundle,
SHACL shapes, executable competency questions, evidence-backed mappings, and an
independent verification path. Models may propose sector concepts, but they
cannot activate a pack or approve their own output.

Run verification:

```bash
pnpm verify
cd services/semantic-gateway && uv run ruff check . && uv run pytest
python3 scripts/validate_repo.py
```

## Repository map

| Path | Purpose |
|---|---|
| `apps/web` | App Hosting UI, secure session, BFF gateway proxy |
| `services/semantic-gateway` | FastAPI/RDFLib/pySHACL runtime |
| `functions` | Firebase Functions v2 event and task handlers |
| `semantic` | Versioned ontology, shapes, mappings, and manifest |
| `data` | Synthetic, non-sensitive pilot fixtures |
| `contracts` | OpenAPI and canonical JSON Schemas |
| `packages/contracts` | Runtime-validated TypeScript contracts |
| `infra` | Terraform environment and cloud modules |
| `.agents/skills` | Project-specific Codex workflows |

## Cloud delivery

The default target is a new Firebase/GCP project named
`ontology-appliance-dev-<unique-suffix>` in `europe-west4`, using Blaze billing.
An operator-created Firebase project can instead be adopted only through the
separate exact-ID gate documented in [`infra/README.md`](./infra/README.md).
The bootstrap owns only the project shell and Terraform state bucket; Terraform
owns durable cloud resources, Firebase CLI owns control-plane Rules/Functions,
GitHub Actions owns the private Semantic Gateway Function v2 and its underlying
Cloud Run invoker policy, and the guarded App Hosting API scripts own the
connected frontend control plane.

Use this cycle-free order:

1. Select the exact billing account and globally unique project ID, then run the
   guarded `scripts/bootstrap_dev_project.sh` command documented in
   [`infra/README.md`](./infra/README.md). It refuses ambiguous adoption or
   relinking.
2. Review the ignored generated `terraform.tfvars` and `backend.hcl`, create and
   inspect a dev plan, then apply that exact reviewed plan. Production remains
   disabled.
3. Configure keyless GitHub credentials without enabling automatic deploys:

   ```bash
   CONFIGURE_MODE=bootstrap \
   GITHUB_PUBLICATION_REVIEWER_LOGIN=<independent-reviewer> \
   scripts/configure_github_deployment.sh
   ```

   This also protects `main`: pull requests, an up-to-date branch, and all three
   CI jobs are required; administrators cannot bypass the gate and force pushes
   or deletion are disabled.

4. Manually run `Deploy dev backends` with `deployment_scope=bootstrap` and
   `semantic_mode=candidate`. This deploys the private gateway and creates its
   Secret Manager URL version; it deliberately skips Functions, rules, and cloud
   smoke tests.
   If App Hosting is temporarily blocked by repository prerequisites, a manual
   `deployment_scope=backend` run may then deploy Functions and Firebase policy
   and execute gateway/Functions cloud smoke tests. This remains a partial,
   candidate-only deployment: it neither enables automatic deploys nor declares
   a release GO.
5. Create and verify the App Hosting backend against the Terraform-managed Web
   App and service account:

   ```bash
   GCP_PROJECT_ID="$(terraform -chdir=infra/terraform/environments/dev output -raw project_id)" \
   APPHOSTING_SERVICE_ACCOUNT="$(terraform -chdir=infra/terraform/environments/dev output -json runtime_service_accounts | jq -r .apphosting)" \
   APPHOSTING_WEB_APP_ID="$(terraform -chdir=infra/terraform/environments/dev output -raw firebase_web_app_id)" \
   APPHOSTING_REPOSITORY_RESOURCE="projects/<project>/locations/europe-west4/connections/<connection>/gitRepositoryLinks/<repository>" \
   APPHOSTING_GIT_SHA="<exact-lowercase-40-character-main-sha>" \
   CONFIRM_GCP_PROJECT_ID="<project>" \
   CONFIRM_APPHOSTING_GIT_SHA="<same-exact-sha>" \
   APPHOSTING_APPLY=true \
   scripts/create_apphosting_backend.sh
   ```

   First create the one-time GitHub `GitRepositoryLink` through
   Firebase console and copy its full Developer Connect resource name. The
   script itself is non-interactive: it verifies that link, protected `main`,
   and the exact GitHub SHA; creates the backend in `europe-west4` using App
   Hosting's currently supported `GLOBAL_ACCESS` serving locality; builds and
   rolls out that commit; then proves that one active
   build receives 100% of traffic and resolved to the same full SHA. Preserve
   the emitted `APP_HOSTING_URL`. Re-run the read-only proof at any time with
   the same project, repository resource, and SHA using
   `scripts/verify_apphosting_rollout.sh`.
6. Rerun `scripts/configure_github_deployment.sh` with
   `CONFIGURE_MODE=complete` and that exact `APP_HOSTING_URL`, then manually run
   `Deploy dev backends` with `deployment_scope=full` and
   `semantic_mode=candidate`. The full run deploys Functions and rules and must
   pass cloud smoke tests before automatic post-CI deploys become active.
   Automatic gateway deployments inspect the governed pointer: once a release
   exists they preserve `PUBLISHED` and its exact Storage generation. A manual
   candidate deployment cannot downgrade it; use the protected rollback path.
7. Leave `VERIFIER_PROVIDER=mock`, legacy `OPENAI_VERIFIER_MODE=mock`, and
   `GENERATOR_PROVIDER=mock`. The checked-in
   deployment grants no Vertex role and does not enable its API unless
   `enable_vertex_ai=true` is separately reviewed; changing that Terraform opt-in
   still does not activate calls until the deployment explicitly selects
   `GENERATOR_PROVIDER=vertex-ai`. OpenAI and Anthropic likewise require their
   own separately stored key and an explicit provider change. No paid model call
   is required by this baseline.
8. Once every mapping has an independent review receipt, the protected `Publish
   reviewed semantics` workflow is the only path that may write an immutable
   release and tenant `active.json` pointer; a later dev deployment can select
   `published`. Rollback uses its own protected identity and audit trail.

No credential, service-account key, Firebase token, or Terraform state belongs in Git.

## Acceptance targets

These are pilot goals from `proyect.md`, not claims about the checked-in candidate.
The repository currently proves provenance, deterministic competency-question
fixtures, and fail-closed publication; it intentionally reports no auto-approval
precision or acceptance-rate result while all mappings remain under human review.

- 100% of proposals and answers carry provenance.
- Auto-approved mappings exceed 95% precision on the labeled synthetic evaluation.
- More than 80% of high-confidence proposals are accepted.
- Zero high-risk changes publish without a person.
- At least four of five golden competency questions pass.
- Every response can be reproduced from trace metadata and immutable artifact hashes.

The original product thesis and broader roadmap remain in [`proyect.md`](./proyect.md).
