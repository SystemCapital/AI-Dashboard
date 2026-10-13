"""
Rate history: the series behind the 'Market history' page (data/rate_history.json).

  Silicon Data indices   portal.silicondata.com serves a public, embeddable chart page per index whose server-rendered
                         payload carries the last seven daily index values:
                           https://portal.silicondata.com/gpu-index-chart?standalone=true&gpu=<b200|h200|h100|a100|mi300x>&mainTab=<neo-cloud|hyperscaler>
                         Every run reads the configured series and merges the new dates in, so a run at least weekly
                         keeps an unbroken daily series (the portal always answers with h100 for a GPU it does not index,
                         so the GPU echoed in the payload is checked). Older points that Silicon Data stated in its own
                         monthly index posts are kept under 'stated' with the post's URL; they are drawn as hollow markers.
  Ornn indices           Ornn's Compute Price Index (OCPI, data.ornn.com; Bloomberg-listed) has a public, keyless API:
                           https://api.ornnai.com/api/gpu/<B200|H200|H100 SXM|A100 SXM4|RTX 5090>/index-history   trailing three months, daily
                           https://api.ornnai.com/api/daily-index/all                                              latest settled value per GPU
                         Each run reads the three-month series for the configured GPUs and merges the new dates in, so the
                         file keeps the full series beyond the API's window.
  Token indices          Silicon Data's LLM Token Expenditure Index family (broad market = Bloomberg SDLLMTK, open-weight
                         models, proprietary models): USD per million tokens, usage-weighted across routing gateways and
                         inference networks, input/output blended at the observed mix. Same public chart-page mechanism:
                           https://portal.silicondata.com/token-indexes-chart?standalone=true&token=<expenditure|open_expenditure|closed_expenditure>
                         carries the last seven daily values; merged the same way.
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


def silicon_series(gpu, tab="neo-cloud", fetch=None):
    """The last seven daily values of one Silicon Data index from its public chart page.
    Returns (values {date: rate}, ending_date, url). Raises if the page does not carry the requested GPU."""
    if fetch is None:
        from engine.collect_rentals import fetch
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
