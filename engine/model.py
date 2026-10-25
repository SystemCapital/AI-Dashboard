"""
The arithmetic. Two halves:

  prepare(root)          reads assumptions.json, data/*.json and the mastersheet, and resolves every market
                         input ONCE into a compact `inputs` block with provenance: per-model prices and
                         throughput curves, per-task-type demand and open-weight candidates, rental evidence,
                         capital and power. Nothing here depends on a dial.
  compute(inputs, dials) the pure model: routing, the frontier vs open split under the split mode (framework + premium
                         tolerance | OpenRouter's weekly closed share | manual), throughput at the
                         interactivity target, per-model market-implied realisation, fleet allocation, revenue,
                         costs, the rental term structure and the returns of every scenario (rent, serve with
                         the Anthropic basket, serve with the OpenAI basket). The page carries a JavaScript twin
                         of this function (template.html, function compute) and re-runs it on every dial move;
                         build.py embeds the Python result so the page can check the two agree.

Standard library only.
"""
import json, math, datetime
from pathlib import Path

HOURS = 8760.0
HW_OTHER = ["GB200", "B300", "B200"]          # Blackwell parts a GB300 rate can be implied from, in order of preference


# ----------------------------------------------------------------------------------------------- helpers
def median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else 0.5 * (xs[n // 2 - 1] + xs[n // 2])


def wmedian(pairs):
    """Weighted median of (value, weight) pairs."""
    pairs = sorted((p for p in pairs if p[1] > 0), key=lambda p: p[0])
    tot = sum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= tot / 2:
            return v
    return pairs[-1][0] if pairs else None


def interp_curve(points, inter, col):
    """Log-linear interpolation of column `col` of the curve at `inter` tok/s/user; clamped to the measured range."""
    pts = sorted(points, key=lambda p: p[0])
    if inter <= pts[0][0]:
        return pts[0][col], (inter < pts[0][0])
    if inter >= pts[-1][0]:
        return pts[-1][col], (inter > pts[-1][0])
    for p0, p1 in zip(pts, pts[1:]):
        if p0[0] <= inter <= p1[0]:
            if p1[0] == p0[0]:
                return p0[col], False
            f = (inter - p0[0]) / float(p1[0] - p0[0])
            y0, y1 = max(p0[col], 1e-9), max(p1[col], 1e-9)
            return math.exp(math.log(y0) + f * (math.log(y1) - math.log(y0))), False
    return pts[-1][col], True


def irr(cashflows, lo=-0.99, hi=1000.0):
    """Bisection IRR on annual cashflows [c0, c1, ...]; None if there is no sign change."""
    def npv(r):
        return sum(c / (1 + r) ** t for t, c in enumerate(cashflows))
    if not (cashflows[0] < 0 and any(c > 0 for c in cashflows[1:])):
        return None
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        f_mid = npv(mid)
        if abs(f_mid) < 1e-6:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return 0.5 * (lo + hi)


def strip_variant(p):
    import re
    return re.sub(r":(free|batch|exacto|thinking|nitro|floor|fast)$", "", p)


def guess_slug(p):
    import re
    return re.sub(r"-\d{8}$", "", strip_variant(p))


# ----------------------------------------------------------------------------------------------- prepare
MARKET_FILES = ("openrouter.json", "throughput.json", "lab_prices.json", "rental_rates.json")   # a day's market inputs (engine/restate.py snapshots them)


def prepare(root, log=print, market=None):
    """market: optional {file name: parsed JSON} for MARKET_FILES, used in place of data/ (restating a past day
    from its snapshot under today's assumptions); everything else is read from root as usual."""
    root = Path(root)
    A = json.load(open(root / "assumptions.json", encoding="utf-8"))
    D = root / "data"
    mk = lambda name: market[name] if market and name in market else json.load(open(D / name, encoding="utf-8"))
    OR = mk("openrouter.json")
    REG = json.load(open(D / "models.json", encoding="utf-8"))
    TP = mk("throughput.json")
    LAB = mk("lab_prices.json")
    RENT = mk("rental_rates.json")

    # --- registry: id -> row; alias -> id
    reg = {m["id"]: m for m in REG["models"]}
    alias = {}
    for m in REG["models"]:
        for a in m.get("aliases", []):
            alias[a] = m["id"]
        alias[m["id"]] = m["id"]

    def slug_of(permaslug):
        q = strip_variant(permaslug)
        c = OR["catalog"].get(q)
        return c[0] if c else guess_slug(permaslug)

    def id_of(permaslug):
        s = slug_of(permaslug)
        if s in alias:
            return alias[s]
        g = guess_slug(permaslug)
        return alias.get(g)

    # --- mastersheet
    from engine import read_mastersheet as rm
    ms = rm.read(root, A["mastersheet"]["cells"], A["mastersheet"].get("path"))
    fb = A["fallback_if_mastersheet_missing"]
    msv = {}
    for k in fb:
        if k == "note":
            continue
        v = ms["values"].get(k, {}).get("value") if ms["found"] else None
        msv[k] = {"value": (v if v is not None else fb[k]), "cell": (ms["values"].get(k, {}).get("cell") if ms["found"] and v is not None else None),
                  "basis": ("mastersheet" if (ms["found"] and v is not None) else "fallback")}
    ov = A["overrides"]
    def pick(k):
        return ov.get(k) if ov.get(k) is not None else msv[k]["value"]
    gpus = msv["gpus"]["value"]
    kw_per_gpu = msv["kw_per_rack"]["value"] / msv["gpus_per_rack"]["value"]
    capex_usd = msv["total_capex_musd"]["value"] * 1e6
    fleet = {
        "chip": A["site"]["chip"], "chip_label": A["site"]["chip_label"], "site_mw": msv["site_mw"]["value"],
        "gpus": gpus, "gpus_per_rack": msv["gpus_per_rack"]["value"], "racks": gpus / msv["gpus_per_rack"]["value"],
        "gpu_cost": msv["gpu_cost"]["value"], "rack_cost_usd": msv["rack_cost_musd"]["value"] * 1e6,
        "capex_usd": capex_usd, "capex_per_gpu": capex_usd / gpus,
        "shell_cost_usd": (msv["shell_cost_musd"]["value"] or 0) * 1e6,
        "kw_per_gpu": kw_per_gpu, "pue": msv["pue"]["value"], "it_mw": gpus * kw_per_gpu / 1000.0,
        "facility_mw": gpus * kw_per_gpu * msv["pue"]["value"] / 1000.0,
        "power_price_mwh": pick("power_price_mwh"), "roic_sheet_power_price": msv["roic_power_price"]["value"],
        "other_opex_usd": pick("other_opex_musd") * 1e6,
        "rent_util": pick("rent_util"), "serve_util": pick("serve_util"),
        "gpus_per_it_mw": 1000.0 / kw_per_gpu,
        "provenance": {k: msv[k] for k in msv},
        "mastersheet": {k: v for k, v in ms.items() if k != "values"},
        "overrides": {k: v for k, v in ov.items() if k != "note" and v is not None},
    }

    # --- rental evidence: long-term bases and near-term bases (engine/rental_history.py computes the near-term ones, for
    # today from data/rental_rates.json and for any past date from data/rate_history.json, with one piece of arithmetic)
    from engine import rental_history as RHX
    RA = A["rental"]
    TS = RA["term_structure"]
    max_age = int(RA.get("max_quote_age_days", 10))
    ref_date = max((q["read_on"] for q in RENT["quotes"] if q.get("read_on")), default=datetime.date.today().isoformat())
    cur_quotes = RHX.current(RENT["quotes"], ref_date, max_age)
    chips_od = set(RA["chips_for_ondemand"])
    od_rows = [q for q in cur_quotes if q["chip"] in chips_od and q["tier"] in ("on-demand", "capacity-block") and q["per_gpu_hr"]]
    idx_rows = [q for q in RENT["quotes"] if q["tier"] == "index" and q["per_gpu_hr"] and q["vendor"] in ("Silicon Data", "Ornn")]
    # contract rows that may enter the medians: active GB300 / B300 GPU rentals (and market references) with a derivable rate
    ct_rows = [c for c in RENT["contracts"] if c.get("per_gpu_hr") and c.get("use", True)]
    NOMINAL_GPUS = 10000.0                      # weight given to a reference quote with no GPU count in the GPU-weighted median
    ct_w = wmedian([(c["per_gpu_hr"], float(c.get("gpus") or NOMINAL_GPUS)) for c in ct_rows])
    # GPU-rental deals disclosed as value / term / MW (GB300 and Vera Rubin alike): $ per MW-year, converted at this
    # fleet's density; MW quoted as facility power carries PUE-fewer GPUs than MW quoted as IT
    def mw_rate(c):
        dens = fleet["gpus_per_it_mw"] / (fleet["pue"] if c.get("mw_basis") == "facility" else 1.0)
        return c["value_usd_b"] * 1e9 / (c["term_years"] * HOURS * c["mw"] * dens)
    mw_rows = [c for c in RENT["contracts"] if c.get("kind") == "gpu-rental" and c.get("status", "active") == "active" and not c.get("cancellable")
               and c.get("value_usd_b") and c.get("term_years") and c["term_years"] >= 3 and c.get("mw")]
    mw_w = wmedian([(mw_rate(c), float(c["mw"])) for c in mw_rows])
    acv_rows = [c for c in RENT["contracts"] if c.get("acv_per_it_mw_yr_musd")]
    acv = median([c["acv_per_it_mw_yr_musd"] for c in acv_rows])
    near_opts = RHX.near_options(RENT["quotes"], RA, ref_date, max_age)
    rental = {
        "basis": RA["basis"],
        "options": {
            "contract": {"rate": ct_w, "n": len(ct_rows), "label": "Long-term contract, GPU-weighted median of disclosed GB300/B300 deals",
                         "rows": [[c["parties"], c["per_gpu_hr"], c.get("gpus")] for c in ct_rows]},
            "contract_median": {"rate": median([c["per_gpu_hr"] for c in ct_rows]), "n": len(ct_rows), "label": "Long-term contract, simple median of the same deals"},
            "mw_deals": {"rate": mw_w, "n": len(mw_rows), "label": "GPU-rental deals priced per MW (MW-weighted median, at this fleet's GPUs per MW)",
                         "rows": [[c["parties"], round(mw_rate(c), 2), c["mw"], c.get("mw_basis"), c.get("per_mw_yr_musd")] for c in mw_rows]},
            "ondemand": {"rate": median([q["per_gpu_hr"] for q in od_rows]), "n": len(od_rows), "label": "On-demand list (median of published GB200/GB300 quotes)"},
            "acv2026": {"rate": (acv * 1e6 / (fleet["gpus_per_it_mw"] * HOURS)) if acv else None, "n": len(acv_rows),
                         "acv_musd_per_it_mw": acv, "label": "2026 new-deal ACV per IT-MW (IREN, Nebius) at this fleet's density"},
        },
        "near_basis": TS["near_term_basis"],
        "near_options": near_opts,
        "max_quote_age_days": max_age, "ref_date": ref_date, "chips_for_average": TS.get("chips_for_average", TS["chips_for_spot"]),
        "indices": [{"vendor": q["vendor"], "chip": q["chip"], "rate": q["per_gpu_hr"], "read_on": q["read_on"], "as_of": q.get("as_of"), "url": q["url"], "instance": q["instance"], "note": q.get("note", "")} for q in idx_rows],
        "converge_years": TS["converge_years"], "spot_years": TS.get("spot_years", 1),
        "quotes": RENT["quotes"], "contracts": RENT["contracts"],
        "changes": RENT.get("changes", []), "notices": RENT.get("notices", []), "price_news": RENT.get("price_news", []), "price_actions": RENT.get("price_actions", []),
        "bases_note": RA["bases"], "near_bases_note": TS["near_term_bases"], "term_note": TS["note"],
    }

    # --- demand: the task framework, with measured per-run volumes where a task maps to an agent-trace family
    TT = {k: v for k, v in A["task_types"].items() if not k.startswith("_")}
    rule = A["frontier_rule"]
    TR = json.load(open(D / "traces.json", encoding="utf-8")) if (D / "traces.json").exists() else {"agg": {}}
    agg = TR.get("agg", {})
    def pooled(rows, basis):
        n = sum(r["n_runs"] for r in rows)
        return {"n_runs": n, "out_tok": sum(r["out_tok"] * r["n_runs"] for r in rows) / n, "in_tok": sum(r["in_tok"] * r["n_runs"] for r in rows) / n,
                "spans": sum(r["spans"] * r["n_runs"] for r in rows) / n, "cached_share": sum(r["cached_share"] * r["n_runs"] for r in rows) / n,
                "success": sum(r["success"] * r["n_runs"] for r in rows) / n, "score": sum(r["score"] * r["n_runs"] for r in rows) / n,
                "in_basis": basis, "harnesses": sorted({h for r in rows for h in r["harnesses"]})}
    for fam, byfam in agg.items():
        base = {k: v for k, v in byfam.items() if k in ("anthropic", "openai", "deepseek", "kimi", "google")}
        opens = [base[k] for k in ("deepseek", "kimi") if k in base]
        if opens:                              # open-weight average = run-weighted mean of the open families
            byfam["open_avg"] = pooled(opens, "run-weighted mean of the DeepSeek and Kimi rows")
        if base:                               # pooled = every model family together (removes provider accounting differences)
            byfam["all"] = pooled(list(base.values()), "run-weighted mean of every model family")

    def frontier_share(task):
        if task.get("frontier") is not None:
            return float(task["frontier"])
        return max(0.0, min(1.0, (max(task["reasoning"], task["consequence"]) - 2) / 3.0))
    tasks_out = []
    for task in A["tasks"]:
        f = frontier_share(task)
        fw_out = task["calls"] * sum(w * TT[t]["tout"] for t, w in task["mix"].items())
        fw_in = task["calls"] * sum(w * TT[t]["tin"] for t, w in task["mix"].items())
        tf = task.get("trace_family")
        tasks_out.append({"name": task["name"], "group": task["group"], "runs": task["runs"], "calls": task["calls"],
                          "reasoning": task["reasoning"], "consequence": task["consequence"], "frontier": f,
                          "mix": task["mix"], "fw_out": fw_out, "fw_in": fw_in,
                          "trace_family": (tf if tf in agg else None), "trace_note": (TR.get("families", {}).get(tf) if tf in agg else None),
                          "top_types": sorted(task["mix"].items(), key=lambda kv: -kv[1])[:3]})
    demand = {
        "types": {t: {"name": TT[t]["name"], "tag": TT[t]["tag"], "tin": TT[t]["tin"], "tout": TT[t]["tout"]} for t in TT},
        "tasks": tasks_out,
        "frontier_rule": rule["formula"], "heads": A["workload_profile"]["heads"],
        "traces": {"agg": agg, "families": TR.get("families", {}), "model_families": TR.get("model_families", {}), "source": TR.get("source"),
                   "read_on": TR.get("read_on"), "sessions": TR.get("sessions"), "spans": TR.get("spans"), "collected": TR.get("collected"),
                   "rows": TR.get("rows", []), "columns": TR.get("columns", [])},
        "trace_note": A.get("trace_mapping_note", ""),
    }

    # --- OpenRouter: tokens view per tag -> open-weight candidates; models_week -> per-model volume
    tag_view = {t[0]: t for t in OR["task_spend"]["tokens"]}
    weekly = {}
    for perma, variant, ptok, ctok, req in OR["models_week"]["rows"]:
        mid = id_of(perma)
        if mid:
            w = weekly.setdefault(mid, {"prompt": 0, "completion": 0, "requests": 0})
            w["prompt"] += ptok
            w["completion"] += ctok
            w["requests"] += req
    total_week = sum(w["prompt"] + w["completion"] for w in weekly.values())
    or_week_all = {"prompt": sum(r[2] for r in OR["models_week"]["rows"]), "completion": sum(r[3] for r in OR["models_week"]["rows"]),
                   "requests": sum(r[4] for r in OR["models_week"]["rows"]), "rows": len(OR["models_week"]["rows"])}
    # closed-weight share of the week's OpenRouter tokens, every model in the ranking: the registry says open or closed
    # where a model is mapped, the catalog's published-weights flag otherwise (the 'openrouter' split mode uses this)
    tok_split = {"open": [0, 0], "closed": [0, 0], "unknown": [0, 0]}
    for perma, variant, ptok, ctok, req in OR["models_week"]["rows"]:
        mid = id_of(perma)
        c = OR["catalog"].get(strip_variant(perma))
        # catalog rows carry the hf_slug (live reads) or "(published)" (the legacy import): any non-empty value = open weights
        k = ("open" if reg[mid]["weights"] == "open" else "closed") if mid else (("open" if c[2] else "closed") if c else "unknown")
        tok_split[k][0] += ptok
        tok_split[k][1] += ctok
    known_out = tok_split["open"][1] + tok_split["closed"][1]
    known_all = sum(tok_split[k][0] + tok_split[k][1] for k in ("open", "closed"))
    all_tok = known_all + tok_split["unknown"][0] + tok_split["unknown"][1]
    closed_share_week = {"out": (tok_split["closed"][1] / known_out if known_out else None), "total": (tok_split["closed"][0] + tok_split["closed"][1]) / known_all if known_all else None,
                         "unknown_share": ((tok_split["unknown"][0] + tok_split["unknown"][1]) / all_tok if all_tok else 0.0), "rows": len(OR["models_week"]["rows"]),
                         "week_date": OR.get("week_date"), "read_on": OR["read_on"],
                         "basis": "completion tokens of every model in OpenRouter's weekly ranking, closed = weights not published (registry flag where mapped, catalog flag otherwise)"}

    candidates, unlisted = {}, {}
    for t, spec in TT.items():
        view = tag_view.get(spec["tag"])
        if not view:
            candidates[t] = {"list": [], "basis": "no OpenRouter tag; inherits the overall open-weight mix"}
            continue
        acc = {}
        for perma, share in view[3]:
            mid = id_of(perma)
            if mid is None:
                unlisted[slug_of(perma)] = unlisted.get(slug_of(perma), 0) + share
                continue
            m = reg[mid]
            if m["weights"] != "open":
                continue
            acc[mid] = acc.get(mid, 0.0) + share
        candidates[t] = {"list": sorted(acc.items(), key=lambda kv: -kv[1]),
                         "open_share_measured": sum(acc.values()), "traffic_share": view[2],
                         "basis": "OpenRouter tokens view, 30-day window"}
    overall = {}
    for mid, w in weekly.items():
        if reg[mid]["weights"] == "open":
            overall[mid] = w["prompt"] + w["completion"]
    overall_list = sorted(overall.items(), key=lambda kv: -kv[1])[:15]
    s = sum(v for _, v in overall_list) or 1.0
    overall_list = [[k, v / s] for k, v in overall_list]
    for t in candidates:
        if not candidates[t]["list"]:
            candidates[t]["list"] = overall_list
            candidates[t]["inherited"] = True

    # --- prices per model: list (cheapest host / lab list) and effective (OpenRouter traffic-weighted)
    ST = OR.get("stats", {})
    prices, stats_by_id, providers_by_id = {}, {}, {}
    for mid, m in reg.items():
        st, ep = None, None
        for a in m.get("aliases", []):
            if st is None and a in ST:
                st = ST[a]
            if ep is None and a in OR["endpoints"]:
                ep = OR["endpoints"][a]
        if st:
            stats_by_id[mid] = st
        # every host's list price and every provider's effective price for the week, kept for the provider-prices panel:
        # hosts rows [name, in, out, cache_read, context, quant, uptime_30m, tag]; week rows [name, eff_in, eff_out, cache_hit, tokens_week, tps]
        providers_by_id[mid] = {"hosts": list((ep or {}).get("hosts") or []), "week": list((st or {}).get("providers") or []),
                                "week_tokens": sum(int(p[4] or 0) for p in (st or {}).get("providers") or []),
                                "or_url": ("https://openrouter.ai/" + m["aliases"][0]) if m.get("aliases") else None}
        if mid in LAB["models"]:
            L = LAB["models"][mid]
            prices[mid] = {"in": L["in"], "out": L["out"], "cache": L["cache_read"], "provider": "%s list price" % L.get("lab", m["lab"]),
                           "basis": "lab list price", "hosts": None, "url": L["url"], "read_on": L["read_on"], "list_note": L.get("note", "")}
        else:
            if not ep or not ep["hosts"]:
                continue
            hosts = [h for h in ep["hosts"] if h[2] is not None and h[2] > 0]
            if not hosts:
                continue
            best = sorted(hosts, key=lambda h: (h[2], h[1]))[0]
            prices[mid] = {"in": best[1], "out": best[2], "cache": (best[3] if best[3] is not None else best[1]), "provider": best[0],
                           "basis": "cheapest host by output price", "hosts": len(hosts), "median_out": median([h[2] for h in hosts]),
                           "dearest_out": max(h[2] for h in hosts), "quant": best[5], "url": "https://openrouter.ai/" + m["aliases"][0],
                           "read_on": OR["read_on"]}
        if st:
            prices[mid]["eff_in"], prices[mid]["eff_out"], prices[mid]["cache_hit"] = st["eff_in"], st["eff_out"], st["cache_hit"]
            prices[mid]["eff_hosts"] = len(st.get("providers", []))
            prices[mid]["eff_basis"] = "OpenRouter traffic-weighted effective price, trailing week"

    # --- throughput curves (InferenceX API frontier: [inter, output tok/s/GPU, input tok/s/GPU], system-wide)
    chip = A["site"]["chip"]
    curve_by_name = {}
    for row in TP["curves"]:
        name, hw, workload, n, date, precs, fws, pts = row
        curve_by_name.setdefault(name, []).append({"hw": hw, "workload": workload, "n": n, "date": date, "precisions": precs,
                                                   "frameworks": fws, "points": pts, "url": TP["source"].replace("<name>", name)})
    workloads = {"8k/1k": {"isl": 8192, "osl": 1024}, "1k/1k": {"isl": 1024, "osl": 1024}}

    # --- models block: every priced model that is not excluded (eligibility for the mix is decided per workload in compute)
    baskets = {k: v for k, v in A["frontier_baskets"].items()}
    basket_members = {mid for b in baskets.values() for mid in b["models"]}
    models = {}
    for mid, m in reg.items():
        if m.get("tier") in ("excluded", "other-closed"):
            continue
        if m.get("tier") == "frontier" and mid not in basket_members:
            continue
        if mid not in prices and not (m.get("tier") == "benchmark-only" or (m["weights"] == "open" and m.get("inferencex"))):
            continue
        w = weekly.get(mid)
        st = stats_by_id.get(mid)
        act = st["activity7d"] if st else None
        models[mid] = {
            "id": mid, "name": m["name"], "lab": m["lab"], "weights": m["weights"], "tier": m.get("tier", "open"),
            "total_b": m.get("total_b"), "active_b": m.get("active_b"), "inferencex": m.get("inferencex"), "inferencex_note": m.get("inferencex_note"),
            "inferencex_family": m.get("inferencex_family"), "family_note": m.get("family_note"), "trace_family": m.get("trace_family", "open_avg"),
            "price": prices.get(mid), "url": m.get("url"), "providers": providers_by_id.get(mid),
            "or_week": ({"prompt": w["prompt"], "completion": w["completion"], "requests": w["requests"],
                         "share": (w["prompt"] + w["completion"]) / total_week if total_week else 0,
                         "in_out_ratio": (w["prompt"] / w["completion"] if w["completion"] else None)} if w else None),
            "measured": ({"tps_user": st["tps_wmedian"], "cache_hit": st["cache_hit"], "hosts": len(st.get("providers", [])),
                          "in_out": (act["prompt"] / act["completion"] if act and act["completion"] else None),
                          "cached_share": (act["cached"] / act["prompt"] if act and act["prompt"] else None),
                          "reasoning_share": (act["reasoning"] / act["completion"] if act and act["completion"] else None)} if st else None),
            "curves": curve_by_name.get(m.get("inferencex") or "", []),
        }
    basket_out = {}
    for key, b in baskets.items():
        rows = []
        for mid in b["models"]:
            if mid in models:
                w = weekly.get(mid)
                rows.append([mid, (w["prompt"] + w["completion"]) if w else 0])
        bs = sum(v for _, v in rows) or 1.0
        basket_out[key] = {"label": b["label"], "weights": [[mid, v / bs] for mid, v in rows], "note": b["note"],
                           "week_tokens": sum(v for _, v in rows)}

    VT = json.load(open(D / "vendor_throughput.json", encoding="utf-8")) if (D / "vendor_throughput.json").exists() else {"points": []}
    ANCH = json.load(open(D / "anchors.json", encoding="utf-8")) if (D / "anchors.json").exists() else {"anchors": []}
    HIST = json.load(open(D / "rate_history.json", encoding="utf-8")) if (D / "rate_history.json").exists() else {"silicon_index": {"series": {}}, "spot": {"series": {}}}
    HIST = {k: v for k, v in HIST.items() if not k.startswith("_")}
    DEALS = json.load(open(D / "deal_candidates.json", encoding="utf-8")) if (D / "deal_candidates.json").exists() else {"candidates": [], "scanned_on": None}
    S = A["serving"]
    inputs = {
        "built_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "fleet": fleet,
        "rental": rental,
        "finance": {k: v for k, v in A["finance"].items() if k != "note"}, "finance_note": A["finance"].get("note", ""),
        "serving_defaults": {k: v for k, v in S.items() if k != "notes"},
        "aws": {k: v for k, v in (A.get("aws") or {}).items()},
        "serving_notes": S["notes"],
        "workloads": workloads,
        "demand": demand,
        "candidates": candidates,
        "overall_open": overall_list,
        "unlisted_models": sorted(unlisted.items(), key=lambda kv: -kv[1])[:10],
        "models": models,
        "baskets": basket_out,
        "chip": chip,
        "anchors": ANCH["anchors"],
        "vendor_points": VT.get("points", []),
        "openrouter": {"read_on": OR["read_on"], "week_date": OR.get("week_date"), "window_days": OR["task_spend"]["window_days"], "closed_share_week": closed_share_week,
                       "source": OR["source"], "license": OR["license"], "basis": OR.get("basis"),
                       "stats_source": OR.get("stats_source"), "n_stats": len(ST),
                       "macro_tokens": OR["task_spend"].get("macro_tokens"), "macro_spend": OR["task_spend"].get("macro_spend"),
                       "spend_view": OR["task_spend"].get("spend"), "week_totals": or_week_all},
        "throughput_meta": {"curves": len(TP["curves"]), "read_on": TP.get("read_on"), "source": TP.get("source"), "license": TP.get("license"),
                            "newest_run": max(r[4] for r in TP["curves"]), "reference_points": TP.get("reference_points", []),
                            "api_models": TP.get("api_models", []), "api_models_note": TP.get("api_models_note", "")},
        "lab_prices_meta": {"read_on": max(m["read_on"] for m in LAB["models"].values()),
                            "urls": sorted({m["url"] for m in LAB["models"].values()})},
        "rental_meta": {"read_on": max(q["read_on"] for q in RENT["quotes"] if q.get("read_on")), "refreshed_at": RENT.get("refreshed_at")},
        "history": HIST,
        "or_share": (json.load(open(D / "openrouter_share.json", encoding="utf-8")) if (D / "openrouter_share.json").exists() else None),
        "deal_scout": {"scanned_on": DEALS.get("scanned_on"), "errors": DEALS.get("errors", []), "edgar": bool(DEALS.get("edgar_phrases")),
                       "candidates": [{k: c.get(k) for k in ("title", "link", "source", "published", "channel", "value_usd_b", "term_years", "gpus", "mw", "chip", "parties", "first_seen", "kind_guess", "matched_contract")}
                                      for c in DEALS.get("candidates", []) if c.get("status") == "new"]},
    }
    return inputs


# ----------------------------------------------------------------------------------------------- compute
def default_dials(inputs):
    S = inputs["serving_defaults"]
    F = inputs["finance"]
    R = inputs["rental"]
    return {
        "interactivity": S["interactivity_tok_s_per_user"], "interactivity_basis": S.get("interactivity_basis", "measured"),
        "workload": S["workload"], "price_basis": S.get("price_basis", "effective"),
        "cache_hit_rate": S["cache_hit_rate"], "frontier_derate": S["frontier_derate"], "realisation": S["realisation"],
        "tps_realisation": S.get("tps_realisation", "market"), "frontier_realisation": S.get("frontier_realisation", "reference"),
        "implied_rate": S.get("implied_rate", "spot"), "renter_roic": S.get("renter_roic", 0.0),
        "throughput_scope": S.get("throughput_scope", "measured"), "volumes": S.get("volumes", "traces"),
        "split_mode": S.get("split_mode", "cost"), "premium_tolerance": S.get("premium_tolerance"),
        "training_share": S.get("training_share", 0.0), "aws_rev_share": (inputs.get("aws") or {}).get("rev_share", 0.25),
        "closed_override": S["closed_share_override"], "closed_override_openai": S.get("closed_share_override_openai"),
        "basket": S.get("basket", "anthropic"),
        "rental_basis": R["basis"], "rental_rate_override": None,
        "near_basis": R["near_basis"], "near_rate_override": None, "converge_years": R["converge_years"], "spot_years": R.get("spot_years", 1),
        "rent_util": inputs["fleet"]["rent_util"], "serve_util": inputs["fleet"]["serve_util"],
        "power_price": inputs["fleet"]["power_price_mwh"], "other_opex": inputs["fleet"]["other_opex_usd"],
        "life": F["life_years"], "compute_life": F.get("compute_life_years", F["life_years"]), "shell_life": F.get("shell_life_years", F["life_years"]),
        "compute_residual": F.get("compute_residual", F.get("residual", 0.0)), "shell_residual": F.get("shell_residual", 0.0),
        "rent_decline": F["rental_rate_decline_per_year"], "token_decline": F["token_price_decline_per_year"],
    }


def logfit(xs, ys):
    """Least-squares fit of log(y) = a + b log(x). Returns (a, b, r2, n)."""
    pts = [(math.log(x), math.log(y)) for x, y in zip(xs, ys) if x > 0 and y > 0]
    n = len(pts)
    if n < 2:
        return None, None, None, n
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
    if sxx == 0:
        return my, 0.0, 0.0, n
    b = sxy / sxx
    a = my - b * mx
    ss_tot = sum((p[1] - my) ** 2 for p in pts)
    ss_res = sum((p[1] - (a + b * p[0])) ** 2 for p in pts)
    return a, b, (1 - ss_res / ss_tot if ss_tot else 1.0), n


def resolve_tps(inputs, dials):
    """Benchmark output and input tokens/s per GPU per model on the chip, at that model's interactivity.
    Returns ({id: {...}}, meta). Under scope 'measured' only a model's own InferenceX runs count (on the chip, or
    on another Blackwell part scaled by the measured chip ratio). Under scope 'estimated' a model with no runs of
    its own takes the curve of the same architecture under another name (family), else a log-log fit of output
    tok/s per GPU on active parameters across every benchmarked model at its interactivity (fitted). The frontier
    basket always borrows the largest measured open model's curve at the derate."""
    chip, wl = inputs["chip"], dials["workload"]
    M = inputs["models"]
    fixed = dials["interactivity"]
    scope = dials.get("throughput_scope", "measured")
    W = inputs["workloads"][wl]
    R_wl = W["isl"] / float(W["osl"])

    def inter_of(m):
        if dials["interactivity_basis"] == "measured" and m.get("measured") and m["measured"].get("tps_user"):
            return m["measured"]["tps_user"], "measured"
        return fixed, "fixed"

    def read(m, hw, inter):
        for c in m["curves"]:
            if c["hw"] == hw and c["workload"] == wl and len(c["points"]) >= 2:
                out, clamped = interp_curve(c["points"], inter, 1)
                inp, _ = interp_curve(c["points"], inter, 2)
                return out, inp, clamped, c
        return None, None, False, None

    ratios = {}
    for hw in HW_OTHER:
        rs = []
        for m in M.values():
            inter, _ = inter_of(m)
            a, _, _, _ = read(m, chip, inter)
            b, _, _, _ = read(m, hw, inter)
            if a and b:
                rs.append(a / b)
        ratios[hw] = {"ratio": median(rs) or 1.0, "n": len(rs)}

    def own(m, inter):
        """The model's own benchmark on the chip, or on another part x ratio. Returns dict or None."""
        o, i, clamped, c = read(m, chip, inter)
        if o:
            return {"tps": o, "tps_in": i, "hw": chip, "clamped": clamped, "c": c, "k": 1.0}
        for hw in HW_OTHER:
            o, i, clamped, c = read(m, hw, inter)
            if o:
                k = ratios[hw]["ratio"]
                return {"tps": o * k, "tps_in": i * k, "hw": hw, "clamped": clamped, "c": c, "k": k}
        return None

    # the fit pool: every model with its own benchmark on the chip and an active-parameter count
    pool, seen = [], set()
    for m in M.values():
        if m["tier"] != "frontier" and m.get("active_b") and m.get("inferencex") and m["inferencex"] not in seen and own(m, inter_of(m)[0]):
            pool.append(m)
            seen.add(m["inferencex"])
    fit_cache = {}

    def fit_at(inter):
        key = round(inter, 3)
        if key not in fit_cache:
            xs, ys = [], []
            for pm in pool:
                r = own(pm, inter)
                if r:
                    xs.append(pm["active_b"])
                    ys.append(r["tps"])
            fit_cache[key] = logfit(xs, ys)
        return fit_cache[key]

    out, largest = {}, None
    for mid, m in M.items():
        if m["tier"] == "frontier":
            continue
        inter, ib = inter_of(m)
        r = own(m, inter)
        if r:
            c = r["c"]
            if r["hw"] == chip:
                out[mid] = {"tps": r["tps"], "tps_in": r["tps_in"], "io": r["tps_in"] / r["tps"], "inter": inter, "inter_basis": ib, "hw": chip, "kind": "measured",
                            "basis": "InferenceX %s on %s, %d runs to %s" % (m["inferencex"], chip, c["n"], c["date"]), "est": False, "clamped": r["clamped"],
                            "url": c["url"], "n": c["n"], "date": c["date"]}
                if m["tier"] != "benchmark-only" and m.get("total_b") and (largest is None or m["total_b"] > M[largest]["total_b"]):
                    largest = mid
            else:
                out[mid] = {"tps": r["tps"], "tps_in": r["tps_in"], "io": r["tps_in"] / r["tps"], "inter": inter, "inter_basis": ib, "hw": r["hw"], "kind": "implied",
                            "basis": "InferenceX %s on %s x %.2f (%s:%s ratio, n=%d), %d runs to %s" % (m["inferencex"], r["hw"], r["k"], chip, r["hw"], ratios[r["hw"]]["n"], c["n"], c["date"]),
                            "est": True, "clamped": r["clamped"], "url": c["url"], "n": c["n"], "date": c["date"]}
            continue
        why = ("no InferenceX run under this name" if not m.get("inferencex") else "InferenceX has %s runs, none on Blackwell under %s" % (m["inferencex"], wl))
        if scope != "estimated" or m["tier"] == "benchmark-only":
            out[mid] = {"tps": None, "tps_in": None, "io": None, "inter": inter, "inter_basis": ib, "basis": why, "est": True, "excluded": True, "kind": "excluded"}
            continue
        fam = m.get("inferencex_family")
        rf = own(M[fam], inter) if fam and fam in M else None
        if rf:
            c = rf["c"]
            out[mid] = {"tps": rf["tps"], "tps_in": rf["tps_in"], "io": rf["tps_in"] / rf["tps"], "inter": inter, "inter_basis": ib, "hw": rf["hw"], "kind": "family",
                        "basis": "family curve: %s (%s), InferenceX on %s%s" % (M[fam]["name"], m.get("family_note") or "same architecture", rf["hw"], ("" if rf["hw"] == chip else " x %.2f" % rf["k"])),
                        "est": True, "clamped": rf["clamped"], "url": c["url"], "n": c["n"], "date": c["date"], "ref": fam}
            continue
        a, b, r2, n = fit_at(inter)
        if a is not None and m.get("active_b"):
            tps = math.exp(a + b * math.log(m["active_b"]))
            out[mid] = {"tps": tps, "tps_in": tps * R_wl, "io": R_wl, "inter": inter, "inter_basis": ib, "hw": chip, "kind": "fitted",
                        "basis": "fitted: out tok/s/GPU ~ active params^%.2f across %d benchmarked models at %.0f tok/s/user (R2 %.2f); %sB active" % (b, n, inter, r2, m["active_b"]),
                        "est": True, "clamped": False, "fit": {"a": a, "b": b, "r2": r2, "n": n}}
        else:
            out[mid] = {"tps": None, "tps_in": None, "io": None, "inter": inter, "inter_basis": ib, "basis": why + "; no parameter count to fit", "est": True, "excluded": True, "kind": "excluded"}

    for mid, m in M.items():
        if m["tier"] != "frontier":
            continue
        inter, ib = inter_of(m)
        if largest:
            ref = M[largest]
            o, i, clamped, c = read(ref, chip, inter)
            d = dials["frontier_derate"]
            od, _, _, _ = read(ref, chip, fixed)            # the same curve at the design speed, for the measured-speed realisation
            out[mid] = {"tps": o * d, "tps_in": i * d, "io": (i / o if o else None), "inter": inter, "inter_basis": ib, "hw": chip, "kind": "proxy",
                        "tps_design": (od * d if od else None),
                        "est": True, "clamped": clamped, "ref": largest, "url": c["url"], "n": c["n"], "date": c["date"],
                        "basis": "proxy: %s curve on %s x %.2f derate" % (ref["name"], chip, d)}
        else:
            out[mid] = {"tps": None, "tps_in": None, "io": None, "inter": inter, "inter_basis": ib, "est": True, "excluded": True, "kind": "excluded",
                        "basis": "no open model measured on %s under %s to borrow from" % (chip, wl)}
    fit_meta = fit_at(fixed)
    return out, {"chip_ratios": ratios, "frontier_ref": largest, "workload": wl, "scope": scope,
                 "fit": {"a": fit_meta[0], "b": fit_meta[1], "r2": fit_meta[2], "n": fit_meta[3], "at_inter": fixed, "pool": [pm["id"] for pm in pool]}}


def compute(inputs, dials):
    M, F = inputs["models"], inputs["fleet"]
    tps, tmeta = resolve_tps(inputs, dials)
    h_dial = dials["cache_hit_rate"]
    gpus = F["gpus"]
    life = int(dials["life"])
    DEM = inputs["demand"]
    agg = DEM["traces"]["agg"]
    vol_mode = dials.get("volumes", "traces")
    use_traces = vol_mode in ("traces", "pooled")

    def price_of(m):
        """(out $/M, effective in $/M, basis) under the price basis dial."""
        p = m["price"]
        if dials["price_basis"] == "effective" and p.get("eff_out") is not None:
            return p["eff_out"], p["eff_in"], "effective (traffic-weighted, cache embedded)"
        h = h_dial if h_dial is not None else (p.get("cache_hit") if p.get("cache_hit") is not None else 0.0)
        return p["out"], (1 - h) * p["in"] + h * p["cache"], "list, cache hit %.0f%%" % (100 * h)

    def routable(mid):
        return mid in M and M[mid]["tier"] != "benchmark-only" and M[mid].get("price") is not None and bool(tps[mid]["tps"])

    # --- rental: long-term rate, near-term rate, term structure
    ropt = inputs["rental"]["options"][dials["rental_basis"]]
    rate = dials["rental_rate_override"] if dials["rental_rate_override"] is not None else ropt["rate"]
    nopt = inputs["rental"]["near_options"][dials["near_basis"]]
    near = dials["near_rate_override"] if dials["near_rate_override"] is not None else nopt["rate"]
    if near is None:
        near = rate
    N = dials["converge_years"]
    S_yrs = int(dials.get("spot_years") or 1)          # years the near-term (spot) rate holds before the convergence starts
    rate_path, rate_w = [], []
    for t in range(1, life + 1):
        if t <= S_yrs:
            w = 1.0
        else:
            w = max(0.0, 1.0 - (t - S_yrs) / float(N)) if N and N > 0 else 0.0
        rate_w.append(w)
        rate_path.append((rate + (near - rate) * w) * (1 - dials["rent_decline"]) ** (t - 1))

    # --- per-task volumes per model family: measured traces where mapped, else the framework shape
    def volume(task, fam):
        tf = task.get("trace_family")
        if use_traces and tf and tf in agg:
            byfam = agg[tf]
            key = "all" if vol_mode == "pooled" else (fam if fam in byfam else "open_avg")
            rec = byfam.get(key)
            if rec:
                return {"out": rec["out_tok"], "in": rec["in_tok"], "calls": rec["spans"], "cached": rec["cached_share"], "success": rec["success"],
                        "score": rec["score"], "basis": "traces", "family": key, "n": rec["n_runs"]}
        return {"out": task["fw_out"], "in": task["fw_in"], "calls": task["calls"], "cached": None, "success": None, "score": None, "basis": "framework", "family": None, "n": None}

    # --- routing of open-weight runs: per task, the mix of open models its open runs go to (OpenRouter's per-task-type
    #     usage, restricted to models the throughput basis can carry). The mix is volume-independent, so one pass serves
    #     every scenario; the bookkeeping for the page (task types, excluded models) is weighted by the framework's open runs.
    mixes, excluded, type_acc = {}, {}, {}
    unmeasured_w, est_w, total_w = 0.0, 0.0, 0.0
    for task in DEM["tasks"]:
        r_open0 = task["runs"] * (1 - task["frontier"])
        mix = mixes.setdefault(task["name"], {})
        for t, w in task["mix"].items():
            cand = inputs["candidates"][t]["list"]
            weight = r_open0 * w
            elig = [[mid, s] for mid, s in cand if routable(mid)]
            fallback = False
            if not elig:
                elig = [[mid, s] for mid, s in inputs["overall_open"] if routable(mid)]
                fallback = True
            tot_c = sum(s for mid, s in cand if mid in M and M[mid]["tier"] != "benchmark-only")
            tot_e = 0.0 if fallback else sum(s for _, s in elig)
            tot_est = 0.0 if fallback else sum(s for mid, s in elig if tps[mid].get("kind") in ("family", "fitted"))
            if tot_c > 0:
                unmeasured_w += weight * (1 - tot_e / tot_c)
                est_w += weight * (tot_est / tot_c)
            total_w += weight
            for mid, s in cand:
                if mid in M and M[mid]["tier"] != "benchmark-only" and not routable(mid):
                    e = excluded.setdefault(mid, {"w": 0.0, "types": set(), "why": tps[mid]["basis"]})
                    e["w"] += weight * s / tot_c if tot_c else 0.0
                    e["types"].add(t)
            ssum = sum(s for _, s in elig) or 1.0
            ta = type_acc.setdefault(t, {"w": 0.0, "kept": {}, "measured_share": 0.0, "fallback": fallback})
            ta["w"] += weight
            ta["measured_share"] += weight * (tot_e / tot_c if tot_c else 0.0)
            for mid, s in elig:
                mix[mid] = mix.get(mid, 0.0) + w * s / ssum                 # share of this task's open-weight runs
                ta["kept"][mid] = ta["kept"].get(mid, 0.0) + weight * s / ssum
    type_rows = []
    for t, ta in type_acc.items():
        top = sorted(ta["kept"].items(), key=lambda kv: -kv[1])[:3]
        type_rows.append({"type": t, "name": DEM["types"][t]["name"], "share_runs": (ta["w"] / total_w if total_w else 0),
                          "measured_share": (ta["measured_share"] / ta["w"] if ta["w"] else 0), "fallback": ta["fallback"],
                          "top": [[mid, (v / ta["w"] if ta["w"] else 0.0)] for mid, v in top]})
    type_rows.sort(key=lambda r: -r["share_runs"])
    excluded_rows = sorted(({"id": k, "name": M[k]["name"], "share_of_open": (v["w"] / total_w if total_w else 0), "types": len(v["types"]), "why": v["why"]}
                            for k, v in excluded.items()), key=lambda r: -r["share_of_open"])
    unmeasured_share = unmeasured_w / total_w if total_w else 0.0
    estimated_share = est_w / total_w if total_w else 0.0

    def open_side(fshare):
        """Open-weight runs and tokens per model when each task sends fshare[name] of its runs to the frontier basket:
        runs x that model family's measured volume per run where the task has traces."""
        open_runs, task_open_runs, open_tokens, open_in_tokens = {}, {}, {}, {}
        for task in DEM["tasks"]:
            r_open = task["runs"] * (1 - fshare[task["name"]])
            per = task_open_runs.setdefault(task["name"], {})
            for mid, frac in mixes[task["name"]].items():
                runs = r_open * frac
                per[mid] = per.get(mid, 0.0) + runs
                open_runs[mid] = open_runs.get(mid, 0.0) + runs
                v = volume(task, M[mid].get("trace_family", "open_avg"))
                open_tokens[mid] = open_tokens.get(mid, 0.0) + runs * v["out"]
                open_in_tokens[mid] = open_in_tokens.get(mid, 0.0) + runs * v["in"]
        total = sum(open_tokens.values())
        return {"runs": open_runs, "task_runs": task_open_runs, "tokens": open_tokens, "in_tokens": open_in_tokens, "total": total,
                "w": {mid: (v / total if total else 0.0) for mid, v in open_tokens.items()}, "runs_total": sum(open_runs.values())}

    # --- one row per model: benchmark economics and its own market-implied realisation
    def make_row(mid, share):
        m = M[mid]
        p_out, p_in_eff, pbasis = price_of(m)
        real = dials["realisation"] if m["tier"] == "frontier" else 1.0
        T = tps[mid]
        io = T["io"] if T["io"] is not None else 0.0
        blended = real * (p_out + io * p_in_eff)          # $ per million OUTPUT tokens, input billed at the run's own in:out
        rev_bench = T["tps"] * 3600 * blended / 1e6 if T["tps"] else 0.0
        return {"id": mid, "name": m["name"], "lab": m["lab"], "tier": m["tier"], "share": share,
                "tps_bench": T["tps"], "tps_in_bench": T["tps_in"], "io": io, "hw": T.get("hw"), "kind": T.get("kind"),
                "inter": T["inter"], "inter_basis": T["inter_basis"], "tps_basis": T["basis"], "tps_est": T.get("est", False), "clamped": T.get("clamped", False),
                "tps_url": T.get("url"), "tps_ref": T.get("ref"), "trace_family": m.get("trace_family", "open_avg"),
                "price": m["price"], "p_out": p_out, "p_in_eff": p_in_eff, "price_basis": pbasis, "blended_per_m_out": blended,
                "rev_bench_per_gpu_hr": rev_bench, "active_b": m.get("active_b"), "total_b": m.get("total_b"),
                "measured": m.get("measured"), "or_in_out": (m["or_week"]["in_out_ratio"] if m.get("or_week") else None)}

    tr = dials["tps_realisation"]
    if tr == "market":
        f_mode, f_basis = "market", "market-implied per model"
    elif tr in (None, "benchmark", 1, 1.0):
        f_mode, f_basis = "benchmark", "benchmark peak"
    else:
        f_mode, f_basis = float(tr), "manual"
    # the rate an open-weight host pays for its GPU-hour, and the return it earns on top: every open model's
    # realisation factor is set so that a GPU-hour serving it earns rate_f_base x (1 + renter_roic)
    spot_opt = inputs["rental"]["near_options"].get("spot") or {}
    ir = dials["implied_rate"]
    if ir == "spot" and spot_opt.get("rate"):
        rate_f_base, rate_f_label = spot_opt["rate"], "published spot rate"
    elif ir in ("spot", "near"):
        rate_f_base, rate_f_label = near, "near-term rate"
    else:
        rate_f_base, rate_f_label = rate, "long-term rate"
    renter_roic = dials.get("renter_roic") or 0.0
    rate_f = rate_f_base * (1.0 + renter_roic)

    def implied(row):
        return min(1.0, rate_f / row["rev_bench_per_gpu_hr"]) if row["rev_bench_per_gpu_hr"] > 0 else 1.0

    # --- the framework's open-weight side (every scenario starts from it) and each open model's market-implied factor
    f0 = {task["name"]: task["frontier"] for task in DEM["tasks"]}
    base = open_side(f0)
    open_ids = sorted({mid for mx in mixes.values() for mid in mx})
    open_rows_base = {mid: make_row(mid, 0.0) for mid in open_ids}
    open_f = {mid: implied(r) for mid, r in open_rows_base.items()}
    f_open_median = wmedian([(open_f[mid], base["w"].get(mid, 0.0)) for mid in open_f]) or 1.0
    ref = tmeta["frontier_ref"]
    if ref and ref in open_rows_base:
        f_ref = open_f[ref]
    elif ref:
        f_ref = implied(make_row(ref, 0.0))
    else:
        f_ref = f_open_median
    fr = dials["frontier_realisation"]
    if fr == "reference":
        f_frontier, f_frontier_basis = f_ref, "reference model's factor"
    elif fr == "median":
        f_frontier, f_frontier_basis = f_open_median, "open-weight token-weighted median"
    elif fr == "speed":
        f_frontier, f_frontier_basis = None, "measured delivery speed"    # per model; the summary is the basket's token-weighted mean
    else:
        f_frontier, f_frontier_basis = float(fr), "manual"

    def speed_factor(row):
        """'speed': the reference curve at the design speed (dials['interactivity'], tok/s per user) x this model's measured
        OpenRouter delivery speed / that design speed - hosts run the benchmark's batch and deliver tokens at the speed
        OpenRouter measures - and never more than the curve at the delivered speed, so the factor is at most 1. It reads no
        price, so an open-weight price move cannot shift it."""
        T, s = tps[row["id"]], (M[row["id"]].get("measured") or {}).get("tps_user")
        if not s or not T.get("tps") or not T.get("tps_design"):
            return f_ref, "reference model's factor (no measured delivery speed)"
        return min(1.0, (s / dials["interactivity"]) * T["tps_design"] / T["tps"]), "measured delivery speed"

    def factor(row):
        if f_mode == "benchmark":
            return 1.0, "benchmark peak"
        if f_mode != "market":
            return f_mode, "manual"
        if row["tier"] == "frontier":
            return speed_factor(row) if fr == "speed" else (f_frontier, f_frontier_basis)
        return open_f[row["id"]], "market-implied"

    def power_cost(util):
        return gpus * F["kw_per_gpu"] * F["pue"] * HOURS * util * dials["power_price"] / 1000.0
    capex = F["capex_usd"]
    # depreciation: straight-line in two pools over the analysis horizon (life). Compute = GPUs + racks (the rack
    # cost x racks, plus any rounding residue of the total), shell = powered shell / mechanical / electrical. A pool
    # that outlives the horizon keeps book value, recovered as a terminal inflow in the last year.
    shell_cost = F["shell_cost_usd"]
    comp_cost = capex - shell_cost
    cl, sl = float(dials["compute_life"]), float(dials["shell_life"])
    cr, sr = float(dials["compute_residual"]), float(dials.get("shell_residual") or 0.0)

    def dep_path(cost, L, res):
        return [cost * (1 - res) / L if t < L else 0.0 for t in range(life)]

    def book_end(cost, L, res):
        return cost * max(res, 1.0 - (1.0 - res) * life / L)
    dep_comp, dep_shell = dep_path(comp_cost, cl, cr), dep_path(shell_cost, sl, sr)
    dep_years = [a + b for a, b in zip(dep_comp, dep_shell)]
    dep = sum(dep_years) / life
    terminal = book_end(comp_cost, cl, cr) + book_end(shell_cost, sl, sr)
    depreciation = {"avg": dep, "path": dep_years, "compute_path": dep_comp, "shell_path": dep_shell, "compute_cost": comp_cost, "shell_cost": shell_cost,
                    "compute_life": cl, "shell_life": sl, "compute_residual": cr, "shell_residual": sr, "terminal": terminal,
                    "terminal_compute": book_end(comp_cost, cl, cr), "terminal_shell": book_end(shell_cost, sl, sr), "horizon": life}

    def returns(rev_path, util):
        pw, other = power_cost(util), dials["other_opex"]
        ebitda_path = [r - pw - other for r in rev_path]
        flows = [-capex] + list(ebitda_path)
        flows[-1] += terminal
        rev_avg = sum(rev_path) / len(rev_path)
        ebitda = sum(ebitda_path) / len(ebitda_path)
        return {"revenue": rev_avg, "revenue_y1": rev_path[0], "revenue_path": rev_path, "power": pw, "other": other,
                "ebitda": ebitda, "ebitda_y1": ebitda_path[0], "ebitda_path": ebitda_path, "ebitda_margin": (ebitda / rev_avg if rev_avg else 0),
                "cash_yield": ebitda / capex, "roic": (ebitda - dep) / capex, "roic_y1": (ebitda_path[0] - dep_years[0]) / capex,
                "roic_path": [(e - d) / capex for e, d in zip(ebitda_path, dep_years)], "terminal": terminal,
                "payback_years": (capex / ebitda if ebitda > 0 else None),
                "irr": irr(flows), "npv0": sum(flows), "flows": flows,
                "rev_per_gpu_hr": rev_avg / (gpus * HOURS), "rev_per_gpu_hr_y1": rev_path[0] / (gpus * HOURS)}

    # --- rent
    rent = returns([gpus * r * dials["rent_util"] * HOURS for r in rate_path], dials["rent_util"])
    rent.update({"rate": rate, "rate_near": near, "rate_path": rate_path, "rate_avg": sum(rate_path) / len(rate_path),
                 "basis": dials["rental_basis"], "basis_label": ropt["label"], "n": ropt["n"],
                 "near_basis": dials["near_basis"], "near_label": nopt["label"], "near_n": nopt["n"], "converge_years": N, "spot_years": S_yrs, "rate_weights": rate_w,
                 "rate_undeclined": [rate + (near - rate) * w for w in rate_w], "rent_decline": dials["rent_decline"],
                 "util": dials["rent_util"], "indices": inputs["rental"].get("indices", [])})

    # --- cost per task per model: the model's own measured volume for that task at its own price
    def cost_cell(task, mid):
        m = M[mid]
        v = volume(task, m.get("trace_family", "open_avg"))
        p_out, p_in_eff, _ = price_of(m)
        p = m["price"]
        if dials["price_basis"] == "effective" and p.get("eff_out") is not None:
            cost = (v["in"] * p_in_eff + v["out"] * p_out) / 1e6
        else:
            h = (v["cached"] if v["cached"] is not None else (h_dial if h_dial is not None else (p.get("cache_hit") or 0.0)))
            cost = (v["in"] * ((1 - h) * p["in"] + h * p["cache"]) + v["out"] * p["out"]) / 1e6
        return {"cost": cost, "out": v["out"], "in": v["in"], "calls": v["calls"], "cached": v["cached"], "success": v["success"], "score": v["score"],
                "basis": v["basis"], "family": v["family"], "cost_per_success": (cost / v["success"] if v["success"] else None)}

    # --- serve, once per frontier basket (same open-weight side, different frontier rows), and once with no frontier at all
    util_s = dials["serve_util"]
    serves = {}

    split_mode = dials.get("split_mode", "cost")
    tol = dials.get("premium_tolerance")
    or_week = (inputs.get("openrouter") or {}).get("closed_share_week") or {}

    def serve_for(bkey, B, open_only=False, peak=False, training=None):
        """One serving scenario. The frontier vs open-weight split follows the split mode: 'cost' = the framework's
        frontier share per task, pulled down where the basket's premium over the routed open mix exceeds the tolerance;
        'openrouter' = the closed-weight share OpenRouter routed this week, as an override of output tokens; 'manual' =
        the override dials. open_only sends every task to the open-weight side (scenario D)."""
        bw = [(mid, w) for mid, w in B["weights"] if routable(mid)] if not open_only else []
        premiums = {}
        if bw:
            wsum = sum(w for _, w in bw) or 1.0
            pf_out = sum(w * dials["realisation"] * price_of(M[mid])[0] for mid, w in bw) / wsum
            pf_in = sum(w * dials["realisation"] * price_of(M[mid])[1] for mid, w in bw) / wsum
            for task in DEM["tasks"]:
                mx = mixes[task["name"]]
                ms = sum(mx.values()) or 1.0
                po_out = sum(frac * price_of(M[mid])[0] for mid, frac in mx.items()) / ms
                po_in = sum(frac * price_of(M[mid])[1] for mid, frac in mx.items()) / ms
                cf = task["fw_out"] * pf_out + task["fw_in"] * pf_in
                co = task["fw_out"] * po_out + task["fw_in"] * po_in
                premiums[task["name"]] = cf / co if co else None
        mode = "open" if open_only else split_mode
        fshare = {}
        for task in DEM["tasks"]:
            f0t = task["frontier"]
            if open_only:
                f = 0.0
            elif mode == "cost" and tol is not None and f0t > 0 and premiums.get(task["name"]):
                f = min(1.0, f0t * min(1.0, tol / premiums[task["name"]]) ** (1 - f0t))
            else:
                f = f0t
            fshare[task["name"]] = f
        if open_only:
            override = 0.0
        elif mode == "openrouter":
            override = or_week.get("out")
        elif mode == "manual":
            override = dials["closed_override"] if bkey == "anthropic" else dials.get("closed_override_openai")
        else:
            override = None
        O = base if fshare == f0 else open_side(fshare)
        fr_tokens, fr_in_tokens, fr_runs = {}, {}, {}
        for task in DEM["tasks"]:
            r_f = task["runs"] * fshare[task["name"]]
            for mid, w in bw:
                v = volume(task, M[mid].get("trace_family", "open_avg"))
                fr_runs[mid] = fr_runs.get(mid, 0.0) + r_f * w
                fr_tokens[mid] = fr_tokens.get(mid, 0.0) + r_f * w * v["out"]
                fr_in_tokens[mid] = fr_in_tokens.get(mid, 0.0) + r_f * w * v["in"]
        fr_total = sum(fr_tokens.values())
        total_out = fr_total + O["total"]
        closed_derived = fr_total / total_out if total_out else 0.0
        closed_share = override if override is not None else closed_derived
        runs_total = sum(fr_runs.values()) + O["runs_total"]
        closed_runs = sum(fr_runs.values()) / runs_total if runs_total else 0.0
        shares = {}
        for mid in fr_tokens:
            shares[mid] = closed_share * (fr_tokens[mid] / fr_total if fr_total else 0.0)
        for mid, w in O["w"].items():
            shares[mid] = shares.get(mid, 0.0) + (1 - closed_share) * w
        ssum = sum(shares.values()) or 1.0
        rows = [make_row(mid, s / ssum) for mid, s in shares.items()]
        denom = 0.0
        for r in rows:
            f, fb = (1.0, "benchmark peak (scenario E)") if peak else factor(r)
            r["f"], r["f_basis"] = f, fb
            r["tps"] = r["tps_bench"] * f
            r["tps_in"] = r["tps_in_bench"] * f
            r["rev_per_gpu_hr"] = r["rev_bench_per_gpu_hr"] * f
            r["runs_per_head_day"] = fr_runs.get(r["id"], O["runs"].get(r["id"], 0.0))
            r["out_per_head_day"] = fr_tokens.get(r["id"], O["tokens"].get(r["id"], 0.0))
            r["in_per_head_day"] = fr_in_tokens.get(r["id"], O["in_tokens"].get(r["id"], 0.0))
            r["trace_io"] = (r["in_per_head_day"] / r["out_per_head_day"] if r["out_per_head_day"] else None)
            if r["share"] > 0 and r["tps"] > 0:
                denom += r["share"] / r["tps"]
        train = 0.0 if open_only else float(dials.get("training_share") or 0.0 if training is None else training)
        serving_gpus = gpus * (1.0 - train)                      # the rest of the fleet trains and earns no token revenue
        fleet_tokens_hr = serving_gpus * util_s * 3600.0 / denom if denom else 0.0
        for r in rows:
            r["tokens_hr"] = fleet_tokens_hr * r["share"]
            r["gpus"] = serving_gpus * (r["share"] / r["tps"]) / denom if (denom and r["tps"]) else 0
            r["revenue_hr"] = r["tokens_hr"] * r["blended_per_m_out"] / 1e6
        rows.sort(key=lambda r: (r["tier"] != "frontier", -r["share"]))
        rev_hr = sum(r["revenue_hr"] for r in rows)
        rev_yr = rev_hr * HOURS
        frontier_rows = [r for r in rows if r["tier"] == "frontier"]
        open_rows = [r for r in rows if r["tier"] != "frontier"]
        inter_w = sum(r["share"] * r["inter"] for r in rows if r.get("inter")) / (sum(r["share"] for r in rows if r.get("inter")) or 1.0)
        io_w = sum(r["share"] * r["io"] for r in rows) / (sum(r["share"] for r in rows) or 1.0)
        f_w = (sum(r["gpus"] * r["f"] for r in rows) / serving_gpus) if serving_gpus else 0.0
        fsh = sum(r["share"] for r in frontier_rows)
        f_fr = f_frontier if f_frontier is not None else ((sum(r["share"] * r["f"] for r in frontier_rows) / fsh) if fsh else f_ref)
        sv = returns([rev_yr * (1 - dials["token_decline"]) ** t for t in range(life)], util_s)
        fg = sum(r["gpus"] for r in frontier_rows)
        og = sum(r["gpus"] for r in open_rows)
        est_rows = [r for r in open_rows if r.get("kind") in ("family", "fitted")]
        # token-weighted prices of the two sides: output price alone, and all-in per million output tokens
        def wprice(rs, key):
            tot = sum(r["share"] for r in rs)
            return sum(r["share"] * r[key] for r in rs) / tot if tot else 0.0
        frontier_p_out, frontier_blended = wprice(frontier_rows, "p_out"), wprice(frontier_rows, "blended_per_m_out")
        open_p_out, open_blended = wprice(open_rows, "p_out"), wprice(open_rows, "blended_per_m_out")
        # per million tokens counting input AND output (the basis of Silicon Data's token expenditure indices):
        # revenue per million output tokens divided by the tokens billed per million output tokens (1 + in:out)
        def per_total(rs):
            rev = sum(r["share"] * r["blended_per_m_out"] for r in rs)
            tok = sum(r["share"] * (1.0 + r["io"]) for r in rs)
            return rev / tok if tok else 0.0
        frontier_per_m_total, open_per_m_total, blended_per_m_total = per_total(frontier_rows), per_total(open_rows), per_total(rows)
        # cost per task per model for this basket's frontier models and the open models carrying tokens
        cost_models = [mid for mid, _ in B["weights"] if routable(mid)] + [r["id"] for r in open_rows if r["share"] > 0][:6]
        task_costs = []
        for task in DEM["tasks"]:
            task_costs.append({"task": task["name"], "group": task["group"], "runs": task["runs"], "frontier": fshare[task["name"]], "trace_family": task.get("trace_family"),
                               "cells": {mid: cost_cell(task, mid) for mid in cost_models}})
        # the split itself, task by task: framework share, this basket's premium, the share applied
        task_split = [{"name": task["name"], "group": task["group"], "runs": task["runs"], "reasoning": task["reasoning"], "consequence": task["consequence"],
                       "frontier_framework": task["frontier"], "premium": premiums.get(task["name"]), "frontier": fshare[task["name"]],
                       "frontier_runs": task["runs"] * fshare[task["name"]]} for task in DEM["tasks"]]
        pw = [(t["premium"], t["runs"] * t["frontier_framework"]) for t in task_split if t["premium"] and t["frontier_framework"] > 0]
        premium_weighted = (sum(p * w for p, w in pw) / sum(w for _, w in pw)) if pw and sum(w for _, w in pw) else None
        all_runs = sum(task["runs"] for task in DEM["tasks"])
        sv.update({"basket": bkey, "basket_label": B["label"], "util": util_s, "tokens_hr": fleet_tokens_hr, "tokens_yr": fleet_tokens_hr * HOURS,
                   "blended_per_m_out": (rev_hr * 1e6 / fleet_tokens_hr if fleet_tokens_hr else 0.0),
                   "frontier_p_out": frontier_p_out, "frontier_blended_per_m_out": frontier_blended, "open_p_out": open_p_out, "open_blended_per_m_out": open_blended,
                   "frontier_per_m_total": frontier_per_m_total, "open_per_m_total": open_per_m_total, "blended_per_m_total": blended_per_m_total,
                   "eff_tps": (fleet_tokens_hr / (serving_gpus * util_s * 3600.0) if (serving_gpus and util_s) else 0.0),
                   "training_share": train, "training_gpus": gpus - serving_gpus, "serving_gpus": serving_gpus,
                   "frontier_gpus": fg, "open_gpus": og, "frontier_revenue_hr": sum(r["revenue_hr"] for r in frontier_rows), "open_revenue_hr": sum(r["revenue_hr"] for r in open_rows),
                   "closed_share": closed_share, "closed_share_derived": closed_derived, "closed_runs_share": closed_runs, "open_share": 1 - closed_share,
                   "closed_override": override,
                   "io_ratio": io_w, "workload": dials["workload"],
                   "price_basis": dials["price_basis"], "interactivity_basis": dials["interactivity_basis"], "inter_weighted": inter_w,
                   "frontier_rows": frontier_rows, "open_rows": open_rows, "n_open_models": len([r for r in open_rows if r["share"] > 0]), "rows": rows,
                   "frontier_share_of_revenue": (sum(r["revenue_hr"] for r in frontier_rows) / rev_hr if rev_hr else 0),
                   "frontier_share_of_gpus": (fg / gpus if gpus else 0),
                   "frontier_rev_per_gpu_hr": (sum(r["revenue_hr"] for r in frontier_rows) / fg if fg else 0),
                   "open_rev_per_gpu_hr": (sum(r["revenue_hr"] for r in open_rows) / og if og else 0),
                   "tps_realisation_basis": f_basis, "f_gpu_weighted": f_w, "f_frontier": (f_fr if f_mode == "market" else (1.0 if f_mode == "benchmark" else f_mode)),
                   "f_frontier_basis": f_frontier_basis, "f_open_median": f_open_median, "n_implied": len(open_f), "rate_f": rate_f, "implied_rate": dials["implied_rate"],
                   "rate_f_base": rate_f_base, "rate_f_label": rate_f_label, "renter_roic": renter_roic,
                   "rev_bench_per_gpu_hr": (sum(r["rev_bench_per_gpu_hr"] * r["gpus"] for r in rows) / gpus if gpus else 0),
                   "estimated_share_of_open_tokens": (sum(r["share"] for r in est_rows) / (sum(r["share"] for r in open_rows) or 1.0)),
                   "out_per_head_day": total_out, "runs_per_head_day": runs_total,
                   "task_costs": task_costs, "cost_models": cost_models,
                   "split_mode": mode, "premium_tolerance": tol, "tasks": task_split,
                   "premium_min": (min(p for p, _ in pw) if pw else None), "premium_max": (max(p for p, _ in pw) if pw else None), "premium_weighted": premium_weighted,
                   "frontier_runs_share": (sum(t["frontier_runs"] for t in task_split) / all_runs if all_runs else 0.0),
                   "frontier_runs_share_framework": (sum(t["runs"] * t["frontier_framework"] for t in task_split) / all_runs if all_runs else 0.0),
                   "or_closed_share_week": or_week.get("out")})
        sv["breakeven_factor"] = rent["rev_per_gpu_hr"] / sv["rev_per_gpu_hr"] if sv["rev_per_gpu_hr"] else None
        return sv

    for bkey, B in inputs["baskets"].items():
        serves[bkey] = serve_for(bkey, B)
    # D: the same fleet serving open-weight tokens only (every task run on the open-weight side, no frontier basket)
    b0 = next(iter(inputs["baskets"].items()))
    serve_open = serve_for(b0[0], b0[1], open_only=True)
    serve_open.update({"basket": "open", "basket_label": "Open-weight only"})
    # E: scenario D with every model at its published InferenceX peak (realisation factor 1.0): the ceiling if the
    # benchmark were the whole story. Token utilisation still applies.
    serve_open_peak = serve_for(b0[0], b0[1], open_only=True, peak=True)
    serve_open_peak.update({"basket": "open_peak", "basket_label": "Open-weight only at InferenceX peak", "tps_realisation_basis": "benchmark peak (scenario E)"})
    # F: 'AWS ROIC' - scenario B with 0% training, monetised as a landlord: the GPUs B allocates to Anthropic's frontier
    # tokens earn the rental scenario's rate path x rental utilisation (base rent) plus aws_rev_share of the token revenue
    # they generate; the open-weight GPUs earn their token revenue as in B; power and other opex as in B.
    B0 = serves["anthropic"] if serves.get("anthropic") and serves["anthropic"]["training_share"] == 0.0 else serve_for("anthropic", inputs["baskets"]["anthropic"], training=0.0)
    share = float(dials.get("aws_rev_share") or 0.0)
    td = dials["token_decline"]
    rent_block = [B0["frontier_gpus"] * HOURS * r * dials["rent_util"] for r in rate_path]
    tok_share = [share * B0["frontier_revenue_hr"] * HOURS * (1 - td) ** t for t in range(life)]
    open_rev = [B0["open_revenue_hr"] * HOURS * (1 - td) ** t for t in range(life)]
    aws = returns([a + b + c for a, b, c in zip(rent_block, tok_share, open_rev)], util_s)
    aws.update({"basket": "aws", "basket_label": "AWS: rent the Anthropic block + %d%% token share" % round(100 * share), "util": util_s,
                "rev_share": share, "frontier_gpus": B0["frontier_gpus"], "open_gpus": B0["open_gpus"], "training_share": 0.0,
                "rent_block_path": rent_block, "token_share_path": tok_share, "open_rev_path": open_rev,
                "rent_util": dials["rent_util"], "rate_path": rate_path,
                "frontier_token_rev_hr": B0["frontier_revenue_hr"], "frontier_rev_per_gpu_hr": B0["frontier_rev_per_gpu_hr"], "open_rev_per_gpu_hr": B0["open_rev_per_gpu_hr"],
                "closed_share": B0["closed_share"], "n_open_models": B0["n_open_models"], "basis_label": rent["basis_label"], "near_label": rent["near_label"]})
    aws["breakeven_factor"] = rent["rev_per_gpu_hr"] / aws["rev_per_gpu_hr"] if aws["rev_per_gpu_hr"] else None
    serve = serves.get(dials["basket"]) or next(iter(serves.values()))
    return {"dials": dials, "rent": rent, "serve": serve, "serves": serves, "serve_open": serve_open, "serve_open_peak": serve_open_peak, "serve_aws": aws, "types": type_rows,
            "excluded": excluded_rows, "unmeasured_share_of_open": unmeasured_share, "estimated_share_of_open": estimated_share,
            "split_mode": split_mode, "premium_tolerance": tol, "or_closed_share_week": or_week,
            "tmeta": tmeta, "capex": capex, "depreciation": dep, "dep": depreciation, "gpus": gpus, "rate_lt": rate, "rate_near": near}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    inp = prepare(Path(__file__).resolve().parent.parent)
    res = compute(inp, default_dials(inp))
    print(json.dumps({k: res[k] for k in ("rent", "serve")}, indent=1, default=str)[:6000])
