"""The ROIC history on one set of assumptions.

Every row of data/roic_history.csv is kept exactly as its day's build computed it (the as-built record). This module
restates every row on a chosen set of assumptions - by default today's assumptions.json and today's mastersheet - so
the history chart compares like with like, and the history page's dials re-run the same arithmetic in the browser.

How a row is restated. The model's arithmetic splits cleanly in two:
  1. the market model: from the day's market inputs (OpenRouter prices and volumes, InferenceX throughput, rental
     quotes and contracts, lab list prices) and the market-model assumptions (baskets, task framework, split mode,
     premium tolerance, renter's ROIC, throughput scope, volume basis, rental bases) it produces a handful of
     per-GPU quantities - the row's MARKET PRIMITIVES: the spot and long-term rental rates, each serving scenario's
     revenue per serving GPU-hour at 100% token utilisation, and for F the Anthropic block's share of GPUs and the
     revenue per GPU-hour of its frontier and open-weight sides;
  2. the fleet and finance arithmetic, which is exactly linear in those primitives: fleet size and cost (mastersheet),
     training share, utilisations, AWS revenue share, power price, other opex, horizon, depreciation lives and
     residuals, rental term structure and the two price declines (the SEPARABLE assumptions).
A change to a separable assumption is applied to every past row exactly (restate() below; its JavaScript twin is
restateRow() in template.html). A change to a market-model assumption needs the day's market inputs: from 2026-09-28
each build saves them to data/snapshots/<date>.json.gz and every build re-runs the full model on each snapshot under
today's assumptions (rerun()). Rows built before snapshots existed keep their as-built market primitives; where a
market-model assumption has changed since, the row is flagged as not fully comparable and says which.

Each row also carries what serving the closed-weight models earns and sells for on that day ('tok': revenue per busy
GPU-hour of each lab's basket and the token prices behind it), which the rental market page charts: from the snapshot
re-run where a snapshot exists, else as built with the per-GPU-hour figure scaled like the serving primitives.
"""
import csv, gzip, json, re
from pathlib import Path

HOURS = 8760.0
SCEN = ("rent", "anthropic", "openai", "open", "open_peak", "aws")

# separable assumptions recorded on every row: CSV column -> dial key
BUILT_COLS = [("training_share", "training_share"), ("aws_rev_share", "aws_rev_share"), ("rent_util", "rent_util"), ("serve_util", "serve_util"),
              ("power_price_mwh", "power_price"), ("other_opex_usd", "other_opex"), ("horizon_years", "life"), ("compute_life_years", "compute_life"),
              ("shell_life_years", "shell_life"), ("compute_residual", "compute_residual"), ("shell_residual", "shell_residual"),
              ("spot_years", "spot_years"), ("converge_years", "converge_years"), ("rent_decline", "rent_decline"), ("token_decline", "token_decline")]
SEP_KEYS = [k for _, k in BUILT_COLS]
FLEET_COLS = [("gpus", "gpus"), ("capex_usd", "capex"), ("fleet_kw", "kw"), ("shell_cost_usd", "shell")]
# market primitives: CSV column -> key
PRIM_COLS = [("rent_rate_spot", "near"), ("rent_rate_lt", "lt"), ("mkt_rev_anthropic", "anthropic"), ("mkt_rev_openai", "openai"),
             ("mkt_rev_open", "open"), ("mkt_rev_open_peak", "open_peak"), ("mkt_aws_frontier_share", "aws_phi"),
             ("mkt_aws_rev_frontier", "aws_frontier"), ("mkt_aws_rev_open", "aws_open")]
# market-model assumptions recorded on the rows (a change needs the day's snapshot to restate)
MODEL_COLS = [("basket_anthropic", "Anthropic basket"), ("basket_openai", "OpenAI basket"), ("split_mode", "split mode"),
              ("premium_tolerance", "premium tolerance"), ("renter_roic", "renter's ROIC"), ("throughput_scope", "throughput scope"), ("volumes", "volume basis")]

