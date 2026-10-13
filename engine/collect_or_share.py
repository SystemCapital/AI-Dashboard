"""
OpenRouter's closed- vs open-weight share of tokens, week by week -> data/openrouter_share.json

Three public JSON feeds, no API key:

  /api/frontend/v1/rankings/model-rankings-chart
      the 'Top Models' chart on openrouter.ai/rankings: 53 weekly points (weeks starting Monday), each with the
      tokens (prompt + completion) of that week's top models by name and one 'Others' bucket for everything else.
      The named models are classified open or closed; OpenRouter does not split 'Others', so a week's closed share
      is only known to lie between closed_named / total (every 'Others' token open) and (closed_named + others) / total
      (every 'Others' token closed). The current week is partial until it ends.
  /api/frontend/v1/rankings/models?view=week
      every model's prompt and completion tokens over the trailing week (several hundred rows), classified one by
      one: the full split, kept as one 'read' per day this runs.
  /api/frontend/v1/catalog/models
      which permaslug is which model and whether its weights are published (a non-empty hf_slug).

Classification: open = weights published. The registry's flag (data/models.json) decides where the model is mapped,
OpenRouter's catalog otherwise; a model in neither is 'unknown' and stays out of both numerator and denominator.

Every run keeps the weeks already stored (the chart only serves the trailing 53) and adds or replaces the read for
its date. Standard library only.
"""
import datetime, json, re, urllib.request
from pathlib import Path

BASE = "https://openrouter.ai"
URLS = {
    "chart": BASE + "/api/frontend/v1/rankings/model-rankings-chart",
    "ranking": BASE + "/api/frontend/v1/rankings/models?view=week",
    "catalog": BASE + "/api/frontend/v1/catalog/models",
}
UA = {"User-Agent": "Mozilla/5.0 (compatible; blackwell-roic/1.0; +local research tool)"}
VARIANT_RE = re.compile(r":(free|batch|exacto|thinking|nitro|floor|fast)$")
DATE_RE = re.compile(r"-\d{8}$")
NOTE = ("OpenRouter's closed-weight share of tokens. 'weeks' come from OpenRouter's weekly Top Models chart (all tokens, "
        "prompt + completion): closed / open = that week's named top models by published weights, others = the chart's "
        "'Others' bucket, which OpenRouter does not split, so the week's closed share lies between closed/total and "
        "(closed + others)/total. 'reads' are this project's reads of OpenRouter's full weekly ranking (every model, "
        "trailing seven days), classified model by model: the complete split on the days it was read. Open = weights "
        "published (registry flag where the model is mapped, else a non-empty hf_slug in OpenRouter's catalog). "
        "OpenRouter rankings are CC BY 4.0.")


