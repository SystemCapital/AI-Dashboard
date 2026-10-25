"""
Rate history: the series behind the 'Market history' page (data/rate_history.json).

  Silicon Data indices   Silicon Data's public index overview page, https://www.silicondata.com/products/silicon-index,
                         server-renders one card per index (key 'b200-neo', 'h100-hs', 'expenditure', ...) carrying its
                         last 30 daily values. Every run reads it once and merges the configured series' new dates in, so a
                         run at least monthly keeps an unbroken daily series. Until 2026-10-19 the series came from the
                         embeddable chart pages (portal.silicondata.com/gpu-index-chart?standalone=true&gpu=..&mainTab=..,
                         last seven values); since then those load their data from an API that needs a login and render
                         empty, so they are only a fallback. The two sources agree on every overlapping day. Older points
                         that Silicon Data stated in its own monthly index posts are kept under 'stated' with the post's URL;
                         they are drawn as hollow markers.
  Ornn indices           Ornn's Compute Price Index (OCPI, data.ornn.com; Bloomberg-listed) has a public, keyless API:
                           https://api.ornnai.com/api/gpu/<B200|H200|H100 SXM|A100 SXM4|RTX 5090>/index-history   trailing three months, daily
                           https://api.ornnai.com/api/daily-index/all                                              latest settled value per GPU
                         Each run reads the three-month series for the configured GPUs and merges the new dates in, so the
                         file keeps the full series beyond the API's window.
  Token indices          Silicon Data's LLM Token Expenditure Index family (broad market = Bloomberg SDLLMTK, open-weight
                         models, proprietary models): USD per million tokens, usage-weighted across routing gateways and
                         inference networks, input/output blended at the observed mix. Read from the same overview page
                         (cards 'expenditure', 'open_expenditure', 'closed_expenditure'), with the token chart pages
                         (portal.silicondata.com/token-indexes-chart?standalone=true&token=..) as the fallback; merged the same way.
  GetDeploying           an aggregator's public price dataset (CC-BY-4.0): getdeploying.com/dataset/gpu-prices/<gpu>.json
                         carries every week since the GPU was first listed - for each billing type the median of each
                         provider's median price, and the number of providers. Each run merges the weeks in (B300 and B200
                         on-demand and spot, GB200 on-demand), so the market history reaches back before this project's own
                         daily readings (B300 from November 2025). A reference, not an input.
  Provider rental rates  after collect_rentals refreshes the published quotes, every quote (each vendor, chip and tier) is
                         recorded under the date it was read in the 'quotes' block (engine/rental_history.py describes the
                         block). Only what a run observed is written; nothing is interpolated.

The page reduces all of it to weekly series (the last reading in each ISO week). Standard library only.
"""
import json, re, datetime, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "data" / "rate_history.json"
PORTAL = "https://portal.silicondata.com/gpu-index-chart?standalone=true&gpu=%s&mainTab=%s"
SILICON_SITE = "https://www.silicondata.com/products/silicon-index"
MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}
ORNN_HISTORY = "https://api.ornnai.com/api/gpu/%s/index-history"
ORNN_LATEST = "https://api.ornnai.com/api/daily-index/all"
GD_SERIES = [("b300_on_demand", "nvidia-b300", "B300", "ON_DEMAND", "B300 on-demand"), ("b300_spot", "nvidia-b300", "B300", "SPOT", "B300 spot"),
             ("b200_on_demand", "nvidia-b200", "B200", "ON_DEMAND", "B200 on-demand"), ("b200_spot", "nvidia-b200", "B200", "SPOT", "B200 spot"),
             ("gb200_on_demand", "nvidia-gb200", "GB200", "ON_DEMAND", "GB200 on-demand")]


def ornn_series(gpu, fetch=None):
    """Ornn's public daily index series for one GPU ('B200', 'H200', 'H100 SXM'): (values {date: rate}, latest date, url).
    Settled daily at 20:00 UTC; the date is the settlement day."""
    if fetch is None:
        from engine.collect_rentals import fetch
    url = ORNN_HISTORY % urllib.parse.quote(gpu)
    d = json.loads(fetch(url))
    if not d.get("success") or not d.get("data"):
        raise ValueError("Ornn answered without data for %s (%s)" % (gpu, str(d)[:120]))
    if (d.get("gpu_type") or gpu) != gpu:
        raise ValueError("Ornn answered with %s for %s" % (d.get("gpu_type"), gpu))
    values = {x["timestamp"][:10]: round(float(x["index_value"]), 4) for x in d["data"] if x.get("index_value") is not None}
    if not values:
        raise ValueError("Ornn series for %s carried no values" % gpu)
    return values, max(values), url


