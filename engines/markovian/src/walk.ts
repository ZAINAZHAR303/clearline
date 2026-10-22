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
  current: string | null;
  visited: string[];
  hits: Array<{ key: string; name: string; entity_id: string; depth: number }>;
  depth: number;
}

const encode = (s: CarriedState) =>
  [
    `CURRENT: ${s.current ?? "none"}`,
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
  const visited = field("VISITED");
  const depth = Number.parseInt(field("DEPTH"), 10);
  return {
    current: current && current !== "none" ? current : null,
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
  const carryoverTokens = Number.parseInt(arg("--carryover", "640")!, 10);

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
  let state: CarriedState = { current: vendorId, visited: [vendorId], hits: [], depth: 0 };
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

    const edges = parents.get(from) ?? [];
    const next = edges[0];
    if (!next) {
      terminated = "ROOT";
      return { text: `${nodes.get(from)?.name ?? from} has no recorded parent. ${MARKERS.complete}` };
    }

    if (state.visited.includes(next.parent)) {
      terminated = "CYCLE";
      return {
        text: `Cycle: ${nodes.get(next.parent)?.name ?? next.parent} already visited. ${MARKERS.complete}`,
      };
    }

    const parentNode = nodes.get(next.parent);
    const depth = state.depth + 1;
    const hit = parentNode?.entity_id && listed.has(parentNode.entity_id) ? parentNode.entity_id : null;

    chain.push({
      lei: next.parent,
      name: parentNode?.name ?? next.parent,
      country: parentNode?.country ?? null,
      relation: next.relation,
      depth,
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
      visited: [...state.visited, next.parent],
      hits: hit
        ? [...state.hits, { key: next.parent, name: parentNode!.name, entity_id: hit, depth }]
        : state.hits,
      depth,
    };

    if (hit) {
      terminated = "SANCTIONS_HIT";
      return {
        text: `Hop ${depth}: ${parentNode!.name} (${next.relation}) is a LISTED entity. ${MARKERS.complete}`,
      };
    }
    if (depth >= maxDepth) {
      terminated = "DEPTH";
      return { text: `Hop ${depth}: reached the depth cap. ${MARKERS.complete}` };
    }
    return {
      text:
        `Hop ${depth}: ${parentNode!.name} (${next.relation}), no listing.\n` +
        `${MARKERS.checkpoint}\n${encode(state)}`,
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