def get_json(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def strip_variant(p):
    return VARIANT_RE.sub("", p or "")


def guess_slug(p):
    return DATE_RE.sub("", strip_variant(p))


def registry(root):
    """alias -> (id, weights) from data/models.json"""
    try:
        REG = json.load(open(Path(root) / "data" / "models.json", encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for m in REG.get("models", []):
        for a in m.get("aliases", []) + [m["id"]]:
            out[a] = (m["id"], m.get("weights"))
    return out


def catalog_map(rows):
    """permaslug -> [slug, name, hf_slug, author] from the catalog feed's rows (or an already reduced map)"""
    if isinstance(rows, dict):
        return rows
    return {m["permaslug"]: [m.get("slug") or "", m.get("name") or "", m.get("hf_slug") or "", m.get("author") or ""] for m in rows if m.get("permaslug")}


def classifier(cat, reg):
    """perma -> ('open' | 'closed' | 'unknown', how); cat: permaslug -> [slug, name, hf_slug, author]"""
    def classify(perma):
        q = strip_variant(perma)
        c = cat.get(q)
        slug = c[0] if c else guess_slug(perma)
        hit = reg.get(slug) or reg.get(guess_slug(perma))
        if hit and hit[1] in ("open", "closed"):
            return hit[1], "registry"
        if c:
            return ("open" if c[2] else "closed"), "catalog"
        return "unknown", "not in the catalog"
    return classify


def name_of(perma, cat):
    c = cat.get(strip_variant(perma))
    return (c[1] if c and c[1] else perma)


def read_entry(rows, classify, cat, read_on, data_through=None, source="live"):
    """rows: [permaslug, variant, prompt, completion, requests] for every model in the weekly ranking"""
    tok = {"closed": [0, 0], "open": [0, 0], "unknown": [0, 0]}
    per = {}
    for perma, variant, ptok, ctok, *_ in rows:
        k, _how = classify(perma)
        tok[k][0] += int(ptok)
        tok[k][1] += int(ctok)
        if k != "unknown":
            key = (k, name_of(perma, cat))
            per[key] = per.get(key, 0) + int(ptok) + int(ctok)
    known_all = sum(sum(tok[k]) for k in ("closed", "open"))
    known_out = tok["closed"][1] + tok["open"][1]
    total = known_all + sum(tok["unknown"])
    top = {k: [[n, round(v / known_all, 4)] for (kk, n), v in sorted(per.items(), key=lambda kv: -kv[1]) if kk == k][:6] for k in ("closed", "open")} if known_all else {}
    return {"read_on": read_on, "data_through": data_through, "source": source, "rows": len(rows), "tokens": tok,
            "closed_share_all": round(sum(tok["closed"]) / known_all, 5) if known_all else None,
            "closed_share_out": round(tok["closed"][1] / known_out, 5) if known_out else None,
            "unknown_share": round(sum(tok["unknown"]) / total, 5) if total else None,
            "total_tokens": total, "top": top}


def chart_weeks(chart, classify, cat, read_on):
    """the weekly Top Models chart -> {week start: {...}}; a week still running on read_on is marked partial"""
    pts = chart.get("data", chart)
    pts = pts.get("data", pts) if isinstance(pts, dict) else pts
    out = {}
    rd = datetime.date.fromisoformat(read_on)
    for w in pts:
        wk = w["x"][:10]
        c = o = ot = 0
        models = []
        for perma, v in (w.get("ys") or {}).items():
            v = int(v)
            if perma == "Others":
                ot += v
                continue
            k, _how = classify(perma)
            if k == "open":
                o += v
            else:                          # 'unknown' cannot occur for a named chart model unless the catalog dropped it
                c += v
            models.append([name_of(perma, cat), v, k])
        tot = c + o + ot
        partial = datetime.date.fromisoformat(wk) + datetime.timedelta(days=7) > rd
        out[wk] = {"total": tot, "closed": c, "open": o, "others": ot, "partial": partial, "read_on": read_on,
                   "closed_min": round(c / tot, 5) if tot else None, "closed_max": round((c + ot) / tot, 5) if tot else None,
                   "models": sorted(models, key=lambda m: -m[1])}
    return out


def load(root):
    p = Path(root) / "data" / "openrouter_share.json"
    if p.exists():
        return json.load(open(p, encoding="utf-8"))
    return {"note": NOTE, "source": URLS, "license": "OpenRouter rankings, CC BY 4.0", "weeks": {}, "reads": {}}


def save(root, H):
    H["weeks"] = dict(sorted(H.get("weeks", {}).items()))
    H["reads"] = dict(sorted(H.get("reads", {}).items()))
    p = Path(root) / "data" / "openrouter_share.json"
    p.write_text(json.dumps(H, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def merge(H, weeks, read=None):
    W = H.setdefault("weeks", {})
    for wk, x in weeks.items():
        old = W.get(wk)
        # a newer read of a week replaces the stored one, except that a complete week is never replaced by a partial one
        if old and not old.get("partial") and x.get("partial"):
            continue
        W[wk] = x
    if read:
        H.setdefault("reads", {})[read["read_on"]] = read
    return H


def refresh(root, log=print, today=None):
    root = Path(root)
    today = today or datetime.date.today().isoformat()
    chart = get_json(URLS["chart"])
    mw = get_json(URLS["ranking"])["data"]
    cat = catalog_map(get_json(URLS["catalog"])["data"])
    classify = classifier(cat, registry(root))
    rows = [[x["model_permaslug"], x.get("variant"), int(x.get("total_prompt_tokens") or 0), int(x.get("total_completion_tokens") or 0), int(x.get("count") or 0)] for x in mw]
    through = max((x.get("date") or "")[:10] for x in mw) if mw else None
    H = load(root)
    weeks = chart_weeks(chart, classify, cat, today)
    read = read_entry(rows, classify, cat, today, through, "live: every model in the weekly ranking")
    merge(H, weeks, read)
    H["refreshed_at"] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    H["note"], H["source"] = NOTE, URLS
    save(root, H)
    done = [w for w in sorted(weeks) if not weeks[w]["partial"]]
    last = weeks[done[-1]] if done else None
    log("   openrouter share: %d weeks from the Top Models chart (%s to %s); read of %d models: closed %.1f%% of all tokens, %.1f%% of output tokens%s" % (
        len(weeks), min(weeks) if weeks else "-", max(weeks) if weeks else "-", len(rows), 100 * (read["closed_share_all"] or 0), 100 * (read["closed_share_out"] or 0),
        ("; week of %s: named closed %.1f%%, named open %.1f%%, unsplit 'Others' %.1f%%" % (done[-1], 100 * last["closed"] / last["total"], 100 * last["open"] / last["total"], 100 * last["others"] / last["total"])) if last else ""))
    return H


if __name__ == "__main__":
    import sys
    refresh(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
