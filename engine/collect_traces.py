"""
Agent-trace collector: measured token volumes per task family and model family, from the public
Hugging Face dataset Exgentic/agent-llm-traces-v2 (10,057 complete agent sessions, OpenTelemetry GenAI spans).

This step is NOT part of the daily run: the dataset changes when its authors publish a new version, the
parquet shards total ~230 MB, and the aggregation needs a parquet reader (the folder is standard-library
only). It documents exactly how data/traces.json was produced so it can be reproduced or refreshed:

  1. Shards (auto-converted parquet):
       https://huggingface.co/datasets/Exgentic/agent-llm-traces-v2/resolve/refs%2Fconvert%2Fparquet/default/train/000N.parquet   N = 0..8
  2. Per shard, the DuckDB query in QUERY below (run in a browser with duckdb-wasm on 2026-09-07; it runs
     unchanged in any DuckDB). It keeps only the token fields of each span, unnests them, reconstructs the
     'new' input per call within a conversation, and aggregates per (benchmark, subset, harness, model).
  3. reduce(rows) below turns those rows into the per-family table the model uses (run-weighted medians
     across harness rows; input only from rows whose accounting looks like totals).

python engine/collect_traces.py rows.json   rebuilds data/traces.json from a JSON list of query rows.
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "data" / "traces.json"

QUERY = """
WITH p AS (
  SELECT session_id, benchmark, benchmark_subset, harness, models[1] AS model, score, success, steps, agent_cost, execution_time,
         list_transform(spans, s -> s.attributes."gen_ai.usage.input_tokens") AS tins,
         list_transform(spans, s -> s.attributes."gen_ai.usage.output_tokens") AS touts,
         list_transform(spans, s -> s.attributes."gen_ai.conversation.id") AS convs,
         list_transform(spans, s -> s.start_time) AS sts
  FROM read_parquet('SHARD.parquet')
), s AS (
  SELECT session_id, benchmark, benchmark_subset, harness, model, score, success, steps, agent_cost, execution_time,
         unnest(tins) AS tin, unnest(touts) AS tout, unnest(convs) AS conv, unnest(sts) AS st FROM p
), w AS (
  SELECT *, lag(tin) OVER (PARTITION BY session_id, conv ORDER BY st) AS prev_in, lag(tout) OVER (PARTITION BY session_id, conv ORDER BY st) AS prev_out FROM s
), r AS (
  SELECT session_id, benchmark, benchmark_subset, harness, model, any_value(score) AS run_score, any_value(success) AS run_ok, any_value(steps) AS run_steps,
         any_value(agent_cost) AS run_cost, any_value(execution_time) AS run_secs, count(*) AS n_spans, sum(tin) AS in_tok, sum(tout) AS out_tok,
         sum(CASE WHEN prev_in IS NULL THEN tin ELSE greatest(tin - prev_in - coalesce(prev_out,0), 0) END) AS new_in_tok, max(tin) AS max_ctx
  FROM w GROUP BY 1,2,3,4,5
)
SELECT benchmark, benchmark_subset, harness, model, count(*) AS n_runs, avg(run_score) AS score, avg(run_ok::int) AS success, avg(run_steps) AS steps,
       avg(n_spans) AS spans, avg(in_tok) AS in_tok, avg(out_tok) AS out_tok, avg(new_in_tok) AS new_in_tok, avg(max_ctx) AS max_ctx,
       avg(run_cost) AS run_cost, avg(run_secs) AS run_secs
FROM r GROUP BY 1,2,3,4 ORDER BY 1,2,3,4
"""

FAMILY = {"appworld": "appworld", "browsecompplus": "browsecompplus", "swebench": "swebench",
          "tau2_airline": "tau2", "tau2_retail": "tau2", "tau2_telecom": "tau2"}
MODEL_FAMILY = {"claude-opus-4-5": "anthropic", "gpt-5.2-2025-12-11": "openai", "DeepSeek-V3.2": "deepseek",
                "Kimi-K2.5": "kimi", "gemini-3-pro-preview": "google"}
COLS = ["benchmark", "subset", "harness", "model", "n", "score", "success", "steps", "spans", "in_tok", "out_tok", "new_in", "max_ctx", "cost", "secs"]
TOTAL_ACCOUNTING_MIN = 2000      # input tokens per call below which a row is treated as 'uncached input only'


def wmed(pairs):
    pairs = sorted((p for p in pairs if p[1] > 0), key=lambda p: p[0])
    tot = sum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= tot / 2:
            return v
    return pairs[-1][0] if pairs else None


def reduce(rows):
    R = [dict(zip(COLS, r)) for r in rows]
    groups, pool = {}, {}
    for r in R:
        groups.setdefault((FAMILY[r["benchmark"]], MODEL_FAMILY[r["model"]]), []).append(r)
        if r["in_tok"] / max(r["spans"], 1e-9) >= TOTAL_ACCOUNTING_MIN:
            pool.setdefault(FAMILY[r["benchmark"]], []).append(r)
    out = {}
    for (f, m), rs in sorted(groups.items()):
        n = sum(r["n"] for r in rs)
        tot = [r for r in rs if r["in_tok"] / max(r["spans"], 1e-9) >= TOTAL_ACCOUNTING_MIN]
        ctx = wmed([(r["in_tok"] / r["spans"], r["n"]) for r in pool[f]])
        cached_pool = wmed([(1 - r["new_in"] / r["in_tok"], r["n"]) for r in pool[f]])
        rec = {"n_runs": int(n), "harnesses": sorted({r["harness"] for r in rs}),
               "out_tok": wmed([(r["out_tok"], r["n"]) for r in rs]), "spans": wmed([(r["spans"], r["n"]) for r in rs]),
               "steps": wmed([(r["steps"], r["n"]) for r in rs]),
               "success": sum(r["success"] * r["n"] for r in rs) / n, "score": sum(r["score"] * r["n"] for r in rs) / n,
               "cost_reported": wmed([(r["cost"], r["n"]) for r in rs]),
               "in_tok": (wmed([(r["in_tok"], r["n"]) for r in tot]) if tot else None),
               "cached_share": (wmed([(1 - r["new_in"] / r["in_tok"], r["n"]) for r in tot]) if tot else None),
               "in_basis": ("own runs, %d of %d harness rows with total input accounting" % (len(tot), len(rs))) if tot
                           else "no row with total input accounting; task-family context per call x own calls"}
        if rec["in_tok"] is None:
            rec["in_tok"] = rec["spans"] * ctx
            rec["cached_share"] = cached_pool
        out.setdefault(f, {})[m] = rec
    return out


def rebuild(rows_path, log=print):
    rows = json.load(open(rows_path, encoding="utf-8"))
    doc = json.load(open(PATH, encoding="utf-8"))
    doc["rows"] = rows
    doc["agg"] = reduce(rows)
    json.dump(doc, open(PATH, "w", encoding="utf-8"), indent=1)
    log("traces: %d query rows -> %d families" % (len(rows), len(doc["agg"])))


if __name__ == "__main__":
    rebuild(sys.argv[1])
