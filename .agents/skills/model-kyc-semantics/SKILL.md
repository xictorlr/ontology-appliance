---
name: model-kyc-semantics
description: Design, revise, and validate governed KYC/AML ontology packages using RDF, SKOS, OWL, SHACL, provenance, mappings, and competency questions. Use for Party–LegalEntity–Account–Payment modeling, lightweight external-reference planning, tenant overlays, ontology versioning, semantic acceptance tests, or changes to ontology artifacts such as ontology.ttl, shapes.ttl, mappings.ttl, provenance.nq, and manifest.json.
---

# Model KYC Semantics

Model a small, evidence-backed KYC/AML semantic core that can be published and queried safely.

## Workflow

1. Read `references/kyc-package-contract.md` before changing the semantic model.
2. Inspect source evidence, existing artifacts, and the five competency questions. Never infer a business definition from a column name alone.
3. Keep the reusable domain model separate from the tenant overlay. Prefer stable `urn:ontology-appliance:{tenant}:...` IRIs until a governed public namespace exists.
4. Define concepts and relations with SKOS labels/definitions, OWL semantics only where justified, and explicit provenance.
5. Express integrity and publication gates in SHACL. Keep source mappings separate from domain semantics.
6. Test every change against competency questions, SHACL, mapping evidence, and backward compatibility.
7. Generate immutable runtime RDF artifacts, governed JSON sidecars, and a manifest with verified SHA-256 hashes. From the repository root run:

   `python3 .agents/skills/model-kyc-semantics/scripts/validate_package_manifest.py semantic/artifacts/manifest.json --pilot`

8. Publish only through the Publisher workflow after verification. Never write to source systems or mutate the active production graph directly.

## Guardrails

- Let models propose; let evidence, deterministic checks, and authorized humans decide.
- Preserve provenance for every term, relation, mapping, and decision.
- The MVP does not vendor FIBO. Treat any current external-reference score or alignment note as planning metadata, never as a verified FIBO import.
- Avoid unsupported OWL 2 DL complexity and massive materialization in the MVP.
- Represent uncertainty as a confidence vector; do not replace it with a single approval score.

## Required outputs

Produce the runtime bundle `ontology.ttl`, `demo-data.ttl`, `shapes.ttl`, `mappings.ttl`, and `provenance.nq`; keep `competency-questions.json`, immutable discovery proposals, and separate verification runs as hashed supporting artifacts so the RDF loader never treats JSON as RDF. For the MVP pilot, the validator must count 30–50 materialized concepts, 15–25 materialized relations, 100–200 materialized mappings, three to five structured sources, at least one document repository, and at least four of five passing competency questions. Declared statistics must exactly match the artifact bytes and never substitute for evidence, SHACL, provenance, or publication gates.

A reviewed, license-preserving, pinned FIBO subset is roadmap work. Add it only with vendored source metadata, explicit alignment tests, and governance approval.
