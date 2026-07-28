"use client";

import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BookOpen,
  Box,
  Braces,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock3,
  CloudUpload,
  Code2,
  Database,
  Eye,
  FileCheck2,
  FileSearch,
  Fingerprint,
  GitBranch,
  GitCommitHorizontal,
  GitPullRequestArrow,
  KeyRound,
  Layers3,
  LoaderCircle,
  LockKeyhole,
  Network,
  PackageCheck,
  Plus,
  RefreshCw,
  SearchCheck,
  Send,
  ServerCog,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  UserCheck,
  Users,
  WandSparkles,
  Workflow,
  X,
} from "lucide-react";
import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import {
  connectorCatalog,
  connectorCategories,
  isActiveFileConnector,
  type ConnectorCategory,
} from "@/lib/connector-catalog";
import { competencyQuestions, concepts, initialProposals, traceRows, type ProposalView } from "@/lib/demo-data";
import { industryPacks } from "@/lib/industry-catalog";
import {
  resolveReviewQueue,
  type ReviewQueueMode,
  type ReviewQueuePayload,
} from "@/lib/review-queue-state";
import type { SourceType } from "@/lib/source-contract";

export function SectionContent({ section }: { section: string }) {
  switch (section) {
    case "dashboard": return <Dashboard />;
    case "sources": return <Sources />;
    case "model": return <SemanticModel />;
    case "proposals": return <Proposals />;
    case "versions": return <Versions />;
    case "playground": return <GatewayPlayground />;
    case "traces": return <Traces />;
    case "settings": return <SettingsPage />;
    default: return null;
  }
}

