"""
What OpenRouter's traffic paid for tokens, week by week -> data/token_revenue.json

Revenue of a model in a week = its prompt tokens x its effective input price + its completion tokens x its effective
output price. The effective prices are OpenRouter's traffic-weighted prices across every host serving the model
(cache hits inside the input price), so the product is what the traffic paid, not what list prices would charge.
A ':free' variant earns nothing. Weeks start on Monday (UTC), as on OpenRouter's rankings.

Two bases, because OpenRouter keeps per-model history for 31 days only:

  full    the week lies inside the 31-day window of /api/frontend/v1/stats/model-activity, read for every model that
          carries real traffic (the largest models by last-30-day tokens until 99.5% of them are covered, plus every
          model named in the weekly Top Models chart): daily prompt / completion / cached tokens, summed to the week.
          The few tokens below that cut are priced at the week's rate for small models.
  chart   older weeks. The weekly Top Models chart names about nine models and lumps the rest into 'Others'; the
          weekly market-share chart gives every large lab's tokens. Named models are priced as above (their input /
          output split from their own activity); the rest of each lab's tokens is priced at that lab's rate for the
          models below the chart, measured on the full weeks, and the market-share chart's 'others' at the rate of
          labs below the top ones. The same estimate is made for the full weeks so its error can be shown.

Prices: each run reads every model's effective price and keeps a price history (a new point only when a price moves).
A week is priced at the read in force on its last day; weeks before the first read use the first read. The history
is seeded from the daily snapshots in data/snapshots (the dashboard's basket models from 28 Sep 2026). A model with no
effective price falls back to its OpenRouter list price, cached tokens at the cache-read price.

A complete full week is stored once and kept; the running week and the chart weeks are recomputed every run.
OpenRouter rankings are CC BY 4.0. Standard library only.
"""
import datetime, gzip, json, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from engine import net
from engine import collect_or_share as S

BASE = "https://openrouter.ai"
URLS = {
    "activity": BASE + "/api/frontend/v1/stats/model-activity?permaslug={permaslug}&variant={variant}",
    "effective_pricing": BASE + "/api/frontend/v1/stats/effective-pricing?permaslug={permaslug}&shape=v7&variant={variant}",
    "ranking_month": BASE + "/api/frontend/v1/rankings/models?view=month",
    "chart": BASE + "/api/frontend/v1/rankings/model-rankings-chart",
    "labs_chart": BASE + "/api/frontend/v1/rankings/author-market-share",
    "catalog": BASE + "/api/frontend/v1/catalog/models",
    "list_prices": BASE + "/api/v1/models",
}
WEEKS = 13                  # complete weeks shown, plus the running one
COVER = 0.995               # share of last-30-day tokens the per-model reads must cover
MAX_MODELS = 220
KEEP_ROWS = 60              # model rows stored per week; the rest are summed per lab
FREE_LABS = {"stealth"}     # OpenRouter's unnamed 'stealth' test models are served free
TOL = 0.02                  # a new price point only when the input or output price moves more than this
LABS = {"deepseek": "DeepSeek", "z-ai": "Z.ai", "openai": "OpenAI", "anthropic": "Anthropic", "google": "Google", "minimax": "MiniMax",
        "tencent": "Tencent", "nvidia": "NVIDIA", "xiaomi": "Xiaomi", "moonshotai": "Moonshot AI", "qwen": "Qwen", "x-ai": "xAI",
        "meta-llama": "Meta", "mistralai": "Mistral", "stealth": "Stealth (unnamed)", "openrouter": "OpenRouter", "baidu": "Baidu",
        "bytedance-seed": "ByteDance Seed", "inclusionai": "inclusionAI", "stepfun": "StepFun", "arcee-ai": "Arcee", "amazon": "Amazon",
        "microsoft": "Microsoft", "cohere": "Cohere", "ibm-granite": "IBM", "liquid": "Liquid", "kwaipilot": "Kwaipilot", "meituan": "Meituan"}
NOTE = ("Weekly token revenue on OpenRouter: each model's prompt and completion tokens times its effective (traffic-weighted, "
        "cache-inclusive) input and output price; ':free' variants earn nothing. 'full' weeks count every model from OpenRouter's "
        "daily per-model activity (31-day window); 'chart' weeks price the Top Models chart's named models the same way and the rest "
        "of each lab's tokens (weekly market-share chart) at that lab's measured rate for its smaller models. See "
        "engine/collect_token_revenue.py.")
UA = S.UA


