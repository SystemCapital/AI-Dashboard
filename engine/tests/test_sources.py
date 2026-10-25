"""
Offline check of two page readers against what the sources served on 2026-10-26:
    python engine/tests/test_sources.py
Silicon Data: every index is read from the cards on its public overview page (the old chart pages render empty since
2026-10-19). Nebius: the on-demand rate is read past the 'from $0.99' preemptible floor its table now shows first.
No network; nothing in data/ is touched.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from engine import collect_history as ch, collect_rentals as cr

SD_PAGE = (HERE / "samples" / "silicondata_index_2026-10-26.html").read_text(encoding="utf-8")
# the Nebius table as its page text read on 2026-10-26 (two rows), between the table heading and the footnote
NEBIUS = ("<p>NVIDIA GPU Instances Item vCPUs RAM, GB Preemptible, GPU-hour * On-demand, GPU-hour "
          "NVIDIA GB300 NVL72 112 800 - Contact us NVIDIA HGX B300 24 346 from $0.99 $9.50 "
          "NVIDIA GB200 NVL72 112 800 - Contact us NVIDIA HGX B200 20 224 from $0.99 $8.50 "
          "NVIDIA HGX H200 16 200 from $0.79 $5.40 * Spot prices are dynamic</p>")


def main():
    fetch = lambda url: SD_PAGE if url == ch.SILICON_SITE else (_ for _ in ()).throw(OSError("unexpected fetch " + url))
    cards = ch.silicon_cards(fetch)
    assert {"b200-neo", "h200-neo", "h100-neo", "h100-hs", "b300-neo", "expenditure", "open_expenditure", "closed_expenditure"} <= set(cards), sorted(cards)
    v, end, url = ch.silicon_series("b200", "neo-cloud", fetch=fetch)
    assert (end, v[end], len(v), url) == ("2026-10-25", 6.6, 30, ch.SILICON_SITE), (end, v.get(end), len(v), url)
    assert ch.silicon_series("h100", "hyperscaler", fetch=fetch)[0]["2026-10-25"] == 7.17
    v, end, _ = ch.silicon_token_series("closed_expenditure", fetch=fetch)
    assert end == "2026-10-24" and 2.0 < v[end] < 3.0, (end, v.get(end))

    url = "https://nebius.com/prices"
    cr._cache[url] = NEBIUS
    try:
        assert cr.html_rate(url, "HGX B300", stop="NVIDIA")[0] == 0.99                     # the old reading: the floor
        assert cr.html_rate(url, "HGX B300", stop="NVIDIA", skip_floor=True)[0] == 9.50
        assert cr.html_rate(url, "HGX B200", stop="NVIDIA", skip_floor=True)[0] == 8.50
    finally:
        cr._cache.pop(url, None)
    print("sources OK: Silicon Data cards (B200 $6.60 on 2026-10-25, 30 days), Nebius on-demand past the preemptible floor")


if __name__ == "__main__":
    main()
