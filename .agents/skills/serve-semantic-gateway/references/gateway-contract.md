# Semantic Gateway contract

## Runtime boundary

Run a private Python 3.12 FastAPI service on Cloud Run. Use RDFLib, pySHACL, and bounded OWL-RL reasoning for the MVP. Store canonical immutable RDF artifacts in Cloud Storage and operational version metadata in Firestore. Load the active version into memory; Cloud Run disk is only ephemeral scratch space.

## Endpoints

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/resolve` | Resolve a term, alias, field, or phrase to governed concepts |
| `POST /v1/context` | Return a bounded semantic context bundle for an agent |
| `POST /v1/query` | Execute a named, parameterized competency or business query |
| `POST /v1/explain` | Explain a mapping, relation, decision, or impact path |
| `POST /v1/validate` | Validate candidate RDF or mappings without publishing |
| `POST /v1/sparql` | Execute bounded read-only SPARQL for authorized roles |

Use POST for structured, auditable requests, but keep operations semantically read-only. Give each operation a stable `operationId`.

## Success envelope

```json
{
  "data": {},
  "ontologyVersion": "0.1.0",
  "traceId": "trace-...",
  "publicationState": "CANDIDATE",
  "servingMode": "DEMO_ONLY",
  "isPublished": false,
  "evidence": [],
  "warnings": [],
  "status": "ok"
}
```

Return the ontology version actually used, not merely the currently active pointer. Bound context size, evidence count, query rows, reasoning depth, and execution time.

Candidate graphs may be served only for an explicit demo: return `CANDIDATE`,
`DEMO_ONLY`, `isPublished: false`, and a non-published warning in every envelope.
Reject the intermediate `PUBLISHABLE` state at runtime. Only a Publisher-promoted
manifest and receipt may be returned as `PUBLISHED` / `ACTIVE`.

## Error envelope

Use RFC 9457-style Problem Details with `type`, `title`, `status`, `detail`, `instance`, stable `code`, and `traceId`. Do not leak credentials, stack traces, cross-tenant identifiers, or raw sensitive values.

## Authorization

Support pilot roles `admin`, `steward`, and `auditor`. Verify secure session or service identity, derive tenant from claims, and recheck permissions in the gateway. The browser must not receive broad direct Firestore or Storage access. Remember that server Admin SDK access bypasses Firebase Security Rules.

## SPARQL safety

Parse the algebra before execution. Permit SELECT, ASK, CONSTRUCT, and DESCRIBE only. Reject update operations and remote `SERVICE` clauses. Apply allowlisted named graphs, tenant scoping, deadline, row/triple limit, query-size limit, and cost controls. Log a normalized query hash and trace rather than sensitive literals.

## Snapshot activation

Resolve only the stable `tenants/{tenantId}/ontology/active.json` pointer; never
accept an arbitrary release prefix from deployment configuration. Verify the
pointer's tenant, immutable release path, manifest SHA-256, Publisher identity,
publication receipt, and release SHA before fetching artifacts. Then verify RDF
hashes, parse, run mandatory SHACL, and atomically swap the in-memory reference.
If any step fails, keep the last valid published version and emit an activation
failure trace. Production must never fall back to the bundled demo candidate.

## Contract implementation boundary

OpenAPI and `contracts/schemas/` are canonical. The MVP keeps Pydantic and Zod models synchronized with drift and fixture tests; it does not yet generate SDK clients. Add generated clients only after the generator, language targets, compatibility policy, and release process are pinned.
