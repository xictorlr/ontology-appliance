export type IndustryPackAvailability = "active" | "planned";

export type IndustryPackDefinition = {
  id: string;
  label: string;
  detail: string;
  availability: IndustryPackAvailability;
  coreConcepts: readonly string[];
  activationRequirements: readonly string[];
};

const governedPackRequirements = [
  "versioned-rdf-bundle",
  "shacl-shapes",
  "competency-questions",
  "evidence-backed-mappings",
  "independent-verification",
] as const;

export const industryPacks: readonly IndustryPackDefinition[] = [
  {
    id: "financial-crime-kyc-aml",
    label: "Financial Crime · KYC / AML",
    detail: "Governed Party → LegalEntity → Account → Payment semantics.",
    availability: "active",
    coreConcepts: ["Party", "Legal entity", "Account", "Payment", "Case", "Sanction"],
    activationRequirements: governedPackRequirements,
  },
  {
    id: "oil-gas",
    label: "Oil & Gas",
    detail: "Upstream, midstream, and downstream asset and production semantics.",
    availability: "planned",
    coreConcepts: ["Field", "Reservoir", "Well", "Facility", "Pipeline", "Production volume"],
    activationRequirements: governedPackRequirements,
  },
  {
    id: "energy-utilities",
    label: "Energy & Utilities",
    detail: "Grid assets, generation, metering, consumption, and service points.",
    availability: "planned",
    coreConcepts: ["Grid asset", "Generation unit", "Meter", "Service point", "Consumption"],
    activationRequirements: governedPackRequirements,
  },
  {
    id: "insurance",
    label: "Insurance",
    detail: "Policy, coverage, insured party, claim, exposure, and loss events.",
    availability: "planned",
    coreConcepts: ["Policy", "Coverage", "Claim", "Exposure", "Loss event"],
    activationRequirements: governedPackRequirements,
  },
  {
    id: "manufacturing",
    label: "Manufacturing",
    detail: "Product, bill of materials, plant, equipment, work order, and quality.",
    availability: "planned",
    coreConcepts: ["Product", "BOM", "Plant", "Equipment", "Work order", "Quality event"],
    activationRequirements: governedPackRequirements,
  },
  {
    id: "healthcare-life-sciences",
    label: "Healthcare & Life Sciences",
    detail: "Patient-safe clinical, provider, product, trial, and regulatory semantics.",
    availability: "planned",
    coreConcepts: ["Patient", "Provider", "Encounter", "Therapy", "Clinical trial"],
    activationRequirements: governedPackRequirements,
  },
  {
    id: "retail-cpg",
    label: "Retail & CPG",
    detail: "Customer, product, assortment, promotion, order, and fulfillment semantics.",
    availability: "planned",
    coreConcepts: ["Customer", "Product", "Assortment", "Promotion", "Order"],
    activationRequirements: governedPackRequirements,
  },
  {
    id: "telecommunications",
    label: "Telecommunications",
    detail: "Subscriber, service, network resource, usage, incident, and billing.",
    availability: "planned",
    coreConcepts: ["Subscriber", "Service", "Network resource", "Usage", "Incident"],
    activationRequirements: governedPackRequirements,
  },
  {
    id: "public-sector",
    label: "Public Sector",
    detail: "Citizen, organization, case, benefit, permit, and public-service semantics.",
    availability: "planned",
    coreConcepts: ["Citizen", "Organization", "Case", "Benefit", "Permit"],
    activationRequirements: governedPackRequirements,
  },
] as const;
