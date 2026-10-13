"""
Deal scout: every run scans two public feeds for newly announced multi-year GPU / AI-compute contracts and queues
anything that looks like one in data/deal_candidates.json, with the figures it could read from the headline
(value, term, GPUs, MW, chip, the companies named). Candidates are for review: the page lists them under the
contracts table, and a person (or Claude) moves a confirmed deal into data/rental_rates.json 'contracts' with the
right classification. Nothing enters the medians automatically.

  Google News RSS      https://news.google.com/rss/search?q=<query>&hl=en-US&gl=US&ceid=US:en
                       three queries limited to the last 7 days (when:7d). Google's feed terms allow personal,
                       non-commercial use in a feed reader, which is what this research tool is; keep it light.
  SEC EDGAR full-text  https://efts.sec.gov/LATEST/search-index?q=<phrase>&forms=8-K,6-K&dateRange=custom&startdt=..&enddt=..
                       8-K / 6-K exhibits of the last 7 days mentioning GPU agreements (Nebius, CoreWeave, IREN, Cipher,
                       Hut 8, Sharon AI and the other listed operators file their deals here). Each hit's exhibit is
                       fetched once so the headline and figures come from the filing itself. The SEC asks every
                       automated client to identify itself with a company name and contact email in the User-Agent:
                       set assumptions.json -> deals.sec_user_agent; the EDGAR pass is skipped while it is blank.

Standard library only. A source that fails keeps the file as it was and writes the reason to the log.
Test offline:  python engine/tests/test_deals.py
"""
import json, re, time, datetime, html as htmllib, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "data" / "deal_candidates.json"
NEWS = "https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en"
EDGAR = "https://efts.sec.gov/LATEST/search-index?q=%s&forms=8-K,6-K&dateRange=custom&startdt=%s&enddt=%s"
QUERIES = [
    '"GPU" (agreement OR contract OR deal OR lease) billion ("multi-year" OR "five-year" OR "six-year" OR "10-year" OR "15-year") when:7d',
    '("AI cloud" OR "compute capacity" OR neocloud OR "AI compute") (agreement OR contract OR deal OR signs) billion when:7d',
    '("data center" OR "data centre") lease (MW OR gigawatt) (AI OR GPU OR hyperscaler) billion when:7d',
]
EDGAR_PHRASES = ['"GPU" "agreement"', '"AI cloud" "agreement"', '"compute capacity" "agreement"']
EDGAR_DOC_LIMIT = 12          # exhibits fetched per run, newest first
DEAL_WORDS = re.compile(r"\b(agreement|contract|deal|lease|signs?|signed|commit(?:s|ment)?|secures?|inks?|order form|offtake|anchor)\b", re.I)
TOPIC_WORDS = re.compile(r"\b(GPU|GPUs|compute|AI cloud|capacity|data cent(?:er|re)s?|GB300|GB200|B300|B200|Blackwell|Rubin|TPU|Trainium|neo[- ]?cloud|hosting|colocation|MW|gigawatt|NVIDIA)\b", re.I)
NOISE = re.compile(r"\b(stock|shares? (?:jump|drop|fall|rise|surge|slide)|price target|analyst|earnings call|why |should you|buy|sell|rating|ETF|options|short interest|valuation|funding round|raises? (?:\$|USD)|IPO|offering|notes? offering|convertible|loan|financing|credit facility|acqui(?:res?|sition)|takeover|merger|buyout)\b", re.I)
COMPANIES = ["CoreWeave", "Nebius", "Nscale", "IREN", "Iren", "Lambda", "Crusoe", "Fluidstack", "Together AI", "Vultr", "Voltage Park", "Firmus", "Sharon AI", "SharonAI", "Applied Digital", "ChronoScale",
             "Core42", "G42", "Bitdeer", "HIVE", "BUZZ HPC", "Cipher", "TeraWulf", "Hut 8", "Core Scientific", "Galaxy", "CleanSpark", "Riot", "Bitfarms", "WhiteFiber", "Soluna", "Mawson", "Ionic Digital",
             "Axe Compute", "Volta", "Akamai", "Corvex", "QumulusAI", "Exascale", "Northern Data", "Vantage", "Aligned", "Related Digital", "Blue Owl",
             "Microsoft", "Azure", "Meta", "OpenAI", "Anthropic", "Google", "Alphabet", "AWS", "Amazon", "Oracle", "xAI", "SpaceX", "NVIDIA", "Nvidia", "AMD", "Cerebras",
             "Jane Street", "Hudson River Trading", "Poolside", "Mistral", "Cohere", "Perplexity", "Reflection", "Figure", "Thinking Machines", "Safe Superintelligence", "Cursor", "Stargate", "Hugging Face"]
