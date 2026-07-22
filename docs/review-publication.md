# Review receipt to publication ledger

The Publisher consumes reviewed, content-addressed files. It does not trust a digest
merely because it has 64 hexadecimal characters, and it does not query Firestore while
activating a release.

## 1. Explicit read-only Firestore export

Run the export with an operator or future automation identity that has read-only access
to exactly `tenants/{tenantId}/reviewReceipts`. Do not use the Publisher identity. The
command uses Application Default Credentials, performs no Firestore writes, refuses an
existing output file, and omits reviewer email and rationale text:

```bash
pnpm --filter @ontology-appliance/web reviews:export \
  --project exact-development-project-id \
  --tenant demo-bank \
  --output /a/private/existing-directory/review-receipts.json \
  --confirm-cloud-read
```

The cloud read is deliberately gated by `--confirm-cloud-read`. No deployment or
publication workflow runs it implicitly. Keep the local export outside the repository;
the file is created with mode `0600`.

The normalized local document has this contract:

```json
{
  "$schema": "urn:ontology-appliance:schema:firestore-review-receipts-export:1",
  "tenantId": "demo-bank",
  "collectionPath": "tenants/demo-bank/reviewReceipts",
  "exportedAt": "2026-07-22T15:00:00Z",
  "receipts": [
    {
      "receiptId": "review-...",
      "proposalId": "mapping-crm-cif",
      "tenantId": "demo-bank",
      "reviewerUid": "firebase-uid",
      "reviewerRoles": ["steward"],
      "decision": "REVIEW_REQUIRED",
      "resultingStatus": "HUMAN_REVIEW",
      "rationaleSha256": "64 lowercase hexadecimal characters",
      "verificationRunId": "verification-run-id",
      "verificationRunSha256": "64 lowercase hexadecimal characters",
      "frozenProposalSha256": "64 lowercase hexadecimal characters",
      "frozenEvidenceIndexSha256": "64 lowercase hexadecimal characters",
      "policyVersion": "semantic-verification-policy-v1",
      "activeOntologyVersion": "2026.07.1",
      "createdAt": "2026-07-22T14:59:00Z"
    }
  ]
}
```

Timestamps are normalized to UTC second precision and receipts are sorted by proposal
and receipt ID. Duplicate roles are removed. The export is intentionally data-minimized.
Its schema is the normalization version. The later `sourceExportSha256` is the SHA-256
of this normalized JSON value using sorted object keys, UTF-8, and no insignificant
whitespace; `sourceReceiptSha256` applies the same rule to each normalized receipt.

The review API accepts `APPROVED` only for a hash-bound run using
`semantic-verification-policy-v1`, with a recognized risk matching the frozen proposal,
a live independent model, explicit
independent agreement, and exactly eight ordered gates. Gates 1–7 must all be `PASSED`;
only `HUMAN_ADJUDICATION` may remain `REVIEW_REQUIRED`. Medium/high-risk changes are
never auto-approved: this endpoint's verified steward authorization is their mandatory
human gate. Mock, disabled, skipped, failed, or non-independent runs cannot expose or
execute approval. They can only remain in review or be abstained. The current pilot fixture is mock mode,
so it intentionally has no approval action.

## 2. Deterministic ledger materialization

Every reviewed proposal must have exactly three manifest records with the same
`proposalId`: `proposal`, `verification`, and `evidence-index`. Their paths must remain
inside the bundle and their manifest hashes must match the files. Materialize a ledger
to a new path:

```bash
cd services/semantic-gateway
uv run python ../../scripts/export_publication_review.py \
  --manifest ../../semantic/artifacts/manifest.json \
  --receipts /a/private/existing-directory/review-receipts.json \
  --output /a/private/existing-directory/publication-review.json
```

For each receipt the exporter checks tenant and proposal identity, verification-run ID,
the proposal hash, and the source evidence-index hash frozen by both the receipt and
verifier. It also recomputes `verification_run_sha256` from the complete canonical
verification object after omitting that digest field; a changed gate, model result, risk,
or policy therefore invalidates the run. A materialized evidence-index may carry that source hash in
`sourceEvidenceIndexSha256`; its selected evidence and counterevidence must still equal
the proposal and verification records exactly. The ledger's `reviewEvidence` contains
the real hashes of the three materialized bundle files. The output bytes are
deterministic for the same manifest, artifacts, and normalized export. The private
Firestore export is represented only by its canonical SHA-256 and is not copied into
the ledger.

`exportProvenance` records the export schema, normalization version, digest algorithm,
tenant-bound collection path, export time, and the explicit trust boundary
`UNSIGNED_OPERATOR_EXPORT_REQUIRES_PROTECTED_PR_REVIEW`. These digests prove that the
reviewed ledger remains bound to the exact normalized input; they do **not** prove who
performed the Firestore read, that the source database was uncompromised, or that the
receipt was authentic. That authenticity boundary is the read-only operator credential,
the protected semantic-change pull request, its human review, and the Publisher's
subsequent artifact-chain verification. The Publisher intentionally has no Firestore
access and cannot independently recreate or bless the export.

Review the generated file, replace `semantic/artifacts/publication-review.json` in the
semantic change pull request, and update both its `supportingArtifacts` SHA-256 and
`publication.reviewLedgerSha256` in `manifest.json`. Proposal, verification, and
evidence-index files and their manifest records must be part of the same reviewed
change. CI then runs:

```bash
uv run python ../../scripts/check_semantic_publication.py --mode candidate
```

For a future publishable bundle, all mapping states and receipt statuses must be
`APPROVED` or `PUBLISHED`, receipt coverage must be full, and the manifest/ledger state
must be `PUBLISHABLE`. The protected publication workflow reruns the same artifact-chain
gate before it authenticates the Publisher. The current mock-only demo remains
`CANDIDATE`, with all mappings in `HUMAN_REVIEW`, so this process cannot accidentally
make it publishable.

## Local tests with no cloud access

```bash
pnpm --filter @ontology-appliance/web reviews:export --self-test
cd services/semantic-gateway
uv run python ../../scripts/export_publication_review.py --self-test
uv run python ../../scripts/check_semantic_publication.py --self-test
```