def get_json(url, timeout=60):
    return json.loads(net.read(urllib.request.Request(url, headers=UA), timeout).decode("utf-8"))


def lab_of(perma):
    return (perma or "").split("/")[0]


def lab_name(lab):
    return LABS.get(lab, lab.replace("-", " ").title() if lab else "unknown")


def split_key(chart_key):
    """'minimax/minimax-m3.1-flash-20261019:free' -> ('minimax/minimax-m3.1-flash-20261019', 'free')"""
    if ":" in chart_key:
        p, v = chart_key.rsplit(":", 1)
        return p, v
    return chart_key, "standard"


def key(perma, variant):
    return "%s|%s" % (perma, variant or "standard")


def monday(d):
    d = datetime.date.fromisoformat(d[:10])
    return (d - datetime.timedelta(days=d.weekday())).isoformat()


def week_end(wk):
    return (datetime.date.fromisoformat(wk) + datetime.timedelta(days=6)).isoformat()


# ------------------------------------------------------------------ prices
def price_at(hist, k, day):
    """the price point in force on 'day' ([date, in, out, cache_hit, basis]); before the first point, the first point"""
    pts = hist.get(k) or []
    if not pts:
        return None
    best = pts[0]
    for p in pts:
        if p[0] <= day:
            best = p
    return best


def add_price(hist, k, day, p_in, p_out, hit, basis):
    pts = hist.setdefault(k, [])
    redo = any(p[0] == day for p in pts)          # a second run on the same day replaces its own point
    pts[:] = [p for p in pts if p[0] != day]
    pts.sort()
    prev = [p for p in pts if p[0] < day]
    if prev:
        a = prev[-1]
        same = abs(a[1] - p_in) <= TOL * max(a[1], 1e-9) + 1e-9 and abs(a[2] - p_out) <= TOL * max(a[2], 1e-9) + 1e-9 and a[4] == basis
        if same:
            return False
    pts.append([day, round(p_in, 5), round(p_out, 5), None if hit is None else round(hit, 4), basis])
    pts.sort()
    return not redo


def seed_prices(root, hist):
    """effective prices of the dashboard's models from the daily snapshots (data/snapshots/*.json.gz, openrouter.json)"""
    n = 0
    for f in sorted((Path(root) / "data" / "snapshots").glob("*.json.gz")):
        try:
            snap = json.load(gzip.open(f))
            st = ((snap.get("files") or {}).get("openrouter.json") or {}).get("stats") or {}
        except Exception:
            continue
        day = snap.get("date") or f.name[:10]
        for slug, s in st.items():
            perma = s.get("permaslug")
            if perma and s.get("eff_out") is not None and (s.get("eff_in") or s.get("eff_out")):
                n += add_price(hist, key(perma, "standard"), day, float(s["eff_in"]), float(s["eff_out"]), s.get("cache_hit"), "effective")
    return n


def model_revenue(prompt, completion, cached, price, variant):
    """revenue in USD of one model-week; price = [date, in, out, cache_hit, basis] in $/M tokens"""
    if variant == "free" or not price:
        return 0.0
    _, p_in, p_out, cr, basis = price[:5]
    if basis == "list":           # list prices: cached tokens at the cache-read price (kept in the cache_hit slot)
        cr = p_in if cr is None else cr
        return ((prompt - cached) * p_in + cached * cr + completion * p_out) / 1e6
    return (prompt * p_in + completion * p_out) / 1e6


# ------------------------------------------------------------------ weeks
def full_week(wk, days, meta, hist, chart_total=None, partial=False, n_days=7, inside=None):
    """days: key -> {date: [prompt, completion, cached, requests]}; returns the stored record of a full week"""
    end = week_end(wk)
    rows = []
    for k, dd in days.items():
        p = c = ca = 0
        for d, v in dd.items():
            if wk <= d <= end and (inside is None or d in inside):
                p += v[0]; c += v[1]; ca += v[2]
        if p + c <= 0:
            continue
        perma, variant = k.split("|")
        m = meta.get(k) or {}
        pr = price_at(hist, k, end) if variant != "free" else None
        rev = 0.0 if lab_of(perma) in FREE_LABS else model_revenue(p, c, ca, pr, variant)
        rows.append({"k": k, "name": m.get("name") or perma, "lab": lab_of(perma), "w": m.get("weights", "unknown"), "variant": variant,
                     "p": p, "c": c, "ca": ca, "price": pr, "rev": rev})
    counted = sum(r["p"] + r["c"] for r in rows)
    tail = max(0, (chart_total or 0) - counted) if chart_total else 0
    # the small-model rate: models outside the largest 50 of the week
    small = sorted(rows, key=lambda r: -(r["p"] + r["c"]))[50:]
    st = sum(r["p"] + r["c"] for r in small)
    small_rate = (sum(r["rev"] for r in small) / st * 1e6) if st else 0.0
    return pack(wk, "full", rows, tail, small_rate, chart_total or counted + tail, partial, n_days)