UA_DEFAULT = "Mozilla/5.0 (compatible; blackwell-roic/1.0; research dashboard)"


def fetch(url, ua=UA_DEFAULT, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "application/rss+xml, application/xml, application/json, text/xml, text/html, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


# ------------------------------------------------------------------ extractors (headline or filing text -> figures)
MONEY = re.compile(r"(?:US\s?)?\$\s?([0-9]+(?:[.,][0-9]+)?)\s*(billion|bn|b|million|mn|m)\b"
                   r"|\bUSD\s?([0-9]+(?:[.,][0-9]+)?)\s*(billion|bn|million|mn)\b"
                   r"|\b([0-9]+(?:[.,][0-9]+)?)\s*(billion|million)\s*(?:US\s*)?dollars?\b", re.I)


def money_b(text):
    """First money figure in the text, in USD billions ($13B, US$3.5 billion, USD3 billion, 32 billion US dollars, $350 million)."""
    m = MONEY.search(text)
    if not m:
        return None
    num = m.group(1) or m.group(3) or m.group(5)
    unit = (m.group(2) or m.group(4) or m.group(6)).lower()
    v = float(num.replace(",", ""))
    return round(v if unit in ("billion", "bn", "b") else v / 1000.0, 3)


WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20}


def term_years(text):
    m = re.search(r"\b([0-9]{1,2}|one|two|three|four|five|six|seven|eight|ten|twelve|fifteen|twenty)[- ]year\b", text, re.I)
    if not m:
        return None
    t = m.group(1).lower()
    return int(t) if t.isdigit() else WORDNUM.get(t)


def gpus_of(text):
    m = re.search(r"\b([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,6})\s*(?:additional\s+|latest-generation\s+|NVIDIA\s+)*(?:GB300|GB200|B300|B200|Blackwell|Rubin|Vera Rubin|H100|H200)?\s*(?:GPUs?|chips)\b", text, re.I)
    return int(m.group(1).replace(",", "")) if m else None


def mw_of(text):
    m = re.search(r"\b([0-9]+(?:\.[0-9]+)?)\s*(MW|megawatts?|GW|gigawatts?)\b", text, re.I)
    if not m:
        return None
    v = float(m.group(1))
    return v * 1000 if m.group(2).lower().startswith("g") else v


def chip_of(text):
    m = re.search(r"\b(GB300|GB200|B300|B200|Vera Rubin|Rubin|Blackwell|H200|H100|MI3\d\d[X]?|TPU|Trainium)\b", text, re.I)
    return m.group(1) if m else None


def companies_in(text):
    """Listed company names present as whole words (case-sensitive, so 'figure' the noun is not Figure the customer);
    spellings of one company (NVIDIA / Nvidia, Sharon AI / SharonAI) collapse to the first listed."""
    out, seen = [], set()
    for c in COMPANIES:
        if re.search(r"(?<![A-Za-z])" + re.escape(c) + r"(?![a-z])", text):
            k = c.lower().replace(" ", "")
            if k not in seen:
                seen.add(k)
                out.append(c)
    return out


def has_figure(text):
    return money_b(text) is not None or mw_of(text) is not None or gpus_of(text) is not None


def looks_like_deal(title):
    return bool(DEAL_WORDS.search(title)) and bool(TOPIC_WORDS.search(title)) and not NOISE.search(title) and has_figure(title)


# ------------------------------------------------------------------ feed parsers
def parse_rss(xml_text):
    out = []
    root = ET.fromstring(xml_text)
    for it in root.iter("item"):
        title = htmllib.unescape((it.findtext("title") or "").strip())
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        src = it.find("source")
        source = (src.text or "").strip() if src is not None else ""
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)].strip()
        try:
            published = datetime.datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S").date().isoformat()
        except Exception:
            published = pub[:16]
        out.append({"title": title, "link": link, "source": source, "published": published, "channel": "news"})
    return out


