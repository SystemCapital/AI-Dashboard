"""
Refreshes the published rental quotes in data/rental_rates.json that have a machine-readable source, and makes every
price change visible.

  kind 'oracle'   Oracle's public price-list API (JSON): /cetools/api/v1/products/?partNumber=<part>
  kind 'azure'    Azure Retail Prices API (JSON): armSkuName + priceType Consumption, Linux, chosen region; with
                  "spot": true the Spot meter of the same SKU and region (Azure's current spot price, which can equal
                  pay-as-you-go when the region is full)
  kind 'aws_spot' AWS's public EC2 Spot price feed (website.spot.ec2.aws.a2z.com/spot.json, the file the Spot pricing
                  page reads; JSON or JSONP): Linux price of an instance size in a region, no credentials needed
  kind 'vultr'    Vultr's public plan list (api.vultr.com/v2/plans-metal, no key needed): a bare-metal plan's hourly price
  kind 'html'     a vendor pricing page: the first (or nth) dollar figure that follows the row label, optionally
                  after a sub-label ('Spot Price:') and cut off at the next row ('stop'); every occurrence of the
                  label is tried in order. A row that says 'Contact sales' / 'Contact us' before any figure is recorded
                  as not published (no error). 'effective_header' handles a table that shows today's price and an
                  announced one side by side ('GPU-hour (Effective October 1, 2026)'): before that date the row takes
                  the first column and records the second as announced; from that date it takes the second column.
                  'announce' reads a dated announcement elsewhere on the page ('Effective October 7, 2026, hourly rates
                  per accelerator ... P6-B300 at $16.146') the same way. 'skip_floor' ignores figures written 'from $X'
                  (a floor, not a rate: Nebius's preemptible column since October 2026). Brittle by nature, so a parse that fails or
                  moves by more than 3x keeps the old value and says why.
  kind 'silicon'  a Silicon Data index: the public chart page behind it (engine/collect_history.silicon_series)
  kind 'ornn'     an Ornn Compute Price Index: the public keyless API (engine/collect_history.ornn_series)
  kind 'getdeploying'  GetDeploying's public price dataset (getdeploying.com/dataset/gpu-prices/<gpu>.json, CC-BY-4.0):
                  the latest week's median across providers for one billing type (an aggregator reference, tier 'index')

Making changes visible (all written to data/rental_rates.json, all shown on the dashboard's rental market page):
  changes      every move in a list price (any amount) and every move of 10% or more in a dynamically priced row since
               the last logged value, with the old and new rate and the dates read
  announced    on each quote: a published future price and its effective date
  notices      pricing notices found on the vendors' pages ('Announcement: ... pricing update', 'Effective <date> ...',
               'scheduled to be updated next in <month>'), with the day each was first and last seen
  price_news   news headlines about GPU price moves by the providers tracked here (Google News RSS, last 14 days),
               for review: unverified until a rate card or filing shows the change
  price_actions  curated, sourced record of price moves that never reached a rate card (management disclosures,
               contract pricing per MW) or that predate the daily collection - edited by hand (or by Claude)
Every refreshed row gets today's read_on; a row that could not be refreshed keeps its old read_on so the page can show
its age, and rows not read within rental.max_quote_age_days drop out of the near-term bases. engine/rental_history
records each day's readings in data/rate_history.json. Standard library only.
"""
import json, re, sys, datetime, urllib.request, urllib.parse, html as htmllib
from pathlib import Path
from engine import net

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "data" / "rental_rates.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; blackwell-roic/1.0; +local research tool)", "Accept": "text/html,application/json"}
NEWS = "https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en"
PRICE_NEWS_QUERY = ('(CoreWeave OR Nebius OR Lambda OR Verda OR "Together AI" OR Oracle OR Azure OR AWS OR "Google Cloud" OR Vultr OR Crusoe OR Hyperbolic) '
                    'GPU (price OR prices OR pricing) (increase OR increases OR raise OR raises OR hike OR hikes OR cut OR cuts OR lower) when:14d')