function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description: string; actions?: ReactNode }) {
  return (
    <div className="page-header">
      <div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

function Dashboard() {
  const [runStarted, setRunStarted] = useState(false);
  return (
    <>
      <PageHeader eyebrow="Synthetic pilot · 22 July 2026" title="Semantic operations" description="A reproducible preview of evidence, verification, and candidate meaning for Demo Bank EU." actions={
        <><button className="button secondary"><FileSearch size={17} /> View audit</button><button className="button primary" onClick={() => setRunStarted(true)}><WandSparkles size={17} /> {runStarted ? "Run queued" : "Run discovery"}</button></>
      } />

      <section className="pilot-banner">
        <div className="pilot-title"><span className="pilot-icon"><Sparkles size={20} /></span><div><span>Active pilot</span><h2>KYC / AML semantic foundation</h2></div></div>
        <div className="pilot-progress">
          <div><span>Fixture evidence connected</span><strong>6 / 6</strong></div>
          <div className="progress-track"><i style={{ width: "100%" }} /></div>
          <span>100%</span>
        </div>
        <div className="pilot-version"><span>Candidate · demo only</span><strong>2026.07.1</strong><small>Not published</small></div>
        <button className="circle-link" aria-label="Open pilot"><ArrowRight size={19} /></button>
      </section>

      <section className="metric-grid">
        <Metric icon={<BookOpen size={19} />} label="Candidate concepts" value="44" change="Pilot target met" tone="mint" />
        <Metric icon={<GitBranch size={19} />} label="Modeled relations" value="23" change="Candidate graph" tone="blue" />
        <Metric icon={<GitPullRequestArrow size={19} />} label="Mapping proposals" value="100" change="All require review" tone="violet" />
        <Metric icon={<ShieldCheck size={19} />} label="Connector evidence" value="79" change="96.12% complete" tone="amber" />
      </section>

      <div className="dashboard-grid">
        <section className="panel pipeline-panel">
          <PanelTitle title="Discovery pipeline" subtitle="Run 2026-07-22.04" action={<button className="text-button">Open run <ChevronRight size={15} /></button>} />
          <div className="pipeline-list">
            {[
              ["Source inventory", "6 synthetic evidence sources", "done", Database],
              ["Profiling & terminology", "Reproducible fixture profiles", "done", SearchCheck],
              ["Ontology candidate", "44 concepts · 23 relations", "done", Network],
              ["Verification fabric", "100 mappings require human review", "active", ShieldCheck],
              ["Publisher gate", "Blocked until independent approval", "waiting", PackageCheck],
            ].map(([name, detail, state, Icon], index) => {
              const StepIcon = Icon as typeof Database;
              return <div className={`pipeline-step ${state}`} key={String(name)}><span className="step-line" /><span className="step-icon"><StepIcon size={17} /></span><div><strong>{String(name)}</strong><span>{String(detail)}</span></div><em>{state === "done" ? <Check size={15} /> : state === "active" ? <LoaderCircle className="spin" size={15} /> : index + 1}</em></div>;
            })}
          </div>
        </section>

        <section className="panel competency-panel">
          <PanelTitle title="Competency coverage" subtitle="5 of 5 executable on the candidate fixture" action={<span className="score-ring">100%</span>} />
          <div className="question-list">
            {competencyQuestions.map((question) => <div key={question.id} className="question-row"><span className={question.score ? "question-status pass" : "question-status pending"}>{question.score ? <Check size={14} /> : <Clock3 size={14} />}</span><div><strong>{question.short}</strong><span>{question.id} · {question.score ? "Passed" : "Awaiting source"}</span></div><ChevronRight size={15} /></div>)}
          </div>
        </section>
      </div>

      <section className="panel attention-panel">
        <PanelTitle title="Needs human judgment" subtitle="The mock verifier cannot authorize publication" action={<button className="button compact">Preview review queue <ArrowRight size={15} /></button>} />
        <div className="attention-table">
          {initialProposals.filter((item) => item.status === "Human review").map((item) => <div className="attention-row" key={item.id}><span className={`kind-icon ${item.kind.toLowerCase()}`}><GitCommitHorizontal size={17} /></span><div className="attention-main"><strong>{item.title}</strong><span>{item.id} · {item.detail}</span></div><span className={`risk ${item.risk.toLowerCase()}`}>{item.risk} risk</span><span className="confidence"><i style={{ width: `${item.confidence}%` }} />{item.confidence}%</span><button className="icon-button"><ChevronRight size={17} /></button></div>)}
        </div>
      </section>
    </>
  );
}

function Metric({ icon, label, value, change, tone }: { icon: ReactNode; label: string; value: string; change: string; tone: string }) {
  return <article className="metric-card"><div className={`metric-icon ${tone}`}>{icon}</div><div className="metric-copy"><span>{label}</span><strong>{value}</strong><small><CheckCircle2 size={13} />{change}</small></div></article>;
}

function PanelTitle({ title, subtitle, action }: { title: string; subtitle: string; action?: ReactNode }) {
  return <div className="panel-title"><div><h2>{title}</h2><p>{subtitle}</p></div>{action}</div>;
}

type SourceInventoryItem = {
  id: string;
  name: string;
  kind: string;
  sourceType: string;
  accessMode: "read_only";
  status: string;
  fields: number | null;
  records: number | null;
  bytes: number | null;
  snapshotId: string | null;
  sha256: string | null;
  mediaType: string | null;
  updatedAt: string | null;
  origin: "firebase" | "fixture";
};

type SourceKind = SourceType;

const connectorCategoryView: Record<ConnectorCategory, {
  label: string;
  detail: string;
  icon: typeof Database;
}> = {
  file: {
    label: "Files",
    detail: "Bounded uploads with immutable source evidence",
    icon: FileCheck2,
  },
  api: {
    label: "API contracts",
    detail: "Contract metadata without remote execution",
    icon: Code2,
  },
  database: {
    label: "Databases",
    detail: "Read-only catalogs, allowlists, and query limits",
    icon: Database,
  },
  "object-storage": {
    label: "Object storage",
    detail: "Federated identities and version-pinned objects",
    icon: CloudUpload,
  },
  lakehouse: {
    label: "Warehouses & lakehouses",
    detail: "Governed catalogs and bounded compute",
    icon: Layers3,
  },
};

function Sources() {
  const [inventory, setInventory] = useState<SourceInventoryItem[]>([]);
  const [inventoryMode, setInventoryMode] = useState<"loading" | "demo" | "firebase" | "unavailable">("loading");
  const [canManage, setCanManage] = useState(false);
  const [selectedType, setSelectedType] = useState<SourceKind | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [sourceIdTouched, setSourceIdTouched] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");

  const loadInventory = useCallback(async () => {
    try {
      const response = await fetch("/api/sources", { cache: "no-store" });
      const payload = await response.json() as {
        mode?: "demo" | "firebase";
        canManageSources?: boolean;
        sources?: SourceInventoryItem[];
        detail?: string;
      };
      if (!response.ok) throw new Error(payload.detail ?? "Source inventory could not be loaded.");
      setInventory(Array.isArray(payload.sources) ? payload.sources : []);
      setCanManage(payload.canManageSources === true);
      setInventoryMode(payload.mode === "firebase" ? "firebase" : "demo");
    } catch (error) {
      setInventoryMode("unavailable");
      setMessage(error instanceof Error ? error.message : "Source inventory could not be loaded.");
    }
  }, []);

  useEffect(() => {
    void loadInventory();
  }, [loadInventory]);

  function slug(value: string) {
    return value
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/gu, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/gu, "-")
      .replace(/^-+|-+$/gu, "")
      .slice(0, 64);
  }

  function openConnector(type: SourceKind) {
    if (!canManage) {
      setMessage("An administrator or steward role is required to connect sources.");
      return;
    }
    setSelectedType(type);
    setDisplayName("");
    setSourceId("");
    setSourceIdTouched(false);
    setSelectedFile(null);
    setMessage("");
  }

  async function connectSource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedType || !selectedFile) return;
    setSubmitting(true);
    setMessage("");
    try {
      const body = new FormData();
      body.set("sourceType", selectedType);
      body.set("displayName", displayName);
      body.set("sourceId", sourceId);
      body.set("file", selectedFile);
      const response = await fetch("/api/sources", { method: "POST", body });
      const payload = await response.json() as { detail?: string; source?: SourceInventoryItem };
      if (!response.ok) throw new Error(payload.detail ?? "The source could not be connected.");
      setSelectedType(null);
      setMessage("Source registered. Firebase is creating its immutable profile and evidence snapshot.");
      await loadInventory();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The source could not be connected.");
    } finally {
      setSubmitting(false);
    }
  }

  const totalBytes = inventory.reduce((total, source) => total + (source.bytes ?? 0), 0);
  const readySources = inventory.filter((source) => source.status === "READY").length;
  const selectedConnector = connectorCatalog.find((connector) => connector.id === selectedType);

  function statusView(status: string) {
    if (status === "READY") return { label: "Ready", className: "ready" };
    if (status === "UPLOAD_FAILED" || status === "FAILED") return { label: "Failed", className: "review" };
    return { label: "Profiling", className: "profiling" };
  }

  return (
    <>
      <PageHeader
        eyebrow="Evidence layer"
        title="Connected sources"
        description="Register read-only evidence, profile it serverlessly, and preserve an immutable, tenant-bound snapshot."
        actions={<button className="button primary" disabled={inventoryMode === "loading" || !canManage} onClick={() => openConnector("csv")}><Plus size={17} /> Connect source</button>}
      />
      {message && <div className="source-message" role="status">{message}</div>}
      <div className="source-summary">
        <div><Database size={20} /><span><strong>{inventoryMode === "loading" ? "—" : inventory.length}</strong> sources</span></div>
        <div><Layers3 size={20} /><span><strong>{readySources}</strong> profiled</span></div>
        <div><Fingerprint size={20} /><span><strong>{totalBytes.toLocaleString("en-US")}</strong> bytes observed</span></div>
        <div><LockKeyhole size={20} /><span><strong>Read-only</strong> enforced</span></div>
      </div>

      <section className="panel connector-catalog">
        <PanelTitle
          title="Enterprise connector catalog"
          subtitle="Active adapters are usable now. Planned adapters require read-only credentials, network policy, provenance, and an integration test before activation."
          action={<span className={`inventory-mode ${inventoryMode}`}>{inventoryMode === "firebase" ? "Live Firebase" : inventoryMode === "demo" ? "Fixture preview" : inventoryMode}</span>}
        />
        <div className="connector-groups">
          {connectorCategories.map((category) => {
            const categoryView = connectorCategoryView[category];
            const CategoryIcon = categoryView.icon;
            const connectors = connectorCatalog.filter((connector) => connector.category === category);
            return (
              <section className="connector-group" key={category}>
                <header>
                  <span><CategoryIcon size={17} /></span>
                  <div><h3>{categoryView.label}</h3><p>{categoryView.detail}</p></div>
                  <em>{connectors.length}</em>
                </header>
                <div className="connector-options">
                  {connectors.map((connector) => {
                    const active = isActiveFileConnector(connector);
                    return (
                      <button
                        className={`connector-option ${active ? "" : "roadmap"}`}
                        disabled={!active || !canManage}
                        key={connector.id}
                        onClick={() => active && openConnector(connector.id)}
                      >
                        <span><CategoryIcon size={19} /></span>
                        <strong>{connector.label}</strong>
                        <small>{connector.detail}</small>
                        <em>{active ? "Active" : "Planned"}</em>
                      </button>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
      </section>

      {inventoryMode === "loading" ? (
        <section className="source-empty"><LoaderCircle className="spin" size={22} /><h2>Loading source inventory</h2></section>
      ) : inventory.length === 0 ? (
        <section className="source-empty"><Database size={24} /><h2>No sources connected yet</h2><p>Choose an available connector. The tenant is taken from your verified session, never from the upload form.</p></section>
      ) : (
        <section className="source-grid">
          {inventory.map((source, index) => {
            const state = statusView(source.status);
            return <article className="source-card" key={source.id}>
              <div className="source-card-head"><span className={`source-icon ${["mint", "blue", "violet", "amber", "rose", "cyan"][index % 6]}`}><Database size={19} /></span><span className={`source-state ${state.className}`}><i />{state.label}</span></div>
              <h2>{source.name}</h2><p><code>{source.id}</code> · {source.kind} · {source.origin === "firebase" ? "live" : "fixture"}</p>
              <div className="source-stats">
                <span><strong>{source.fields ?? "—"}</strong> fields</span>
                <span><strong>{source.records ?? "—"}</strong> records</span>
                <span><strong>{source.sha256 ? source.sha256.slice(0, 8) : "pending"}</strong> hash</span>
              </div>
              <div className="quality-bar" aria-label={`${state.label} source profile`}><i style={{ width: state.className === "ready" ? "100%" : state.className === "review" ? "100%" : "38%" }} /></div>
              <footer><span>{source.bytes?.toLocaleString("en-US") ?? "—"} B · {source.updatedAt ? new Date(source.updatedAt).toLocaleString() : "awaiting snapshot"}</span><span className="read-only-badge"><LockKeyhole size={11} />read only</span></footer>
            </article>;
          })}
        </section>
      )}
      <section className="panel source-policy-panel">
        <div className="policy-copy"><span className="metric-icon mint"><ShieldCheck size={19} /></span><div><h2>Ingestion policy</h2><p>20 MiB maximum. UTF-8 and contract validation occur before upload; Functions create the authoritative profile and snapshot.</p></div></div>
        <div className="policy-tags"><span>Metadata first</span><span>Tenant isolated</span><span>SHA-256 evidence</span></div>
        <button className="button secondary" onClick={() => void loadInventory()}><RefreshCw size={16} />Refresh inventory</button>
      </section>

      {selectedType && selectedConnector && (
        <div className="source-dialog-backdrop" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget && !submitting) setSelectedType(null);
        }}>
          <section className="source-dialog" role="dialog" aria-modal="true" aria-labelledby="source-dialog-title">
            <header><div><span className="eyebrow">Read-only connector</span><h2 id="source-dialog-title">Connect {selectedConnector.label}</h2><p>{selectedConnector.detail}</p></div><button className="icon-button" disabled={submitting} onClick={() => setSelectedType(null)} aria-label="Close"><X size={18} /></button></header>
            <form onSubmit={connectSource}>
              <label>Source name<input required minLength={3} maxLength={80} value={displayName} onChange={(event) => {
                const value = event.target.value;
                setDisplayName(value);
                if (!sourceIdTouched) setSourceId(slug(value));
              }} placeholder="Customer master EU" /></label>
              <label>Source ID<input required pattern="[a-z][a-z0-9-]{2,63}" value={sourceId} onChange={(event) => {
                setSourceId(event.target.value.toLowerCase());
                setSourceIdTouched(true);
              }} placeholder="customer-master-eu" /><small>Stable evidence identifier; it cannot be renamed after registration.</small></label>
              <label>Source file<input required type="file" accept={selectedConnector.accept} onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)} /><small>{selectedType === "openapi" ? "OpenAPI 3.x JSON only; the platform does not call the remote API in this release." : "Maximum 20 MiB. Uploads become immutable versioned source objects."}</small></label>
              <div className="source-boundary"><LockKeyhole size={17} /><div><strong>No source writes</strong><span>The server derives your tenant and uploader identity from the verified session. No credential is accepted in this form.</span></div></div>
              <footer><button type="button" className="button secondary" disabled={submitting} onClick={() => setSelectedType(null)}>Cancel</button><button type="submit" className="button primary" disabled={submitting || !selectedFile}>{submitting ? <LoaderCircle className="spin" size={17} /> : <CloudUpload size={17} />}{submitting ? "Registering…" : "Register & profile"}</button></footer>
            </form>
          </section>
        </div>
      )}
    </>
  );
}

function SemanticModel() {
  const [selected, setSelected] = useState("Beneficial owner");
  const selectedNode = concepts.find((concept) => concept.label === selected) ?? concepts[0];
  return (
    <>
      <PageHeader eyebrow="Ontology factory" title="Semantic model" description="Core concepts, the KYC/AML domain pack, and Demo Bank's governed overlay." actions={<><button className="button secondary"><Code2 size={17} /> View Turtle</button><button className="button primary"><Plus size={17} /> Propose concept</button></>} />
      <div className="model-toolbar"><label><SearchCheck size={16} /><input placeholder="Find a concept, synonym, or IRI…" /></label><div className="legend"><span><i className="core" />Core</span><span><i className="domain" />Domain pack</span><span><i className="overlay" />Company overlay</span></div><span className="version-chip">2026.07.1 · candidate</span></div>
      <div className="model-layout">
        <section className="panel graph-panel">
          <svg className="graph-lines" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
            <path d="M49 13 L28 32 M49 13 L70 32 M28 32 L15 57 M70 32 L44 57 M70 32 L80 58 M15 57 L26 82 M44 57 L26 82 M44 57 L58 82 M80 58 L87 84 M58 82 L87 84" />
          </svg>
          {concepts.map((concept) => <button key={concept.label} onClick={() => setSelected(concept.label)} className={`concept-node ${concept.kind} ${selected === concept.label ? "selected" : ""}`} style={{ left: `${concept.x}%`, top: `${concept.y}%` }}><span>{concept.label}</span><small>{concept.kind === "core" ? "Core" : concept.kind === "domain" ? "KYC pack" : "Overlay"}</small></button>)}
          <div className="graph-zoom"><button>−</button><span>100%</span><button>+</button></div>
        </section>
        <aside className="panel inspector-panel">
          <div className="inspector-head"><span className={`concept-symbol ${selectedNode?.kind}`}><Network size={19} /></span><button className="icon-button"><X size={17} /></button></div>
          <span className="eyebrow">Class</span><h2>{selectedNode?.label}</h2><code>oa:BeneficialOwner</code>
          <p className="definition">A party that ultimately owns or controls a legal entity, directly or indirectly, under the applicable KYC policy.</p>
          <dl className="properties"><div><dt>Aligned to</dt><dd>fibo-fnd-pty-pty:PartyInRole</dd></div><div><dt>Preferred label</dt><dd>Beneficial owner</dd></div><div><dt>Alternate labels</dt><dd>UBO · ultimate owner</dd></div><div><dt>Evidence</dt><dd>5 references</dd></div></dl>
          <div className="relation-block"><h3>Relations</h3><div><span>beneficialOwnerOf</span><ArrowRight size={14} /><strong>Legal entity</strong></div><div><span>controls</span><ArrowRight size={14} /><strong>Account</strong></div></div>
          <button className="button secondary full"><Eye size={16} /> Open full record</button>
        </aside>
      </div>
    </>
  );
}

function Proposals() {
  const [proposals, setProposals] = useState(initialProposals);
  const [selectedId, setSelectedId] = useState(initialProposals[0]?.id ?? "");
  const [rationale, setRationale] = useState("");
  const [reviewMode, setReviewMode] = useState<ReviewQueueMode>("loading");
  const [reviewMessage, setReviewMessage] = useState("");
  const [pendingCount, setPendingCount] = useState(100);
  const [abstainedCount, setAbstainedCount] = useState(1);
  const [receiptCount, setReceiptCount] = useState(0);
  const [canRecordReview, setCanRecordReview] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const selected = proposals.find((proposal) => proposal.id === selectedId);

  useEffect(() => {
    let active = true;
    void fetch("/api/reviews", { cache: "no-store" })
      .then(async (response) => {
        const payload = await response.json() as ReviewQueuePayload;
        if (!response.ok) throw new Error("review-queue-unavailable");
        if (!active) return;
        const queue = resolveReviewQueue(payload, initialProposals);
        setProposals(queue.proposals);
        setSelectedId(queue.selectedId);
        setPendingCount(queue.pendingCount);
        setAbstainedCount(queue.abstainedCount);
        setReceiptCount(queue.receiptCount);
        setCanRecordReview(queue.canRecordReview);
        setReviewMode(queue.mode);
        setReviewMessage(queue.message);
      })
      .catch(() => {
        if (!active) return;
        setCanRecordReview(false);
        setReviewMode("unavailable");
        setReviewMessage("The governed review queue is currently unavailable.");
      });
    return () => { active = false; };
  }, []);

  async function decide(id: string, decision: "APPROVED" | "REVIEW_REQUIRED" | "ABSTAINED") {
    if (reviewMode !== "firebase" || !canRecordReview) {
      setReviewMessage("A verified steward role is required to create a reviewer receipt.");
      return;
    }
    if (rationale.trim().length < 10) {
      setReviewMessage("Add a rationale of at least 10 characters before recording the decision.");
      return;
    }
    setSubmitting(true);
    setReviewMessage("");
    try {
      const response = await fetch(`/api/reviews/${encodeURIComponent(id)}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ decision, rationale, requestId: crypto.randomUUID() }),
      });
      const payload = await response.json() as { detail?: string; idempotent?: boolean; receiptId?: string };
      if (!response.ok) throw new Error(payload.detail ?? "The review decision was rejected.");
      const status: ProposalView["status"] = decision === "APPROVED"
        ? "Approved"
        : decision === "ABSTAINED"
          ? "Abstained"
          : "Human review";
      setProposals((items) => items.map((item) => item.id === id ? { ...item, status, reviewed: true, reviewDecision: decision } : item));
      if (!payload.idempotent) {
        setReceiptCount((count) => count + 1);
        if (decision === "ABSTAINED" || decision === "APPROVED") {
          setPendingCount((count) => Math.max(0, count - 1));
          if (decision === "ABSTAINED") setAbstainedCount((count) => count + 1);
        }
      }
      setRationale("");
      setReviewMessage(`Content-bound receipt ${payload.receiptId ?? "recorded"} created.`);
    } catch (error) {
      setReviewMessage(error instanceof Error ? error.message : "The review decision could not be recorded.");
    } finally {
      setSubmitting(false);
    }
  }

  const confidenceVector = selected?.confidenceVector ?? [];
  const gateSummary = selected?.gates ?? [];
  return (
    <>
      <PageHeader eyebrow="Verification fabric" title="Review queue" description="Atomic proposals are routed by evidence, deterministic gates, model agreement, and risk." actions={<button className="button secondary"><ShieldCheck size={17} /> Policy matrix</button>} />
      <div className="review-stats"><div><span className="metric-icon amber"><Clock3 size={18} /></span><p><strong>{pendingCount}</strong> require review</p></div><div><span className="metric-icon mint"><PackageCheck size={18} /></span><p><strong>0</strong> published</p></div><div><span className="metric-icon rose"><ShieldAlert size={18} /></span><p><strong>{abstainedCount}</strong> abstained</p></div><div><span className="metric-icon blue"><UserCheck size={18} /></span><p><strong>{receiptCount}</strong> reviewer receipts</p></div></div>
      <div className="review-layout">
        <section className="panel review-list-panel">
          <div className="table-filter"><div><button className="active">Representative <em>5</em></button><button>Pilot population <em>100</em></button></div><label><SearchCheck size={15} /><input placeholder="Filter proposals…" /></label></div>
          <div className="proposal-list">
            {proposals.map((proposal) => <button key={proposal.id} onClick={() => setSelectedId(proposal.id)} className={`proposal-item ${selectedId === proposal.id ? "selected" : ""}`}><span className={`kind-icon ${proposal.kind.toLowerCase()}`}><GitCommitHorizontal size={16} /></span><div><span className="proposal-meta">{proposal.id} · {proposal.kind}</span><strong>{proposal.title}</strong><small>{proposal.detail}</small></div><aside><span className={`risk ${proposal.risk.toLowerCase()}`}>{proposal.risk}</span><em>{proposal.confidence}%</em></aside></button>)}
          </div>
        </section>
        {selected && <aside className="panel review-detail">
          <div className="review-detail-head"><div><span className="proposal-meta">{selected.id} · {selected.kind}</span><h2>{selected.title}</h2></div><span className={`risk ${selected.risk.toLowerCase()}`}>{selected.risk} risk</span></div>
          <p className="review-description">Source: <code>{selected.detail}</code>. Target: <code>{selected.targetIri ?? "not recorded"}</code>{selected.reasonCodes?.length ? ` · Reasons: ${selected.reasonCodes.join(", ")}` : ""}.</p>
          <div className="confidence-vector"><h3>Confidence vector <strong>{selected.confidence}% evidence coverage</strong></h3>{confidenceVector.length ? confidenceVector.map(({ label, value }) => <div key={label}><span>{label}</span><i className={label === "Model" && value === 0 ? "unavailable" : undefined}><b style={{ width: `${value}%` }} /></i><em>{label === "Model" && value === 0 ? "n/a" : `${value}%`}</em></div>) : <p className="empty-verification">No confidence vector was recorded.</p>}</div>
          <div className="gate-summary"><h3>Verification gates</h3><div className="gate-grid">{gateSummary.length ? gateSummary.map((gate) => {
            const className = `gate-${gate.status.toLowerCase().replace("_", "-")}`;
            const Icon = gate.status === "PASSED" ? CheckCircle2 : gate.status === "FAILED" ? X : gate.status === "SKIPPED" ? Clock3 : UserCheck;
            return <span className={className} key={gate.name} title={gate.status}><Icon size={14} />{gate.name.replaceAll("_", " ")}</span>;
          }) : <span className="gate-skipped"><Clock3 size={14} />No gate results recorded</span>}</div></div>
          <div className="mock-warning"><ShieldAlert size={18} /><p>{selected.approvalEligible ? <><strong>Independent verification is complete.</strong> The bound risk policy permits an authorized steward to approve.</> : <><strong>Approval is unavailable.</strong> The {selected.verifierMode ?? "unknown"} verifier run does not satisfy every fail-closed approval gate.</>}</p></div>
          <label className="review-rationale"><span>Reviewer rationale</span><textarea value={rationale} onChange={(event) => setRationale(event.target.value)} disabled={!canRecordReview || selected.status !== "Human review" || selected.reviewed} maxLength={1_000} placeholder="Explain the evidence and policy basis for this decision…" /></label>
          {selected.reviewed && <p className="review-feedback">A content-bound {selected.reviewDecision === "APPROVED" ? "approval" : selected.reviewDecision === "ABSTAINED" ? "abstention" : "review-required"} receipt already exists for this proposal.</p>}
          {reviewMessage && <p className="review-feedback" role="status">{reviewMessage}</p>}
          <div className="review-actions"><button className="button danger" disabled={submitting || reviewMode !== "firebase" || !canRecordReview || selected.status !== "Human review" || selected.reviewed} onClick={() => void decide(selected.id, "ABSTAINED")}><X size={16} /> Record abstention</button><button className="button secondary" disabled={submitting || reviewMode !== "firebase" || !canRecordReview || selected.status !== "Human review" || selected.reviewed} onClick={() => void decide(selected.id, "REVIEW_REQUIRED")}><ShieldAlert size={16} /> Keep in review</button>{selected.approvalEligible && <button className="button primary" disabled={submitting || reviewMode !== "firebase" || !canRecordReview || selected.status !== "Human review" || selected.reviewed} onClick={() => void decide(selected.id, "APPROVED")}><Check size={16} /> Approve proposal</button>}</div>
        </aside>}
      </div>
    </>
  );
}

function Versions() {
  const [publishing, setPublishing] = useState(false);
  return (
    <>
      <PageHeader eyebrow="Immutable registry" title="Ontology versions" description="Reproducible bundles of ontology, shapes, mappings, provenance, and policy." actions={<button className="button primary" onClick={() => setPublishing(true)}><PackageCheck size={17} /> {publishing ? "Candidate queued" : "Prepare release"}</button>} />
      <section className="active-version-card"><div className="version-art"><PackageCheck size={28} /></div><div className="version-title"><span><i />Candidate bundle · demo only</span><h2>2026.07.1</h2><p>Publication is blocked: all 100 mappings remain in HUMAN_REVIEW.</p></div><div className="artifact-hash"><span>Integrity</span><code>manifest hashes verified</code></div><div className="version-meta"><span>State</span><strong>CANDIDATE</strong><small>no publisher receipt</small></div></section>
      <div className="version-layout">
        <section className="panel release-history"><PanelTitle title="Candidate history" subtitle="No active production release exists" /><div className="timeline">
          {[
            ["2026.07.1", "Candidate", "KYC/AML synthetic pilot", "44 concepts · 23 relations · 100 mappings", "22 Jul 2026"],
          ].map(([version, state, title, delta, date]) => <article key={version}><span className={`timeline-dot ${state === "Active" ? "active" : ""}`} /><div className="release-version"><strong>{version}</strong><span className={state === "Active" ? "active" : ""}>{state}</span></div><div className="release-copy"><h3>{title}</h3><p>{delta}</p></div><time>{date}</time><button className="icon-button"><ChevronRight size={17} /></button></article>)}
        </div></section>
        <aside className="panel bundle-panel"><PanelTitle title="Candidate bundle" subtitle="semantic/artifacts" /><div className="bundle-files">{[["ontology.ttl", "12.0 KB"], ["shapes.ttl", "6.4 KB"], ["mappings.ttl", "129.1 KB"], ["provenance.nq", "74.4 KB"], ["manifest.json", "2.5 KB"]].map(([file, size]) => <div key={file}><FileCheck2 size={16} /><code>{file}</code><span>{size}</span><CheckCircle2 size={14} /></div>)}</div><div className="bundle-check"><ShieldCheck size={19} /><div><strong>Integrity verified</strong><span>All hashes match; governance still blocks publication.</span></div></div><button className="button secondary full"><CloudUpload size={16} /> Export candidate</button></aside>
      </div>
    </>
  );
}

type GatewayResult = { status?: string; ontologyVersion?: string; publicationState?: string; traceId?: string; data?: unknown; detail?: string; [key: string]: unknown };
const gatewayOperations = [["query", "Query"], ["resolve", "Resolve"], ["context", "Context"]] as const;

function GatewayPlayground() {
  const [operation, setOperation] = useState("query");
  const [input, setInput] = useState(competencyQuestions[0]?.question ?? "");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<GatewayResult | null>(null);
  const body = useMemo(() => operation === "resolve" ? { term: input } : operation === "context" ? { term: input } : { question: input }, [input, operation]);
  async function submit(event: FormEvent) {
    event.preventDefault(); setLoading(true); setResult(null);
    try {
      const response = await fetch(`/api/gateway/${operation}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
      setResult(await response.json() as GatewayResult);
    } catch (error) { setResult({ status: "ERROR", detail: error instanceof Error ? error.message : "Request failed" }); }
    finally { setLoading(false); }
  }
  return (
    <>
      <PageHeader eyebrow="Semantic runtime" title="Gateway playground" description="Resolve terms and ask evidence-backed questions against the explicitly labeled candidate graph." actions={<span className="api-status"><i /> Read-only API · candidate</span>} />
      <div className="playground-layout">
        <section className="panel request-builder"><div className="operation-tabs">{gatewayOperations.map(([value, label]) => <button key={value} className={operation === value ? "active" : ""} onClick={() => setOperation(value)}>{label}</button>)}</div><form onSubmit={submit}><label htmlFor="gateway-input">{operation === "resolve" ? "Business term" : operation === "context" ? "Agent intent" : "Governed question"}</label><textarea id="gateway-input" rows={5} value={input} onChange={(event) => setInput(event.target.value)} /><div className="request-meta"><span><LockKeyhole size={14} /> tenant: demo-bank</span><span><Box size={14} /> ontology: candidate / demo only</span></div><button className="button primary" disabled={loading}>{loading ? <LoaderCircle className="spin" size={17} /> : <Send size={17} />} Run {operation}</button></form><div className="sample-questions"><h3>Golden questions</h3>{competencyQuestions.slice(0, 3).map((question) => <button key={question.id} onClick={() => { setOperation("query"); setInput(question.question); }}><span>{question.id}</span>{question.short}<ChevronRight size={14} /></button>)}</div></section>
        <section className="panel response-viewer"><div className="response-head"><div><span className={`response-dot ${result?.status === "ERROR" ? "error" : ""}`} /><strong>{result ? result.status ?? "Response" : "Awaiting request"}</strong></div>{result?.ontologyVersion && <code>{result.ontologyVersion}</code>}</div>{result ? <><div className="response-summary">{result.detail ? <p>{result.detail}</p> : <pre>{JSON.stringify(result.data, null, 2)}</pre>}</div><div className="response-provenance"><div><Fingerprint size={16} /><span><strong>Trace</strong><code>{result.traceId ?? "not emitted"}</code></span></div><div><ShieldCheck size={16} /><span><strong>Policy</strong><small>Read-only · evidence required</small></span></div></div></> : <div className="response-empty"><Braces size={38} /><h3>Evidence will appear here</h3><p>Run a golden question; the BFF selects the local or private cloud gateway.</p></div>}</section>
      </div>
    </>
  );
}

function Traces() {
  return (
    <>
      <PageHeader eyebrow="Observability" title="Trace & audit" description="Every answer and decision can be replayed from its inputs, artifacts, policy, and model metadata." actions={<><button className="button secondary"><RefreshCw size={16} /> Refresh</button><button className="button primary"><CloudUpload size={16} /> Export evidence</button></>} />
      <section className="trace-overview"><div><Activity size={19} /><p><strong>5</strong><span>synthetic trace fixtures</span></p></div><div><Clock3 size={19} /><p><strong>n/a</strong><span>no cloud latency yet</span></p></div><div><ShieldCheck size={19} /><p><strong>100%</strong><span>fixture trace IDs</span></p></div><div><AlertTriangle size={19} /><p><strong>0</strong><span>publication receipts</span></p></div></section>
      <section className="panel trace-panel"><div className="trace-filter"><div className="filter-pills"><button className="active">All events</button><button>Queries</button><button>Verification</button><button>Publication</button></div><label><SearchCheck size={15} /><input placeholder="Trace ID, actor, version…" /></label></div><div className="data-table"><div className="data-row header"><span>Trace</span><span>Action</span><span>Actor</span><span>Version</span><span>Duration</span><span>Status</span><span>Time</span><span /></div>{traceRows.map((row) => <div className="data-row" key={row.id}><code>{row.id}</code><strong>{row.action}</strong><span>{row.actor}</span><code>{row.version}</code><span>{row.duration}</span><em className={`trace-status ${row.status.toLowerCase()}`}>{row.status}</em><time>{row.time}</time><button className="icon-button"><ChevronRight size={15} /></button></div>)}</div></section>
      <section className="audit-note"><Fingerprint size={20} /><div><strong>Synthetic audit preview</strong><p>Cloud Logging begins after dev deployment. This local table is fixture data and does not claim operational events.</p></div></section>
    </>
  );
}

function SettingsPage() {
  return (
    <>
      <PageHeader eyebrow="Tenant controls" title="Settings" description="Security, model routing, publication policy, industry packs, and budget guardrails for Demo Bank EU." actions={<span className="version-chip"><ShieldCheck size={13} /> Governed policy</span>} />
      <div className="settings-layout">
        <section className="panel settings-panel"><PanelTitle title="Identity & tenancy" subtitle="Server-side authorization is always rechecked" /><SettingRow icon={<Users size={18} />} title="Pilot tenant" detail="demo-bank · Europe West 4"><span className="setting-value">Single pilot</span></SettingRow><SettingRow icon={<KeyRound size={18} />} title="Authentication" detail="Passwordless email and Google via Firebase Auth"><span className="state-good"><CheckCircle2 size={14} /> Firebase enabled</span></SettingRow><SettingRow icon={<ShieldCheck size={18} />} title="Workspace roles" detail="Admin, steward, and auditor"><button className="text-button">Manage roles</button></SettingRow></section>
        <section className="panel settings-panel"><PanelTitle title="Model routing" subtitle="Deterministic Functions workflow active; model adapters remain disabled" /><SettingRow icon={<WandSparkles size={18} />} title="Proposal generator adapter" detail="Vertex AI · not invoked"><span className="state-warning"><TriangleAlert size={14} /> Disabled</span></SettingRow><SettingRow icon={<SearchCheck size={18} />} title="Independent verifier" detail="No OpenAI credential configured"><span className="state-warning"><TriangleAlert size={14} /> Deterministic mock</span></SettingRow><div className="settings-callout"><ShieldAlert size={18} /><p>No model API is called in this pilot mode. Mock verification never claims independent model agreement; model-dependent or high-risk proposals are routed to a person or abstain.</p></div></section>
        <section className="panel settings-panel"><PanelTitle title="Publication policy" subtitle="Only the Publisher identity writes an active version" /><SettingRow icon={<Workflow size={18} />} title="Low-risk threshold" detail="All deterministic gates must pass"><span className="setting-value">≥ 0.95</span></SettingRow><SettingRow icon={<UserCheck size={18} />} title="High-risk changes" detail="Relations, merges, regulatory semantics"><span className="state-warning">Always human</span></SettingRow><SettingRow icon={<PackageCheck size={18} />} title="Rollback" detail="Last valid immutable bundle"><span className="state-good"><CheckCircle2 size={14} /> Enabled</span></SettingRow></section>
        <section className="panel settings-panel"><PanelTitle title="Dev budget guardrails" subtitle="Terraform definition; no billing data before deployment" /><div className="budget-meter"><div><span>Cloud spend</span><strong>Not connected <small>/ €50 alert policy</small></strong></div><i><b style={{ width: "0%" }} /></i><div className="budget-thresholds"><span>50%</span><span>80%</span><span>100%</span></div></div><SettingRow icon={<ServerCog size={18} />} title="Serverless limits" detail="Scale to zero; bounded workers"><span className="state-good"><CheckCircle2 size={14} /> Defined</span></SettingRow></section>
      </div>
      <section className="panel industry-pack-panel">
        <PanelTitle title="Industry semantic packs" subtitle="Only a versioned, tested, independently verified RDF/SHACL bundle may become active." action={<span className="setting-value">1 active · {industryPacks.length - 1} planned</span>} />
        <div className="industry-pack-grid">
          {industryPacks.map((pack) => (
            <article className={`industry-pack ${pack.availability}`} key={pack.id}>
              <header><span>{pack.availability === "active" ? <CheckCircle2 size={16} /> : <Clock3 size={16} />}</span><em>{pack.availability === "active" ? "Active pilot" : "Planned"}</em></header>
              <h3>{pack.label}</h3>
              <p>{pack.detail}</p>
              <div>{pack.coreConcepts.slice(0, 4).map((concept) => <span key={concept}>{concept}</span>)}</div>
              <footer>{pack.availability === "active" ? "Candidate · demo only" : "RDF + SHACL + competency questions required"}</footer>
            </article>
          ))}
        </div>
      </section>
    </>
  );
}

function SettingRow({ icon, title, detail, children }: { icon: ReactNode; title: string; detail: string; children: ReactNode }) {
  return <div className="setting-row"><span className="setting-icon">{icon}</span><div><strong>{title}</strong><span>{detail}</span></div><aside>{children}</aside></div>;
}