def parse_edgar(json_text):
    """One entry per filing (accession), preferring the press-release exhibit (EX-99.*) over the 8-K body."""
    by_acc = {}
    d = json.loads(json_text)
    for h in d.get("hits", {}).get("hits", []):
        s = h.get("_source", {})
        ent = (s.get("display_names") or [""])[0]
        acc, _, fname = (h.get("_id") or "").partition(":")
        if not acc or not fname:
            continue
        cik = re.search(r"CIK (\d+)", ent)
        link = "https://www.sec.gov/Archives/edgar/data/%s/%s/%s" % (int(cik.group(1)) if cik else "", acc.replace("-", ""), fname)
        filer = re.sub(r"\s*\(.*$", "", ent).strip()
        e = {"title": "%s: %s (%s)" % (filer, s.get("file_description") or fname, s.get("form")), "link": link, "source": "SEC EDGAR %s" % (s.get("form") or ""),
             "published": s.get("file_date", ""), "channel": "edgar", "filer": filer, "items": s.get("items") or [], "file_type": s.get("file_type") or ""}
        cur = by_acc.get(acc)
        if cur is None or (e["file_type"].startswith("EX-99") and not cur["file_type"].startswith("EX-99")):
            by_acc[acc] = e
    return sorted(by_acc.values(), key=lambda e: e["published"], reverse=True)


SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
BLOCK = re.compile(r"</(p|div|h[1-6]|li|tr|td|th|table)>|<br\s*/?>", re.I)
TAG = re.compile(r"<[^>]+>")


def filing_text(html_text, limit=4000):
    """Filing HTML -> plain text, one line per block, EDGAR's header lines before 'Exhibit 99.x' dropped."""
    t = htmllib.unescape(TAG.sub(" ", BLOCK.sub("\n", SCRIPT.sub(" ", html_text))))
    lines = [re.sub(r"[ \t\xa0]+", " ", l).strip() for l in t.splitlines()]
    t = "\n".join(l for l in lines if l)
    m = re.search(r"\bExhibit 99\.\d\s*", t[:400], re.I)
    if m:
        t = t[m.end():]
    return t[:limit]


def edgar_worth_reading(e):
    """Fetch a filing only when its filer is a listed operator or the 8-K reports a material definitive agreement (item 1.01)."""
    return bool(companies_in(e.get("filer", ""))) or "1.01" in (e.get("items") or [])


def edgar_relevant(text):
    """...and keep it when the text talks about compute and carries a figure."""
    return bool(TOPIC_WORDS.search(text)) and has_figure(text)


def edgar_headline(text):
    """First line of the release that reads like a title (25+ characters), trimmed to 220."""
    for l in text.splitlines():
        if len(l.strip()) >= 25:
            return l.strip()[:220]
    return text[:160].strip()


# ------------------------------------------------------------------ dedupe against the queue and the contracts list
def key_of(c):
    """Near-duplicate key: the companies named plus the headline value, so ten write-ups of one deal collapse to one."""
    return "|".join(sorted(set(x.lower() for x in c.get("parties", [])))) + "|" + str(c.get("value_usd_b"))


def same_story(a, b):
    """Two candidates describe one announcement when they carry the same value (or MW) and share a named party."""
    pa, pb = set(x.lower() for x in a.get("parties", [])), set(x.lower() for x in b.get("parties", []))
    if not (pa & pb):
        return False
    if a.get("value_usd_b") is not None and a.get("value_usd_b") == b.get("value_usd_b"):
        return True
    return a.get("value_usd_b") is None and b.get("value_usd_b") is None and a.get("mw") is not None and a.get("mw") == b.get("mw")


def already_listed(c, contracts):
    """The listed contract this headline most likely describes: a contract naming two of the same parties (best when
    the value also agrees within 15%), else one naming one party with the same value; None when nothing fits."""
    parties = [p.lower().replace(" ", "") for p in c.get("parties", [])]
    if not parties:
        return None
    v = c.get("value_usd_b")
    def close(kv):
        return not (v and kv) or abs(v - kv) <= 0.15 * max(v, kv)
    scored = []
    for k in contracts:
        name = (k.get("parties") or "").lower().replace(" ", "")
        hit = [p for p in parties if p in name]
        if len(hit) >= 2:
            scored.append((3 if (v and k.get("value_usd_b") and close(k.get("value_usd_b"))) else 2, k["parties"]))
        elif hit and v and k.get("value_usd_b") and close(k.get("value_usd_b")):
            scored.append((1, k["parties"]))
    return max(scored, key=lambda s: s[0])[1] if scored else None


