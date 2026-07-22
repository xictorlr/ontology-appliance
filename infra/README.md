# Ontology Appliance infrastructure

The guarded bootstrap creates the new Firebase/GCP project shell and its remote
state bucket. Terraform then adopts that project and owns the durable cloud
resources in `europe-west4`. Firebase CLI owns Functions, Firestore
indexes/rules, and Storage rules. The guarded REST scripts own the App Hosting
backend, traffic policy, pinned builds, and rollouts; the one-time private
Developer Connect link is established manually. GitHub Actions exclusively owns
the Semantic Gateway Cloud Run service and its invoker policy. No runtime
resource has two owners.

## Bootstrap order

1. Select the exact billing account, choose a globally unique project ID, and run
   the guarded bootstrap from the repository root. It creates only the labeled
   project shell and its private, versioned state bucket, writes ignored local
   configuration, and imports the project into remote Terraform state:

   `GCP_PROJECT_ID=... BILLING_ACCOUNT_ID=... CONFIRM_GCP_PROJECT_ID=... scripts/bootstrap_dev_project.sh`

   Set `GCP_FOLDER_ID` or `GCP_ORGANIZATION_ID` only when organizational policy
   requires a parent. The script refuses an existing project unless it already
   carries the exact appliance/dev/bootstrap identity, and it never relinks an
   existing project from a different billing account. After a partial failure,
   inspect the ignored configuration and existing resources before retrying the
   same confirmed inputs with `RESUME_BOOTSTRAP=true`.
2. Review the generated ignored `terraform.tfvars` and `backend.hcl` files.
3. Run and review
   `terraform -chdir=infra/terraform/environments/dev plan -out=dev.tfplan`;
   do not apply an unreviewed plan.
4. Apply only the reviewed dev plan. Production defaults to
   `enable_production = false` and therefore creates nothing. The dev apply
   also creates the exact synthetic `demo-bank` tenant with `status=ACTIVE`
   plus an immutable bootstrap audit document; this is the enumerated source
   for the scheduled drift workflow.
5. Add secret **versions** out-of-band. Terraform intentionally creates only
   empty Secret Manager containers, so secret values never enter tfvars/state.
6. Configure the GitHub environment variables from Terraform outputs while
   keeping cloud deployment disabled:

   `CONFIGURE_MODE=bootstrap GITHUB_PUBLICATION_REVIEWER_LOGIN=<independent-reviewer> scripts/configure_github_deployment.sh`

   All values are non-secret resource identifiers; authentication remains keyless
   through separate deployment and Publisher WIF providers. The deployment workflow
   builds and pushes the gateway image, owns the private Cloud Run service, grants
   only the App Hosting and Functions runtimes `run.invoker`, and adds the discovered
   URL as a version of `oa-dev-semantic-gateway-url`. The protected publication
   environment rejects self-review and is the only workflow allowed to update the
   semantic active pointer.
   The configuration script also applies and verifies `main` branch protection
   from `infra/github/main-branch-protection.json` before App Hosting can be
   connected.
7. Manually dispatch `Deploy dev backends` with `deployment_scope=bootstrap`
   and `semantic_mode=candidate`. This partial run creates the gateway and the
   required URL secret version, but does not deploy Firebase policy or claim
   release readiness.
