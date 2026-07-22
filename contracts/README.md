# Canonical contracts

The MVP has two canonical JSON Schema records:

- `schemas/connector-manifest.schema.json` describes the read-only synthetic connector manifests committed under `data/contracts/*.connector.json`.
- `schemas/proposal.schema.json` describes immutable discovery proposal records such as `semantic/artifacts/proposals/mapping-crm-cif.json`.

Both contracts use the snake_case wire names already present in the immutable artifacts. `packages/contracts` mirrors them in Zod, while `ontology_appliance_gateway.contract_records` mirrors them in Pydantic. `scripts/check_contract_drift.py`, the TypeScript contract tests, and the gateway contract tests validate the same committed fixtures and compare required fields and enums.

These models are maintained rather than generated in the MVP. OpenAPI request and response models remain a separate API boundary. Internal generator/verifier DTOs are not proposal records and must not be treated as publication decisions.

`data/contracts/source-connector.schema.json` is only a compatibility alias to the canonical connector schema. `data/contracts/postgres.example.json` is a roadmap example and is intentionally excluded from MVP fixture validation until a read-only adapter and an ephemeral integration test exist.