def silicon_cards(fetch=None):
    """Every index card on Silicon Data's public overview page: {key: {"title", "unit", "as_of", "values" {date: value}}}.
    The page is Next.js; each card sits in its server-rendered payload as {"key":..,"group":..,..,"asOf":"As of Oct 25,
    2026","points":[{"date":"2026-09-26","price":5.87},..]} (30 daily points)."""
    if fetch is None:
        from engine.collect_rentals import fetch
    body = fetch(SILICON_SITE).replace('\\"', '"')
    cards = {}
    for m in re.finditer(r'\{"key":"([a-z0-9_-]+)","group":"([a-z]+)"(.*?)"points":\[(.*?)\]', body):
        values = {d: float(v) for d, v in re.findall(r'"date":"(\d{4}-\d{2}-\d{2})","price":([0-9.]+)', m.group(4))}
        if not values:
            continue
        a = re.search(r'"asOf":"As of ([A-Z][a-z]{2})[a-z]* (\d{1,2}), (\d{4})"', m.group(3))
        as_of = "%s-%02d-%02d" % (a.group(3), MONTHS[a.group(1)], int(a.group(2))) if a and a.group(1) in MONTHS else max(values)
        t = re.search(r'"title":"([^"]*)"', m.group(3))
        u = re.search(r'"unit":"([^"]*)"', m.group(3))
        cards.setdefault(m.group(1), {"title": t.group(1) if t else m.group(1), "unit": u.group(1) if u else "", "as_of": as_of, "values": values})
    return cards


def silicon_series(gpu, tab="neo-cloud", fetch=None):
    """The latest daily values of one Silicon Data GPU index: the overview page's card ('<gpu>-neo' or '<gpu>-hs',
    30 values), else the old embeddable chart page (seven values). Returns (values {date: rate}, ending_date, url).
    Raises if neither carries the requested GPU."""
    if fetch is None:
        from engine.collect_rentals import fetch
    try:
        card = silicon_cards(fetch).get("%s-%s" % (gpu, "hs" if tab == "hyperscaler" else "neo"))
    except Exception:
        card = None
    if card:
        return card["values"], card["as_of"], SILICON_SITE
    url = PORTAL % (gpu, tab)
    body = fetch(url).replace('\\"', '"')
    m = re.search(r'"gpu":"([a-z0-9]+)","indexes":\{([^}]*)\}', body)
    if not m:
        raise ValueError("no index payload on %s" % url)
    if m.group(1) != gpu:
        raise ValueError("portal answered with %s for %s (index not published)" % (m.group(1), gpu))
    values = {d: float(v) for d, v in re.findall(r'"(\d{4}-\d{2}-\d{2})":"([0-9.]+)"', m.group(2))}
    if not values:
        raise ValueError("payload for %s carried no dated values" % gpu)
    e = re.search(r'"ending_date":"(\d{4}-\d{2}-\d{2})"', body)
    return values, (e.group(1) if e else max(values)), url


TOKEN_PORTAL = "https://portal.silicondata.com/token-indexes-chart?standalone=true&token=%s"


def silicon_token_series(token, fetch=None):
    """The last seven daily values of one Silicon Data LLM Token Expenditure Index from its public chart page.
    token: 'expenditure' (broad market, Bloomberg SDLLMTK), 'open_expenditure' (open-weight models) or
    'closed_expenditure' (proprietary models). USD per million tokens, usage-weighted, input/output blended at the
    observed mix. Returns (values {date: price}, ending_date, url); raises if the page answers with another series
    (an unknown token name silently falls back to the broad index)."""
    if fetch is None:
        from engine.collect_rentals import fetch
    try:
        card = silicon_cards(fetch).get(token)
    except Exception:
        card = None
    if card:
        return card["values"], card["as_of"], SILICON_SITE
    url = TOKEN_PORTAL % token
    body = fetch(url).replace('\\"', '"')
    m = re.search(r'"token":"([a-z_]+)","starting_date":"[^"]*","ending_date":"(\d{4}-\d{2}-\d{2})","indexes":\{([^}]*)\},"index_name":"([^"]*)"', body)
    if not m:
        raise ValueError("no token-index payload on %s" % url)
    if m.group(1) != token:
        raise ValueError("portal answered with %s for %s" % (m.group(1), token))
    values = {d: float(v) for d, v in re.findall(r'"(\d{4}-\d{2}-\d{2})":"([0-9.]+)"', m.group(3))}
    if not values:
        raise ValueError("token index %s carried no dated values" % token)
    return values, m.group(2), url