8. In the Firebase console, establish the one-time App Hosting GitHub connection
   to the private `xictorlr/ontology-appliance` repository. Copy the full
   `GitRepositoryLink` name, choose the exact reviewed 40-character SHA currently
   at protected `main`, and create the backend with the Terraform-managed Web App
   and runtime identity. Firebase requires the caller to be a project Owner for
   the first App Hosting backend (an App Hosting Admin can manage later ones):

   ```bash
   GCP_PROJECT_ID=<project> \
   APPHOSTING_SERVICE_ACCOUNT=<terraform-apphosting-service-account> \
   APPHOSTING_WEB_APP_ID=<terraform-firebase-web-app-id> \
   APPHOSTING_REPOSITORY_RESOURCE=projects/<project>/locations/europe-west4/connections/<connection>/gitRepositoryLinks/<repository> \
   APPHOSTING_GIT_SHA=<exact-lowercase-40-character-main-sha> \
   CONFIRM_GCP_PROJECT_ID=<project> \
   CONFIRM_APPHOSTING_GIT_SHA=<same-exact-sha> \
   APPHOSTING_APPLY=true \
   scripts/create_apphosting_backend.sh
   ```

   The script uses the App Hosting REST API without an interactive CLI flow. It
   verifies the private Developer Connect link, required `main` protections, and
   live GitHub ref; creates only a `REGIONAL_STRICT` backend in `europe-west4`
   rooted at `apps/web`; pauses automatic branch rollout while it creates the
   pinned build and rollout; and re-enables protected `main` only after success.
   It refuses to proceed until the gateway URL secret has a version.

   Independently re-run the read-only deployment proof with
   `GCP_PROJECT_ID`, `APPHOSTING_REPOSITORY_RESOURCE`, and
   `APPHOSTING_GIT_SHA` set to the same values:

   `scripts/verify_apphosting_rollout.sh`

   That verifier requires exactly one 100% traffic split, a `READY` build whose
   resolved source hash and repository match, and the deterministic pinned
   rollout in `SUCCEEDED` state. Run
   `bash scripts/tests/create_apphosting_backend_test.sh` and
   `bash scripts/tests/verify_apphosting_rollout_test.sh` for cloud-free
   fail-closed tests.
9. Capture the script's exact `APP_HOSTING_URL`, then finish GitHub configuration:

   `CONFIGURE_MODE=complete APP_HOSTING_URL=https://... GITHUB_PUBLICATION_REVIEWER_LOGIN=<independent-reviewer> scripts/configure_github_deployment.sh`

   Manually dispatch `Deploy dev backends` with `deployment_scope=full` and
   `semantic_mode=candidate`. That run configures the two Storage targets and
   ignored Functions environment file, deploys Functions/indexes/rules, and
   requires all cloud smoke tests. Only complete mode sets
   `CLOUD_DEPLOY_ENABLED=true` for later post-CI deployments.
   Published deployments pin `OA_ACTIVE_POINTER_GENERATION`; automatic builds
   preserve that mode and refuse a `PUBLISHED` → demo-candidate downgrade.

The EUR 50 budget emits alerts at 50%, 80%, and 100%. Google Cloud budgets are
alerts, not a hard spending cap. Runtime resources use zero minimum instances and
explicit autoscaling caps.

App Hosting's required project-level Compute Runner role contains Cloud Storage
write permissions for its managed build/runtime buckets. Terraform therefore
tags only the canonical ontology artifact bucket `publisher-only` and creates a
tag-conditioned project IAM Deny before granting Compute Runner. The App Hosting
identity keeps its required storage access elsewhere but cannot create, replace,
move, restore, retain, or delete canonical artifacts. After deployment, verify
both sides: an App Hosting build must still succeed and an impersonated mutation
against the artifact bucket must fail. Tag attachment and IAM Deny are cloud
resources and are created only by a reviewed Terraform apply. The checked-in
configuration and local validation create no billable usage; after apply,
Google Cloud charges a monthly fee for a tag attached to a bucket, so include
that line item in the reviewed cost decision.

The task queues and daily Scheduler job are created by Firebase from the
Functions v2 declarations; Terraform intentionally does not create duplicates.
The deployment identity has `roles/cloudtasks.queueAdmin` (queue configuration,
not task payload access) and `roles/cloudscheduler.admin` so Firebase CLI can
reconcile those declared resources. Runtime task creation remains separately
limited to `roles/cloudtasks.enqueuer` on the Functions service account.
Run the real Firestore and multi-bucket Storage authorization suite with Java 21
via `pnpm --filter @ontology-appliance/rules-tests test`. A compile-only Storage
validation remains available with
`firebase emulators:exec --config firebase.storage-validation.json --only storage --project demo-ontology-appliance "true"`.

Email-link sign-in is initialized through Terraform. Enabling Google sign-in
requires OAuth client material; do that after bootstrap using the Firebase/Google
identity setup so no client secret is placed in Terraform state, then set
`NEXT_PUBLIC_GOOGLE_SIGN_IN_ENABLED=true` in App Hosting.