def extract(c, text):
    c.update({"value_usd_b": money_b(text), "term_years": term_years(text), "gpus": gpus_of(text), "mw": mw_of(text), "chip": chip_of(text), "parties": companies_in(text)})
    c["kind_guess"] = ("dc-lease" if re.search(r"\b(lease|colocation|hosting|powered shell)\b", text, re.I)
                       else "cloud-commit" if re.search(r"\b(Azure|AWS|Google Cloud|Oracle|OCI)\b", text) and re.search(r"\b(OpenAI|Anthropic|Meta|xAI)\b", text)
                       else "gpu-rental")
    return c


def refresh(log=print, sec_user_agent="", contracts=None, fetch_fn=None, today=None):
    fetch_fn = fetch_fn or fetch
    today = today or datetime.date.today()
    doc = json.load(open(PATH, encoding="utf-8")) if PATH.exists() else {"candidates": []}
    if contracts is None:
        contracts = json.load(open(ROOT / "data" / "rental_rates.json", encoding="utf-8")).get("contracts", [])
    seen_links = {c["link"] for c in doc["candidates"]}
    found, added, errors, scanned = [], 0, [], 0
    for q in QUERIES:
        try:
            items = parse_rss(fetch_fn(NEWS % urllib.parse.quote(q)))
            scanned += len(items)
            found += [dict(it, text=it["title"]) for it in items if looks_like_deal(it["title"])]
        except Exception as ex:
            errors.append("news: %s" % str(ex)[:120])
    if sec_user_agent.strip():
        start, end = (today - datetime.timedelta(days=7)).isoformat(), today.isoformat()
        hits = []
        for ph in EDGAR_PHRASES:
            try:
                hits += parse_edgar(fetch_fn(EDGAR % (urllib.parse.quote(ph), start, end), ua=sec_user_agent))
                time.sleep(0.2)
            except Exception as ex:
                errors.append("edgar: %s" % str(ex)[:120])
        seen_acc = set()
        for e in hits:
            if e["link"] in seen_links or e["link"] in seen_acc or not edgar_worth_reading(e):
                continue
            seen_acc.add(e["link"])
            if len(seen_acc) > EDGAR_DOC_LIMIT:
                break
            scanned += 1
            try:
                text = filing_text(fetch_fn(e["link"], ua=sec_user_agent))
                time.sleep(0.2)
            except Exception as ex:
                errors.append("edgar doc: %s" % str(ex)[:80])
                continue
            if not edgar_relevant(text):
                continue
            e["title"] = "%s: %s" % (e["filer"], edgar_headline(text))
            if "1.01" in e["items"]:
                e["source"] += " item 1.01 (material definitive agreement)"
            found.append(dict(e, text=text[:1500]))
    else:
        log("   deals: EDGAR pass skipped (set assumptions.json -> deals.sec_user_agent to your name and email, as the SEC requires)")
    for it in found:
        if it["link"] in seen_links:
            continue
        text = it.pop("text")
        c = {k: v for k, v in it.items() if k not in ("filer", "items", "file_type")}
        extract(c, text)
        c.update({"first_seen": today.isoformat(), "status": "new"})
        c["matched_contract"] = already_listed(c, contracts)
        if any(same_story(c, o) for o in doc["candidates"]):
            seen_links.add(c["link"])
            continue
        seen_links.add(c["link"])
        doc["candidates"].append(c)
        added += 1
    cutoff = (today - datetime.timedelta(days=90)).isoformat()
    doc["candidates"] = [c for c in doc["candidates"] if (c.get("first_seen") or "9999") >= cutoff or c.get("status") == "added"]
    doc["scanned_on"] = today.isoformat()
    doc["queries"] = QUERIES
    doc["edgar_phrases"] = EDGAR_PHRASES if sec_user_agent.strip() else []
    doc["errors"] = errors
    doc["note"] = ("Headlines and filings the daily scan matched to a multi-year GPU / AI-compute contract, with the figures it could read from them. "
                   "Review each one: a confirmed deal goes into data/rental_rates.json 'contracts' (classified; see engine/deals_seed.py for the fields); "
                   "set status to 'added' or 'dismissed' here to drop it from the page's review box. Nothing here enters the model until it is moved.")
    json.dump(doc, open(PATH, "w", encoding="utf-8"), indent=1)
    new = [c for c in doc["candidates"] if c.get("status") == "new"]
    log("deals: %d items scanned, %d new candidates queued (%d awaiting review)%s" % (scanned, added, len(new), ("; " + "; ".join(errors)) if errors else ""))
    return added


if __name__ == "__main__":
    refresh()
