"""
OpenRouter collector: who uses which model for which kind of work, and what every host charges.

Four public JSON feeds, no API key:

  /api/frontend/v1/rankings/task-spend?view=week
      29 task tags. Each carries its share of all traffic over a 30-day window and the ten models that
      took the most of it, given twice: by tokens and by dollars. The tokens view is the evidence for the
      open-weight sub-mix per task type; the spend view is shown on the page for contrast.
  /api/frontend/v1/rankings/models?view=week
      one row per model (and variant) for the week: prompt tokens, completion tokens, requests.
      Sets the frontier basket weights and gives a measured input:output ratio per model.
  /api/frontend/v1/catalog/models
      the authority on which dated permaslug is which model, and whether weights are published
      (a non-empty hf_slug means open weights).
  /api/v1/models/<slug>/endpoints
      every provider's price for one model, in dollars per token. Multiplied by 1e6 here.

Writes data/openrouter.json in a reduced, stable shape. The same shape can be produced from a saved
browser snapshot (--from-legacy, used to seed the folder), so a hand-imported snapshot and a live fetch
go through identical arithmetic downstream.

Standard library only. Python 3.8+.
"""
import json, re, sys, time, datetime, urllib.request, urllib.error, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "openrouter.json"
BASE = "https://openrouter.ai"
UA = {"User-Agent": "Mozilla/5.0 (compatible; blackwell-roic/1.0; +local research tool)"}
VARIANT_RE = re.compile(r":(free|batch|exacto|thinking|nitro|floor|fast)$")
DATE_RE = re.compile(r"-\d{8}$")