PROVIDERS = ["CoreWeave", "Nebius", "Lambda", "Verda", "DataCrunch", "Together AI", "Oracle", "OCI", "Azure", "Microsoft", "AWS", "Amazon",
             "Google Cloud", "Vultr", "Crusoe", "Hyperbolic", "Nscale", "Fluidstack", "RunPod", "Vast.ai", "IREN"]
PRICE_WORDS = re.compile(r"\b(price|prices|pricing|rate|rates)\b", re.I)
MOVE_WORDS = re.compile(r"\b(increase[sd]?|rais(?:e|es|ed|ing)|hike[sd]?|cut[s]?|lower(?:s|ed)?|reduc(?:e|es|ed)|jump[s]?|climb[s]?|surge[sd]?|up \d+%|down \d+%)\b", re.I)
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
S_ = r"(?:[^.]|\.(?=\d))"           # a sentence character: anything but a full stop (a decimal point is fine)
NOTICE_RES = [re.compile(r"(Announcement:?%s{0,160}?(?:[Pp]ric(?:e|ing)|[Rr]ate)%s{0,40}\.(?:%s{0,500}\.)?)" % (S_, S_, S_)),
              re.compile(r"((?:[Ee]ffective|[Ss]tarting|[Bb]eginning|[Ff]rom)(?: on| from| as of)? (?:%s) \d{1,2},? 20\d\d,?%s{0,400}?(?:price|pricing|rate)%s{0,400}\.)" % (MONTHS, S_, S_)),
              re.compile(r"(%s{0,160}scheduled to be updated next in (?:%s),? 20\d\d)" % (S_, MONTHS)),
              re.compile(r"((?:GPU-hour|[Pp]rice|[Pp]ricing|[Rr]ate)[^.(]{0,40}\((?:[Ee]ffective|[Ff]rom|[Ss]tarting) (?:%s) \d{1,2},? 20\d\d\))" % MONTHS)]
DYNAMIC_LOG_STEP = 0.10          # a dynamically priced row is logged when it has moved this much since its last logged value
_cache = {}


class NotPublished(Exception):
    pass


def fetch(url, timeout=45):
    if url in _cache:
        return _cache[url]
    req = urllib.request.Request(url, headers=UA)
    body = net.read(req, timeout).decode("utf-8", "ignore")
    _cache[url] = body
    return body


def page_text(url):
    body = fetch(url)
    text = htmllib.unescape(re.sub(r"<[^>]+>", " ", body))
    return re.sub(r"\s+", " ", text)


def parse_date(s):
    s = re.sub(r"\s*,\s*", " ", s).strip()
    return datetime.datetime.strptime(re.sub(r"\s+", " ", s), "%B %d %Y").date()


def oracle_rate(part):
    url = "https://apexapps.oracle.com/pls/apex/cetools/api/v1/products/?partNumber=%s&currencyCode=USD" % part
    d = json.loads(fetch(url))
    for item in d.get("items", []):
        for cl in item.get("currencyCodeLocalizations", []):
            for p in cl.get("prices", []):
                if p.get("model") in ("PAY_AS_YOU_GO",) or "value" in p:
                    return float(p["value"]), url
    raise ValueError("no PAY_AS_YOU_GO price in Oracle response")


def azure_rate(sku, region, spot=False):
    flt = "armSkuName eq '%s' and priceType eq 'Consumption' and armRegionName eq '%s'" % (sku, region)
    url = "https://prices.azure.com/api/retail/prices?$filter=" + urllib.parse.quote(flt)
    d = json.loads(fetch(url))
    items = [i for i in d.get("Items", []) if "Windows" not in (i.get("productName") or "") and "Low Priority" not in (i.get("meterName") or "")
             and (("Spot" in (i.get("meterName") or "")) == bool(spot))]
    if not items:
        raise ValueError("no Linux %s meter for %s in %s" % ("spot" if spot else "consumption", sku, region))
    return float(items[0]["retailPrice"]), url