def load():
    return json.load(open(PATH, encoding="utf-8"))


def save(doc):
    json.dump(doc, open(PATH, "w", encoding="utf-8"), indent=1)


def record_quotes(doc, quotes, log=print):
    """Record every published rental quote (all vendors, chips and tiers) under its read date."""
    from engine.rental_history import record
    return record(doc, quotes, log)


def getdeploying_block(doc):
    b = doc.setdefault("getdeploying_index", {"source": "GetDeploying GPU price dataset (CC-BY-4.0)", "landing": "https://getdeploying.com/gpus",
                                               "attribution": "GetDeploying, https://getdeploying.com/gpus", "series": {}})
    for key, gpu, chip, billing, label in GD_SERIES:
        b["series"].setdefault(key, {"gpu": gpu, "chip": chip, "billing": billing, "label": "GetDeploying " + label, "family": "Blackwell",
                                     "url": "https://getdeploying.com/gpus/" + gpu, "values": {}, "providers": {}})
    return b


def _merge(block, provider, getter, today, log):
    ok, failed, added = 0, 0, 0
    for key, s in block["series"].items():
        try:
            values, end, url = getter(s)
            new = {d: v for d, v in values.items() if s["values"].get(d) != v}
            s["values"].update(values)
            s["as_of"], s["read_on"], s["url"] = end, today, url
            s.pop("refresh_error", None)
            ok += 1
            added += len(new)
            log("   %-12s %-24s %s = $%.2f  (%d new daily values)" % (provider, s["label"], end, values[end] if end in values else values[max(values)], len(new)))
        except Exception as ex:
            failed += 1
            s["refresh_error"] = "%s: %s" % (today, str(ex)[:160])
            log("   %-12s %-24s FAILED (%s) - kept %d values to %s" % (provider, s["label"], str(ex)[:80], len(s["values"]), max(s["values"]) if s["values"] else "-"))
    block["read_on"] = today
    return ok, failed, added


def refresh(log=print, quotes=None, offline=False):
    doc = load()
    today = datetime.date.today().isoformat()
    ok, failed, added = 0, 0, 0
    if not offline:
        o, f, a = _merge(doc["silicon_index"], "Silicon Data", lambda s: silicon_series(s["gpu"], s["tab"]), today, log)
        ok, failed, added = ok + o, failed + f, added + a
        if "ornn_index" in doc:
            o, f, a = _merge(doc["ornn_index"], "Ornn", lambda s: ornn_series(s["gpu"]), today, log)
            ok, failed, added = ok + o, failed + f, added + a
        if "token_index" in doc:
            o, f, a = _merge(doc["token_index"], "SD tokens", lambda s: silicon_token_series(s["token"]), today, log)
            ok, failed, added = ok + o, failed + f, added + a
        from engine.collect_rentals import getdeploying_series
        gd = getdeploying_block(doc)
        def gd_get(s):
            vals, cnt, url = getdeploying_series(s["gpu"], s["billing"])
            s.setdefault("providers", {}).update(cnt)
            return vals, max(vals), s["url"]
        o, f, a = _merge(gd, "GetDeploying", gd_get, today, log)
        ok, failed, added = ok + o, failed + f, added + a
    if quotes is None:
        quotes = json.load(open(ROOT / "data" / "rental_rates.json", encoding="utf-8"))["quotes"]
    n_q = record_quotes(doc, quotes, log)
    doc["refreshed_at"] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    save(doc)
    log("history: %d index series refreshed (%d new values), %d failed; %d provider rate readings recorded" % (ok, added, failed, n_q))
    return ok, failed


if __name__ == "__main__":
    refresh()
