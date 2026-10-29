"""
Builds dashboard.html: prepares the inputs, runs the Python model at default dials, and injects both into
engine/template.html at the /*__DATA__*/ marker. The page recomputes from the same inputs in JavaScript and
checks itself against the embedded Python result. Appends one line per build to data/history.jsonl.
"""
import json, sys, datetime, csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import model  # noqa: E402
from engine import restate as RS  # noqa: E402

ROIC_CSV = ROOT / "data" / "roic_history.csv"
ROIC_COLS = [
    ("date", "build date (one row per day; the last build of the day)"),
    ("built_at", "build timestamp"),
    ("roic_rent", "A rent: ROIC, life average"), ("roic_rent_y1", "A rent: year-1 ROIC"), ("irr_rent", "A rent: IRR"), ("rev_per_gpu_hr_rent", "A rent: revenue per GPU-hour, life average"),
    ("roic_anthropic", "B serve, Anthropic basket: ROIC"), ("irr_anthropic", "B: IRR"), ("rev_per_gpu_hr_anthropic", "B: revenue per GPU-hour"),
    ("roic_openai", "C serve, OpenAI basket: ROIC"), ("irr_openai", "C: IRR"), ("rev_per_gpu_hr_openai", "C: revenue per GPU-hour"),
    ("roic_open", "D serve open-weight tokens only: ROIC"), ("irr_open", "D: IRR"), ("rev_per_gpu_hr_open", "D: revenue per GPU-hour"),
    ("roic_open_peak", "E open-weight only at InferenceX benchmark peak (realisation 100%): ROIC"), ("irr_open_peak", "E: IRR"), ("rev_per_gpu_hr_open_peak", "E: revenue per GPU-hour"),
    ("roic_aws", "F AWS: Anthropic block rented at the rental path plus a token revenue share, open-weight GPUs as in B: ROIC"), ("irr_aws", "F: IRR"), ("rev_per_gpu_hr_aws", "F: revenue per GPU-hour"),
    ("aws_rev_share", "F: owner's share of Anthropic token revenue"), ("training_share", "B and C: share of capacity given to training"),
    ("capex_usd", "total cost to build, USD (AI mastersheet.xlsx)"), ("gpus", "GPUs in the fleet"),
    ("rent_rate_spot", "model near-term rental rate, $/GPU-hr (year 1 of the rental path; basis in near_basis)"), ("rent_rate_lt", "model long-term rental rate, $/GPU-hr"),
    ("near_basis", "near-term rental basis: all_median = median of every current GB300/B300 rate (spot, on-demand, capacity blocks; default from 2026-10-13), all_avg = their average (2026-10-12), spot = median of spot rates (until 2026-10-11)"),
    ("near_n", "published rates in the near-term basis"), ("implied_rate", "rental rate the open-weight GPU-hour target is built on (near | spot | longterm)"),
    ("sd_b200", "Silicon Data B200 index, $/GPU-hr (Blackwell reference, not an input)"), ("sd_b200_as_of", "index date"),
    ("sd_h100", "Silicon Data H100 neo-cloud index, $/GPU-hr (Hopper reference, not an input)"), ("sd_h200", "Silicon Data H200 index, $/GPU-hr (Hopper reference, not an input)"),
    ("ornn_b200", "Ornn B200 compute price index, $/GPU-hr (Blackwell reference, not an input)"), ("ornn_b200_as_of", "settlement date"),
    ("ornn_h100", "Ornn H100 SXM index, $/GPU-hr (Hopper reference, not an input)"), ("ornn_h200", "Ornn H200 index, $/GPU-hr (Hopper reference, not an input)"),
    ("closed_share_anthropic", "B: closed-weight (frontier) share of output tokens under the split mode in force"), ("closed_share_openai", "C: closed-weight share of output tokens"),
    ("split_mode", "how the split was set: cost (framework + premium tolerance) | openrouter (OpenRouter's weekly closed share) | manual"),
    ("premium_tolerance", "cost dial: frontier premium a task will pay before volume migrates, x open-weight price (blank = no limit)"),
    ("frontier_premium_anthropic", "B: frontier basket price over the routed open-weight mix, x, weighted by the framework's frontier runs"), ("frontier_premium_openai", "C: same for the OpenAI basket"),
    ("or_closed_share_week", "closed-weight share of completion tokens in OpenRouter's latest weekly ranking, every closed lab (reference; the input under the openrouter split mode)"), ("or_week_date", "that ranking's week"),
    ("closed_price_anthropic", "B: closed-model token price, $ per M output tokens all-in (input billed at the run's ratio), token-weighted"),
    ("closed_price_out_anthropic", "B: closed-model output price alone, $/M"),
    ("closed_price_openai", "C: closed-model token price, $ per M output tokens all-in"), ("closed_price_out_openai", "C: closed-model output price alone, $/M"),
    ("frontier_rev_gpu_hr_anthropic", "B: what a GPU-hour earns serving the Anthropic closed-weight basket at market token prices, $/GPU-hour at 100% token utilisation (comparable with a rental rate)"),
    ("frontier_rev_gpu_hr_openai", "C: the same for the OpenAI closed-weight basket"),
    ("open_price", "open-weight token price, $ per M output tokens all-in, token-weighted across the routed open models"), ("open_price_out", "open-weight output price alone, $/M"),
    ("open_per_m_tokens", "open-weight price per M tokens counting input and output (Silicon Data basis)"),
    ("closed_per_m_tokens_anthropic", "B: closed-model price per M tokens, input and output"), ("closed_per_m_tokens_openai", "C: closed-model price per M tokens, input and output"),
    ("blended_per_m_tokens_anthropic", "B: fleet-wide blended price per M tokens, input and output"), ("blended_per_m_tokens_openai", "C: fleet-wide blended price per M tokens, input and output"),
    ("blended_per_m_out_anthropic", "B: fleet-wide blended price per M output tokens all-in"), ("blended_per_m_out_openai", "C: fleet-wide blended price per M output tokens all-in"),
    ("sd_tok_llm", "Silicon Data LLM Token Expenditure Index (SDLLMTK), $ per M tokens (reference, not an input)"), ("sd_tok_open", "Silicon Data Open LLM Token Expenditure Index, $/M tokens"),
    ("sd_tok_proprietary", "Silicon Data Proprietary LLM Token Expenditure Index, $/M tokens"), ("sd_tok_as_of", "token index date"),
    ("open_gpu_hr_target", "what an open-weight GPU-hour is made to earn: rate x (1 + renter ROIC), $/GPU-hr"), ("renter_roic", "renter's ROIC dial"),
    ("horizon_years", "cash-flow horizon, years"), ("compute_life_years", "depreciation life of GPUs + racks, years"), ("shell_life_years", "depreciation life of the shell / M&E, years"),
    ("depreciation_avg_usd", "average annual depreciation over the horizon, USD"), ("terminal_value_usd", "book value recovered at the end of the horizon, USD (IRR only)"),
    ("throughput_scope", "throughput basis"), ("volumes", "token-volume basis"),
    ("basket_anthropic", "B: models in the Anthropic frontier basket (assumptions.json frontier_baskets), joined with +"),
    ("basket_openai", "C: models in the OpenAI frontier basket, joined with +"),
    ("openrouter_read_on", "OpenRouter data date"), ("inferencex_read_on", "InferenceX data date"), ("rental_read_on", "newest rental quote date"), ("mastersheet", "mastersheet fingerprint"),
]
# each day's separable assumptions and market primitives: what engine/restate.py needs to put every row on today's assumptions
ROIC_COLS += RS.CSV_COLS


