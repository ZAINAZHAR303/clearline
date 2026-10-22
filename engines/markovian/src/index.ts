/**
 * Markovian engine — Clearline implementation.
 *
 * Written to the Meterless spec (engines/markovian/AGENTS.md), not copied from
 * the reference. Verified by the upstream conformance suite:
 *
 *   MARKOVIAN_IMPL=".../engines/markovian/src/index.ts" npx tsx runner.ts
 *
 * Why Clearline needs it: walking a corporate control chain is an unbounded
 * task. Each hop adds entities, aliases and relationships, and appending that
 * to a transcript makes prompt cost grow with depth — a 40-node chain stops
 * being demoable. Markovian keeps per-step cost flat by carrying a bounded
 * state summary between hops instead of the whole history.
 *
 * The core claim, from the spec's own model:
 *
 *   naive_total     = N*(F + G + S) + O * N*(N-1)/2     // O(N²)
 *   markovian_total = N*(F + G + C + S)                 // O(N)
 */

// --- types -------------------------------------------------------------------

export interface ChunkConfig {
  chunkSize: number;
  maxChunks: number;
  carryoverTokens: number;
  overlapTokens: number;
}

export interface Chunk {
  id: number;
  tokens: number;
  carryover: string;
  content: string;
}

export type RunStatus = "completed" | "exhausted" | "failed";
export type TokenLabel = "estimated" | "measured";

export interface RunRecord {
  goal: string;
  status: RunStatus;
  output: string;
  chunks: Chunk[];
  /** Snapshot of the config this run actually used. Historical efficiency is
   *  computed against this, never against whatever the config says later. */
  chunkConfig: ChunkConfig;
  tokenLabel: TokenLabel;
  startedAt: number;
  finishedAt: number;
  reflection?: string;
  reflectionError?: string;
}

export interface GeneratorResult {
  text: string;
  /** Provider-reported usage, when available. Its presence is what upgrades
   *  tokenLabel from "estimated" to "measured" — a number must carry its
   *  source, and chars/4 is a fallback, not a measurement. */
  usage?: { totalTokens?: number };
}

export type Generator = (prompt: string) => Promise<GeneratorResult>;

export interface RunOptions {
  goal: string;
  generator: Generator;
  /** Defaults to true. A reflection pass summarises the run; see runReflection. */
  reflect?: boolean;
}

export interface MarkovianOptions {
  chunkConfig?: Partial<ChunkConfig>;
  clock?: () => number;
}

// --- config ------------------------------------------------------------------

export const DEFAULT_CONFIG: ChunkConfig = {
  chunkSize: 8000,
  maxChunks: 24,
  carryoverTokens: 800,
  overlapTokens: 0,
};

/** Engine constants from the spec: template overhead and reserved output. */
export const FRAMING_TOKENS = 400;
export const OUTPUT_BUDGET = 1200;

export class ConfigError extends Error {
  constructor(public readonly field: string, message: string) {
    super(message);
    this.name = "ConfigError";
  }
}

const BOUNDS = {
  chunkSize: { min: 1000, max: 128000, step: 1000 },
  maxChunks: { min: 1, max: 32, step: 1 },
  carryoverTokens: { min: 128, max: 32768, step: 128 },
  overlapTokens: { min: 0, max: 4096, step: 1 },
} as const;

/**
 * Validate and freeze a config.
 *
 * Out-of-range values are rejected with a typed error and never clamped.
 * Silent truncation is the failure the spec singles out: a run that quietly
 * used different settings than you asked for produces numbers nobody can
 * reconcile afterwards.
 */
export function resolveConfig(partial: Partial<ChunkConfig> = {}): ChunkConfig {
  const config: ChunkConfig = { ...DEFAULT_CONFIG, ...partial };

  for (const [field, bound] of Object.entries(BOUNDS)) {
    const value = config[field as keyof ChunkConfig];
    if (typeof value !== "number" || !Number.isFinite(value)) {
      throw new ConfigError(field, `${field} must be a finite number, got ${value}`);
    }
    if (value < bound.min || value > bound.max) {
      throw new ConfigError(
        field,
        `${field}=${value} is out of range [${bound.min}, ${bound.max}]; values are rejected, never clamped`,
      );
    }
    if (bound.step > 1 && value % bound.step !== 0) {
      throw new ConfigError(field, `${field}=${value} must be a multiple of ${bound.step}`);
    }
  }

  if (config.carryoverTokens <= 0) {
    throw new ConfigError("carryoverTokens", "carryoverTokens must be greater than 0");
  }

  const floor = FRAMING_TOKENS + config.carryoverTokens + OUTPUT_BUDGET;
  if (config.chunkSize < floor) {
    throw new ConfigError(
      "chunkSize",
      `chunkSize=${config.chunkSize} leaves no room: needs >= framing(${FRAMING_TOKENS}) + ` +
        `carryover(${config.carryoverTokens}) + output(${OUTPUT_BUDGET}) = ${floor}`,
    );
  }

  return Object.freeze(config);
}

