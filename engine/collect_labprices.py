"""
OpenAI's published API prices, read from its pricing page for the lab-prices step of update.py.

The page (developers.openai.com/api/docs/pricing) renders each pricing tier from a TextTokenPricingTables component
whose props carry the table as data: {"tier": "standard", "rows": [[model, input, cached input, cache writes, output],
...]} in Astro's serialisation ([0, value] for a value, [1, [...]] for an array). The Standard tab is the list price
(short context; Batch and Flex are 50% off, Fast is the priority tier). A row with one price column fewer has no
cache-write price; '-' is a price the page leaves blank. A page that no longer carries a standard table raises, and
update.py keeps the last good prices. Standard library only.
"""
import re, json, html as htmllib, urllib.request
from engine import net

OPENAI_PRICING = "https://developers.openai.com/api/docs/pricing"
UA = {"User-Agent": "Mozilla/5.0 (compatible; blackwell-roic/1.0; +local research tool)", "Accept": "text/html"}
ISLAND = re.compile(r'<astro-island[^>]*component-export="TextTokenPricingTables"[^>]*props="([^"]*)"')


def _value(v):
    """undo Astro's prop serialisation"""
    if isinstance(v, list) and v and isinstance(v[0], int):
        if v[0] == 1:
            return [_value(x) for x in v[1]]
        return _value(v[1]) if len(v) > 1 else None
    if isinstance(v, dict):
        return {k: _value(x) for k, x in v.items()}
    return v


def _price(x):
    return float(x) if isinstance(x, (int, float)) else None


def parse_openai(page, tier="standard"):
    """{model: {"in", "cache_read", "cache_write", "out"}} in USD per million tokens, from the page's table for one tier"""
    for props in ISLAND.findall(page):
        p = _value(json.loads(htmllib.unescape(props)))
        if p.get("tier") != tier:
            continue
        out = {}
        for row in p.get("rows") or []:
            if not row or not isinstance(row[0], str) or len(row) < 3:
                continue
            name, cols = row[0].split(" (")[0].strip(), row[1:]
            out.setdefault(name, {"in": _price(cols[0]), "cache_read": _price(cols[1]) if len(cols) >= 3 else None,   # first row of a name
                                  "cache_write": _price(cols[2]) if len(cols) >= 4 else None, "out": _price(cols[-1])})
        if out:
            return out
    raise ValueError("no %s-tier price table on the page" % tier)


def openai_prices(tier="standard", timeout=60):
    req = urllib.request.Request(OPENAI_PRICING, headers=UA)
    return parse_openai(net.read(req, timeout).decode("utf-8", "ignore"), tier)
