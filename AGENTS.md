# Ontology Appliance engineering contract

This repository implements a governed KYC/AML semantic vertical. Preserve these invariants in every change:

- Treat source systems as read-only and start with metadata.
- Let models propose; let evidence, deterministic rules, and authorized people decide.
- Keep provenance on every proposal, mapping, answer, and publication.
- Represent confidence as a vector. Never collapse it to an unexplained scalar.
- Only the Publisher identity may activate a version. The verifier cannot approve its own output.
- Derive the tenant from the verified session/token, never from an untrusted request body.
- Reject SPARQL update operations. The canonical RDF bundle is immutable.
- Keep production provisioning and external side effects explicit.

Use the repository skills in `.agents/skills/` for ontology modeling, connectors, discovery, verification, gateway work, and Firebase deployment.