// --- tokens ------------------------------------------------------------------

/** chars/4. The fallback estimate, which is why runs label their numbers. */
export const estimateTokens = (text: string): number => Math.ceil((text?.length ?? 0) / 4);

// --- markers -----------------------------------------------------------------

export const MARKERS = {
  complete: "[TASK_COMPLETE]",
  checkpoint: "[STATE_CHECKPOINT]",
  overlap: "[OVERLAP]",
} as const;

export interface ParsedOutput {
  /** Marker-free text, safe to show a user or concatenate into a result. */
  content: string;
  carryover: string;
  complete: boolean;
}

/**
 * Split a generator response into display content, carried state and a
 * completion signal.
 *
 * Markers are control channel, not content. Leaking them into display output
 * is a contract violation — and in Clearline it would mean a reviewer reading
 * "[STATE_CHECKPOINT]" in an audit trail.
 */
export function parseOutput(text: string): ParsedOutput {
  const raw = text ?? "";
  const complete = raw.includes(MARKERS.complete);

  let carryover = "";
  const checkpointAt = raw.indexOf(MARKERS.checkpoint);
  if (checkpointAt !== -1) {
    carryover = raw
      .slice(checkpointAt + MARKERS.checkpoint.length)
      .split(MARKERS.complete)[0]
      .trim();
  }

  let content = raw;
  if (checkpointAt !== -1) content = content.slice(0, checkpointAt);
  content = content.split(MARKERS.complete).join("");
  // Defensive: strip any marker token that survived, wherever it sits.
  for (const marker of Object.values(MARKERS)) content = content.split(marker).join("");

  return { content: content.trim(), carryover, complete };
}

/** Bound the carried state to its token budget, cutting on a line boundary
 *  where possible so the next prompt receives whole facts. */
export function compressCarryover(carryover: string, carryoverTokens: number): string {
  const limit = carryoverTokens * 4; // chars, per the chars/4 estimator
  if (carryover.length <= limit) return carryover;
  const cut = carryover.slice(0, limit);
  const lastBreak = cut.lastIndexOf("\n");
  return (lastBreak > limit * 0.5 ? cut.slice(0, lastBreak) : cut).trim();
}

// --- prompts -----------------------------------------------------------------

export function buildPrompt(args: {
  goal: string;
  chunkIndex: number;
  maxChunks: number;
  carryover: string;
  overlap: string;
}): string {
  const { goal, chunkIndex, maxChunks, carryover, overlap } = args;
  const parts = [
    `GOAL: ${goal}`,
    `STEP: ${chunkIndex} of at most ${maxChunks}`,
  ];

  if (carryover) parts.push(`${MARKERS.checkpoint}\n${carryover}`);
  // Order matters: overlap follows the carryover, per the spec.
  if (overlap) parts.push(`${MARKERS.overlap}\n${overlap}`);

  parts.push(
    `Continue the work. End with ${MARKERS.complete} when the goal is met, ` +
      `otherwise end with ${MARKERS.checkpoint} followed by the state the next ` +
      `step needs: what is done, what remains, decisions made, context to keep.`,
  );
  return parts.join("\n\n");
}

// --- efficiency --------------------------------------------------------------

export interface ModelTotals {
  naiveTotal: number;
  markovianTotal: number;
  savings: number;
  efficiency: number;
}

/**
 * The spec's modelled comparison, with its documented constants
 * (F=400, G=200, S=300, O=1200, C=800). N=20 gives 246,000 vs 34,000 — 86.18%.
 *
 * Modelled, not measured. Real figures come from runEfficiency over actual
 * chunks, and carry a tokenLabel.
 */
export function modelTotals(
  N: number,
  constants: { F?: number; G?: number; S?: number; O?: number; C?: number } = {},
): ModelTotals {
  const { F = 400, G = 200, S = 300, O = 1200, C = 800 } = constants;
  const naiveTotal = N * (F + G + S) + O * ((N * (N - 1)) / 2);
  const markovianTotal = N * (F + G + C + S);
  const savings = naiveTotal - markovianTotal;
  return {
    naiveTotal,
    markovianTotal,
    savings,
    efficiency: naiveTotal === 0 ? 0 : savings / naiveTotal,
  };
}

