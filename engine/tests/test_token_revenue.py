"""
Offline check of the weekly token revenue arithmetic (engine/collect_token_revenue.py):
    python engine/tests/test_token_revenue.py
A full week sums each model's daily tokens and prices them at the price in force on the week's last day; a ':free'
variant earns nothing; a list price bills cached tokens at the cache-read price; a chart week prices the named models
one by one and the rest of each lab at its rate. No network; nothing in data/ is touched.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from engine import collect_token_revenue as T


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol * max(1.0, abs(b))


def main():
    hist = {}
    T.add_price(hist, "a/m1|standard", "2026-10-01", 1.0, 10.0, 0.5, "effective")
    assert not T.add_price(hist, "a/m1|standard", "2026-10-03", 1.01, 10.05, 0.5, "effective")      # within 2%: no new point
    T.add_price(hist, "a/m1|standard", "2026-10-10", 2.0, 20.0, 0.5, "effective")
    T.add_price(hist, "b/m2|standard", "2026-10-01", 4.0, 8.0, 1.0, "list")                          # cache read $1/M
    assert T.price_at(hist, "a/m1|standard", "2026-10-11")[1] == 2.0
    assert T.price_at(hist, "a/m1|standard", "2026-09-01")[1] == 1.0                                # before the first read: the first

    days = {"a/m1|standard": {"2026-10-05": [1e12, 1e10, 0, 1], "2026-10-11": [1e12, 1e10, 0, 1], "2026-10-12": [5e12, 0, 0, 1]},
            "a/m1|free": {"2026-10-06": [3e12, 1e10, 0, 1]},
            "b/m2|standard": {"2026-10-07": [1e12, 1e11, 5e11, 1]}}
    meta = {k: {"name": k, "weights": "open"} for k in days}
    w = T.full_week("2026-10-05", days, meta, hist, chart_total=7.2e12)
    # m1: 2T in x $2 + 20B out x $20 (priced on 11 Oct) = $4.4M; free = 0; m2: 0.5T x $4 + 0.5T x $1 + 0.1T x $8 = $3.3M
    rev = {m[0]: m[12] for m in w["models"]}
    assert close(rev["a/m1|standard"], 4.4e6) and rev["a/m1|free"] == 0 and close(rev["b/m2|standard"], 3.3e6), rev
    counted = 2.02e12 + 3.01e12 + 1.1e12
    assert w["tail"][0] == int(7.2e12 - counted) and close(w["revenue"], 7.7e6 + w["tail"][2]), w["tail"]
    assert w["labs"]["a"][3] == int(3.01e12)                                                         # free tokens by lab

    # a chart week: one named model, its lab's rest at the lab rate, the market-share chart's others at the others rate
    cw = {"ys": {"a/m1": 2e12, "Others": 3e12}}
    lw = {"ys": {"a": 4e12, "others": 1e12}}
    ratios = {"a/m1|standard": 0.01, "cache:a/m1|standard": 0.0, "@a": 0.02, "@all": 0.02}
    e = T.chart_week("2026-10-05", cw, lw, meta, hist, ratios, {"a": 0.5}, 0.2, rates_all={"a": 0.9})
    named = (2e12 * 0.99 * 2.0 + 2e12 * 0.01 * 20.0) / 1e6
    assert close(e["revenue"], named + 2e12 * 0.5 / 1e6 + 1e12 * 0.2 / 1e6), e["revenue"]
    e2 = T.chart_week("2026-10-05", {"ys": {"Others": 5e12}}, lw, meta, hist, ratios, {"a": 0.5}, 0.2, rates_all={"a": 0.9})
    assert close(e2["revenue"], 4e12 * 0.9 / 1e6 + 1e12 * 0.2 / 1e6), e2["revenue"]                # no named model: the lab's full rate
    print("token revenue OK: weekly sums, price in force, free and list pricing, chart-week estimate")


if __name__ == "__main__":
    main()