CSV_COLS = [
    ("rent_util", "A: rental utilisation (share of GPU-hours rented)"), ("serve_util", "B-F: token utilisation"),
    ("power_price_mwh", "power price, $/MWh"), ("other_opex_usd", "other opex, $/yr"), ("fleet_kw", "fleet power draw at the meter, kW (GPUs x kW/GPU x PUE)"),
    ("shell_cost_usd", "powered shell / mechanical / electrical cost, $ (the depreciation pool on the shell life)"),
    ("compute_residual", "GPU/compute residual value, share"), ("shell_residual", "shell residual value, share"),
    ("spot_years", "years at the spot rate before converging"), ("converge_years", "years to converge to the long-term rate"),
    ("rent_decline", "rental rate decline per year"), ("token_decline", "token price decline per year"),
    ("mkt_rev_anthropic", "market primitive: B revenue per serving GPU-hour at 100% token utilisation"),
    ("mkt_rev_openai", "market primitive: C revenue per serving GPU-hour at 100% token utilisation"),
    ("mkt_rev_open", "market primitive: D revenue per GPU-hour at 100% token utilisation"),
    ("mkt_rev_open_peak", "market primitive: E revenue per GPU-hour at 100% token utilisation"),
    ("mkt_aws_frontier_share", "market primitive: F, share of B's GPUs (no training) carrying the Anthropic block"),
    ("mkt_aws_rev_frontier", "market primitive: F, Anthropic token revenue per block GPU-hour at 100% token utilisation"),
    ("mkt_aws_rev_open", "market primitive: F, open-weight revenue per open GPU-hour at 100% token utilisation"),
]

# what serving the closed models earns and sells for, per day (the rental market page draws these): revenue per GPU-hour
# serving each lab's closed-weight basket at 100% token utilisation, and the token prices behind it, $ per M output tokens
TOK_COLS = [("frontier_rev_gpu_hr_anthropic", "rev", "anthropic"), ("frontier_rev_gpu_hr_openai", "rev", "openai"),
            ("closed_price_anthropic", "price", "anthropic"), ("closed_price_out_anthropic", "price_out", "anthropic"),
            ("closed_price_openai", "price", "openai"), ("closed_price_out_openai", "price_out", "openai"),
            ("open_price", "price", "open"), ("open_price_out", "price_out", "open")]

RESTATED_COLS = (["date", "built_at", "market_model", "not_comparable"]
                 + [c for s in SCEN for c in (["roic_rent", "roic_rent_y1", "irr_rent", "rev_per_gpu_hr_rent"] if s == "rent" else
                                              ["roic_" + s, "irr_" + s, "rev_per_gpu_hr_" + s])]
                 + ["rent_rate_near"] + [c for c, _, _ in TOK_COLS]
                 + [c for c, _ in BUILT_COLS] + ["gpus", "capex_usd", "fleet_kw", "shell_cost_usd"])


def _f(v):
    try:
        return None if v in ("", None) else float(v)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------------------------------------ the arithmetic
def irr(flows, lo=-0.99, hi=1000.0):
    """identical to model.irr (bisection)"""
    def npv(r):
        return sum(c / (1 + r) ** t for t, c in enumerate(flows))
    if not (flows[0] < 0 and any(c > 0 for c in flows[1:])):
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


def rate_path(near, lt, d):
    life, S, N = int(d["life"]), int(d["spot_years"] or 1), d["converge_years"]
    out = []
    for t in range(1, life + 1):
        w = 1.0 if t <= S else (max(0.0, 1.0 - (t - S) / float(N)) if N and N > 0 else 0.0)
        out.append((lt + (near - lt) * w) * (1 - d["rent_decline"]) ** (t - 1))
    return out