export interface RunEfficiency {
  standardCost: number;
  markovianCost: number;
  tokensSaved: number;
  efficiency: number;
}

/**
 * Efficiency for a run that actually happened.
 *
 * `config` is the run's OWN snapshot. Recomputing history against current
 * settings would silently rewrite past numbers whenever someone changed a
 * slider, which is why the run record carries its config.
 *
 *   standardCost  = prefix sums — step i re-sends everything through i
 *   markovianCost = N * carryoverTokens + total output
 */
export function runEfficiency(
  chunks: Array<{ tokens: number }>,
  config: Pick<ChunkConfig, "carryoverTokens">,
): RunEfficiency {
  let running = 0;
  let standardCost = 0;
  let total = 0;
  for (const chunk of chunks) {
    running += chunk.tokens;
    standardCost += running;
    total += chunk.tokens;
  }
  const markovianCost = chunks.length * config.carryoverTokens + total;
  const tokensSaved = standardCost - markovianCost;
  return {
    standardCost,
    markovianCost,
    tokensSaved,
    efficiency: standardCost === 0 ? 0 : tokensSaved / standardCost,
  };
}

// --- engine ------------------------------------------------------------------

export class Markovian {
  readonly config: ChunkConfig;
  private readonly clock: () => number;

  constructor(options: MarkovianOptions = {}) {
    this.config = resolveConfig(options.chunkConfig);
    this.clock = options.clock ?? (() => Date.now());
  }

  async run(options: RunOptions): Promise<RunRecord> {
    const { goal, generator, reflect = true } = options;
    const config = this.config; // snapshot for this run
    const startedAt = this.clock();

    const chunks: Chunk[] = [];
    let carryover = "";
    let previousContent = "";
    let status: RunStatus = "exhausted";
    let measured = false;

    for (let index = 1; index <= config.maxChunks; index += 1) {
      const overlap =
        config.overlapTokens > 0 && previousContent
          ? previousContent.slice(-config.overlapTokens * 4)
          : "";

      const prompt = buildPrompt({
        goal,
        chunkIndex: index,
        maxChunks: config.maxChunks,
        carryover,
        overlap,
      });

      let result: GeneratorResult;
      try {
        result = await generator(prompt);
      } catch (error) {
        // A generation failure ends the run as failed and keeps everything
        // already produced: partial evidence still has value to a reviewer.
        status = "failed";
        const finishedAt = this.clock();
        return {
          goal, status, output: chunks.map((c) => c.content).join("\n\n"),
          chunks, chunkConfig: config,
          tokenLabel: measured ? "measured" : "estimated",
          startedAt, finishedAt,
          reflectionError: (error as Error).message,
        };
      }

      const parsed = parseOutput(result.text);
      const reported = result.usage?.totalTokens;
      if (typeof reported === "number") measured = true;

      chunks.push({
        id: index,
        tokens: typeof reported === "number" ? reported : estimateTokens(result.text),
        carryover,
        content: parsed.content,
      });

      previousContent = parsed.content;
      carryover = compressCarryover(parsed.carryover || carryover, config.carryoverTokens);

      if (parsed.complete) {
        status = "completed";
        break;
      }
    }

    const record: RunRecord = {
      goal,
      status,
      output: chunks.map((c) => c.content).join("\n\n").trim(),
      chunks,
      chunkConfig: config,
      tokenLabel: measured ? "measured" : "estimated",
      startedAt,
      finishedAt: this.clock(),
    };

    if (reflect) await this.runReflection(record, generator);
    return record;
  }

  /**
   * Optional post-run summary.
   *
   * Its failure is recorded and swallowed. Reflection is commentary on work
   * already done, so letting a provider error there discard a completed run
   * would throw away the actual result for the sake of a footnote.
   */
  private async runReflection(record: RunRecord, generator: Generator): Promise<void> {
    try {
      const result = await generator(
        `GOAL: ${record.goal}\n\nThe work is finished in ${record.chunks.length} step(s). ` +
          `Summarise what was produced and anything left open.`,
      );
      record.reflection = parseOutput(result.text).content;
    } catch (error) {
      record.reflectionError = (error as Error).message;
    }
  }
}

export default Markovian;
