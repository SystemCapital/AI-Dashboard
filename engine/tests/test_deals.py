"""
Offline check of the deal scout against feed samples captured on 2026-09-09:
    python engine/tests/test_deals.py
Uses a fake fetch (no network) and a temporary candidates file, so the real data/deal_candidates.json is untouched.
"""
import sys, json, tempfile, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from engine import collect_deals as cd

S = HERE / "samples"
NEWS_XML = (S / "news_gpu_deals_2026-09-09.xml").read_text(encoding="utf-8")
EDGAR_JSON = (S / "edgar_gpu_agreement_2026-09-09.json").read_text(encoding="utf-8")
FILINGS = {
    # first lines of the real exhibits (SEC Archives, 2026-09-02 / 2026-09-04); enough for the headline + figure extraction
    "000121390026096776/ea030434301ex99-1.htm": "<html><body><p>EX-99.1 4 ea030434301ex99-1.htm PRESS RELEASE, DATED AUGUST 31, 2026</p><p>Exhibit 99.1</p>"
        "<p><b>Corvex Announces Significant Data Center Expansion; Increasing Current Capacity 5x with Contracted Path to 13x</b></p>"
        "<p>Critical IT capacity expected to increase more than five times from approximately 1.5 MW to approximately 8 MW by year-end 2026</p>"
        "<p>Expansion expected to support approximately 3,000 additional latest-generation GPUs across two U.S. data centers</p>"
        "<p>$33 million private placement secured to fund expansion plans</p></body></html>",
    "000149315226041450/ex99-1.htm": "<html><body><p>EX-99.1 2 ex99-1.htm EX-99.1</p><p>Exhibit 99.1</p>"
        "<p>Sharon AI Selects Rafay Systems to Support AI Infrastructure Orchestration Platform at Scale</p>"
        "<p>Five-year strategic agreement establishes a standardized orchestration and operations platform across Sharon AI's expanding AI Factory environments</p>"
        "<p>The architecture established through the agreement is designed to support the orchestration of up to 150,000 GPUs over the five-year term.</p></body></html>",
    "000182912626009632/exascalelabs_ex99-1.htm": "<html><body><p>Exhibit 99.1</p><p>Exascale Labs Holdings completes business combination and lists on Nasdaq.</p></body></html>",
}


def fake_fetch(url, ua=None, timeout=45):
    if "news.google.com" in url:
        return NEWS_XML
    if "efts.sec.gov" in url:
        assert ua and "@" in ua, "EDGAR must be called with the declared User-Agent"
        return EDGAR_JSON
    for k, v in FILINGS.items():
        if url.endswith(k):
            return v
    raise RuntimeError("unexpected fetch " + url)


