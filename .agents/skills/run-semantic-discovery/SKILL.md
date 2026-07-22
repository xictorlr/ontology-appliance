---
name: run-semantic-discovery
description: Discover, rank, and package evidence-backed semantic concepts, relationships, source mappings, aliases, and duplicate candidates. Use when profiling sources, generating ontology proposals, comparing source fields to KYC concepts, running Gemini-assisted discovery, calculating confidence vectors, evaluating drift, or producing proposal batches for independent verification and steward review.
---

# Run Semantic Discovery

Turn source evidence into traceable proposals while keeping generation separate from approval.

## Workflow

1. Read `references/discovery-contract.md` before running or changing discovery.
2. Pin tenant, source snapshot IDs, active ontology version, prompt version, model identifier, parameters, and extractor versions.
3. Build deterministic candidates from names, types, constraints, distributions, co-occurrence, joins, document evidence, and pinned reference vocabularies.
4. Let the generator model enrich or challenge candidates using only cited evidence. Require structured output; preserve refusals and incomplete responses.
5. Record lexical, structural, instance, external-reference, model, and evidence-coverage confidence separately.
6. Rank work without approving it:

   `python3 .agents/skills/run-semantic-discovery/scripts/rank_candidates.py --self-test`

   For a real immutable discovery run, replace `--self-test` with its generated JSONL path and an explicit `--output` path.

7. Deduplicate proposals by tenant, snapshot set, target concept, source locator, proposal kind, and algorithm version.
8. Send eligible proposals to the verification fabric. Route insufficient evidence to `ABSTAINED`; never publish from discovery.

## Guardrails

- Treat model output as an untrusted proposal.
- Require evidence coordinates and counterevidence for every mapping or relation.
- Keep a ranking score only as a queue-ordering convenience; never use it as a substitute for the confidence vector.
- Prefer metadata and bounded samples over bulk data movement.
- Re-run affected proposals when source, ontology, prompt, extractor, or model versions change.

## Required outputs

Emit JSONL proposal records, an immutable run manifest, ranked work queues, evidence links, counterevidence, drift observations, and execution traces. Include provider-returned model ID, prompt version, parameters, token usage, latency, and deterministic input hashes when a model participates.

The current MVP includes deterministic fixtures plus provider adapters; it does not claim a production discovery run, measured acceptance rate, or auto-approval eligibility from fixture output.
