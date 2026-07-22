# Semantic bundle lifecycle

`semantic/artifacts` is the checked-in pilot **candidate graph**, not an active ontology.
Its manifest must say `CANDIDATE`, `DEMO_ONLY`, and `isPublished: false`; the gateway
repeats those values and a non-published warning in every response.

Publication is a separate, fail-closed transition:

1. Each mapping in `mappings.ttl` must be `APPROVED` or `PUBLISHED`.
2. `publication-review.json` must cover every mapping and link the exact manifest-backed
   proposal, verification, and evidence-index artifacts to an authorized reviewer who
   is distinct from the generator and verifier. The validator checks each file and
   frozen hash; a digest-shaped string alone is never sufficient.
3. The source manifest moves to `PUBLISHABLE` / `PUBLISHER_ONLY`; the gateway refuses
   to serve that intermediate state.
4. `scripts/check_semantic_publication.py --mode publish` must pass before the CI job
   assumes the Publisher identity.
5. Only that identity may create the `PUBLISHED` / `ACTIVE` manifest and immutable
   publication receipt, then atomically replace
   `tenants/demo-bank/ontology/active.json`. Deployment always configures this
   stable pointer; selecting a release prefix cannot activate a graph.

The normal development workflow deploys the candidate embedded in the private gateway
image with `OA_ALLOW_DEMO_CANDIDATE=true`; it neither assumes Publisher nor writes
`active.json`. The separate, protected `Publish reviewed semantics` workflow invokes the
real publication gate and currently fails because mock verification remains
`HUMAN_REVIEW`. Validate the demo candidate without weakening that gate with:

```bash
cd services/semantic-gateway
uv run python ../../scripts/check_semantic_publication.py --mode candidate
```

The explicit, data-minimized Firestore receipt export and deterministic ledger workflow
are documented in [`docs/review-publication.md`](../docs/review-publication.md). The
Publisher does not read operational Firestore state while activating a release.
