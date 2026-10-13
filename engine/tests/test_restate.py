"""Restating check: every row of data/roic_history.csv, restated at its OWN as-built assumptions and fleet from its
market primitives, must reproduce the ROIC, year-1 ROIC, IRR and revenue per GPU-hour that day's build wrote
(to the CSV's 4-decimal rounding). If this passes, restating at any other assumptions is the same arithmetic.
Run: python engine/tests/test_restate.py"""
import csv, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from engine import restate as RS  # noqa: E402


def main():
    rows = list(csv.DictReader(open(ROOT / "data" / "roic_history.csv", encoding="utf-8")))
    worst, n = 0.0, 0
    for r in rows:
        d, fl = RS.row_built(r)
        if any(v is None for v in fl.values()) or any(d[k] is None for k in ("life", "compute_life", "shell_life", "rent_util", "serve_util")):
            print("%s: no recorded assumptions, skipped" % r["date"])
            continue
        d = {k: (v if v is not None else 0.0) for k, v in d.items()}
        out = RS.restate(RS.row_prim(r), d, fl)
        for s in RS.SCEN:
            if r.get("roic_" + s, "") == "":
                continue
            assert s in out, (r["date"], s, "built but no primitives")
            v = out[s]
            pairs = [("roic_" + s, v["roic"]), ("irr_" + s, v["irr"]), ("rev_per_gpu_hr_" + s, v["rev_per_gpu_hr"])] + ([("roic_rent_y1", v["roic_y1"])] if s == "rent" else [])
            for c, val in pairs:
                gap = abs(float(r[c]) - val)
                worst = max(worst, gap)
                n += 1
                assert gap <= 5.1e-5, "%s %s: as built %s, restated at its own assumptions %.6f" % (r["date"], c, r[c], val)
    print("restate OK: %d as-built numbers reproduced across %d rows, worst gap %.1e (CSV rounds to 1e-4)" % (n, len(rows), worst))


if __name__ == "__main__":
    main()
