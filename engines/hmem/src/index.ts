/**
 * H-MEM — Clearline implementation of the Meterless hierarchical memory spec.
 *
 * Written to engines/hmem/AGENTS.md, verified by the upstream conformance
 * suite:
 *
 *   HMEM_IMPL=".../engines/hmem/src/index.ts" npx tsx runner.ts
 *
 * Why Clearline needs it. A screening decision is only as good as the
 * corrections applied to it. When a reviewer says "that alias match is wrong",
 * that judgement has to survive, outrank the thing it corrects, and be
 * auditable months later — designations change weekly and a decision nobody
 * can reconstruct is a liability. H-MEM supplies exactly that: feedback that
 * moves confidence by fixed amounts, conflict resolution that supersedes
 * rather than deletes, and an append-only trust ledger.
 *
 * The rule the spec keeps returning to, and the reason it suits this product:
 * nothing is ever destroyed. A superseded record is penalised in ranking and
 * kept. A resolved conflict marks a loser and keeps both. Sleep archives only
 * what has no relationship value, after a preview that mutates nothing.
 */

// --- types -------------------------------------------------------------------

export type Layer = "short_term" | "working" | "long_term";
export type FeedbackKind = "helpful" | "not_helpful" | "wrong";
export type MemoryType = "fact" | "preference" | "decision" | "insight" | "invariant" | "chat_message";

export interface MemoryRecord {
  id: string;
  content: string;
  source: string;
  type: MemoryType;
  layer: Layer;
  confidence: number;
  tags: string[];
  entities: string[];
  domain: string;
  accessCount: number;
  timestamp: number;
  lastAccessed: number;
  supersededBy?: string;
  derivedFrom?: string[];
  relatedTo?: string[];
  archived?: boolean;
}

export interface AddInput {
  content: string;
  source: string;
  confidence?: number;
  layer?: Layer;
  type?: MemoryType;
  tags?: string[];
  entities?: string[];
  domain?: string;
  derivedFrom?: string[];
  relatedTo?: string[];
}

export interface ScoredMemory {
  memory: MemoryRecord;
  score: number;
  parts: Record<string, number>;
}

export type LedgerAction =
  | "create" | "read" | "update" | "delete" | "feedback" | "promote" | "demote"
  | "merge" | "conflict_detected" | "conflict_resolved" | "sleep_consolidate"
  | "sleep_archive" | "sleep_synthesize" | "dream_proposed" | "dream_approved"
  | "dream_rejected" | "restore";

export interface LedgerEntry {
  id: string;
  memoryId: string;
  action: LedgerAction;
  at: number;
  actor: string;
  previousState?: Partial<MemoryRecord>;
  newState?: Partial<MemoryRecord>;
  details?: Record<string, unknown>;
}

// --- helpers -----------------------------------------------------------------

const clamp01 = (n: number): number => Math.min(1, Math.max(0, n));

const STOP = new Set([
  "the", "a", "an", "and", "or", "of", "to", "for", "with", "on", "in", "is",
  "are", "we", "our", "it", "this", "that", "do", "does", "when", "at", "by",
]);