AWS_SPOT = "https://website.spot.ec2.aws.a2z.com/spot.json"


def aws_spot_rate(size, region):
    """Linux EC2 Spot price per hour for an instance size in a region, from the public feed behind AWS's Spot pricing page."""
    body = fetch(AWS_SPOT)
    m = re.match(r"\s*callback\((.*)\)\s*;?\s*$", body, re.S)
    d = json.loads(m.group(1) if m else body[body.find("{"):body.rfind("}") + 1])
    for reg in d["config"]["regions"]:
        if reg["region"] != region:
            continue
        for it in reg["instanceTypes"]:
            for sz in it["sizes"]:
                if sz["size"] == size:
                    lin = next((v for v in sz["valueColumns"] if v["name"] == "linux"), None)
                    if lin and lin["prices"].get("USD") not in (None, "N/A*", "N/A"):
                        return float(lin["prices"]["USD"]), "https://aws.amazon.com/ec2/spot/pricing/"
                    raise ValueError("no Linux spot price for %s in %s" % (size, region))
    raise ValueError("%s not in the spot feed for %s" % (size, region))


VULTR_METAL = "https://api.vultr.com/v2/plans-metal?per_page=500"


def vultr_rate(plan):
    d = json.loads(fetch(VULTR_METAL))
    for p in d.get("plans_metal", []):
        if p.get("id") == plan:
            return float(p["hourly_cost"]), VULTR_METAL
    raise ValueError("plan %s not in Vultr's plan list" % plan)


GETDEPLOYING = "https://getdeploying.com/dataset/gpu-prices/%s.json"


def getdeploying_series(gpu, billing="ON_DEMAND", months=None, fetch=None):
    """GetDeploying's weekly series for one GPU and billing type: ({week: provider median $/GPU-hr}, {week: providers}, url).
    CC-BY-4.0; attribution 'GetDeploying, https://getdeploying.com/gpus/<gpu>'."""
    fetch = fetch or globals()["fetch"]
    url = GETDEPLOYING % gpu
    d = json.loads(fetch(url))
    vals, cnt = {}, {}
    for r in d.get("data", []):
        if r.get("billing_type") == billing and r.get("reservation_months") == months and r.get("provider_median_price") is not None:
            vals[r["date"]] = round(float(r["provider_median_price"]), 4)
            cnt[r["date"]] = r.get("provider_count")
    if not vals:
        raise ValueError("no %s series for %s" % (billing, gpu))
    return vals, cnt, url


def html_rate(url, label, after=None, stop=None, nth=1, span=600, skip_floor=False):
    """First (or nth) dollar figure after `label` on the page. `after`: a sub-label that must follow the label
    (e.g. 'Spot Price:'), the figure is taken after it. `stop`: the window ends at the next occurrence of this
    string (e.g. the next row's 'GPU Count'), so a row with no price cannot borrow the next row's. A page often
    carries the label several times (structured-data blocks, menus, a table the browser fills later), so every
    occurrence is tried in order and the first whose window yields the figure wins. A window that reads 'Contact
    sales' / 'Contact us' before any figure raises NotPublished. `skip_floor`: figures written 'from $X' are floors,
    not rates, and are not counted."""
    text = page_text(url)
    i, tried, last, contact = text.find(label), 0, None, False
    if i < 0:
        raise ValueError("label %r not on page" % label)
    while i >= 0 and tried < 40:
        tried += 1
        window = text[i + len(label):i + len(label) + span]
        if stop:
            j = window.find(stop)
            if j > 0:
                window = window[:j]
        k = window.find(after) if after else 0
        if k >= 0:
            if after:
                window = window[k + len(after):]
            m = re.search(r"\$\s?[0-9]", window)
            c = re.search(r"[Cc]ontact (?:sales|us)", window)
            contact_first = bool(c and (not m or c.start() < m.start()))
            contact = contact or contact_first
            figs = re.findall((r"(?<![Ff]rom )" if skip_floor else "") + r"\$\s?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)", window)
            if len(figs) >= nth and not contact_first:
                return float(figs[nth - 1].replace(",", "")), url
            last = "no dollar figure #%d after %r%s" % (nth, label, (" / " + after) if after else "")
        else:
            last = "%r not within the %r row" % (after, label)
        i = text.find(label, i + len(label))
    if contact:
        raise NotPublished("the vendor shows 'Contact sales' for this row (no published price)")
    raise ValueError(last or ("label %r not on page" % label))