def restate(p, d, fl):
    """Every scenario of one row from its market primitives p, separable assumptions d and fleet fl
    ({gpus, capex, kw, shell}). Mirrors model.compute's returns() line for line; restateRow() in template.html is its twin."""
    G, capex, life = fl["gpus"], fl["capex"], int(d["life"])
    comp, shell = capex - fl["shell"], fl["shell"]
    cl, sl, cr, sr = float(d["compute_life"]), float(d["shell_life"]), float(d["compute_residual"]), float(d["shell_residual"])
    dep_path = lambda cost, L, res: [cost * (1 - res) / L if t < L else 0.0 for t in range(life)]
    book_end = lambda cost, L, res: cost * max(res, 1.0 - (1.0 - res) * life / L)
    dep_years = [a + b for a, b in zip(dep_path(comp, cl, cr), dep_path(shell, sl, sr))]
    dep = sum(dep_years) / life
    terminal = book_end(comp, cl, cr) + book_end(shell, sl, sr)
    power = lambda u: fl["kw"] * HOURS * u * d["power_price"] / 1000.0
    td = [(1 - d["token_decline"]) ** t for t in range(life)]

    def returns(rev_path, u):
        eb = [r - power(u) - d["other_opex"] for r in rev_path]
        flows = [-capex] + eb
        flows[-1] += terminal
        e = sum(eb) / life
        return {"roic": (e - dep) / capex, "roic_y1": (eb[0] - dep_years[0]) / capex, "irr": irr(flows),
                "rev_per_gpu_hr": sum(rev_path) / life / (G * HOURS), "ebitda": e}
    out = {}
    uR, uS, train, s = d["rent_util"], d["serve_util"], d["training_share"], d["aws_rev_share"]
    rp = rate_path(p["near"], p["lt"], d) if p.get("near") is not None and p.get("lt") is not None else None
    if rp:
        out["rent"] = returns([G * r * uR * HOURS for r in rp], uR)
    for k in ("anthropic", "openai"):
        if p.get(k) is not None:
            out[k] = returns([G * (1 - train) * uS * p[k] * HOURS * x for x in td], uS)
    for k in ("open", "open_peak"):
        if p.get(k) is not None:
            out[k] = returns([G * uS * p[k] * HOURS * x for x in td], uS)
    if rp and p.get("aws_phi") is not None:
        phi = p["aws_phi"]
        out["aws"] = returns([phi * G * HOURS * uR * r + (s * phi * p["aws_frontier"] + (1 - phi) * p["aws_open"]) * G * uS * HOURS * x
                              for r, x in zip(rp, td)], uS)
    return out


# ------------------------------------------------------------------------------------------------ rows <-> dicts
def sep_dials(dials):
    return {k: float(dials[k] if dials.get(k) is not None else 0.0) for k in SEP_KEYS}


def fleet_of(F):
    return {"gpus": F["gpus"], "capex": F["capex_usd"], "kw": F["gpus"] * F["kw_per_gpu"] * F["pue"], "shell": F["shell_cost_usd"]}


def row_prim(r):
    return {k: _f(r.get(c)) for c, k in PRIM_COLS}


def row_built(r):
    """as-built separable assumptions (None where the row does not record one) and fleet"""
    return {k: _f(r.get(c)) for c, k in BUILT_COLS}, {k: _f(r.get(c)) for c, k in FLEET_COLS}


def prims_from_result(res, dials, F):
    """a build's market primitives from model.compute's result (CSV column -> value)"""
    uS, G = dials["serve_util"], F["gpus"]
    S, out = res["serves"], {}
    for k in ("anthropic", "openai"):
        sv = S.get(k)
        out["mkt_rev_" + k] = sv["revenue_y1"] / (sv["serving_gpus"] * uS * HOURS) if sv and sv["serving_gpus"] and uS else ""
    for k, key in (("open", "serve_open"), ("open_peak", "serve_open_peak")):
        sv = res.get(key)
        out["mkt_rev_" + k] = sv["revenue_y1"] / (G * uS * HOURS) if sv and uS else ""
    x = res.get("serve_aws")
    if x and uS and 0 < x["frontier_gpus"] < G:
        # per GPU-hour of the block and of the rest of the fleet, so (share, 1 - share) x fleet x these = B0's revenues exactly
        out["mkt_aws_frontier_share"] = x["frontier_gpus"] / G
        out["mkt_aws_rev_frontier"] = x["frontier_token_rev_hr"] / (x["frontier_gpus"] * uS)
        out["mkt_aws_rev_open"] = (x["open_rev_path"][0] / HOURS) / ((G - x["frontier_gpus"]) * uS)
    return {k: (round(v, 8) if isinstance(v, float) else v) for k, v in out.items()}


