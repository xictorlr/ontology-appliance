# Semantic discovery contract

## Stages

1. Profile source metadata, constraints, bounded values, distributions, and candidate joins.
2. Retrieve nearby ontology terms using lexical search and embeddings.
3. Generate candidate concepts, relations, aliases, mappings, duplicates, and drift events.
4. Attach supporting and contradicting evidence.
5. Score each confidence dimension and rank the queue.
6. Persist immutable proposals with `PENDING_VERIFICATION` or `ABSTAINED`.

Run stages as durable, idempotent Functions v2 task handlers. Use Cloud Tasks for bounded dispatch, retries, rate limits, and orchestration; move to a separate batch runtime only after an explicit scale review.

## Proposal record

Every proposal contains:

- `proposal_id`, `tenant_id`, `kind`, and `risk`
- source snapshot set and active ontology version
- source locator and proposed target IRI or new-term definition
- normalized transformation or relation expression
- supporting `evidence` and explicit `counterevidence`
- `confidence` dimensions: lexical, structural, instance, external, model, evidence_coverage
- generator trace, algorithm version, and deterministic input hash
- status and reason codes

Use `low`, `medium`, or `high` risk. Beneficial ownership, sanctions, identity resolution, destructive changes, and policy-critical classifications are high risk by default.

## Ranking policy

Rank candidates for efficient review, but preserve the vector. A typical queue score may weight structural and instance evidence most heavily. Evidence-free candidates abstain. High-risk candidates can be sent to verification but can never become auto-approved from ranking.

## Model use

Use an explicitly allowlisted and pinned Gemini model available in `europe-west4` through a provider-neutral adapter. Require JSON Schema output and record the actual returned model version. Never silently switch models. Keep deterministic record/replay fixtures so mandatory CI does not call paid APIs.

## Drift

Compare snapshot fingerprints, schemas, distributions, ontology dependencies, and question impact. Create a new proposal batch instead of editing a prior run. Preserve the old run for reproducibility.
