# Durable Functions workflows

Functions v2 and Cloud Tasks materialize the bounded discovery, verification,
and drift control plane. No handler can activate an ontology version.

Storage, Firestore, and scheduled functions stay with the pilot data plane in
`europe-west4`. Cloud Tasks is not offered there, so the three task queues and
their task-consumer Functions run in `europe-west1`; only bounded task payloads
cross that regional boundary.

- Storage finalization derives the tenant and source from the immutable object
  path, profiles metadata only, and transactionally creates a content-addressed
  snapshot plus a `PENDING_VERIFICATION` proposal.
- Proposal creation derives the tenant from the Firestore path. Verification
  freezes the proposal, writes one `VerificationRun` and eight ordered
  `GateResult` documents, and ends in `HUMAN_REVIEW` or `ABSTAINED`. The local
  workflow never manufactures independent model agreement or auto-approval.
- The daily scheduler enumerates active tenants, compares bounded source
  profiles, and creates a deterministic drift proposal when content hashes
  changed. A no-change check completes without inventing semantic evidence.

All output IDs and hashes are derived from pinned inputs. Each terminal write,
including the corresponding `taskExecutions` outcome, commits in one Firestore
transaction. A completed task is safe to redeliver; an in-flight task is retried
and may be reclaimed only after the configured execution lease expires.

`ONTOLOGY_BASE_VERSION` pins the ontology context recorded on proposals. Source
objects and evidence remain read-only; the Publisher identity and publication
workflows are separate from this package.
