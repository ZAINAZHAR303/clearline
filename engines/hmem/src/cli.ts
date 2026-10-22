/**
 * H-MEM command line, with state on disk.
 *
 *   tsx src/cli.ts remember --vendor V0001 --entity NK-... --decision BLOCK --confidence 0.95
 *   tsx src/cli.ts recall   --vendor V0001
 *   tsx src/cli.ts override --vendor V0001 --entity NK-... --verdict wrong --reviewer alice
 *   tsx src/cli.ts ledger   --vendor V0001
 *
 * The engine itself is in-memory, as the spec has it. Clearline needs those
 * memories to outlive a process, so state is rehydrated from and persisted to
 * a JSON file — which is also what makes the ledger inspectable with `cat`,
 * exactly the "grep-able files on disk" the spec describes.
 *
 * Writes are atomic (temp file then rename) because a half-written memory file
 * would mean an audit trail with a hole in it.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { HMEM, type MemoryRecord, type FeedbackKind } from "./index.js";

const here = path.dirname(fileURLToPath(import.meta.url));
// Overridable so tests and demos do not share a memory file. A suite that
// mutates the same state the demo reads is a suite that passes or fails
// depending on what someone did an hour ago.
const STATE =
  process.env.CLEARLINE_MEMORY_PATH ??
  path.resolve(here, "..", "..", "..", "data", "memory", "hmem.json");

function arg(flag: string, fallback?: string): string | undefined {
  const i = process.argv.indexOf(flag);
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

interface Persisted {
  records: MemoryRecord[];
  ledger: unknown[];
  sequence: number;
}

function load(): { hmem: HMEM; persisted: Persisted } {
  const hmem = new HMEM();
  let persisted: Persisted = { records: [], ledger: [], sequence: 0 };
  if (fs.existsSync(STATE)) {
    try {
      persisted = JSON.parse(fs.readFileSync(STATE, "utf-8"));
      for (const record of persisted.records ?? []) {
        // Rehydrate directly: replaying add() would rewrite ids and timestamps
        // and the ledger would no longer refer to the same records.
        (hmem.store as any).put(record);
      }
      (hmem as any).sequence = persisted.sequence ?? persisted.records?.length ?? 0;
      for (const entry of persisted.ledger ?? []) (hmem.ledger as any).entries?.push(entry);
    } catch {
      // A corrupt file must not silently become an empty memory: say so.
      process.stderr.write(`warning: could not parse ${STATE}; starting empty\n`);
    }
  }
  return { hmem, persisted };
}

function save(hmem: HMEM, previousLedger: unknown[]) {
  fs.mkdirSync(path.dirname(STATE), { recursive: true });
  const payload: Persisted = {
    records: hmem.store.all(),
    ledger: [...previousLedger, ...hmem.ledger.all()],
    sequence: (hmem as any).sequence ?? hmem.store.all().length,
  };
  const temp = `${STATE}.tmp`;
  fs.writeFileSync(temp, JSON.stringify(payload, null, 2), "utf-8");
  fs.renameSync(temp, STATE);
}

const out = (value: unknown) => process.stdout.write(JSON.stringify(value, null, 2) + "\n");

/** One memory per (vendor, entity) screening decision. */
const tagFor = (vendorId: string, entityId: string) => `match:${vendorId}:${entityId}`;

function main() {
  const command = process.argv[2];
  const { hmem, persisted } = load();
  const previousLedger = persisted.ledger ?? [];

  const vendorId = arg("--vendor");
  const entityId = arg("--entity");

  switch (command) {
    case "remember": {
      if (!vendorId || !entityId) return fail("remember needs --vendor and --entity");
      const decision = arg("--decision", "BLOCK")!;
      const confidence = Number.parseFloat(arg("--confidence", "0.8")!);
      const tag = tagFor(vendorId, entityId);
      const existing = hmem.store.all().find((r) => r.tags.includes(tag) && !r.supersededBy);
      if (existing) {
        out({ status: "already-known", record: existing });
        return;
      }
      const record = hmem.add({
        content: `Screening decision ${decision} for vendor ${vendorId} against watchlist entity ${entityId}`,
        source: "clearline",
        type: "decision",
        layer: "working",
        confidence,
        tags: [tag, "screening", decision.toLowerCase()],
        entities: [vendorId, entityId],
      });
      save(hmem, previousLedger);
      out({ status: "remembered", record });
      return;
    }

    case "recall": {
      if (!vendorId) return fail("recall needs --vendor");
      const records = hmem.store
        .all()
        .filter((r) => r.entities.includes(vendorId))
        .map((r) => ({
          id: r.id,
          content: r.content,
          confidence: r.confidence,
          tags: r.tags,
          entities: r.entities,
          supersededBy: r.supersededBy ?? null,
          // The field the orchestrator acts on: a reviewer said this match was
          // wrong, so the system must not keep asserting it.
          overridden: r.tags.includes("review"),
        }));
      out({ vendor_id: vendorId, memories: records });
      return;
    }

    case "override": {
      if (!vendorId || !entityId) return fail("override needs --vendor and --entity");
      const verdict = (arg("--verdict", "wrong") as FeedbackKind)!;
      const reviewer = arg("--reviewer", "reviewer")!;
      const tag = tagFor(vendorId, entityId);
      const target = hmem.store.all().find((r) => r.tags.includes(tag));
      if (!target) return fail(`no remembered decision for ${vendorId} / ${entityId}`);

      const before = target.confidence;
      hmem.feedback(target.id, verdict, reviewer);
      const after = hmem.store.get(target.id)!;
      save(hmem, previousLedger);
      out({
        status: "override-recorded",
        record_id: target.id,
        verdict,
        reviewer,
        confidence_before: before,
        confidence_after: after.confidence,
        tags: after.tags,
        ledger: hmem.ledger.history(target.id),
      });
      return;
    }

    case "ledger": {
      const entries = [...previousLedger, ...hmem.ledger.all()] as Array<Record<string, unknown>>;
      const filtered = vendorId
        ? entries.filter((e) => {
            const record = hmem.store.get(String(e.memoryId));
            return record?.entities.includes(vendorId);
          })
        : entries;
      out({ vendor_id: vendorId ?? null, entries: filtered });
      return;
    }

    case "forget-all": {
      // Demo reset only. Never wired into the agent: the engine's whole
      // premise is that memory is not quietly discarded.
      if (fs.existsSync(STATE)) fs.unlinkSync(STATE);
      out({ status: "cleared", path: STATE });
      return;
    }

    default:
      return fail(`unknown command ${command ?? "(none)"}; expected remember|recall|override|ledger|forget-all`);
  }
}

function fail(message: string): never {
  process.stderr.write(`${message}\n`);
  process.exit(2);
}

main();
