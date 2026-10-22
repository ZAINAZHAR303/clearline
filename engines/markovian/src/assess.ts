/**
 * Per-hop materiality assessment.
 *
 * This is what makes the Markovian engine load-bearing rather than decorative.
 * Without it the walk was graph lookups in a loop, and the engine's central
 * property — flat prompt cost across steps — had nothing to bound.
 *
 * Now each hop is a real model call carrying the chain accumulated so far, so
 * the naive shape would grow every prompt by the previous hop's reasoning.
 * Markovian carries a compressed summary instead, and the saving is measured
 * rather than modelled.
 *
 * The question is also one a human reviewer actually asks. "Reaches a listed
 * entity" is binary; materiality is the judgement. A dormant holding company
 * three hops up is not the same finding as an operating parent that shares a
 * bank jurisdiction with the vendor, and reporting them identically is how a
 * screening tool earns the alert fatigue that gets it switched off.
 */

import { config as loadEnv } from "dotenv";
import path from "node:path";
import { fileURLToPath } from "node:url";
import OpenAI from "openai";

const here = path.dirname(fileURLToPath(import.meta.url));
loadEnv({ path: path.resolve(here, "..", "..", "..", ".env"), quiet: true });

export interface HopContext {
  vendorName: string;
  vendorCountry: string;
  vendorBankCountry: string;
  depth: number;
  parentName: string;
  parentCountry: string;
  relation: string;
  /** The compressed state the engine carried from the previous hop. */
  carried: string;
}

export interface Assessment {
  material: "HIGH" | "MEDIUM" | "LOW";
  reason: string;
  continue_walk: boolean;
  /** "model" when a provider answered, "heuristic" when one was unavailable —
   *  a number has to carry its source, same rule as the token labels. */
  source: "model" | "heuristic";
}

const SYSTEM = `You assess one hop of a corporate control chain during vendor sanctions screening.

A hop is a parent company found above the vendor. Judge how MATERIAL the
relationship is for exposure, not whether it is suspicious in isolation.

HIGH is the exception, not the default. Most intermediate holding companies on
an ordinary ownership route are MEDIUM. If you return HIGH for every hop the
rating carries no information and a reviewer learns nothing from it.

  HIGH    reserve for a specific signal: an ULTIMATE_PARENT relationship, or a
          parent jurisdiction matching the vendor's BANK country while
          differing from its registered country
  MEDIUM  the normal case -- an intermediate holding company on a plausible
          route, with no specific signal
  LOW     a deep layer with nothing tying it to the vendor

continue_walk is advisory only -- the walk continues regardless, because a
missed listed parent is far more costly than one extra hop. Say false only if
the chain looks genuinely exhausted.

Reply with JSON only: {"material":"HIGH|MEDIUM|LOW","reason":"one sentence","continue_walk":true|false}`;

let client: OpenAI | null | undefined;

function getClient(): OpenAI | null {
  if (client !== undefined) return client;
  const baseURL = process.env.MODEL_BASE_URL;
  const apiKey = process.env.MODEL_API_KEY;
  client = baseURL && apiKey ? new OpenAI({ baseURL, apiKey, timeout: 180_000 }) : null;
  return client;
}

/** Deterministic fallback, so the walk still runs offline and the test suite
 *  stays fast. Mirrors the prompt's rules rather than inventing its own. */
export function heuristicAssessment(ctx: HopContext): Assessment {
  const bankMismatch =
    ctx.vendorBankCountry !== ctx.vendorCountry && ctx.parentCountry === ctx.vendorBankCountry;
  if (ctx.relation === "ULTIMATE_PARENT" || bankMismatch) {
    return {
      material: "HIGH",
      reason: bankMismatch
        ? `parent jurisdiction ${ctx.parentCountry} matches the vendor's bank country while its registered country is ${ctx.vendorCountry}`
        : "ultimate parent: control is direct and meaningful",
      continue_walk: true,
      source: "heuristic",
    };
  }
  if (ctx.depth <= 2) {
    return { material: "MEDIUM", reason: "intermediate holding company close to the vendor",
             continue_walk: true, source: "heuristic" };
  }
  return { material: "LOW", reason: `depth ${ctx.depth} with no signal tying it to the vendor`,
           continue_walk: true, source: "heuristic" };
}

export async function assessHop(ctx: HopContext, useModel: boolean): Promise<Assessment> {
  const api = useModel ? getClient() : null;
  if (!api) return heuristicAssessment(ctx);

  const model =
    process.env.NEMOTRON_MODEL_NANO ?? process.env.NEMOTRON_MODEL ?? "";
  if (!model) return heuristicAssessment(ctx);

  const user = JSON.stringify(
    {
      vendor: { name: ctx.vendorName, country: ctx.vendorCountry, bank_country: ctx.vendorBankCountry },
      hop: { depth: ctx.depth, parent: ctx.parentName, parent_country: ctx.parentCountry, relation: ctx.relation },
      chain_so_far: ctx.carried || "(none yet)",
    },
    null,
    2,
  );

  try {
    const reply = await api.chat.completions.create({
      model,
      messages: [{ role: "system", content: SYSTEM }, { role: "user", content: user }],
      max_tokens: 400,
      temperature: 0.2,
      // Deliberation off: measured on nemotron-3.5-lightning, a "/no_think"
      // directive only halves it while this zeroes it. A materiality call per
      // hop has to be cheap or the walk stops being demoable.
      //
      // NOTE the SDK difference. Python's client takes `extra_body={...}`;
      // the Node client has no such parameter and passes unknown fields
      // straight through, so wrapping it returned
      // `400 Unsupported parameter(s): extra_body`. Inline is correct here.
      // @ts-expect-error provider-specific field, passed through by the SDK
      chat_template_kwargs: { thinking: false },
    });
    const text = (reply.choices[0]?.message?.content ?? "").trim();
    const start = text.indexOf("{");
    const end = text.lastIndexOf("}");
    const parsed = JSON.parse(start !== -1 && end > start ? text.slice(start, end + 1) : text);
    const material = ["HIGH", "MEDIUM", "LOW"].includes(parsed.material) ? parsed.material : "MEDIUM";
    return {
      material,
      reason: String(parsed.reason ?? "").slice(0, 300),
      continue_walk: parsed.continue_walk !== false,
      source: "model",
    };
  } catch (err) {
    if (process.env.CLEARLINE_DEBUG_ASSESS) {
      process.stderr.write(`assess error: ${(err as Error).message}
`);
    }
    // A provider failure degrades the assessment, never the walk: a chain that
    // stops halfway is a worse answer than one assessed heuristically.
    return heuristicAssessment(ctx);
  }
}