def effective_column(url, spec, today):
    """(nth to read today, announced dict or None) for a table with a dated second price column"""
    m = re.search(spec["effective_header"], page_text(url))
    if not m:
        return spec.get("nth", 1), None, None
    eff = parse_date(m.group(1))
    return (spec.get("effective_nth", 2) if today >= eff else spec.get("nth", 1)), eff, m.group(0)


def announcement(url, spec):
    """(effective date, price per instance-hour or per GPU per spec, matched text) from a dated announcement on the page, or None"""
    a = spec["announce"]
    text = page_text(url)
    m = re.search(a["date"], text)
    if not m:
        return None
    p = re.search(a["price"], text[m.start():m.start() + 1500])
    if not p:
        return None
    return parse_date(m.group(1)), float(p.group(1).replace(",", "")), text[m.start():m.start() + 400]


def scan_notices(d, pages, today, log=print):
    """pricing notices on the vendors' pages: new ones are added, ones still on the page get last_seen = today"""
    notes = d.setdefault("notices", [])
    seen = {(n["url"], n["text"]): n for n in notes}
    added = 0
    for url, vendor in pages.items():
        try:
            text = page_text(url)
        except Exception:
            continue
        for n_rx, rx in enumerate(NOTICE_RES):
            for m in rx.finditer(text):
                t = m.group(1).strip()[:600]
                if '"' in t or "\\" in t:                        # the same text inside a JSON blob on the page
                    continue
                if n_rx == 3:                                     # a dated price column: keep the date, not the header words
                    t = "price table column headed '%s'" % t[t.rfind("(") + 1:].rstrip(")")
                years = [int(y) for y in re.findall(r"\b(20\d\d)\b", t)]
                if years and max(years) < today.year - 1:        # boilerplate about old changes (e.g. 'On July 1, 2024 ...')
                    continue
                if (url, t) in seen:
                    seen[(url, t)]["last_seen"] = today.isoformat()
                    continue
                n = {"vendor": vendor, "url": url, "text": t, "first_seen": today.isoformat(), "last_seen": today.isoformat()}
                notes.append(n)
                seen[(url, t)] = n
                added += 1
                log("   NOTICE  %-20s %s" % (vendor, t[:150]))
    return added


def scan_price_news(d, today, fetch_fn=None, log=print):
    """headlines about GPU price moves by the tracked providers (Google News RSS, last 14 days), deduplicated by link"""
    from engine.collect_deals import parse_rss
    fetch_fn = fetch_fn or fetch
    items = parse_rss(fetch_fn(NEWS % urllib.parse.quote(PRICE_NEWS_QUERY)))
    have = {n["link"] for n in d.setdefault("price_news", [])}
    added = 0
    for it in items:
        t = it["title"]
        provs = [p for p in PROVIDERS if re.search(r"\b%s\b" % re.escape(p), t)]
        if not provs or not PRICE_WORDS.search(t) or not MOVE_WORDS.search(t) or it["link"] in have:
            continue
        d["price_news"].append({"title": t, "link": it["link"], "source": it.get("source", ""), "published": it.get("published", ""),
                                "providers": provs, "first_seen": today.isoformat(), "status": "unverified"})
        have.add(it["link"])
        added += 1
    cutoff = (today - datetime.timedelta(days=60)).isoformat()
    d["price_news"] = [n for n in d["price_news"] if (n.get("published") or n.get("first_seen") or "") >= cutoff or n.get("status") == "confirmed"]
    log("   price news: %d headlines read, %d new about tracked providers (%d kept, last 60 days)" % (len(items), added, len(d["price_news"])))
    return added


