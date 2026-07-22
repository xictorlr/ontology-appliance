# Pilot acceptance suite

The labeled synthetic dataset defines five golden questions:

1. Which accounts are linked to sanctioned legal entities through beneficial ownership?
2. Which payments originated from those accounts?
3. Which parties are duplicates across sources, with what evidence?
4. Why does `cif_no` map to `Customer.identifier`, and which counterexamples were tested?
5. What is the impact of removing `ubo` from the KYC source?

The test suite measures exact entity IDs, evidence locators, ontology version, and trace presence. A question passes only when its required rows and supporting evidence are both correct. CI uses deterministic fixtures and record/replay; mandatory checks do not call paid model APIs.

The repository validator also fails if the baseline deployment or example
environment selects Vertex AI, OpenAI, or Anthropic. Enabling any paid provider
requires a separately reviewed configuration change; Terraform keeps the Vertex
API and IAM grant behind `enable_vertex_ai=false` by default. The optional
Anthropic adapter is code-only and receives no Terraform, workflow, or App
Hosting secret wiring in the baseline.