def tok_from_result(res, dials, inputs):
    """what a GPU-hour earns serving each lab's closed-weight basket (busy hour, i.e. at 100% token utilisation, so it
    compares with a rental rate) and the token prices behind it, from model.compute's result"""
    uS, S = dials["serve_util"], res["serves"]
    out = {"rev": {}, "price": {}, "price_out": {}, "basket": {}, "f": {}, "ref": (res.get("tmeta") or {}).get("frontier_ref")}
    for k in ("anthropic", "openai"):
        sv = S.get(k)
        if not sv:
            continue
        out["rev"][k] = sv["frontier_rev_per_gpu_hr"] / uS if uS else None
        out["f"][k] = sv.get("f_frontier")
        out["price"][k], out["price_out"][k] = sv.get("frontier_blended_per_m_out"), sv.get("frontier_p_out")
        out["basket"][k] = "+".join(mid for mid, _ in (inputs["baskets"].get(k) or {}).get("weights", []))
    a = S.get("anthropic") or {}
    out["price"]["open"], out["price_out"]["open"] = a.get("open_blended_per_m_out"), a.get("open_p_out")
    return out


def tok_from_row(r):
    """the same quantities as built, from a data/roic_history.csv row"""
    out = {"rev": {}, "price": {}, "price_out": {}, "basket": {k: r.get("basket_" + k) or "" for k in ("anthropic", "openai")}}
    for c, kind, k in TOK_COLS:
        out[kind][k] = _f(r.get(c))
    return out


def built_from(dials, F):
    """a build's separable assumptions and fleet (CSV column -> value)"""
    return {"rent_util": dials["rent_util"], "serve_util": dials["serve_util"], "power_price_mwh": dials["power_price"],
            "other_opex_usd": int(round(dials["other_opex"])), "fleet_kw": round(F["gpus"] * F["kw_per_gpu"] * F["pue"], 3),
            "shell_cost_usd": int(round(F["shell_cost_usd"])), "compute_residual": dials["compute_residual"],
            "shell_residual": dials.get("shell_residual") or 0.0, "spot_years": int(dials.get("spot_years") or 1),
            "converge_years": dials["converge_years"], "rent_decline": dials["rent_decline"], "token_decline": dials["token_decline"]}


# ------------------------------------------------------------------------------------------------ snapshots
def snap_path(root, date):
    return Path(root) / "data" / "snapshots" / ("%s.json.gz" % date)


def save_snapshot(root, date, built_at):
    from engine.model import MARKET_FILES
    D = Path(root) / "data"
    blob = {"date": date, "built_at": built_at, "files": {n: json.load(open(D / n, encoding="utf-8")) for n in MARKET_FILES}}
    p = snap_path(root, date)
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8") as f:
        json.dump(blob, f, separators=(",", ":"))
    return p


def rental_as_of(root, date, rental_file, hist=None, max_age=None):
    """a day's rental_rates.json with every provider quote replaced by the rate in force that day according to
    data/rate_history.json (corrected readings, dated announcements, ended series); the day's index rows and contracts
    are kept as they were"""
    from engine import rental_history as RH
    root = Path(root)
    if hist is None:
        hist = json.load(open(root / "data" / "rate_history.json", encoding="utf-8"))
    if max_age is None:
        max_age = int(json.load(open(root / "assumptions.json", encoding="utf-8"))["rental"].get("max_quote_age_days", 10))
    if not (hist.get("quotes") or {}).get("series"):
        return rental_file
    R = dict(rental_file)
    meta = {RH.key_of(q): q for q in R.get("quotes", []) if q.get("tier") != "index"}
    rebuilt = [q for q in RH.quotes_as_of(hist, date, max_age, meta) if q["tier"] != "index"]
    R["quotes"] = [q for q in R.get("quotes", []) if q.get("tier") == "index"] + rebuilt
    return R


