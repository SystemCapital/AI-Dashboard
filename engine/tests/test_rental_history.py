"""Checks on the provider rental history and the year-1 rate built from it.
  1. today's near-term rental bases computed from data/rental_rates.json (what the model uses) equal the same bases rebuilt
     from data/rate_history.json for the same date (what the ROIC history restates on), basis by basis
  2. the 'rate in force on a date' rule: a reading holds for max_quote_age_days, longer only when the next reading is the
     same price; an ended series stops on its end date; a stated (documented) change takes effect on its date
  3. every list-price change the history shows is in data/rental_rates.json 'changes'
  4. each day's rebuilt quotes for the ROIC history carry every provider rate the history knows for that day
Run: python engine/tests/test_rental_history.py"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from engine import model, rental_history as RH, restate as RS  # noqa: E402


def main():
    A = json.load(open(ROOT / "assumptions.json", encoding="utf-8"))["rental"]
    H = json.load(open(ROOT / "data" / "rate_history.json", encoding="utf-8"))
    R = json.load(open(ROOT / "data" / "rental_rates.json", encoding="utf-8"))
    inp = model.prepare(ROOT, log=lambda *a: None)
    ref, age = inp["rental"]["ref_date"], inp["rental"]["max_quote_age_days"]
    live = inp["rental"]["near_options"]
    hist = RH.near_options(RH.quotes_as_of(H, ref, age), A, ref, age)
    for k in ("all_avg", "all_median", "spot", "neocloud", "ondemand"):
        a, b = live[k]["rate"], hist[k]["rate"]
        assert (a is None and b is None) or abs(a - b) < 1e-9, "%s: live %s vs history %s on %s" % (k, a, b, ref)
        assert live[k]["n"] == hist[k]["n"], "%s: %d live rows vs %d from history" % (k, live[k]["n"], hist[k]["n"])
    print("1. near-term bases on %s: live = history (median of %d GB300/B300 rates = $%.4f, average $%.4f)" % (ref, live["all_median"]["n"], live["all_median"]["rate"], live["all_avg"]["rate"]))

    s = {"values": {"2026-09-01": 5.0, "2026-09-20": 5.0, "2026-09-30": 6.0}}
    assert RH.value_at(s, "2026-09-05", 10)[1] == 5.0
    assert RH.value_at(s, "2026-09-15", 10)[1] == 5.0, "a list price that held between two equal readings holds across the gap"
    assert RH.value_at(s, "2026-09-25", 10)[1] == 5.0
    assert RH.value_at({"values": {"2026-09-01": 5.0, "2026-09-20": 7.0}}, "2026-09-15", 10) is None, "unknown between two different readings past max age"
    assert RH.value_at(dict(s, ended="2026-09-25"), "2026-09-26", 10) is None
    assert RH.value_at(dict(s, stated=[["2026-09-25", 5.5, "notice", ""]]), "2026-09-26", 10)[1] == 5.5
    print("2. rate-in-force rule: ok")

    logged = {(c["key"], c["date"]) for c in R.get("changes", [])}
    want = [c for c in RH.changes_from_series(H) if c["pricing"] != "dynamic"]
    missing = [c for c in want if (c["key"], c["date"]) not in logged]
    assert not missing, "list-price changes in the history but not in the change log: %s" % [(c["key"], c["date"]) for c in missing]
    print("3. %d list-price changes in the history, all in the change log" % len(want))

    snaps = sorted(p.name[:10] for p in (ROOT / "data" / "snapshots").glob("*.json.gz"))
    for d in snaps:
        rebuilt = RS.rental_as_of(ROOT, d, {"quotes": [], "contracts": []}, H, age)
        n_hist = len([q for q in RH.quotes_as_of(H, d, age) if q["tier"] != "index"])
        assert len(rebuilt["quotes"]) == n_hist
    print("4. rental quotes rebuilt for %d snapshot days" % len(snaps))
    print("rental history OK")


if __name__ == "__main__":
    main()