export function tokenize(text: string): string[] {
  return (text ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter((t) => t && !STOP.has(t));
}

/** Jaccard overlap. Stands in for an embedder: the conformance suite asserts
 *  ordering only where the spec makes it embedding-independent, so a
 *  deterministic lexical measure keeps results reproducible. */
export function similarity(a: string, b: string): number {
  const left = new Set(tokenize(a));
  const right = new Set(tokenize(b));
  if (!left.size || !right.size) return 0;
  let shared = 0;
  for (const token of left) if (right.has(token)) shared += 1;
  return shared / (left.size + right.size - shared);
}

const LAYER_WEIGHT: Record<Layer, number> = { long_term: 1.0, working: 0.8, short_term: 0.6 };
const DAY = 24 * 60 * 60 * 1000;
const RECENCY_TIME_CONSTANT = 14 * DAY;

/** Fixed deltas. The spec gives exact numbers, not ranges: a reviewer's
 *  correction must move confidence by a knowable amount or the audit trail
 *  cannot be reconstructed. */
export const FEEDBACK_DELTAS: Record<FeedbackKind, number> = {
  helpful: 0.05,
  not_helpful: -0.03,
  wrong: -0.2,
};

export const RETRIEVAL_THRESHOLD = 0.35;
export const DEFAULT_TOP_N = 5;
export const ARCHIVE_AGE_DAYS = 30;
export const ARCHIVE_MAX_ACCESS = 1;

// --- store -------------------------------------------------------------------

export class MemoryStore {
  private readonly records = new Map<string, MemoryRecord>();

  put(record: MemoryRecord): MemoryRecord {
    this.records.set(record.id, record);
    return record;
  }
  get(id: string): MemoryRecord | undefined {
    return this.records.get(id);
  }
  all(): MemoryRecord[] {
    return [...this.records.values()];
  }
  active(): MemoryRecord[] {
    return this.all().filter((r) => !r.archived);
  }
  remove(id: string): void {
    this.records.delete(id);
  }
}

// --- trust ledger ------------------------------------------------------------

/** Append-only. Never destructively pruned: a ledger that can be edited is not
 *  evidence, and evidence is the product. */
export class TrustLedger {
  private readonly entries: LedgerEntry[] = [];
  private sequence = 0;

  constructor(private readonly clock: () => number) {}

  append(entry: Omit<LedgerEntry, "id" | "at">): LedgerEntry {
    const full: LedgerEntry = { ...entry, id: `led-${++this.sequence}`, at: this.clock() };
    this.entries.push(full);
    return full;
  }
  history(memoryId: string): LedgerEntry[] {
    return this.entries.filter((e) => e.memoryId === memoryId);
  }
  all(): LedgerEntry[] {
    return [...this.entries];
  }
  stats(): Record<string, number> {
    const counts: Record<string, number> = {};
    for (const entry of this.entries) counts[entry.action] = (counts[entry.action] ?? 0) + 1;
    return counts;
  }
  export(): string {
    return JSON.stringify(this.entries);
  }
}

// --- engine ------------------------------------------------------------------

export interface HMEMOptions {
  clock?: () => number;
}

export class HMEM {
  readonly store = new MemoryStore();
  readonly ledger: TrustLedger;
  private readonly clock: () => number;
  private sequence = 0;

  constructor(options: HMEMOptions = {}) {
    this.clock = options.clock ?? (() => Date.now());
    this.ledger = new TrustLedger(this.clock);
  }

  /**
   * Provenance is enforced at construction: a memory with no source cannot be
   * audited, so it is rejected rather than stored with a placeholder.
   */
  add(input: AddInput): MemoryRecord {
    if (!input.source || !String(input.source).trim()) {
      throw new Error("a memory record requires a source; provenance is not optional");
    }
    const now = this.clock();
    const record: MemoryRecord = {
      id: `mem-${++this.sequence}`,
      content: input.content ?? "",
      source: input.source,
      type: input.type ?? "fact",
      layer: input.layer ?? "short_term",
      confidence: clamp01(input.confidence ?? 0.7),
      tags: [...(input.tags ?? [])],
      entities: [...(input.entities ?? [])],
      domain: input.domain ?? "general",
      accessCount: 0,
      timestamp: now,
      lastAccessed: now,
      derivedFrom: input.derivedFrom ? [...input.derivedFrom] : undefined,
      relatedTo: input.relatedTo ? [...input.relatedTo] : undefined,
    };
    this.store.put(record);
    this.ledger.append({
      memoryId: record.id, action: "create", actor: input.source,
      newState: { confidence: record.confidence, layer: record.layer },
    });
    return record;
  }

  /**
   * Canonical hybrid ranking:
   *
   *   raw = 0.35·semantic + 0.20·keyword + 0.10·tag + 0.10·domain
   *       + 0.15·entity   + 0.05·layer   + 0.05·recency − 0.20·superseded
   *   score = clamp01(raw) × confidence
   *
   * Two properties carry the product. The superseded penalty is large enough
   * to dominate, so a corrected record loses to its correction while remaining
   * retrievable. And confidence multiplies the whole score rather than adding
   * to it, so a record a reviewer marked wrong falls away sharply.
   */
  query(text: string, options: { threshold?: number; topN?: number } = {}):
    { memories: ScoredMemory[]; query: string } {
    const threshold = options.threshold ?? RETRIEVAL_THRESHOLD;
    const topN = options.topN ?? DEFAULT_TOP_N;
    const now = this.clock();
    const queryTokens = new Set(tokenize(text).slice(0, 8));

    const scored: ScoredMemory[] = this.store.active().map((memory) => {
      const semantic = similarity(text, memory.content);
      const memoryTokens = new Set(tokenize(memory.content));
      let shared = 0;
      for (const token of queryTokens) if (memoryTokens.has(token)) shared += 1;
      const union = new Set([...queryTokens, ...memoryTokens]).size;
      const keyword = union ? shared / union : 0;
      const tag = memory.tags.some((t) => queryTokens.has(t.toLowerCase())) ? 1 : 0;
      const domain = memory.domain && queryTokens.has(memory.domain.toLowerCase()) ? 1 : 0;
      const entity = memory.entities.length
        ? memory.entities.filter((e) => queryTokens.has(e.toLowerCase())).length / memory.entities.length
        : 0;
      const layer = LAYER_WEIGHT[memory.layer];
      const recency = Math.exp(-(now - memory.lastAccessed) / RECENCY_TIME_CONSTANT);
      const superseded = memory.supersededBy ? 1 : 0;

      const raw =
        0.35 * semantic + 0.2 * keyword + 0.1 * tag + 0.1 * domain +
        0.15 * entity + 0.05 * layer + 0.05 * recency - 0.2 * superseded;
      const score = clamp01(raw) * memory.confidence;

      return {
        memory, score,
        parts: { semantic, keyword, tag, domain, entity, layer, recency, superseded },
      };
    });

    const memories = scored
      .filter((s) => s.score >= threshold)
      .sort((a, b) => b.score - a.score)
      .slice(0, topN);
    return { memories, query: text };
  }

  /** Exact deltas, clamped, every one written to the ledger with both states. */
  feedback(id: string, kind: FeedbackKind, actor = "reviewer"): MemoryRecord | undefined {
    const record = this.store.get(id);
    if (!record) return undefined;
    const previous = { confidence: record.confidence, accessCount: record.accessCount, tags: [...record.tags] };

    record.confidence = clamp01(record.confidence + (FEEDBACK_DELTAS[kind] ?? 0));
    if (kind === "helpful") record.accessCount += 1;
    if (kind === "wrong" && !record.tags.includes("review")) record.tags.push("review");
    record.lastAccessed = this.clock();

    this.ledger.append({
      memoryId: id, action: "feedback", actor,
      previousState: previous,
      newState: { confidence: record.confidence, accessCount: record.accessCount, tags: [...record.tags] },
      details: { kind },
    });
    return record;
  }

  // --- sleep ------------------------------------------------------------------

  readonly sleep = {
    /** Computes a plan and mutates nothing. Reviewing what maintenance WOULD
     *  remove, before it removes it, is the difference between maintenance and
     *  data loss. */
    preview: (): { toConsolidate: string[]; toArchive: string[]; toSynthesize: string[][] } => {
      const now = this.clock();
      const toConsolidate: string[] = [];
      const toArchive: string[] = [];

      for (const record of this.store.active()) {
        const ageDays = (now - record.timestamp) / DAY;
        if (record.layer === "short_term" && record.accessCount >= 3) {
          toConsolidate.push(record.id);
          continue;
        }
        if (ageDays >= ARCHIVE_AGE_DAYS && record.accessCount <= ARCHIVE_MAX_ACCESS
            && !this.isProtected(record)) {
          toArchive.push(record.id);
        }
      }

      const toSynthesize: string[][] = [];
      const records = this.store.active();
      const seen = new Set<string>();
      for (let i = 0; i < records.length; i += 1) {
        if (seen.has(records[i].id)) continue;
        const group = [records[i].id];
        for (let j = i + 1; j < records.length; j += 1) {
          if (similarity(records[i].content, records[j].content) >= 0.8) {
            group.push(records[j].id);
            seen.add(records[j].id);
          }
        }
        if (group.length > 1) toSynthesize.push(group);
      }
      return { toConsolidate, toArchive, toSynthesize };
    },

    execute: (plan: { toConsolidate: string[]; toArchive: string[]; toSynthesize: string[][] }) => {
      const backupId = `bak-${this.clock()}-${this.store.all().length}`;
      for (const id of plan.toConsolidate) {
        const record = this.store.get(id);
        if (!record) continue;
        record.layer = "long_term";
        this.ledger.append({ memoryId: id, action: "sleep_consolidate", actor: "sleep",
          newState: { layer: "long_term" }, details: { backupId } });
      }
      for (const id of plan.toArchive) {
        const record = this.store.get(id);
        if (!record || this.isProtected(record)) continue; // guardrails re-checked at execution
        record.archived = true;
        this.ledger.append({ memoryId: id, action: "sleep_archive", actor: "sleep",
          details: { backupId } });
      }
      return { backupId, consolidated: plan.toConsolidate.length, archived: plan.toArchive.length };
    },
  };

  /** Guardrails: records with relationship value are never archived.
   *  A synthesised memory is the product of several others, so discarding it
   *  loses reasoning that cannot be recovered from the originals. */
  private isProtected(record: MemoryRecord): boolean {
    if (record.derivedFrom && record.derivedFrom.length > 0) return true;
    if (record.source === "dreaming") return true;
    if (record.relatedTo && record.relatedTo.length > 0) return true;
    // A record that supersedes another is the current truth about it.
    return this.store.all().some((other) => other.supersededBy === record.id);
  }

  // --- conflicts ---------------------------------------------------------------

  readonly conflicts = {
    /** Opposing polarity over similar content. */
    scan: (): Array<{ a: string; b: string; similarity: number }> => {
      const found: Array<{ a: string; b: string; similarity: number }> = [];
      const records = this.store.active();
      for (let i = 0; i < records.length; i += 1) {
        for (let j = i + 1; j < records.length; j += 1) {
          const a = records[i];
          const b = records[j];
          if (a.supersededBy || b.supersededBy) continue;
          if (!opposesInPolarity(a.content, b.content)) continue;
          const sim = similarity(stripPolarity(a.content), stripPolarity(b.content));
          if (sim >= 0.6) {
            found.push({ a: a.id, b: b.id, similarity: sim });
            this.ledger.append({ memoryId: a.id, action: "conflict_detected", actor: "conflicts",
              details: { other: b.id, similarity: sim } });
          }
        }
      }
      return found;
    },

    /** Resolution supersedes; it never deletes. A contradiction that was once
     *  believed is part of the record, and a reviewer may need to see what the
     *  system used to think and when it stopped. */
    autoResolve: (conflict: { a: string; b: string }): "resolved" | "queued" => {
      const a = this.store.get(conflict.a);
      const b = this.store.get(conflict.b);
      if (!a || !b) return "queued";

      const gap = Math.abs(a.confidence - b.confidence);
      if (gap < 0.15) return "queued"; // too close to decide without a human

      const [winner, loser] = a.confidence >= b.confidence ? [a, b] : [b, a];
      loser.supersededBy = winner.id;
      this.ledger.append({
        memoryId: loser.id, action: "conflict_resolved", actor: "conflicts",
        previousState: { supersededBy: undefined },
        newState: { supersededBy: winner.id },
        details: { winner: winner.id, gap },
      });
      return "resolved";
    },
  };

  // --- dreaming ----------------------------------------------------------------

  private proposals = new Map<string, { id: string; content: string; derivedFrom: string[] }>();

  readonly dreaming = {
    /** Proposes syntheses. Materialises nothing: an inference the system made
     *  about itself has to clear a human before it becomes something the
     *  system then reasons from. */
    dream: (): Array<{ id: string; content: string; derivedFrom: string[] }> => {
      const preferences = this.store.active().filter((r) => r.type === "preference");
      const proposals: Array<{ id: string; content: string; derivedFrom: string[] }> = [];
      if (preferences.length >= 2) {
        const derivedFrom = preferences.map((p) => p.id);
        const proposal = {
          id: `dream-${this.proposals.size + 1}`,
          content: `Synthesised preference: ${preferences.map((p) => p.content).join("; ")}`,
          derivedFrom,
        };
        this.proposals.set(proposal.id, proposal);
        proposals.push(proposal);
        this.ledger.append({ memoryId: proposal.id, action: "dream_proposed", actor: "dreaming",
          details: { derivedFrom } });
      }
      return proposals;
    },

    approve: (proposalId: string): MemoryRecord | undefined => {
      const proposal = this.proposals.get(proposalId);
      if (!proposal) return undefined;
      const record = this.add({
        content: proposal.content,
        source: "dreaming",
        layer: "long_term",
        type: "insight",
        derivedFrom: proposal.derivedFrom,
      });
      this.proposals.delete(proposalId);
      this.ledger.append({ memoryId: record.id, action: "dream_approved", actor: "reviewer",
        details: { proposalId, derivedFrom: proposal.derivedFrom } });
      return record;
    },

    reject: (proposalId: string): boolean => {
      const existed = this.proposals.delete(proposalId);
      if (existed) {
        this.ledger.append({ memoryId: proposalId, action: "dream_rejected", actor: "reviewer" });
      }
      return existed;
    },
  };
}

// --- polarity ----------------------------------------------------------------

const POSITIVE = ["always", "must", "should", "do"];
const NEGATIVE = ["never", "must not", "should not", "do not", "don't"];

function polarity(text: string): "positive" | "negative" | "neutral" {
  const lower = (text ?? "").toLowerCase();
  if (NEGATIVE.some((w) => lower.includes(w))) return "negative";
  if (POSITIVE.some((w) => new RegExp(`\\b${w}\\b`).test(lower))) return "positive";
  return "neutral";
}

function opposesInPolarity(a: string, b: string): boolean {
  const left = polarity(a);
  const right = polarity(b);
  return left !== "neutral" && right !== "neutral" && left !== right;
}

function stripPolarity(text: string): string {
  let out = (text ?? "").toLowerCase();
  for (const word of [...POSITIVE, ...NEGATIVE]) out = out.split(word).join(" ");
  return out;
}

export default HMEM;