def rerun(root, date, hist=None, want_tok=False):
    """the day's market inputs under today's assumptions: the full model, returning the market primitives (and, with
    want_tok, what serving the closed models earns and sells for). The day's rental quotes are rebuilt from the rate
    history, so a reading corrected later is corrected in the past rows too."""
    from engine import model
    with gzip.open(snap_path(root, date), "rt", encoding="utf-8") as f:
        blob = json.load(f)
    files = dict(blob["files"])
    files["rental_rates.json"] = rental_as_of(root, date, files["rental_rates.json"], hist)
    inputs = model.prepare(root, log=lambda *a: None, market=files)
    dials = model.default_dials(inputs)
    res = model.compute(inputs, dials)
    prim = prims_from_result(res, dials, inputs["fleet"])
    prim["rent_rate_spot"], prim["rent_rate_lt"] = res["rent"]["rate_near"], res["rent"]["rate"]
    out = {k: prim.get(c) for c, k in PRIM_COLS}
    return (out, tok_from_result(res, dials, inputs)) if want_tok else out


def rental_restate(r, prim, hist, inputs, dials, A_rental):
    """a row built before snapshots existed, put on today's rental bases: the near-term rate from the rate history as of
    the row's date (today's near-term basis), the long-term rate as built (it comes from the contracts list), and the
    serving primitives that scale with what an open-weight GPU-hour is made to earn (B, C, D and F's per-GPU revenue)
    scaled by the ratio of the new to the as-built target. Exact unless an open model sits at its benchmark ceiling
    (then it overstates that model's revenue slightly; at today's rates under 0.3% of D's)."""
    from engine import rental_history as RH
    if not (hist.get("quotes") or {}).get("series") or prim.get("near") is None:
        return prim, "", 1.0
    max_age = int(A_rental.get("max_quote_age_days", 10))
    opts = RH.near_options(RH.quotes_as_of(hist, r["date"], max_age), A_rental, r["date"], max_age)
    near = (opts.get(dials["near_basis"]) or {}).get("rate")
    if near is None:
        return prim, "no %s rate in the history for %s; as-built near-term rate kept" % (dials["near_basis"], r["date"]), 1.0
    p = dict(prim)
    p["near"] = near
    rr = dials.get("renter_roic") or 0.0
    ir = dials.get("implied_rate")
    base = (opts["spot"]["rate"] if ir == "spot" and opts["spot"]["rate"] else (near if ir in ("spot", "near") else p.get("lt")))
    old = _f(r.get("open_gpu_hr_target"))
    if base and old:
        k = base * (1 + rr) / old
        for key in ("anthropic", "openai", "open", "aws_frontier", "aws_open"):
            if p.get(key) is not None:
                p[key] = p[key] * k
        return p, "rental rates restated from the rate history (%s %.2f); serving revenue scaled x%.3f with the open-weight GPU-hour target" % (dials["near_basis"], near, k), k
    return p, "rental near-term rate restated from the rate history (%s %.2f)" % (dials["near_basis"], near), 1.0


# ------------------------------------------------------------------------------------------------ model-assumption checks
def launch_dates(root):
    """first-seen date of each registry model on OpenRouter (the date suffix of its permaslug), for basket changes:
    a model added to a basket after a row was built carried no weight on days before it launched"""
    D = Path(root) / "data"
    try:
        OR = json.load(open(D / "openrouter.json", encoding="utf-8"))
        REG = json.load(open(D / "models.json", encoding="utf-8"))
    except Exception:
        return {}
    by_slug = {}
    for perm, v in (OR.get("catalog") or {}).items():
        m = re.search(r"-(20\d{2})(\d{2})(\d{2})$", perm)
        if m and v:
            d = "%s-%s-%s" % m.groups()
            by_slug[v[0]] = min(d, by_slug.get(v[0], d))
    out = {}
    for m in REG["models"]:
        ds = [by_slug[a] for a in m.get("aliases", []) + [m["id"]] if a in by_slug]
        if ds:
            out[m["id"]] = min(ds)
    return out


def model_changes(r, cur, launched):
    """market-model assumptions on row r that differ from today's (cur = today's row), as short labels"""
    out = []
    for c, label in MODEL_COLS:
        a, b = (r.get(c) or ""), (cur.get(c) or "")
        if c.startswith("basket_"):
            if not a or a == b:
                continue
            A, B = a.split("+"), b.split("+")
            seen = r.get("openrouter_read_on") or r["date"]
            added = [m for m in B if m not in A and not (launched.get(m) and launched[m] > seen)]
            dropped = [m for m in A if m not in B]
            if added or dropped:
                out.append("%s %s" % (label, " ".join(["+ " + m for m in added] + ["- " + m for m in dropped])))
        elif a != "" and b != "" and _norm(a) != _norm(b):
            out.append("%s %s -> %s" % (label, a, b))
    return out


