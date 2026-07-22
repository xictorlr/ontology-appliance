export interface IngestionTaskPayload {
  tenantId: string;
  sourceId: string;
  objectName: string;
  bucket: string;
  generation: string;
  contentType: string;
  sizeBytes: number;
  observedAt: string;
  executionId: string;
}

export interface VerificationTaskPayload {
  tenantId: string;
  proposalId: string;
  requestedAt: string;
  executionId: string;
}

export interface DriftTaskPayload {
  tenantId: string;
  scheduledDay: string;
  evaluatedAt: string;
  executionId: string;
}