def pack(wk, basis, rows, tail_tokens, tail_rate, total, partial, n_days, extra=None):
    rows = sorted(rows, key=lambda r: -r["rev"])
    labs = {}
    for r in rows:
        x = labs.setdefault(r["lab"], [0, 0.0, 0, 0])      # tokens, revenue, output tokens, free tokens
        x[0] += r["p"] + r["c"]; x[1] += r["rev"]; x[2] += r["c"] or 0
        if r["variant"] == "free":
            x[3] += r["p"] + r["c"]
    keep, rest = rows[:KEEP_ROWS], rows[KEEP_ROWS:]
    other = {}
    for r in rest:
        x = other.setdefault(r["lab"], [0, 0, 0.0, 0])        # tokens, output, revenue, models
        x[0] += r["p"] + r["c"]; x[1] += r["c"] or 0; x[2] += r["rev"]; x[3] += 1
    tail_rev = tail_tokens * tail_rate / 1e6
    rev = sum(r["rev"] for r in rows) + tail_rev
    out = {"basis": basis, "partial": partial, "days": n_days, "total_tokens": int(total), "revenue": round(rev, 2),
           "per_m": round(rev / total * 1e6, 5) if total else None,
           "output_tokens": int(sum((r["c"] or 0) for r in rows)),
           "free_tokens": int(sum(r["p"] + r["c"] for r in rows if r["variant"] == "free")),
           "tail": [int(tail_tokens), round(tail_rate, 5), round(tail_rev, 2)],
           "labs": {k: [int(v[0]), round(v[1], 2), int(v[2]), int(v[3])] for k, v in sorted(labs.items(), key=lambda kv: -kv[1][1])},
           # [key, name, lab, weights, variant, prompt, completion, cached, p_in, p_out, price basis, priced on, revenue]
           "models": [[r["k"], r["name"], r["lab"], r["w"], r["variant"], int(r["p"]), None if r["c"] is None else int(r["c"]),
                       None if r["ca"] is None else int(r["ca"]),
                       (r["price"][1] if r["price"] else None), (r["price"][2] if r["price"] else None),
                       (r["price"][4] if r["price"] else ("free" if r["variant"] == "free" else r.get("basis_note", "unpriced"))),
                       (r["price"][0] if r["price"] else None), round(r["rev"], 2)] for r in keep],
           "other_models": {k: [int(v[0]), int(v[1]), round(v[2], 2), v[3]] for k, v in other.items()}}
    if extra:
        out.update(extra)
    return out


def tail_rates(full, chart, labs_chart):
    """from the full weeks: each lab's rate ($/M tokens) on the models below that week's Top Models chart, and the
    rate of the labs below the market-share chart's named labs ('others'); and each lab's rate over all its models, for
    a chart week in which none of the lab's models is named"""
    acc, oth, every = {}, [0, 0.0], {}
    for wk, rec in full.items():
        named = {key(*split_key(m)) for m in ((chart.get(wk) or {}).get("ys") or {}) if m != "Others"}
        top = {a for a in ((labs_chart.get(wk) or {}).get("ys") or {}) if a.lower() != "others"}
        for m in rec["_rows"]:
            t = m["p"] + m["c"]
            y = every.setdefault(m["lab"], [0, 0.0]); y[0] += t; y[1] += m["rev"]
            if m["k"] in named:
                continue
            x = acc.setdefault(m["lab"], [0, 0.0]); x[0] += t; x[1] += m["rev"]
            if top and m["lab"] not in top:
                oth[0] += t; oth[1] += m["rev"]
    rates = {lab: v[1] / v[0] * 1e6 for lab, v in acc.items() if v[0] > 0}
    rates_all = {lab: v[1] / v[0] * 1e6 for lab, v in every.items() if v[0] > 0}
    return rates, (oth[1] / oth[0] * 1e6 if oth[0] else None), {lab: v[0] for lab, v in acc.items()}, rates_all


