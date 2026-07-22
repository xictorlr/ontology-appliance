# Semantic Gateway

FastAPI service that loads immutable RDF artifacts, verifies their SHA-256
digests and SHACL conformance, and exposes the active ontology through a
tenant-aware, read-only API.

## Local run

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
uvicorn ontology_appliance_gateway.main:app --reload
```

Development uses the fixed `demo-bank` tenant when no authorization header is
present. A different development principal can be supplied as
`Authorization: Bearer dev:<tenant>:<user>:<comma-separated-roles>` only when
`OA_ALLOW_DEV_TENANT_OVERRIDE=true`. Production defaults to a Firebase session
cookie in the `Authorization: Bearer ...` header with revocation checking. The
private Cloud Run identity token belongs in `X-Serverless-Authorization`, so the
two authentication layers do not collide. Set `OA_AUTH_MODE=firebase-id-token`
only for callers that actually forward an ID token. Both modes require a
`tenant_id` custom claim matching `OA_TENANT_ID` (the single enabled pilot
tenant for that gateway instance).

The checked-in `semantic/artifacts/manifest.json` is a `DEMO_ONLY` candidate,
never an active production version. The service labels it as non-published in
every response. It keeps the previous valid graph in memory and in the
configured `OA_LAST_VALID_PATH` cache.

When Terraform provides `ONTOLOGY_ARTIFACT_BUCKET` (or
`OA_ARTIFACT_BUCKET`), the gateway reads the stable
`tenants/{tenant_id}/ontology/active.json` pointer. Configure the same constant
path with `ONTOLOGY_ARTIFACT_POINTER`/`OA_ARTIFACT_POINTER`; it may resolve only
to an immutable manifest below the tenant's `ontology/releases/` prefix. The
gateway verifies the pointer-to-manifest hash, Publisher/receipt metadata,
artifact digests, and SHACL before swapping snapshots. A remote failure retains
a verified in-process cache. In production `OA_ACTIVE_POINTER_GENERATION` is
mandatory: every revision reads that immutable generation rather than `latest`,
so a cold start remains recoverable and an older revision remains a durable
rollback target even though `/tmp` is ephemeral. Production never falls back to
the bundled demo candidate, and the gateway never writes to the bucket.

Cloud development may explicitly serve the image-bundled candidate only with
`OA_ALLOW_DEMO_CANDIDATE=true` and no artifact bucket configured. This preserves
production authentication while keeping every response labeled `CANDIDATE` /
`DEMO_ONLY`; it cannot activate or upload that candidate.

## Competency-question acceptance

`semantic/artifacts/competency-questions.json` is the hash-pinned golden suite
for CQ-001 through CQ-005. Each case fixes the ordered SPARQL template, exact
normalized rows, bundle and ontology versions, reproducible trace ID, and exact
source provenance coordinates (`sourceId`, `snapshotId`, `locator`, and content
SHA-256). Gateway tests use deep equality; row-count thresholds and subset
matches are not acceptance evidence. The publication gate independently
executes the same five queries over the manifest-verified, OWL-RL-materialized
bundle and derives the pass count before checking `status`, the golden summary,
and manifest statistics.

## Model adapters

Semantic discovery is provider-neutral and defaults to the deterministic mock.
`VertexGeminiGenerator` remains disabled unless
`GENERATOR_PROVIDER=vertex-ai`; when enabled it uses Application Default
Credentials, `europe-west4`, and `gemini-2.5-flash` by default. Override only
the approved model with `GEMINI_GENERATOR_MODEL`. Generation uses controlled
JSON output and records the provider-returned model, prompt version, evidence,
input hash, parameters, response ID, latency, and token usage. Any Gemini output
is still an untrusted, model-dependent proposal.

The independent verifier uses the provider-neutral `VERIFIER_PROVIDER` selector
and defaults to `mock`. `OPENAI_VERIFIER_MODE=mock|openai` remains a legacy
fallback when the new selector is absent; an explicitly selected paid provider
never silently borrows another provider's key. Selecting `openai` still requires
`OPENAI_API_KEY`; that adapter uses the Responses API with `store: false`, low
reasoning effort, and a strict JSON Schema. It defaults to `gpt-5.6-terra` and
remains configurable through `OA_OPENAI_VERIFIER_MODEL`.

`VERIFIER_PROVIDER=anthropic` selects the optional raw Messages API adapter and
still performs no request unless `ANTHROPIC_API_KEY` is present. It defaults to
the official `claude-sonnet-5` model, sends structured output through
`output_config.format`, explicitly disables thinking, and omits `temperature`,
`top_p`, and `top_k`. Refusals become recorded independent abstentions; a
`max_tokens` stop is rejected as incomplete. Returned model, response ID, token
usage, latency, and refusal state are retained in the decision. See Anthropic's
[Sonnet 5 notes](https://platform.claude.com/docs/en/about-claude/models/whats-new-sonnet-5)
and [structured-output contract](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

All mandatory tests use `httpx.MockTransport` and make no paid call. A human may
run exactly one synthetic smoke request only with both the provider opt-in and
the explicit paid-call confirmation. To keep the credential out of shell
history, create the already-ignored local file with owner-only permissions:

```bash
cd services/semantic-gateway
umask 077
$EDITOR .env.local
chmod 600 .env.local
uv run python scripts/smoke_anthropic_verifier.py \
  --env-file .env.local \
  --use-system-truststore \
  --confirm-paid-call
```

Set `VERIFIER_PROVIDER=anthropic` and `ANTHROPIC_API_KEY=...` in that file. The
loader rejects symlinks, non-owner permissions, duplicate allowlisted settings,
and files larger than 64 KiB; it ignores non-allowlisted names and never prints
the key. The script does not even open the file until `--confirm-paid-call` is
present. Omit the flag to verify the fail-closed guard without network access.
Standard process environment variables remain supported for secret managers and
ephemeral CI shells. `--use-system-truststore` is useful behind a managed
corporate TLS proxy: it injects the operating-system CA store before importing
the HTTP client and keeps certificate verification enabled; it never falls back
to an insecure `verify=false` mode.
