---
name: verify-semantic-proposals
description: Verify ontology, mapping, relationship, duplicate, and drift proposals with deterministic gates, evidence lineage, risk policy, mock-safe model checks, and human review routing. Use when implementing RDF/SHACL or fixture-backed source validation, evaluating confidence vectors, testing generator/verifier separation, handling verifier mock mode, assigning proposal statuses, or deciding whether a semantic change must remain in review. Live SQL assertions and measured auto-approval precision remain roadmap work.
---

# Verify Semantic Proposals

Apply independent, reproducible gates between discovery and publication.

## Workflow

1. Read `references/verification-policy.md` before modifying approval logic.
2. Freeze the proposal, evidence set, source snapshots, ontology version, verifier policy version, and model traces.
3. Validate contract shape and provenance before semantic checks. Quarantine malformed or provenance-incomplete inputs.
4. Run implemented deterministic checks: contract/provenance validation, RDF parsing, SHACL, fixture-backed source assertions, namespace rules, dependency impact, and affected competency questions. A Boolean fixture named `sql_valid` is compatibility evidence only; no live SQL runner exists in the MVP.
5. Run an independent verifier only after deterministic checks. Use a distinct provider/model from the generator and structured output with `store: false`.
6. Evaluate gates:

   `python3 .agents/skills/verify-semantic-proposals/scripts/evaluate_gates.py semantic/artifacts/verification/mapping-crm-cif.mock.json`

7. Persist the decision, every gate result, reason code, policy version, and reviewer identity. Never overwrite a prior decision trace.
8. Send `AUTO_APPROVED` proposals to the Publisher queue; send `HUMAN_REVIEW` to a steward. The verifier never publishes.

## Guardrails

- Never let a verifier approve its own generated proposal.
- Treat mock verification as useful workflow testing, not independent agreement. Keep agreement null and require human review or abstention.
- Require human review for high-risk semantics regardless of aggregate confidence.
- Reject deterministic contradictions; quarantine broken contracts or lineage; abstain when evidence is insufficient.
- Measure pilot auto-approval precision on labeled synthetic evaluation data and require greater than 95 percent before enabling it.

## Required outputs

Produce a `VerificationRun`, ordered `GateResult` records, final status, reason codes, confidence vector, evidence links, model traces, and review requirement. Fixture and mock runs must remain `HUMAN_REVIEW` or `ABSTAINED`; they are not measured auto-approval evidence. Only an authorized Publisher may activate a separately reviewed release after these outputs exist.
