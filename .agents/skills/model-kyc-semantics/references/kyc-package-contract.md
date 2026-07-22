# KYC ontology package contract

## Package boundaries

- Model the pilot around `Party`, `Person`, `LegalEntity`, `Account`, `Payment`, `Identifier`, `Address`, `Jurisdiction`, `SanctionsEntry`, `KycCase`, and `EvidenceRecord`.
- Cover relations such as beneficial ownership, control, account ownership, payment origin/destination, identity evidence, sanctions match, and source-system equivalence.
- Keep domain semantics reusable. Put company labels, source fields, aliases, and mapping choices in a tenant overlay.
- The MVP does not vendor FIBO. It may record explicit alignment candidates as unapproved planning metadata. A reviewed, pinned subset with license and source metadata is roadmap work.
- Use RDF/JSON-LD for interchange, SKOS for vocabulary, OWL 2 for justified semantics, SHACL for constraints, PROV-O for lineage, DCAT for source metadata, and R2RML-style mapping terms where useful.

## Canonical artifacts

The Semantic Gateway consumes exactly five runtime RDF entries from `semantic/artifacts/manifest.json`:

| File | Format | Kind | Purpose |
| --- | --- | --- | --- |
| `ontology.ttl` | `turtle` | `graph` | Classes, properties, vocabulary, alignments |
| `demo-data.ttl` | `turtle` | `graph` | Synthetic tenant fixture assertions |
| `mappings.ttl` | `turtle` | `graph` | Source-to-concept mappings and transformations |
| `provenance.nq` | `nquads` | `provenance` | Evidence, generation, and verification lineage |
| `shapes.ttl` | `turtle` | `shapes` | Integrity and publication constraints |

Keep non-RDF package records outside the runtime `artifacts` array so the gateway cannot parse JSON as RDF. Under `supportingArtifacts`, list `competency-questions.json` with role `questions`, the immutable discovery proposal with role `proposal`, the separate frozen verification decision with role `verification`, and the hashed mapping decision ledger with role `publication-review`. A Publisher-promoted release also includes an immutable `publication-receipt`.

The manifest uses the runtime field names `$schema`, `version`, `tenantId`, `ontologyVersion`, `namespace`, `createdAt`, `materializeOwlRl`, `artifacts`, `supportingArtifacts`, and `stats`. Every entry carries a safe relative `path` and lowercase SHA-256; runtime entries also carry `format` and `kind`, while supporting entries carry `role` and `mediaType`. Validation must recompute file hashes, count the materialized RDF/source coverage, validate supporting JSON and frozen hashes, enforce the MVP ranges, and reject mock verification that claims independent agreement or publication.

## Five pilot competency questions

1. Which accounts are linked to sanctioned legal entities through beneficial ownership?
2. Which payments originated from those accounts?
3. Which parties are likely duplicates across sources, and what evidence supports the match?
4. Why does `cif_no` map to a chosen concept, and what counterevidence exists?
5. What mappings, relations, and competency questions are affected if `ubo` is removed?

Store each question with an ID, natural-language question, query or evaluation reference, and expected outcome. Require at least four of five to pass for a pilot release; do not hide a failed high-risk question inside an aggregate score.

## Provenance and uncertainty

Attach every assertion to immutable evidence coordinates: source ID, snapshot ID, record or document location, extractor version, observed timestamp, and content hash. Record generation and review traces separately.

Keep confidence dimensions distinct: lexical, structural, instance, external-reference, model, and evidence coverage. A ranking score may order work, but it is not an approval decision.

## Publication rules

- Reject packages with missing hashes, broken IRIs, invalid RDF, failing mandatory SHACL shapes, or incomplete provenance.
- Require human review for high-risk semantics, deletions with material impact, and model-dependent outcomes without independent verification.
- Let only the Publisher role replace the generation-guarded stable
  `tenants/{tenantId}/ontology/active.json` pointer. The pointer may resolve only
  to an immutable Publisher-promoted release manifest and carries its SHA-256.
- Retain the last valid package and support rollback by changing the pointer, never by editing an immutable version.