def roic_row(inputs, dials, res):
    r, S, F = res["rent"], res["serves"], inputs["fleet"]
    idx = {q["chip"]: q for q in inputs["rental"]["quotes"] if q.get("tier") == "index" and q.get("vendor") == "Silicon Data" and q.get("per_gpu_hr")}
    orn = {q["chip"]: q for q in inputs["rental"]["quotes"] if q.get("tier") == "index" and q.get("vendor") == "Ornn" and q.get("per_gpu_hr")}
    tok = ((inputs.get("history") or {}).get("token_index") or {}).get("series") or {}
    def tok_latest(k):
        v = (tok.get(k) or {}).get("values") or {}
        return (v[max(v)], max(v)) if v else ("", "")
    a, o, w, e, x = S.get("anthropic", {}), S.get("openai", {}), res.get("serve_open", {}), res.get("serve_open_peak", {}), res.get("serve_aws", {})
    now = datetime.datetime.now()
    rd = lambda v, n=4: (round(v, n) if isinstance(v, (int, float)) and v is not None else "")
    return {
        "date": now.strftime("%Y-%m-%d"), "built_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "roic_rent": rd(r["roic"]), "roic_rent_y1": rd(r["roic_y1"]), "irr_rent": rd(r["irr"]), "rev_per_gpu_hr_rent": rd(r["rev_per_gpu_hr"]),
        "roic_anthropic": rd(a.get("roic")), "irr_anthropic": rd(a.get("irr")), "rev_per_gpu_hr_anthropic": rd(a.get("rev_per_gpu_hr")),
        "roic_openai": rd(o.get("roic")), "irr_openai": rd(o.get("irr")), "rev_per_gpu_hr_openai": rd(o.get("rev_per_gpu_hr")),
        "roic_open": rd(w.get("roic")), "irr_open": rd(w.get("irr")), "rev_per_gpu_hr_open": rd(w.get("rev_per_gpu_hr")),
        "roic_open_peak": rd(e.get("roic")), "irr_open_peak": rd(e.get("irr")), "rev_per_gpu_hr_open_peak": rd(e.get("rev_per_gpu_hr")),
        "roic_aws": rd(x.get("roic")), "irr_aws": rd(x.get("irr")), "rev_per_gpu_hr_aws": rd(x.get("rev_per_gpu_hr")),
        "aws_rev_share": rd(x.get("rev_share")), "training_share": rd(dials.get("training_share")),
        "capex_usd": int(round(F["capex_usd"])), "gpus": int(round(F["gpus"])),
        "rent_rate_spot": rd(r["rate_near"]), "rent_rate_lt": rd(r["rate"]),
        "near_basis": dials["near_basis"], "near_n": (inputs["rental"]["near_options"].get(dials["near_basis"]) or {}).get("n", ""), "implied_rate": dials.get("implied_rate", ""),
        "sd_b200": rd(idx["B200"]["per_gpu_hr"]) if "B200" in idx else "", "sd_b200_as_of": (idx["B200"].get("as_of") or idx["B200"].get("read_on")) if "B200" in idx else "",
        "sd_h100": rd(idx["H100"]["per_gpu_hr"]) if "H100" in idx else "", "sd_h200": rd(idx["H200"]["per_gpu_hr"]) if "H200" in idx else "",
        "ornn_b200": rd(orn["B200"]["per_gpu_hr"]) if "B200" in orn else "", "ornn_b200_as_of": (orn["B200"].get("as_of") or orn["B200"].get("read_on")) if "B200" in orn else "",
        "ornn_h100": rd(orn["H100"]["per_gpu_hr"]) if "H100" in orn else "", "ornn_h200": rd(orn["H200"]["per_gpu_hr"]) if "H200" in orn else "",
        "closed_share_anthropic": rd(a.get("closed_share")), "closed_share_openai": rd(o.get("closed_share")),
        "split_mode": res.get("split_mode", ""), "premium_tolerance": rd(res.get("premium_tolerance")),
        "frontier_premium_anthropic": rd(a.get("premium_weighted"), 2), "frontier_premium_openai": rd(o.get("premium_weighted"), 2),
        "or_closed_share_week": rd((res.get("or_closed_share_week") or {}).get("out")), "or_week_date": ((res.get("or_closed_share_week") or {}).get("week_date") or "")[:10],
        "closed_price_anthropic": rd(a.get("frontier_blended_per_m_out")), "closed_price_out_anthropic": rd(a.get("frontier_p_out")),
        "closed_price_openai": rd(o.get("frontier_blended_per_m_out")), "closed_price_out_openai": rd(o.get("frontier_p_out")),
        "frontier_rev_gpu_hr_anthropic": rd(a["frontier_rev_per_gpu_hr"] / dials["serve_util"]) if a.get("frontier_rev_per_gpu_hr") and dials.get("serve_util") else "",
        "frontier_rev_gpu_hr_openai": rd(o["frontier_rev_per_gpu_hr"] / dials["serve_util"]) if o.get("frontier_rev_per_gpu_hr") and dials.get("serve_util") else "",
        "open_price": rd(a.get("open_blended_per_m_out")), "open_price_out": rd(a.get("open_p_out")),
        "open_per_m_tokens": rd(a.get("open_per_m_total")), "closed_per_m_tokens_anthropic": rd(a.get("frontier_per_m_total")), "closed_per_m_tokens_openai": rd(o.get("frontier_per_m_total")),
        "blended_per_m_tokens_anthropic": rd(a.get("blended_per_m_total")), "blended_per_m_tokens_openai": rd(o.get("blended_per_m_total")),
        "blended_per_m_out_anthropic": rd(a.get("blended_per_m_out")), "blended_per_m_out_openai": rd(o.get("blended_per_m_out")),
        "sd_tok_llm": rd(tok_latest("llm")[0]), "sd_tok_open": rd(tok_latest("open")[0]), "sd_tok_proprietary": rd(tok_latest("proprietary")[0]), "sd_tok_as_of": tok_latest("llm")[1],
        "open_gpu_hr_target": rd(a.get("rate_f")), "renter_roic": rd(a.get("renter_roic")),
        "horizon_years": int(dials["life"]), "compute_life_years": dials.get("compute_life", ""), "shell_life_years": dials.get("shell_life", ""),
        "depreciation_avg_usd": int(round(res["depreciation"])), "terminal_value_usd": int(round((res.get("dep") or {}).get("terminal", 0))),
        "throughput_scope": dials["throughput_scope"], "volumes": dials["volumes"],
        "basket_anthropic": "+".join(mid for mid, _ in (inputs["baskets"].get("anthropic") or {}).get("weights", [])),
        "basket_openai": "+".join(mid for mid, _ in (inputs["baskets"].get("openai") or {}).get("weights", [])),
        "openrouter_read_on": inputs["openrouter"]["read_on"], "inferencex_read_on": inputs["throughput_meta"]["read_on"], "rental_read_on": inputs["rental_meta"]["read_on"],
        "mastersheet": F["mastersheet"].get("fingerprint") or "",
        **RS.built_from(dials, F), **RS.prims_from_result(res, dials, F),
    }