def get_json(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def strip_variant(permaslug):
    return VARIANT_RE.sub("", permaslug)


def guess_slug(permaslug):
    return DATE_RE.sub("", strip_variant(permaslug))


def reduce_task_view(view):
    out = []
    for t in view.get("tasks", []):
        share = t.get("spendShareOfTotal", t.get("tokenShareOfTotal", 0.0)) or 0.0
        out.append([t["tag"], t.get("macroCategory", ""), round(float(share), 6),
                    [[m["model"], round(float(m["share"]), 6)] for m in t.get("models", [])]])
    return out


def fetch_live(basket_slugs, extra_slugs=(), log=print):
    """Fetch the four feeds and reduce them. basket_slugs: closed models whose lab list price we also want."""
    ts = get_json(BASE + "/api/frontend/v1/rankings/task-spend?view=week")["data"]
    mw = get_json(BASE + "/api/frontend/v1/rankings/models?view=week")["data"]
    cat = get_json(BASE + "/api/frontend/v1/catalog/models")["data"]
    pmap = {m["permaslug"]: [m["slug"], m.get("name", ""), m.get("hf_slug") or "", m.get("author") or ""] for m in cat}

    task_spend = {
        "window_days": ts["tokens"].get("windowDays"),
        "macro_tokens": [[m["key"], round(float(m["spendShare"]), 5)] for m in ts["tokens"].get("macroCategories", [])],
        "macro_spend": [[m["key"], round(float(m["spendShare"]), 5)] for m in ts["spend"].get("macroCategories", [])],
        "tokens": reduce_task_view(ts["tokens"]),
        "spend": reduce_task_view(ts["spend"]),
    }
    rows = sorted(([x["model_permaslug"], x["variant"], int(x["total_prompt_tokens"]), int(x["total_completion_tokens"]), int(x["count"])]
                   for x in mw), key=lambda r: -(r[2] + r[3]))[:250]
    week_date = mw[0]["date"] if mw else None

    referenced = set()
    for view in ("tokens", "spend"):
        for t in task_spend[view]:
            for m in t[3]:
                referenced.add(m[0])
    for r in rows:                     # every ranked row, so each one can be classified open or closed (closed_share_week)
        referenced.add(r[0])
    catalog = {}
    for p in referenced:
        q = strip_variant(p)
        if q in pmap:
            catalog[q] = pmap[q]

    slugs = set(basket_slugs) | set(extra_slugs)
    top = {strip_variant(r[0]) for r in rows[:80]} | {strip_variant(m[0]) for view in ("tokens", "spend") for t in task_spend[view] for m in t[3]}
    for q, (slug, name, hf, author) in catalog.items():
        if q in top and (hf or author == "anthropic"):     # prices and stats for the models that carry traffic, as before
            slugs.add(slug)
    endpoints, errors = {}, []
    for slug in sorted(slugs):
        try:
            e = get_json(BASE + "/api/v1/models/%s/endpoints" % slug)["data"]
            hosts = []
            for ep in e.get("endpoints", []):
                pr = ep.get("pricing") or {}
                if pr.get("completion") is None:
                    continue
                cr = pr.get("input_cache_read")
                hosts.append([ep.get("provider_name", ""), round(float(pr.get("prompt", 0)) * 1e6, 4),
                              round(float(pr["completion"]) * 1e6, 4), (round(float(cr) * 1e6, 4) if cr not in (None, "") else None),
                              ep.get("context_length"), ep.get("quantization") or "",
                              (round(float(ep["uptime_last_30m"]), 1) if ep.get("uptime_last_30m") is not None else None), ep.get("tag", "")])
            endpoints[slug] = {"name": e.get("name", slug), "hosts": hosts}
        except Exception as ex:  # one model failing must not sink the run
            errors.append([slug, str(ex)[:120]])
            log("   endpoints failed for %s: %s" % (slug, ex))
        time.sleep(0.15)

    stats = fetch_stats(sorted(slugs), pmap, log=log)

    return {
        "schema": "openrouter-snapshot/1",
        "basis": "measured",
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "read_on": datetime.date.today().isoformat(),
        "week_date": week_date,
        "source": {
            "task_spend": BASE + "/api/frontend/v1/rankings/task-spend?view=week",
            "models_week": BASE + "/api/frontend/v1/rankings/models?view=week",
            "catalog": BASE + "/api/frontend/v1/catalog/models",
            "endpoints": BASE + "/api/v1/models/{slug}/endpoints",
        },
        "license": "OpenRouter rankings, CC BY 4.0",
        "task_spend": task_spend,
        "models_week": {"cols": ["permaslug", "variant", "prompt_tokens", "completion_tokens", "requests"], "rows": rows},
        "catalog": catalog,
        "endpoints": endpoints,
        "endpoint_errors": errors,
        "stats": stats,
        "stats_source": STATS_SOURCE,
    }


STATS_SOURCE = {
    "effective_pricing": BASE + "/api/frontend/v1/stats/effective-pricing?permaslug={permaslug}&shape=v7&variant=standard",
    "throughput": BASE + "/api/frontend/v1/stats/throughput-comparison?perfWorkload=text_generation&permaslug={permaslug}&timeRange=1w&variant=standard",
    "activity": BASE + "/api/frontend/v1/stats/model-activity?permaslug={permaslug}&variant=standard",
    "note": ("Per model: traffic-weighted effective input/output price and cache-hit rate across every host over the trailing week; "
             "delivered output tokens/s per request per host (7-day mean of daily medians), summarised as the token-weighted median across hosts; "
             "and the last 7 days of prompt/completion/cached/reasoning tokens. providers rows: [name, eff_in, eff_out, cache_hit, tokens_week, tps_7d]."),
}


def wmedian(pairs):
    pairs = sorted((p for p in pairs if p[0] and p[0] > 0 and p[1] and p[1] > 0), key=lambda p: p[0])
    tot = sum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= tot / 2:
            return v
    return pairs[-1][0] if pairs else None


def fetch_stats(slugs, pmap, log=print):
    """The three public per-model stats feeds behind every OpenRouter model page, reduced to one row per slug."""
    slug2perma = {v[0]: k for k, v in pmap.items()} if pmap and isinstance(next(iter(pmap.values())), list) else {}
    stats = {}
    for slug in slugs:
        perma = slug2perma.get(slug)
        if not perma:
            continue
        q = urllib.parse.quote(perma, safe="")
        try:
            e = get_json(STATS_SOURCE["effective_pricing"].format(permaslug=q))["data"]
            t = get_json(STATS_SOURCE["throughput"].format(permaslug=q))["data"]
            a = get_json(STATS_SOURCE["activity"].format(permaslug=q))["data"]
            acc = {}
            for row in t or []:
                for eid, v in (row.get("y") or {}).items():
                    if v and v > 0:
                        acc.setdefault(eid, []).append(v)
            tps = {eid: sum(vs) / len(vs) for eid, vs in acc.items()}
            providers = []
            for p in e.get("providerSummaries", []):
                providers.append([p.get("providerName"), round(float(p.get("effectiveInputPrice", 0)), 4), round(float(p.get("effectiveOutputPrice", 0)), 4),
                                  round(float(p.get("cacheHitRate") or 0), 3), int(p.get("totalTokens") or 0),
                                  (round(tps[p["endpointId"]], 1) if p.get("endpointId") in tps else None)])
            act = (a.get("analytics") or [])[:7]
            def tot(k):
                return sum(int(x.get(k) or 0) for x in act)
            stats[slug] = {"permaslug": perma, "eff_in": round(float(e.get("weightedInputPrice", 0)), 4), "eff_out": round(float(e.get("weightedOutputPrice", 0)), 4),
                           "cache_hit": round(float(e.get("weightedCacheHitRate") or 0), 3),
                           "tps_wmedian": wmedian([(p[5], p[4]) for p in providers]),
                           "activity7d": {"days": len(act), "prompt": tot("total_prompt_tokens"), "completion": tot("total_completion_tokens"),
                                          "cached": tot("total_native_tokens_cached"), "reasoning": tot("total_native_tokens_reasoning"), "requests": tot("count")},
                           "providers": providers[:12]}
        except Exception as ex:
            log("   stats failed for %s: %s" % (slug, str(ex)[:80]))
        time.sleep(0.12)
    return stats


def from_legacy(task_spend_path, usage_rows_path, endpoints_path, lab_prices_path, read_on):
    """Build the same snapshot shape from the reduced files a browser session saved (used to seed the folder)."""
    ts = json.load(open(task_spend_path, encoding="utf-8"))
    ur = json.load(open(usage_rows_path, encoding="utf-8"))
    ep = json.load(open(endpoints_path, encoding="utf-8"))
    lab = json.load(open(lab_prices_path, encoding="utf-8"))
    cols = ur["cols"]
    ci = {c: i for i, c in enumerate(cols)}
    rows, catalog = [], {}
    for r in ur["rows"]:
        perma, slug, name, author, is_open = r[ci["permaslug"]], r[ci["slug"]], r[ci["name"]], r[ci["author"]], r[ci["open"]]
        rows.append([perma, "standard", int(r[ci["prompt_tokens"]]), int(r[ci["completion_tokens"]]), int(r[ci["requests"]])])
        catalog[strip_variant(perma)] = [slug, name, ("(published)" if is_open else ""), author]
    for t in ts["tokens"]:
        for m in t[3]:
            q = strip_variant(m[0])
            if q not in catalog:
                catalog[q] = [guess_slug(m[0]), q, "", q.split("/")[0]]
    endpoints = {}
    for slug, (name, is_open, hosts) in ep["models"].items():
        endpoints[slug] = {"name": name, "hosts": [[h[0], h[1], h[2], h[3], (h[4] * 1024 if h[4] else None), h[5], None, ""] for h in hosts]}
    for mid, m in lab["models"].items():
        if m["slug"] not in endpoints:
            endpoints[m["slug"]] = {"name": m["name"], "hosts": [["Anthropic", m["in"], m["out"], m["cache_read"], m.get("context"), "", None, "lab list price"]]}
    return {
        "schema": "openrouter-snapshot/1",
        "basis": "measured (imported from a browser snapshot)",
        "fetched_at": read_on + "T00:00:00Z",
        "read_on": read_on,
        "week_date": None,
        "source": {
            "task_spend": BASE + "/api/frontend/v1/rankings/task-spend?view=week",
            "models_week": BASE + "/api/frontend/v1/rankings/models?view=week",
            "catalog": BASE + "/api/frontend/v1/catalog/models",
            "endpoints": BASE + "/api/v1/models/{slug}/endpoints",
        },
        "license": "OpenRouter rankings, CC BY 4.0",
        "task_spend": {"window_days": ts.get("windowDays", 30), "macro_tokens": [[m[0], m[2]] for m in ts.get("macro", [])],
                       "macro_spend": [], "tokens": ts["tokens"], "spend": None},
        "models_week": {"cols": ["permaslug", "variant", "prompt_tokens", "completion_tokens", "requests"], "rows": rows},
        "catalog": catalog,
        "endpoints": endpoints,
        "endpoint_errors": [],
    }


def main(argv):
    lab = json.load(open(DATA / "lab_prices.json", encoding="utf-8"))
    basket = [m["slug"] for m in lab["models"].values()]
    if "--from-legacy" in argv:
        i = argv.index("--from-legacy")
        snap = from_legacy(argv[i + 1], argv[i + 2], argv[i + 3], DATA / "lab_prices.json", argv[i + 4])
    else:
        print("openrouter: fetching four feeds ...")
        snap = fetch_live(basket, extra_slugs=("openai/gpt-5.6-luna", "openai/gpt-5.6-sol", "google/gemini-3.7-flash"))
    OUT.write_text(json.dumps(snap, indent=1), encoding="utf-8")
    n_tasks = len(snap["task_spend"]["tokens"])
    print("openrouter: %d task types, %d model rows, %d models priced -> %s" % (n_tasks, len(snap["models_week"]["rows"]), len(snap["endpoints"]), OUT.name))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
