# Semantic verification policy

## Separation of duties

- Discovery produces immutable proposals.
- Verification evaluates but never edits the proposal or publishes it.
- A steward decides human-review cases.
- Only Publisher changes the active ontology pointer.
- The same model/provider pair cannot count as independent generation and verification.

## Gate order

1. Contract and tenant binding
2. Complete provenance and evidence integrity
3. RDF, schema, namespace, and mapping syntax
4. SHACL constraints
5. Implemented fixture-backed source assertions; live SQL assertions are roadmap work
6. Dependency and competency-question impact
7. Independent model verification
8. Risk and confidence policy
9. Human decision or Publisher queue

Stop on quarantine or deterministic rejection, but record skipped gates explicitly.

## Status policy

| Condition | Status |
| --- | --- |
| Broken contract, wrong tenant, missing provenance | `QUARANTINED` |
| Deterministic semantic contradiction | `REJECTED` |
| No evidence or extremely low evidence coverage | `ABSTAINED` |
| High/medium risk or uncertain outcome | `HUMAN_REVIEW` |
| Mock verifier or no independent agreement | `HUMAN_REVIEW` |
| Low risk, all gates pass, independent agreement, strong vector | `AUTO_APPROVED` |

`PENDING_VERIFICATION` is the discovery handoff state. `PUBLISHED` is assigned only by the Publisher after artifact creation and activation.

## Mock mode

Until an OpenAI API key is supplied and the labeled evaluation passes, run a deterministic verifier mock in development. Set:

- `models.mode` to `mock`
- `independent_agreement` to null
- the result to `HUMAN_REVIEW` or `ABSTAINED`

Never fabricate provider agreement.

## Live model trace

Use the OpenAI Responses API through a provider-neutral adapter. Start with the approved `gpt-5.6-terra` verifier, but run a model-lifecycle check before enabling live calls and pin the selected snapshot/configuration. Require JSON Schema output, set `store: false`, and handle refusal or incomplete output. Record actual provider/model, prompt version, parameters, token usage, latency, response status, and evidence/input hashes without logging sensitive source values.

## Pilot acceptance

Require complete provenance, greater than 95 percent precision on auto-approved labeled mappings, greater than 80 percent steward acceptance for high-confidence proposals, zero high-risk changes without human review, at least four of five competency questions correct, and full run reproducibility.

These percentages are enablement gates, not current MVP results. Until a labeled evaluation set and live independent verifier are run, keep auto-approval disabled and do not report fixture outcomes as measured precision or steward acceptance.