def chart_week(wk, cw, lw, meta, hist, ratios, rates, other_rate, partial=False, rates_all=None):
    """estimate of a week from the Top Models chart (cw) and the market-share chart (lw)"""
    end = week_end(wk)
    rows, named_lab = [], {}
    total = sum(int(v) for v in (cw.get("ys") or {}).values())
    for ck, v in (cw.get("ys") or {}).items():
        if ck == "Others":
            continue
        perma, variant = split_key(ck)
        k, v = key(perma, variant), int(v)
        m = meta.get(k) or {}
        lab = lab_of(perma)
        fo = ratios.get(k) or ratios.get(key(perma, "standard")) or ratios.get("@" + lab) or ratios.get("@all")
        c = v * fo
        pr = price_at(hist, k, end) if variant != "free" else None
        if pr is None and variant == "batch":
            pr = price_at(hist, key(perma, "standard"), end)
        if pr is not None or variant == "free":
            # cached share unknown for a chart week: use the model's own measured share of prompt tokens
            hit = ratios.get("cache:" + k)
            rev = model_revenue(v - c, c, (v - c) * (hit or 0), pr, variant)
        else:
            rev = 0.0 if lab in FREE_LABS else v * (rates_all or {}).get(lab, rates.get(lab, other_rate or 0)) / 1e6
        rows.append({"k": k, "name": m.get("name") or perma, "lab": lab, "w": m.get("weights", "unknown"), "variant": variant,
                     "p": v - c, "c": c, "ca": None, "price": pr, "rev": rev, "basis_note": "lab rate"})
        named_lab[lab] = named_lab.get(lab, 0) + v
    lys = {a: int(v) for a, v in (lw.get("ys") or {}).items()}
    others = sum(v for a, v in lys.items() if a.lower() == "others")
    for lab, v in lys.items():
        if lab.lower() == "others":
            continue
        rest = max(0, v - named_lab.get(lab, 0))
        if rest <= 0:
            continue
        # the lab's rate below the chart when some of its models are named; over all its models when none is
        r = rates.get(lab, other_rate or 0) if named_lab.get(lab) else (rates_all or {}).get(lab, rates.get(lab, other_rate or 0))
        fo = ratios.get("@" + lab) or ratios.get("@all")
        rows.append({"k": "rest|" + lab, "name": ("Other %s models, below the chart" if named_lab.get(lab) else "%s, every model (none named in the chart)") % lab_name(lab),
                     "lab": lab, "w": "", "variant": "estimate",
                     "p": rest * (1 - fo), "c": rest * fo, "ca": None, "price": None, "rev": rest * r / 1e6, "basis_note": "lab rate"})
    # named chart models of labs below the market-share chart are already inside its 'others'
    inside = sum(v for lab, v in named_lab.items() if lab not in lys)
    tail = max(0, others - inside)
    if not lys:                         # no market-share chart for the week: the Top Models chart's 'Others' at the 'others' rate
        tail = int((cw.get("ys") or {}).get("Others", 0))
    return pack(wk, "chart", rows, tail, other_rate or 0, total, partial, 7)


def series(chart):
    pts = chart.get("data", chart)
    pts = pts.get("data", pts) if isinstance(pts, dict) else pts
    return {p["x"][:10]: p for p in pts}


# ------------------------------------------------------------------ main
def load(root):
    p = Path(root) / "data" / "token_revenue.json"
    if p.exists():
        return json.load(open(p, encoding="utf-8"))
    return {"weeks": {}, "prices": {}}