def main():
    # extractors
    assert cd.money_b("Crusoe signs $13 billion AI cloud deal") == 13.0
    assert cd.money_b("Nscale, Figure ink US$3.5 billion AI compute deal") == 3.5
    assert cd.money_b("Raises Over USD3 Billion in Funding") == 3.0
    assert cd.money_b("Signed a 32 Billion US Dollar Contract") == 32.0
    assert cd.money_b("HIVE signs $350 million contract") == 0.35
    assert cd.money_b("Anthropic's $35B Deal") == 35.0
    assert cd.term_years("five-year strategic agreement") == 5 and cd.term_years("a 15-year lease") == 15 and cd.term_years("multi-year deal") is None
    assert cd.gpus_of("2,016 NVIDIA GB300 GPUs") == 2016 and cd.gpus_of("approximately 3,000 additional latest-generation GPUs") == 3000 and cd.gpus_of("up to 100,000 Nvidia chips") == 100000
    assert cd.mw_of("900MW AI Compute Capacity") == 900.0 and cd.mw_of("1.2 GW campus") == 1200.0
    assert cd.chip_of("HGX B200 and Vera Rubin") == "B200"
    # headline filter
    keep = ["Crusoe signs $13 billion AI cloud deal with market maker Jane Street: Bloomberg", "Firmus Signs OpenAI as Anchor for 900MW AI Compute Capacity",
            "Nscale Commits Up to $6 Billion in GPU Deal as It Becomes Figure's Preferred AI Cloud Partner", "HIVE Digital signs $350 million contract for 2,016 GB300 GPUs"]
    drop = ["IREN Stock Drops After $6B Offering, But Retail Bulls Supercharged With Massive Nvidia GPU Buy", "Blue Owl leads $2.4 billion IREN GPU financing at 9%",
            "Nscale seeks about $3.5 billion pre-IPO funding, source says", "Sharon AI signs five-year Rafay deal for GPU orchestration",
            "HPE is deploying its networking gear across Oracle's AI data centers in a multi-year deal", "Why Did Jane Street Sign a $13 Billion Cloud Contract If the Hall Can Wait?"]
    for t in keep:
        assert cd.looks_like_deal(t), "should keep: " + t
    for t in drop:
        assert not cd.looks_like_deal(t), "should drop: " + t
    # parsers
    items = cd.parse_rss(NEWS_XML)
    assert len(items) == 22 and items[1]["title"].startswith("Crusoe signs $13 billion") and items[1]["published"] == "2026-09-04" and items[1]["source"] == "blockspace.media"
    hits = cd.parse_edgar(EDGAR_JSON)
    assert [h["filer"] for h in hits] == ["SharonAI Holdings Inc.", "Corvex, Inc.", "Exascale Labs Holdings Inc.", "Eco Wave Power Global AB"], [h["filer"] for h in hits]
    assert hits[1]["link"] == "https://www.sec.gov/Archives/edgar/data/1734750/000121390026096776/ea030434301ex99-1.htm"
    assert cd.edgar_worth_reading(hits[0]) and cd.edgar_worth_reading(hits[1]) and cd.edgar_worth_reading(hits[2]) and not cd.edgar_worth_reading(hits[3])
    text = cd.filing_text(FILINGS["000121390026096776/ea030434301ex99-1.htm"])
    assert text.startswith("Corvex Announces"), text[:80]
    assert cd.edgar_headline(text) == "Corvex Announces Significant Data Center Expansion; Increasing Current Capacity 5x with Contracted Path to 13x", cd.edgar_headline(text)
    # a full refresh against a scratch file
    contracts = json.load(open(HERE.parent.parent / "data" / "rental_rates.json", encoding="utf-8"))["contracts"]
    tmp = Path(tempfile.mkdtemp()) / "deal_candidates.json"
    cd.PATH = tmp
    logs = []
    today = datetime.date(2026, 9, 9)
    added = cd.refresh(log=logs.append, sec_user_agent="Example Co example@example.com", contracts=contracts, fetch_fn=fake_fetch, today=today)
    doc = json.load(open(tmp, encoding="utf-8"))
    titles = [c["title"] for c in doc["candidates"]]
    print("\n".join("  %-9s %-4s %-6s %-30s %s" % (c["channel"], c.get("value_usd_b"), c.get("mw"), (c.get("matched_contract") or "-")[:30], c["title"][:90]) for c in doc["candidates"]))
    assert added == len(doc["candidates"]) and doc["scanned_on"] == "2026-09-09" and not doc["errors"], (added, doc["errors"])
    assert sum("Jane Street" in t for t in titles) == 1, "three write-ups of Crusoe-Jane Street should collapse to one"
    by = {c["title"]: c for c in doc["candidates"]}
    cj = next(c for t, c in by.items() if t.startswith("Crusoe signs $13 billion"))
    assert cj["value_usd_b"] == 13.0 and cj["matched_contract"] == "Crusoe - Jane Street" and cj["kind_guess"] == "gpu-rental" and set(cj["parties"]) == {"Crusoe", "Jane Street"}
    fo = next(c for t, c in by.items() if t.startswith("Firmus Signs OpenAI"))
    assert fo["mw"] == 900.0 and fo["matched_contract"] == "Firmus - OpenAI (Malaysia)", fo
    n6 = next(c for t, c in by.items() if t.startswith("Nscale Commits Up to $6"))
    assert n6["value_usd_b"] == 6.0 and n6["matched_contract"] == "Nscale - Figure (Barstow, Texas)"
    assert any(t.startswith("Corvex, Inc.: Corvex Announces") for t in titles), titles
    assert not any("Eco Wave" in t or "Exascale" in t for t in titles), titles
    corvex = next(c for t, c in by.items() if t.startswith("Corvex"))
    assert corvex["gpus"] == 3000 and corvex["mw"] == 1.5 and "item 1.01" in corvex["source"] and corvex["channel"] == "edgar"
    sharon = next(c for t, c in by.items() if t.startswith("SharonAI"))
    assert sharon["term_years"] == 5 and sharon["gpus"] == 150000
    # second run: nothing new, statuses preserved
    doc["candidates"][0]["status"] = "dismissed"
    json.dump(doc, open(tmp, "w", encoding="utf-8"))
    added2 = cd.refresh(log=logs.append, sec_user_agent="Example Co example@example.com", contracts=contracts, fetch_fn=fake_fetch, today=today)
    doc2 = json.load(open(tmp, encoding="utf-8"))
    assert added2 == 0 and len(doc2["candidates"]) == len(doc["candidates"]) and doc2["candidates"][0]["status"] == "dismissed"
    # no user agent: EDGAR skipped, news still scanned
    tmp2 = tmp.parent / "b.json"
    cd.PATH = tmp2
    cd.refresh(log=logs.append, sec_user_agent="", contracts=contracts, fetch_fn=fake_fetch, today=today)
    doc3 = json.load(open(tmp2, encoding="utf-8"))
    assert all(c["channel"] == "news" for c in doc3["candidates"]) and doc3["edgar_phrases"] == [] and any("EDGAR pass skipped" in l for l in logs)
    print("\n".join(logs))
    print("deal scout OK: %d candidates from the 2026-09-09 samples" % len(doc["candidates"]))


if __name__ == "__main__":
    main()