def _norm(v):
    f = _f(v)
    return round(f, 9) if f is not None else str(v)


# ------------------------------------------------------------------------------------------------ the page's basis
def history_basis(root, rows, inputs, dials, log=print):
    """per row: market primitives (snapshot re-run where a snapshot exists, else as built), as-built assumptions,
    not-comparable flags; plus today's assumptions and the Python restatement at them (the page checks itself
    against it) and data/roic_history_restated.csv."""
    root = Path(root)
    cur_d, cur_fl = sep_dials(dials), fleet_of(inputs["fleet"])
    today = rows[-1] if rows else {}
    launched = launch_dates(root)
    out, n_snap = [], 0
    hist = json.load(open(root / "data" / "rate_history.json", encoding="utf-8")) if (root / "data" / "rate_history.json").exists() else {}
    A_rental = json.load(open(root / "assumptions.json", encoding="utf-8"))["rental"]
    for r in rows:
        prim, src, note, tok = row_prim(r), "as built", "", None
        if snap_path(root, r["date"]).exists():
            try:
                (prim, tok), src = rerun(root, r["date"], hist, want_tok=True), "snapshot"
                n_snap += 1
            except Exception as ex:              # a snapshot the current code cannot read keeps the as-built primitives
                note = "snapshot re-run failed (%s); as-built market model kept" % type(ex).__name__
        if src == "as built":
            prim, rnote, k = rental_restate(r, prim, hist, inputs, dials, A_rental)
            note = "; ".join(x for x in (note, rnote) if x)
            # token prices as built; what a GPU-hour earns serving them scales with the open-weight GPU-hour target,
            # exactly as the serving primitives do (the closed basket's realisation is the reference open model's)
            tok = tok_from_row(r)
            tok["rev"] = {kk: (v * k if v is not None else None) for kk, v in tok["rev"].items()}
        tok["src"] = src
        bd, bfl = row_built(r)
        kept = [] if src == "snapshot" else model_changes(r, today, launched)
        out.append({"date": r["date"], "prim": prim, "src": src, "note": note, "built": bd, "built_fleet": bfl, "kept": kept, "tok": tok})
    py = [restate(o["prim"], cur_d, cur_fl) for o in out]
    with open(root / "data" / "roic_history_restated.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RESTATED_COLS)
        w.writeheader()
        for r, o, x in zip(rows, out, py):
            row = {"date": r["date"], "built_at": r["built_at"], "market_model": ("re-run from the day's snapshot" if o["src"] == "snapshot" else "as built"),
                   "not_comparable": "; ".join(o["kept"])}
            for s, v in x.items():
                row["roic_" + s], row["irr_" + s], row["rev_per_gpu_hr_" + s] = round(v["roic"], 4), (round(v["irr"], 4) if v["irr"] is not None else ""), round(v["rev_per_gpu_hr"], 4)
                if s == "rent":
                    row["roic_rent_y1"] = round(v["roic_y1"], 4)
            row["rent_rate_near"] = round(o["prim"]["near"], 4) if o["prim"].get("near") is not None else ""
            for c, kind, k in TOK_COLS:
                v = ((o.get("tok") or {}).get(kind) or {}).get(k)
                row[c] = round(v, 4) if v is not None else ""
            inv = {k: c for c, k in BUILT_COLS}
            for k, v in cur_d.items():
                row[inv[k]] = v
            row.update({"gpus": int(round(cur_fl["gpus"])), "capex_usd": int(round(cur_fl["capex"])), "fleet_kw": round(cur_fl["kw"], 3), "shell_cost_usd": int(round(cur_fl["shell"]))})
            w.writerow(row)
    log("roic history restated on today's assumptions: %d rows (%d re-run from snapshots) -> roic_history_restated.csv" % (len(rows), n_snap))
    return {"rows": out, "current": cur_d, "fleet": cur_fl, "py": py, "sep_keys": SEP_KEYS, "file": "data/roic_history_restated.csv", "launched": launched}