def save(root, H):
    H["weeks"] = dict(sorted(H.get("weeks", {}).items()))
    H["prices"] = dict(sorted(H.get("prices", {}).items()))
    p = Path(root) / "data" / "token_revenue.json"
    p.write_text(json.dumps(H, indent=None, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def refresh(root, log=print, today=None, fetch=None, workers=8):
    root = Path(root)
    fetch = fetch or get_json
    today = today or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    H = load(root)
    hist = H.setdefault("prices", {})
    if not H.get("seeded"):
        n = seed_prices(root, hist)
        H["seeded"] = today
        log("   token revenue: %d price points seeded from data/snapshots" % n)

    month = fetch(URLS["ranking_month"])["data"]
    chart = series(fetch(URLS["chart"]))
    labs_chart = series(fetch(URLS["labs_chart"]))
    cat = S.catalog_map(fetch(URLS["catalog"])["data"])
    classify = S.classifier(cat, S.registry(root))
    listp = {}
    for m in fetch(URLS["list_prices"])["data"]:
        pr = m.get("pricing") or {}
        try:
            listp[(m.get("canonical_slug") or m["id"]).split(":")[0] + ("|free" if m["id"].endswith(":free") else "|standard")] = (
                m.get("name"), float(pr.get("prompt") or 0) * 1e6, float(pr.get("completion") or 0) * 1e6,
                float(pr["input_cache_read"]) * 1e6 if pr.get("input_cache_read") not in (None, "") else None)
        except (TypeError, ValueError, KeyError):
            continue

    # which models to read one by one
    rows = sorted(month, key=lambda x: -(int(x["total_prompt_tokens"]) + int(x["total_completion_tokens"])))
    tot = sum(int(x["total_prompt_tokens"]) + int(x["total_completion_tokens"]) for x in rows) or 1
    want, acc = [], 0
    for x in rows:
        if acc / tot >= COVER or len(want) >= MAX_MODELS:
            break
        want.append(key(x["model_permaslug"], x.get("variant")))
        acc += int(x["total_prompt_tokens"]) + int(x["total_completion_tokens"])
    weeks_all = sorted(chart)
    current = monday(today)
    shown = [w for w in weeks_all if w <= current][-(WEEKS + 1):]
    for wk in shown:
        for ck in (chart[wk].get("ys") or {}):
            if ck != "Others":
                k = key(*split_key(ck))
                if k not in want:
                    want.append(k)
    meta = {}
    for k in want:
        perma, variant = k.split("|")
        w, _how = classify(perma)
        nm = S.name_of(perma, cat)
        if nm == perma and (listp.get(key(perma, "standard")) or (None,))[0]:
            nm = listp[key(perma, "standard")][0]
        meta[k] = {"name": nm + ({"free": " (free)", "batch": " (batch)"}.get(variant, "")), "weights": w}

    def one(k):
        perma, variant = k.split("|")
        q = {"permaslug": urllib.parse.quote(perma, safe="/"), "variant": variant}
        act, eff, err = None, None, None
        try:
            act = fetch(URLS["activity"].format(**q))["data"]["analytics"]
        except Exception as ex:
            err = "activity: %s" % ex
        if variant != "free":
            try:
                eff = fetch(URLS["effective_pricing"].format(**q)).get("data")
            except Exception as ex:
                err = (err + "; " if err else "") + "price: %s" % ex
        return k, act, eff, err

    with ThreadPoolExecutor(max_workers=workers) as ex:
        got = list(ex.map(one, want))
    days, errors, n_eff, n_list = {}, [], 0, 0
    ratios, cache_share = {}, {}
    lab_ratio = {}
    for k, act, eff, err in got:
        if err:
            errors.append([k, err[:160]])
        perma, variant = k.split("|")
        if act:
            dd = days.setdefault(k, {})
            for a in act:
                dd[a["date"][:10]] = [int(a.get("total_prompt_tokens") or 0), int(a.get("total_completion_tokens") or 0),
                                      int(a.get("total_native_tokens_cached") or 0), int(a.get("count") or 0)]
            P = sum(v[0] for v in dd.values()); C = sum(v[1] for v in dd.values()); CA = sum(v[2] for v in dd.values())
            if P + C:
                ratios[k] = C / (P + C)
                ratios["cache:" + k] = CA / P if P else 0
                x = lab_ratio.setdefault(lab_of(perma), [0, 0]); x[0] += P + C; x[1] += C
        if variant == "free":
            continue
        if eff and (eff.get("weightedOutputPrice") or eff.get("weightedInputPrice")):
            n_eff += add_price(hist, k, today, float(eff.get("weightedInputPrice") or 0), float(eff.get("weightedOutputPrice") or 0),
                               eff.get("weightedCacheHitRate"), "effective") or 0
        elif listp.get(key(perma, "standard")) and not hist.get(k):
            _, a, b, cr = listp[key(perma, "standard")]
            if variant == "batch":
                a, b, cr = a / 2, b / 2, (None if cr is None else cr / 2)
            n_list += add_price(hist, k, today, a, b, cr, "list") or 0
    for lab, (t, c) in lab_ratio.items():
        ratios["@" + lab] = c / t if t else 0
    allt = sum(v[0] for v in lab_ratio.values())
    ratios["@all"] = (sum(v[1] for v in lab_ratio.values()) / allt) if allt else 0.02

    # full weeks: every day of the week inside the activity window
    # the window every long-served model shares (each model's 31 days start and end a day apart, by when it was cached)
    spans = [(min(dd), max(dd), len(dd)) for dd in days.values() if dd]
    most = max((n for _, _, n in spans), default=0)
    long_ = [(a, b) for a, b, n in spans if n >= most - 1]
    lo, hi = (max(a for a, _ in long_), min(b for _, b in long_)) if long_ else ("", "")
    have = sorted({d for dd in days.values() for d in dd if lo <= d <= hi})
    W = H.setdefault("weeks", {})
    full = {}
    for wk in shown:
        end = week_end(wk)
        span = [(datetime.date.fromisoformat(wk) + datetime.timedelta(days=i)).isoformat() for i in range(7)]
        inside = [d for d in span if d in have]
        complete = len(inside) == 7
        running = wk == current
        if not (complete or (running and inside)):
            continue
        cw = chart.get(wk) or {}
        ctot = sum(int(v) for v in (cw.get("ys") or {}).values()) if not running else None
        rec = full_week(wk, days, meta, hist, ctot, partial=running, n_days=len(inside), inside=set(inside))
        rec["_rows"] = [{"k": m[0], "lab": m[2], "p": m[5], "c": m[6], "rev": m[12]} for m in rec["models"]] + [
            {"k": "other|" + lab, "lab": lab, "p": v[0] - v[1], "c": v[1], "rev": v[2]} for lab, v in rec["other_models"].items()]
        full[wk] = rec
    # a stored complete full week is kept (its activity has since left the window)
    for wk, rec in W.items():
        if rec.get("basis") == "full" and not rec.get("partial") and wk not in full and rec.get("_rows"):
            full[wk] = rec
    rates, other_rate, rate_tokens, rates_all = tail_rates({w: r for w, r in full.items() if not r["partial"]}, chart, labs_chart)
    out = {}
    for wk in shown:
        cw, lw = chart.get(wk) or {}, labs_chart.get(wk) or {}
        est = chart_week(wk, cw, lw, meta, hist, ratios, rates, other_rate, partial=(wk == current), rates_all=rates_all) if cw else None
        if wk in full:
            rec = full[wk]
            if est and not rec["partial"]:
                rec["chart_estimate"] = est["revenue"]
            out[wk] = rec
        elif est:
            out[wk] = est
    for wk, rec in out.items():
        W[wk] = rec
    # weeks that fell out of the window of shown weeks are dropped unless they are stored full weeks
    for wk in list(W):
        if wk not in out and W[wk].get("basis") != "full":
            del W[wk]
    H.update({"note": NOTE, "source": URLS, "license": "OpenRouter rankings, CC BY 4.0", "read_on": today,
              "refreshed_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
              "models_read": len(want), "coverage_30d": round(acc / tot, 4), "errors": errors[:40],
              "tail_rates": {k: round(v, 5) for k, v in sorted(rates.items(), key=lambda kv: -rate_tokens.get(kv[0], 0))[:20]},
              "other_rate": None if other_rate is None else round(other_rate, 5),
              "activity_window": [have[0], have[-1]] if have else None})
    save(root, H)
    done = [w for w in sorted(out) if not out[w]["partial"]]
    if done:
        last = out[done[-1]]
        log("   token revenue: %d models read (%.1f%% of 30-day tokens), %d new effective / %d list price points; week of %s: $%.1fM on %.1fT tokens ($%.3f/M, %s)%s; %d weeks (%d full, %d chart)%s" % (
            len(want), 100 * acc / tot, n_eff, n_list, done[-1], last["revenue"] / 1e6, last["total_tokens"] / 1e12, last["per_m"] or 0, last["basis"],
            ("; chart estimate $%.1fM" % (last["chart_estimate"] / 1e6)) if last.get("chart_estimate") else "",
            len(out), sum(1 for r in out.values() if r["basis"] == "full"), sum(1 for r in out.values() if r["basis"] == "chart"),
            ("; %d reads failed" % len(errors)) if errors else ""))
    return H


def page_view(H):
    """what the dashboard embeds: the shown weeks without the working rows"""
    if not H:
        return None
    weeks = {wk: {k: v for k, v in r.items() if not k.startswith("_")} for wk, r in sorted(H.get("weeks", {}).items())}
    weeks = dict(list(weeks.items())[-(WEEKS + 1):])
    keep = {k: v for k, v in H.items() if k not in ("weeks", "prices")}
    keep["weeks"] = weeks
    keep["lab_names"] = {lab: lab_name(lab) for r in weeks.values() for lab in r.get("labs", {})}
    return keep


if __name__ == "__main__":
    import sys
    refresh(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