def record_roic(row, log=print):
    """One row per calendar day in data/roic_history.csv: today's build replaces an earlier build of the same day."""
    cols = [c for c, _ in ROIC_COLS]
    rows = []
    if ROIC_CSV.exists():
        with open(ROIC_CSV, encoding="utf-8", newline="") as f:
            rows = [x for x in csv.DictReader(f) if x.get("date") and x["date"] != row["date"]]
    rows.append(row)
    rows.sort(key=lambda x: x["date"])
    with open(ROIC_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for x in rows:
            w.writerow({c: x.get(c, "") for c in cols})
    log("roic history: %s now holds %d daily rows (%s to %s)" % (ROIC_CSV.name, len(rows), rows[0]["date"], rows[-1]["date"]))
    return rows


def build(log=print):
    inputs = model.prepare(ROOT, log=log)
    dials = model.default_dials(inputs)
    res = model.compute(inputs, dials)
    today = roic_row(inputs, dials, res)
    rows = record_roic(today, log=log)
    # the day's market inputs, so any later change of assumptions can be applied to this day too (engine/restate.py)
    RS.save_snapshot(ROOT, today["date"], today["built_at"])
    basis = RS.history_basis(ROOT, rows, inputs, dials, log=log)
    live = {k: RS._f(today.get(c)) for c, k in RS.PRIM_COLS}
    gap = max(abs(live[k] - v) / max(abs(v), 1e-9) for k, v in basis["rows"][-1]["prim"].items() if v is not None and live.get(k) is not None)
    if gap > 2e-5:          # the CSV keeps 4 decimals (rent_rate_spot is an average of many quotes now), so 1e-5 relative is rounding
        log("build: WARNING today's snapshot re-run differs from the build (relative gap %.1e)" % gap)
    tk = basis["rows"][-1].get("tok") or {}
    for k in ("anthropic", "openai"):
        a_, b_ = RS._f(today.get("frontier_rev_gpu_hr_" + k)), (tk.get("rev") or {}).get(k)
        if a_ and b_ and abs(a_ - b_) / a_ > 2e-4:
            log("build: WARNING today's %s closed-basket revenue per GPU-hour from the snapshot re-run (%.4f) differs from the build (%.4f)" % (k, b_, a_))
    inputs["roic_history"] = {"rows": rows, "columns": ROIC_COLS, "file": "data/" + ROIC_CSV.name, "basis": basis}
    # the near-term rental bases on every day of the provider rate history (the rental market page draws them)
    from engine import rental_history as RHX
    A_rental = json.load(open(ROOT / "assumptions.json", encoding="utf-8"))["rental"]
    hist = inputs.get("history") or {}
    meta = {RHX.key_of(q): q for q in inputs["rental"]["quotes"] if q.get("tier") != "index"}
    start = RHX.coverage_start(hist, set(inputs["rental"]["chips_for_average"]))
    inputs["rental"]["near_history"] = RHX.near_history(hist, A_rental, inputs["rental"]["max_quote_age_days"], start=start, end=today["date"], meta=meta)
    # weekly token revenue on OpenRouter (display only; not a model input)
    from engine import collect_token_revenue as TR
    try:
        inputs["token_revenue"] = TR.page_view(TR.load(ROOT)) if (ROOT / "data" / "token_revenue.json").exists() else None
    except Exception as ex:
        log("build: token revenue not embedded (%s)" % ex)
        inputs["token_revenue"] = None
    slim = {k: res[k] for k in ("rent", "serve", "serves", "serve_open", "serve_open_peak", "tmeta", "capex", "depreciation", "dep", "gpus", "unmeasured_share_of_open")}
    tpl = (ROOT / "engine" / "template.html").read_text(encoding="utf-8")
    marker = "/*__DATA__*/\nconst INPUTS = {};\nconst PY = {};"
    if marker not in tpl:
        raise SystemExit("template marker not found")
    blob = "/*__DATA__*/\nconst INPUTS = %s;\nconst PY = %s;" % (
        json.dumps(inputs, separators=(",", ":")).replace("</", "<\\/"),
        json.dumps(slim, separators=(",", ":"), default=lambda o: None).replace("</", "<\\/"))
    out = ROOT / "dashboard.html"
    page = tpl.replace(marker, blob)
    out.write_text(page, encoding="utf-8")
    (ROOT / "index.html").write_text(page, encoding="utf-8")     # the same page under the name GitHub Pages serves first

    s, r, F = res["serve"], res["rent"], inputs["fleet"]
    def serve_line(x):
        return {"basket": x["basket"], "rev_per_gpu_hr": x["rev_per_gpu_hr"], "blended_per_m_out": x.get("blended_per_m_out"), "eff_tps": x.get("eff_tps"), "closed_share": x.get("closed_share"),
                "ebitda": x["ebitda"], "roic": x["roic"], "irr": x["irr"], "f_frontier": x.get("f_frontier"), "f_open_median": x.get("f_open_median"),
                "rate_f": x.get("rate_f"), "rate_f_base": x.get("rate_f_base"), "renter_roic": x.get("renter_roic"), "training_share": x.get("training_share"), "rev_share": x.get("rev_share"),
                "frontier": [[y["id"], round(y["share"], 4), round(y["p_out"], 3), round(y["tps"]), round(y["f"], 4)] for y in x.get("frontier_rows", [])],
                "open": [[y["id"], round(y["share"], 4), round(y["p_out"], 3), round(y["tps"]), round(y["f"], 4)] for y in x.get("open_rows", []) if y["share"] > 0]}
    line = {
        "built_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "openrouter_read_on": inputs["openrouter"]["read_on"], "inferencex_read_on": inputs["throughput_meta"]["read_on"], "mastersheet": F["mastersheet"].get("fingerprint"),
        "gpus": F["gpus"], "capex_usd": F["capex_usd"],
        "rent": {"basis": r["basis"], "rate": r["rate"], "near_basis": r["near_basis"], "rate_near": r["rate_near"], "rate_path": [round(v, 4) for v in r["rate_path"]],
                 "rev_per_gpu_hr": r["rev_per_gpu_hr"], "ebitda": r["ebitda"], "roic": r["roic"], "roic_y1": r["roic_y1"], "irr": r["irr"]},
        "serve": serve_line(s),
        "serves": {k: serve_line(v) for k, v in res["serves"].items()}, "serve_open": serve_line(res["serve_open"]), "serve_open_peak": serve_line(res["serve_open_peak"]), "serve_aws": serve_line(res["serve_aws"]),
        "unmeasured_share_of_open": res["unmeasured_share_of_open"], "estimated_share_of_open": res["estimated_share_of_open"],
        "horizon_years": int(dials["life"]), "compute_life_years": dials.get("compute_life", ""), "shell_life_years": dials.get("shell_life", ""),
        "depreciation_avg_usd": int(round(res["depreciation"])), "terminal_value_usd": int(round((res.get("dep") or {}).get("terminal", 0))),
        "throughput_scope": dials["throughput_scope"], "volumes": dials["volumes"], "traces_read_on": inputs["demand"]["traces"].get("read_on"),
    }
    with open(ROOT / "data" / "history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")
    log("build: %s  rent $%.2f/GPU-hr (ROIC %.1f%%, y1 %.1f%%)  %s  frontier %.0f%% of tokens; %.0f%% of open traffic unbenchmarked" % (
        out.name, r["rev_per_gpu_hr"], 100 * r["roic"], 100 * r["roic_y1"],
        "  ".join("serve/%s $%.2f (ROIC %.1f%%)" % (k, v["rev_per_gpu_hr"], 100 * v["roic"]) for k, v in list(res["serves"].items()) + [("open-only", res["serve_open"]), ("open-peak", res["serve_open_peak"]), ("aws", res["serve_aws"])]),
        100 * s["closed_share"], 100 * res["unmeasured_share_of_open"]))
    if not F["mastersheet"].get("found"):
        log("build: WARNING AI mastersheet.xlsx not found; fallback capital/power values used (the page says so).")
    return res


if __name__ == "__main__":
    build()
