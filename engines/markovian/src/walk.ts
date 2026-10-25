/**
 * Control-chain walk, bounded by the Markovian engine.
 *
 *   tsx src/walk.ts --vendor V0004 [--max-depth 5] [--carryover 640]
 *
 * Reads data/sample/control_graph.json and sanctions_sample.json; writes one
 * JSON object to stdout. No network, so it is deterministic and works offline.
 *
 * Why the engine rather than a for-loop
 * -------------------------------------
 * A loop would also walk the graph. What Markovian supplies is the property
 * that makes the walk safe to demo: each hop is one chunk whose prompt carries
 * a BOUNDED state summary instead of the whole traversal so far, so cost per
 * hop is flat rather than growing with depth. It also owns termination --
 * [TASK_COMPLETE] when a listed entity or a root is reached, maxChunks as the
 * depth cap -- and the efficiency accounting the run reports.
 *
 * The state carried between hops is the frontier node, the visited set and any
 * hits. That it stays inside carryoverTokens at depth 5 is the engine's job,
 * and run.chunkConfig records the budget it was held to.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Markovian, runEfficiency, MARKERS } from "./index.js";
import { assessHop } from "./assess.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const SAMPLE = path.resolve(here, "..", "..", "..", "data", "sample");

interface Node { key: string; name: string; country: string; kind: string; entity_id?: string }
interface Edge { child: string; parent: string; relation: string }

const readJson = (name: string) =>
  JSON.parse(fs.readFileSync(path.join(SAMPLE, name), "utf-8"));

function arg(flag: string, fallback?: string): string | undefined {
  const i = process.argv.indexOf(flag);
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

interface CarriedState {
  /** Nodes still to visit. A company can have several parents, and following
   *  only the first silently misses exposure through the others -- the
   *  labelled set caught exactly that. Breadth-first, bounded by maxChunks. */
  frontier: string[];
  current: string | null;
  visited: string[];
  hits: Array<{ key: string; name: string; entity_id: string; depth: number }>;
  depth: number;
}

const encode = (s: CarriedState) =>
  [
    `CURRENT: ${s.current ?? "none"}`,
    `FRONTIER: ${s.frontier.join(",")}`,
    `DEPTH: ${s.depth}`,
    `VISITED: ${s.visited.join(",")}`,
    `HITS: ${s.hits.map((h) => `${h.key}|${h.entity_id}|${h.depth}`).join(";") || "none"}`,
  ].join("\n");

/** Defensive: the engine may compress the carryover, so a missing field falls
 *  back rather than throwing. Losing state is a termination condition, not a
 *  crash. */
function decode(text: string, previous: CarriedState): CarriedState {
  const field = (name: string) =>
    (text.split("\n").find((l) => l.startsWith(`${name}:`)) ?? "").slice(name.length + 1).trim();
  const current = field("CURRENT");
  const frontierRaw = field("FRONTIER");
  const visited = field("VISITED");
  const depth = Number.parseInt(field("DEPTH"), 10);
  return {
    current: current && current !== "none" ? current : null,
    frontier: frontierRaw ? frontierRaw.split(",").filter(Boolean) : previous.frontier,
    visited: visited ? visited.split(",").filter(Boolean) : previous.visited,
    hits: previous.hits,
    depth: Number.isFinite(depth) ? depth : previous.depth,
  };
}

