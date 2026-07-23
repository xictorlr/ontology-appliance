# Security model

- Source connectors are read-only; sampling requires explicit policy.
- Tenant identity is derived from the verified session or service token.
- Admin SDK access bypasses Firebase Rules, so server handlers repeat tenant and role checks.
- Browser Firestore/Storage writes are denied. Governed review writes pass through the BFF, which derives the tenant and reviewer from the server-verified session and creates an idempotent, content-bound staging receipt plus audit event in one transaction. The protected Publisher validates those hashes and seals accepted decisions into immutable release evidence; Firestore staging data is not described as WORM storage.
- Service accounts are separate for App Hosting, the gateway, Functions, CI deployment, and Publisher.
- Default Compute and App Engine service accounts are retained, while exact negative IAM resources remove only their automatic Editor grants and the Compute identity keeps the explicit build role required by the Functions deployment path. Projects with an organization parent also apply a project policy that blocks future automatic basic-role grants; standalone projects cannot receive the organization-level permission needed to create that policy, so every Terraform apply re-enforces the two exact absences.
- The App Hosting identity receives Firebase's minimum Compute Runner role for build/runtime plumbing; application access is added separately (session issuance, the gateway URL secret, and gateway invocation). Because Compute Runner also carries project-level Storage mutations, a regional `publisher-only` bucket tag and a tag-conditioned allow binding exclude the canonical artifact bucket while leaving App Hosting-managed buckets usable. Organization-scoped projects add a tag-conditioned IAM Deny as defense in depth; standalone projects cannot receive Google's organization-only Deny Admin role.
- Secrets are referenced from Secret Manager and never placed in images, repository files, Terraform state, or logs.
- SPARQL is parsed and restricted to bounded local `SELECT`, `ASK`, `CONSTRUCT`, and `DESCRIBE`; updates, dataset clauses, aggregation, nested selects, and remote `SERVICE` operations are denied.
- Evidence excerpts are sensitivity-labeled and permission-filtered.
- High-risk proposals require a steward even when all automated gates pass.
- Demo identities cannot persist review decisions; auditors and administrators can read the queue, but only an explicitly assigned steward can record a decision. Approval is intentionally unavailable while independent verification remains in mock mode.
- Publication produces an immutable, hash-linked Publisher receipt and a generation-guarded active pointer. Operational events begin flowing to Cloud Logging after deployment; the local trace table is explicitly synthetic and is not an operational audit ledger.
- Production can enable locked log retention after the irreversible retention decision is separately approved.