def log_change(d, q, old, new, today, prev_read, kind="observed", note=""):
    """append a price change to d['changes']: list prices on any move, dynamic prices on a 10% move since last logged"""
    if old is None or new is None:
        return False
    if q.get("pricing") == "dynamic":
        base = q.get("logged_value") or old
        if abs(new / base - 1) < DYNAMIC_LOG_STEP:
            return False
        old = base
    elif abs(new - old) < 0.005:
        return False
    from engine.rental_history import key_of
    d.setdefault("changes", []).append({"date": today.isoformat(), "key": key_of(q), "vendor": q["vendor"], "chip": q["chip"], "tier": q["tier"],
                                        "instance": q.get("instance", ""), "old": round(old, 4), "new": round(new, 4), "pct": round(new / old - 1, 4),
                                        "prev_read": prev_read, "kind": kind, "pricing": q.get("pricing", "list"), "url": q.get("url", ""), "note": note})
    q["logged_value"] = round(new, 4)
    return True


def refresh(log=print, only=None, today=None):
    d = json.load(open(PATH, encoding="utf-8"))
    today = today or datetime.date.today()
    ts = today.isoformat()
    ok, failed, skipped, n_changes = 0, 0, 0, 0
    pages = {}
    for q in d["quotes"]:
        spec = q.get("refresh")
        if not spec:
            skipped += 1
            continue
        old, prev_read = q.get("per_gpu_hr"), q.get("read_on")
        try:
            note = ""
            if spec["kind"] == "oracle":
                per_gpu, url = oracle_rate(spec["part"])
                price_hr = per_gpu * (q.get("gpus") or 1)
            elif spec["kind"] == "azure":
                price_hr, url = azure_rate(spec["sku"], spec["region"], spec.get("spot", False))
                per_gpu = price_hr / spec["gpus"]
            elif spec["kind"] == "aws_spot":
                price_hr, url = aws_spot_rate(spec["size"], spec["region"])
                per_gpu = price_hr / spec["gpus"]
            elif spec["kind"] == "vultr":
                price_hr, url = vultr_rate(spec["plan"])
                per_gpu = price_hr / spec["gpus"]
            elif spec["kind"] == "html":
                pages[q["url"]] = q["vendor"]
                nth = spec.get("nth", 1)
                if spec.get("effective_header"):
                    nth, eff, hdr = effective_column(q["url"], spec, today)
                    if eff and today < eff:
                        nv, _ = html_rate(q["url"], spec["label"], spec.get("after"), spec.get("stop"), spec.get("effective_nth", 2), spec.get("span", 600), spec.get("skip_floor", False))
                        q["announced"] = {"effective": eff.isoformat(), "value": round(nv / spec["gpus"], 4), "seen_on": (q.get("announced") or {}).get("seen_on", ts),
                                          "text": hdr, "url": q["url"]}
                    elif eff:
                        q.pop("announced", None)
                        note = "price from the column headed %r (in force since %s)" % (hdr, eff.isoformat())
                price_hr, url = html_rate(q["url"], spec["label"], spec.get("after"), spec.get("stop"), nth, spec.get("span", 600), spec.get("skip_floor", False))
                per_gpu = price_hr / spec["gpus"]
                if spec.get("announce"):
                    a = announcement(q["url"], spec)
                    if a:
                        eff, ap, txt = a
                        ap_gpu = ap if spec["announce"].get("per") == "gpu" else ap / spec["gpus"]
                        if today < eff:
                            q["announced"] = {"effective": eff.isoformat(), "value": round(ap_gpu, 4), "seen_on": (q.get("announced") or {}).get("seen_on", ts), "text": txt, "url": q["url"]}
                        else:
                            q.pop("announced", None)
                            if abs(ap_gpu - per_gpu) > 0.005:          # in force by the vendor's own notice, table not yet updated
                                note = "the vendor's notice puts $%.3f in force from %s; the table still showed $%.3f" % (ap_gpu, eff.isoformat(), per_gpu)
                                per_gpu, price_hr = ap_gpu, ap_gpu * spec["gpus"]
                    elif (q.get("announced") or {}).get("effective", "9999") <= ts:
                        q.pop("announced", None)
            elif spec["kind"] in ("silicon", "ornn"):
                from engine.collect_history import silicon_series, ornn_series
                if spec["kind"] == "silicon":
                    values, as_of, url = silicon_series(spec["gpu"], spec.get("tab", "neo-cloud"), fetch=fetch)
                else:
                    values, as_of, url = ornn_series(spec["gpu"], fetch=fetch)
                    url = q["url"]
                price_hr = per_gpu = values[as_of] if as_of in values else values[max(values)]
                q["as_of"] = as_of if as_of in values else max(values)
            elif spec["kind"] == "getdeploying":
                values, cnt, url = getdeploying_series(spec["gpu"], spec.get("billing", "ON_DEMAND"), spec.get("months"), fetch=fetch)
                wk = max(values)
                price_hr = per_gpu = values[wk]
                q["as_of"], q["providers"] = wk, cnt.get(wk)
                url = q["url"]
            else:
                skipped += 1
                continue
            if old and (per_gpu > 3 * old or per_gpu < old / 3):
                raise ValueError("parsed $%.2f/GPU-hr, more than 3x away from the recorded $%.2f; kept the old value" % (per_gpu, old))
            q["price_hr"], q["per_gpu_hr"], q["read_on"] = round(price_hr, 4), round(per_gpu, 4), ts
            q.pop("refresh_error", None)
            q.pop("status", None) if q.get("status") == "not published" else None
            if note:
                q["refresh_note"] = note
            else:
                q.pop("refresh_note", None)
            if q.get("tier") != "index" and log_change(d, q, old, per_gpu, today, prev_read, note=note):
                n_changes += 1
                c = d["changes"][-1]
                log("   CHANGE  %-22s %-6s %-14s $%.2f -> $%.2f (%+.1f%%) since %s" % (q["vendor"], q["chip"], q["tier"], c["old"], c["new"], 100 * c["pct"], prev_read))
            ok += 1
            ann = q.get("announced")
            log("   %-22s %-6s %-14s $%.2f/GPU-hr%s%s" % (q["vendor"], q["chip"], q["tier"], per_gpu,
                (" (index as of %s)" % q["as_of"]) if spec["kind"] in ("silicon", "ornn", "getdeploying") else "",
                (" - announced $%.2f from %s" % (ann["value"], ann["effective"])) if ann else ""))
        except NotPublished as ex:
            ok += 1
            q.update({"price_hr": None, "per_gpu_hr": None, "read_on": ts, "status": "not published", "refresh_note": str(ex)})
            q.pop("refresh_error", None)
            log("   %-22s %-6s %-14s not published (%s)" % (q["vendor"], q["chip"], q["tier"], str(ex)[:60]))
        except Exception as ex:
            failed += 1
            q["refresh_error"] = "%s: %s" % (ts, str(ex)[:160])
            log("   %-22s %-6s %-14s FAILED (%s) - kept %s from %s" % (q["vendor"], q["chip"], q["tier"], str(ex)[:80], q.get("per_gpu_hr"), q.get("read_on")))
    try:
        n_notices = scan_notices(d, pages, today, log)
    except Exception as ex:
        n_notices = 0
        log("   notices scan failed (%s)" % str(ex)[:100])
    try:
        scan_price_news(d, today, log=log)
    except Exception as ex:
        log("   price news scan failed (%s)" % str(ex)[:100])
    d["refreshed_at"] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    json.dump(d, open(PATH, "w", encoding="utf-8"), indent=1)
    log("rentals: %d refreshed, %d failed (old values kept), %d manual rows; %d price changes, %d new pricing notices" % (ok, failed, skipped, n_changes, n_notices))
    return ok, failed


if __name__ == "__main__":
    refresh()