async function main() {
  const vendorId = arg("--vendor");
  if (!vendorId) {
    console.error("usage: tsx src/walk.ts --vendor V0004 [--max-depth 5] [--carryover 640]");
    process.exit(2);
  }
  const maxDepth = Number.parseInt(arg("--max-depth", "5")!, 10);
  // Model assessment is on by default and off for tests and offline runs.
  const useModel = !process.argv.includes("--no-model");
  const carryoverTokens = Number.parseInt(arg("--carryover", "256")!, 10);

  const graph = readJson("control_graph.json");
  const sanctions = readJson("sanctions_sample.json");

  const nodes = new Map<string, Node>(graph.nodes.map((n: Node) => [n.key, n]));
  const parents = new Map<string, Edge[]>();
  for (const e of graph.edges as Edge[]) {
    if (!parents.has(e.child)) parents.set(e.child, []);
    parents.get(e.child)!.push(e);
  }
  const listed = new Set<string>(sanctions.entities.map((e: any) => e.id));
  const entityById = new Map<string, any>(sanctions.entities.map((e: any) => [e.id, e]));

  const chain: Array<Record<string, unknown>> = [];
  const vendorNode = nodes.get(vendorId);
  const vendorRecord = (readJson("vendor_master.json").vendors as Array<Record<string, string>>)
    .find((v) => v.vendor_id === vendorId);
  const vendorBankCountry = vendorRecord?.bank_country ?? vendorNode?.country ?? "";
  const assessments: string[] = [];
  let carriedSummary = "";
  let state: CarriedState = {
    current: vendorId, frontier: [], visited: [vendorId], hits: [], depth: 0,
  };
  let terminated = "DEPTH";

  const generator = async (prompt: string) => {
    // Read the frontier back out of the prompt's carryover block, so the walk
    // genuinely depends on what the engine carried rather than on closure
    // state that would make the bounding decorative.
    //
    // Keyed on the state's own first field, not on the marker. The prompt
    // template NAMES [STATE_CHECKPOINT] in its instructions, so splitting on
    // the marker decoded that instruction text as state on the very first hop,
    // yielding current=null, and every walk terminated at ROOT immediately.
    const at = prompt.search(/^CURRENT:/m);
    if (at !== -1) state = decode(prompt.slice(at), state);

    const from = state.current;
    if (!from) {
      terminated = "ROOT";
      return { text: `No further parent. ${MARKERS.complete}` };
    }

    // Enqueue every parent of the current node, then take the next unvisited
    // one. Following only parents[0] made a second ownership route invisible.
    const discovered = (parents.get(from) ?? [])
      .filter((e) => !state.visited.includes(e.parent) && !state.frontier.includes(e.parent))
      .map((e) => e.parent);
    const queue = [...state.frontier, ...discovered];

    if (!queue.length) {
      terminated = state.visited.length > 1 ? "ROOT" : "ROOT";
      return {
        text: `No further parents to check above ${nodes.get(from)?.name ?? from}. ${MARKERS.complete}`,
      };
    }

    const nextKey = queue.shift()!;
    const next = (parents.get(from) ?? []).find((e) => e.parent === nextKey)
      ?? { child: from, parent: nextKey, relation: "DIRECT_PARENT" };

    if (state.visited.includes(next.parent)) {
      terminated = "CYCLE";
      return {
        text: `Cycle: ${nodes.get(next.parent)?.name ?? next.parent} already visited. ${MARKERS.complete}`,
      };
    }

    const parentNode = nodes.get(next.parent);
    const depth = state.depth + 1;
    const hit = parentNode?.entity_id && listed.has(parentNode.entity_id) ? parentNode.entity_id : null;

    // The model call that makes this a reasoning step rather than a lookup.
    // It receives the CARRIED state, not the whole traversal -- which is the
    // engine's contribution and what keeps prompt size flat as depth grows.
    const assessment = await assessHop(
      {
        vendorName: vendorNode?.name ?? vendorId,
        vendorCountry: vendorNode?.country ?? "",
        vendorBankCountry: vendorBankCountry,
        depth,
        parentName: parentNode?.name ?? next.parent,
        parentCountry: parentNode?.country ?? "",
        relation: next.relation,
        carried: carriedSummary,
      },
      useModel,
    );
    assessments.push(assessment.source);

    chain.push({
      lei: next.parent,
      name: parentNode?.name ?? next.parent,
      country: parentNode?.country ?? null,
      relation: next.relation,
      depth,
      materiality: assessment.material,
      assessment: assessment.reason,
      assessed_by: assessment.source,
      sanctions_hit: hit
        ? {
            entity_id: hit,
            caption: entityById.get(hit)?.caption,
            dataset: entityById.get(hit)?.dataset,
            country: entityById.get(hit)?.country,
          }
        : null,
    });

    state = {
      current: next.parent,
      frontier: queue,
      visited: [...state.visited, next.parent],
      hits: hit
        ? [...state.hits, { key: next.parent, name: parentNode!.name, entity_id: hit, depth }]
        : state.hits,
      depth,
    };

    // The findings so far, kept to one line per hop. This is the text the
    // engine compresses into the carryover; the naive shape would instead
    // append every hop's full assessment to every later prompt.
    carriedSummary =
      `${carriedSummary}\nhop ${depth} ${parentNode?.name ?? next.parent} ` +
      `(${next.relation}, ${assessment.material}): ${assessment.reason}`.trim();

    const body =
      `Hop ${depth}: ${parentNode!.name} (${next.relation}) in ${parentNode?.country ?? "?"}.\n` +
      `Materiality ${assessment.material} — ${assessment.reason}`;

    if (hit) {
      terminated = "SANCTIONS_HIT";
      return { text: `${body}\nThis is a LISTED entity. ${MARKERS.complete}` };
    }
    if (depth >= maxDepth) {
      terminated = "DEPTH";
      return { text: `${body}\nReached the depth cap. ${MARKERS.complete}` };
    }
    // assessment.continue_walk is recorded as advice and deliberately NOT
    // acted on. Letting the model end the search is how exposure gets missed:
    // on its first outing it judged hop 1 immaterial and would have stopped
    // one hop short of a listed ultimate parent. Materiality shapes the
    // REPORT; only a hit, a cycle, a root or the depth cap stops the WALK.
    return {
      text: `${body}\n${MARKERS.checkpoint}\n${encode(state)}\nFINDINGS:${carriedSummary}`,
    };
  };

  const engine = new Markovian({
    chunkConfig: { chunkSize: 4000, maxChunks: maxDepth, carryoverTokens },
  });
  const run = await engine.run({
    goal: `Walk the control chain upward from ${vendorId} and report any listed entity.`,
    generator,
    reflect: false,
  });

  const efficiency = runEfficiency(run.chunks, run.chunkConfig);

  process.stdout.write(
    JSON.stringify(
      {
        vendor_id: vendorId,
        chain,
        terminated_because: run.status === "exhausted" ? "DEPTH" : terminated,
        hits: state.hits,
        engine: {
          name: "meterless/markovian",
          implementation: "clearline (engines/markovian/src/index.ts)",
          status: run.status,
          chunks: run.chunks.length,
          chunkConfig: run.chunkConfig,
          tokenLabel: run.tokenLabel,
        assessed_by: assessments.length
          ? (assessments.every((a) => a === "model") ? "model"
             : assessments.every((a) => a === "heuristic") ? "heuristic" : "mixed")
          : "none",
          // The point of using the engine, stated in numbers: what appending
          // the whole traversal to each prompt would have cost, versus
          // carrying a bounded summary.
          standardCost: efficiency.standardCost,
          markovianCost: efficiency.markovianCost,
          tokensSaved: efficiency.tokensSaved,
        },
      },
      null,
      2,
    ) + "\n",
  );
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
