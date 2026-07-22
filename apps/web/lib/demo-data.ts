export type Source = {
  id: string;
  name: string;
  kind: string;
  assets: number;
  fields: number;
  records: number;
  bytes: number;
  evidence: number;
  completeness: number;
  status: "Ready" | "Profiling" | "Review";
  updated: string;
  color: string;
};

export type ProposalView = {
  id: string;
  kind: "Alias" | "Assertion" | "Concept" | "Constraint" | "Drift" | "Duplicate" | "Mapping" | "Relation";
  title: string;
  detail: string;
  confidence: number;
  risk: "Low" | "Medium" | "High";
  status: "Human review" | "Auto-approved" | "Approved" | "Abstained";
  evidence: number;
  confidenceVector?: Array<{ label: string; value: number }>;
  gates?: Array<{ name: string; status: "PASSED" | "FAILED" | "SKIPPED" | "REVIEW_REQUIRED" }>;
  targetIri?: string;
  reasonCodes?: string[];
  reviewed?: boolean;
  reviewDecision?: "APPROVED" | "REVIEW_REQUIRED" | "ABSTAINED";
  approvalEligible?: boolean;
  approvalReasonCodes?: string[];
  verifierMode?: string;
};

const fixtureConfidence = [
  { label: "Lexical", value: 0 },
  { label: "Structural", value: 100 },
  { label: "Instance", value: 100 },
  { label: "External", value: 0 },
  { label: "Model", value: 0 },
  { label: "Evidence coverage", value: 100 },
];

const fixtureGates: NonNullable<ProposalView["gates"]> = [
  { name: "CONTRACT", status: "PASSED" },
  { name: "SEMANTIC", status: "SKIPPED" },
  { name: "SOURCE_EVIDENCE", status: "PASSED" },
  { name: "INDEPENDENT_QUESTIONS", status: "SKIPPED" },
  { name: "MODEL_CONSISTENCY", status: "SKIPPED" },
  { name: "DATA_TESTS", status: "REVIEW_REQUIRED" },
  { name: "GLOBAL_CONSISTENCY", status: "SKIPPED" },
  { name: "HUMAN_ADJUDICATION", status: "REVIEW_REQUIRED" },
];

export const sources: Source[] = [
  { id: "crm-parties", name: "Customer master", kind: "CSV", assets: 1, fields: 7, records: 6, bytes: 492, evidence: 18, completeness: 90.4762, status: "Ready", updated: "22 Jul 2026", color: "mint" },
  { id: "core-accounts", name: "Account ledger", kind: "CSV", assets: 1, fields: 6, records: 3, bytes: 241, evidence: 12, completeness: 100, status: "Ready", updated: "17 Jun 2026", color: "blue" },
  { id: "payments-ledger", name: "Payment stream", kind: "JSONL", assets: 1, fields: 6, records: 3, bytes: 444, evidence: 12, completeness: 100, status: "Ready", updated: "19 Jun 2026", color: "violet" },
  { id: "aml-cases", name: "AML investigations", kind: "CSV", assets: 1, fields: 7, records: 2, bytes: 252, evidence: 12, completeness: 100, status: "Ready", updated: "20 Jun 2026", color: "amber" },
  { id: "sanctions-api", name: "Sanctions service", kind: "OpenAPI + JSON", assets: 2, fields: 6, records: 1, bytes: 1_656, evidence: 11, completeness: 100, status: "Ready", updated: "20 Jun 2026", color: "rose" },
  { id: "kyc-documents", name: "KYC evidence", kind: "PDF", assets: 1, fields: 5, records: 1, bytes: 1_054, evidence: 14, completeness: 100, status: "Ready", updated: "20 Jun 2026", color: "cyan" },
];

export const initialProposals: ProposalView[] = [
  { id: "MAP-104", kind: "Mapping", title: "cif_no → Customer.identifier", detail: "crm.customers.cif_no", confidence: 100, confidenceVector: fixtureConfidence, gates: fixtureGates, risk: "Medium", status: "Human review", evidence: 4 },
  { id: "REL-032", kind: "Relation", title: "ubo → beneficialOwnerOf", detail: "kyc_documents.ubo", confidence: 100, confidenceVector: fixtureConfidence, gates: fixtureGates, risk: "High", status: "Human review", evidence: 5 },
  { id: "MAP-118", kind: "Mapping", title: "iban → Account.accountIdentifier", detail: "ledger.accounts.iban", confidence: 100, confidenceVector: fixtureConfidence, gates: fixtureGates, risk: "Low", status: "Human review", evidence: 3 },
  { id: "CON-017", kind: "Constraint", title: "Payment must have debtor account", detail: "sh:minCount 1", confidence: 100, confidenceVector: fixtureConfidence, gates: fixtureGates, risk: "Medium", status: "Human review", evidence: 7 },
  { id: "MAP-126", kind: "Mapping", title: "party_ref → LegalEntity.identifier", detail: "aml_cases.party_ref", confidence: 100, confidenceVector: fixtureConfidence, gates: fixtureGates, risk: "Medium", status: "Abstained", evidence: 2, reviewed: true, reviewDecision: "ABSTAINED" },
];

export const competencyQuestions = [
  { id: "CQ-001", short: "Sanctioned beneficial owners", question: "Which accounts are linked to sanctioned parties through beneficial ownership?", score: 100 },
  { id: "CQ-002", short: "Payments at risk", question: "Which payments originate from accounts linked to sanctioned beneficial owners?", score: 100 },
  { id: "CQ-003", short: "Duplicate parties", question: "Which party records are potential duplicates across sources, and what evidence supports that?", score: 100 },
  { id: "CQ-004", short: "Mapping evidence", question: "Why is cif_no mapped to Customer Identifier, and what counterexamples were found?", score: 100 },
  { id: "CQ-005", short: "Change impact", question: "What is impacted if the ubo field mapping is deleted?", score: 100 },
];

export const concepts = [
  { x: 49, y: 13, label: "Party", kind: "core" },
  { x: 28, y: 32, label: "Person", kind: "core" },
  { x: 70, y: 32, label: "Legal entity", kind: "core" },
  { x: 15, y: 57, label: "Customer", kind: "overlay" },
  { x: 44, y: 57, label: "Beneficial owner", kind: "domain" },
  { x: 80, y: 58, label: "Sanction", kind: "domain" },
  { x: 26, y: 82, label: "Account", kind: "domain" },
  { x: 58, y: 82, label: "Payment", kind: "domain" },
  { x: 87, y: 84, label: "AML case", kind: "overlay" },
];

export const traceRows = [
  { id: "fixture…cq01", action: "Semantic query fixture", actor: "local-demo", version: "2026.07.1-candidate", duration: "fixture", status: "OK", time: "synthetic" },
  { id: "fixture…gate", action: "Proposal gate fixture", actor: "policy-engine", version: "2026.07.1-candidate", duration: "fixture", status: "REVIEW", time: "synthetic" },
  { id: "fixture…term", action: "Term resolution fixture", actor: "local-demo", version: "2026.07.1-candidate", duration: "fixture", status: "OK", time: "synthetic" },
  { id: "fixture…shacl", action: "SHACL validation fixture", actor: "deterministic-validator", version: "2026.07.1-candidate", duration: "fixture", status: "OK", time: "synthetic" },
  { id: "fixture…disc", action: "Discovery fixture", actor: "source-scout", version: "2026.07.1-candidate", duration: "fixture", status: "PARTIAL", time: "synthetic" },
];
