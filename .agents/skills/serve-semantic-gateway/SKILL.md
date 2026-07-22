---
name: serve-semantic-gateway
description: Build, extend, and validate the governed read-only Semantic Gateway and its REST, OpenAPI, RDF, SHACL, SPARQL, provenance, and trace contracts. Use when implementing resolve, context, query, explain, validate, or SPARQL endpoints; loading immutable ontology snapshots in Cloud Run; maintaining checked-in TypeScript/Pydantic contract models; enforcing tenant/role access; or testing API compatibility and safe semantic query behavior. Generated clients remain roadmap work.
---

# Serve Semantic Gateway

Expose governed semantic context to applications and agents without creating an ungoverned write path.

## Workflow

1. Read `references/gateway-contract.md` before changing routes or response types.
2. Treat OpenAPI 3.1 and the schemas in `contracts/schemas/` as canonical. Keep the current hand-maintained Pydantic and Zod models aligned through fixture and drift tests. Client generation is roadmap work.
3. Load the active immutable RDF snapshot from Cloud Storage, verify its manifest hash, parse it, run mandatory SHACL checks, and cache it in memory.
4. Keep the last valid snapshot available if activation fails. Never depend on Cloud Run's ephemeral filesystem for durable RDF state.
5. Implement `/v1/resolve`, `/v1/context`, `/v1/query`, `/v1/explain`, `/v1/validate`, and role-gated `/v1/sparql`.
6. Validate the API document:

   `python3 .agents/skills/serve-semantic-gateway/scripts/validate_openapi.py contracts/openapi.yaml`

7. Recheck tenant and role server-side on every request. Emit evidence, ontology version, trace ID, warnings, and stable Problem Details errors.
8. Test golden queries, tenant isolation, read-only SPARQL parsing, timeouts, result limits, rollback, and version consistency.

## Guardrails

- Accept SPARQL query forms only; reject UPDATE, LOAD, CLEAR, CREATE, DROP, COPY, MOVE, ADD, and SERVICE.
- Derive tenant from verified identity, never from an arbitrary body field.
- Keep the Cloud Run service private and allow invocation only from approved service identities.
- Do not expose raw source credentials or sensitive evidence values.
- Require an explicit ontology version for reproducible traces or return the active version used.

## Required outputs

Produce a FastAPI service, OpenAPI 3.1 document, checked-in Pydantic/Zod contracts with drift tests, immutable snapshot loader, authorization policy, structured traces, and golden-query tests. Return Problem Details for errors and a consistent success envelope for every semantic operation. Generated clients and real cloud-smoke evidence are roadmap or post-deployment outputs, respectively.
