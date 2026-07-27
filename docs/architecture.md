# Architecture decisions

## Boundaries

Firebase is the product and control plane. Cloud Run is the semantic compute plane. Cloud Storage holds the canonical immutable RDF bundle; Firestore holds workflow state and query-friendly projections. A persistent triplestore is deliberately deferred until the graph exceeds the bounded in-memory runtime.

## Request path

1. Firebase Auth establishes a passwordless-email or Google identity; App Hosting enables Google only after its OAuth provider is configured.
2. A verified identity without membership is enrolled into the configured synthetic pilot tenant as a read-only auditor. The browser refreshes the ID token once so the server can observe the new custom claims.
3. The Next.js BFF exchanges the ID token for an HTTP-only session cookie.
4. Every BFF call derives `tenantId` and roles from the verified session.
5. App Hosting invokes the private Cloud Run gateway with a Google-signed ID token.
6. The gateway verifies the Firebase session or allowlisted Google service token, derives the fixed tenant and permitted roles from that identity, executes against the selected hash-verified bundle, and emits `ontologyVersion`, `traceId`, evidence, warnings, and status.
7. Browser clients do not receive server credentials or direct unrestricted data access.

Human review follows the same BFF boundary. The browser submits only a bounded
decision, rationale, and idempotency UUID. The server derives tenant and reviewer
identity from the verified session, requires an explicit `steward` role, and atomically
creates a transactionally unique, content-bound review receipt and audit event before
updating the proposal. Publisher later validates its referenced proposal, verification
run, gates, and evidence index before sealing the decision into the immutable release ledger.
The synthetic demo session is read-only and cannot create governed receipts.

## Publication path

```text
metadata → discovery proposal → eight verification gates → human route
         → demo candidate graph → complete review ledger → publishable bundle
         → Publisher promotion + receipt → immutable published graph
```

The checked-in pilot is explicitly `CANDIDATE` / `DEMO_ONLY` and may contain proposals
in `HUMAN_REVIEW`; it can be served only by the explicitly opted-in development
candidate rollout and is never a published active graph. A publishable bundle requires every
mapping to be `APPROVED` or `PUBLISHED` and to carry hashed evidence from an authorized
reviewer independent of the generator and verifier. The Publisher workflow fails before
assuming the Publisher identity when that condition is unmet. Only Publisher promotion
creates a `PUBLISHED` / `ACTIVE` manifest and immutable receipt. A failed load or SHACL
check keeps the previous valid published version active. Activation is the
generation-guarded replacement of the stable tenant `active.json` pointer; the
gateway verifies its manifest hash and never accepts an arbitrary release prefix.
Published serving mode may use a last-valid published cache, but never falls back to the
bundled demo candidate. The separate cloud-development candidate rollout opts in
explicitly, configures no artifact bucket, and remains labeled `DEMO_ONLY`.

## Model boundary

The pilot runs deterministic generator and verifier mocks, so it makes no model
API calls. A separately approved opt-in can enable the Vertex AI Gemini
typed-JSON generator. The provider-neutral verifier can select either the OpenAI
Responses adapter (`store: false`) or the optional Anthropic Messages adapter
(`output_config.format`, thinking disabled); each requires its own server-only
credential. When a provider is enabled, its name, returned model identifier,
prompt version, parameters, latency, usage, evidence IDs, and refusal/incomplete
state are recorded. Mock mode never populates independent model agreement.
