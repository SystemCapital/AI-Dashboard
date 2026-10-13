"""
Rental rates through time, provider by provider, and the near-term rental bases built from them.

data/rate_history.json -> 'quotes' holds one series per published rental quote in data/rental_rates.json (every
vendor, chip and tier: on-demand, spot, capacity block, reserved), keyed vendor_chip_tier:

  values      {date: $/GPU-hr} what the vendor's page / API showed on the day it was read (collect_rentals writes the
              day's reading after every refresh; nothing is interpolated)
  stated      [[date, $/GPU-hr, note, url]] dated points documented elsewhere - a price change with a published effective
              date (an announcement on the vendor's own page, or several reports of it) - drawn as hollow markers
  announced   [{effective, value, seen_on, text, url}] a future price the vendor has published but not yet charged
  corrections [{from, to, was, now, why}] readings the collector got wrong, kept for the audit trail (values hold the
              corrected figure)
  ended       the date the vendor stopped publishing this rate (the series ends there)

What rate was in force on a date (value_at): the last point on or before the date, if it was read within max_age days;
an older point still counts when the next point after the date shows the same price (a list price that held between
two readings). A quote with no point in that window is not known for that date and stays out of every basis.

The near-term rental bases (near_options) are computed here from a list of quotes, so the live model (model.prepare,
from data/rental_rates.json) and the history (every past date, from the series) use one piece of arithmetic:
  all_median  median of every current GB300 / B300 rate - spot, on-demand and capacity blocks, every provider (default since 2026-10-13)
  all_avg     average (mean) of the same rates (the default on 2026-10-12)
  spot        median of the current GB300 / B300 spot / preemptible rates
  neocloud    median of current non-hyperscaler on-demand GB200 / GB300 quotes
  ondemand    median of every current on-demand / capacity-block GB200 / GB300 quote
  sdb200      Silicon Data B200 index;  ornnb200  Ornn B200 index (older part, references)
Standard library only.
"""
import datetime, re, statistics

TIERS_ALL = ("spot", "on-demand", "capacity-block")


def slug(vendor, chip, tier):
    return re.sub(r"[^a-z0-9]+", "_", ("%s_%s_%s" % (vendor, chip, tier)).lower()).strip("_")


def key_of(q):
    return slug(q["vendor"], q["chip"], q["tier"])


def _d(s):
    return datetime.date.fromisoformat(str(s)[:10])


def points(s):
    """every dated price of one series, oldest first: (date, value, kind) with kind 'read' or 'stated'"""
    pts = {d: (d, float(v), "read") for d, v in (s.get("values") or {}).items() if v is not None}
    for st in s.get("stated") or []:
        if st[0] not in pts:
            pts[st[0]] = (st[0], float(st[1]), "stated")
    return [pts[d] for d in sorted(pts)]


def value_at(s, date, max_age):
    """(value, point_date, kind) in force on `date`, or None when the series does not establish one"""
    date = str(date)[:10]
    if s.get("ended") and date >= s["ended"]:
        return None
    pts = points(s)
    before = [p for p in pts if p[0] <= date]
    if not before:
        return None
    p = before[-1]
    if (_d(date) - _d(p[0])).days <= max_age:
        return p
    after = [x for x in pts if x[0] > date]
    if after and abs(after[0][1] - p[1]) < 1e-9:
        return p
    return None


def quotes_as_of(hist, date, max_age, meta=None):
    """the published quotes as they stood on `date`, rebuilt from rate_history.json: one dict per series with a known
    rate (same fields as a rental_rates.json quote; read_on = `date`, point_date = the reading or stated point used), plus the Silicon Data and Ornn index
    rows (tier 'index') for the B200 reference bases. meta: current quotes by key, for fields the series lacks."""
    out, meta = [], (meta or {})
    for k, s in ((hist.get("quotes") or {}).get("series") or {}).items():
        v = value_at(s, date, max_age)
        if not v:
            continue
        m = meta.get(k, {})
        out.append({"vendor": s["vendor"], "chip": s["chip"], "tier": s["tier"], "instance": s.get("instance") or m.get("instance", ""),
                    "hyperscaler": bool(s.get("hyperscaler", m.get("hyperscaler", False))), "url": s.get("url") or m.get("url", ""),
                    "gpus": s.get("gpus") or m.get("gpus"), "pricing": s.get("pricing", "list"),
                    "per_gpu_hr": v[1], "read_on": date, "point_date": v[0], "point": v[2], "key": k})
    for block, vendor in (("silicon_index", "Silicon Data"), ("ornn_index", "Ornn")):
        for k, s in ((hist.get(block) or {}).get("series") or {}).items():
            gpu = (s.get("gpu") or k).upper().split()[0]
            if gpu != "B200" or (s.get("tab") and s["tab"] != "neo-cloud"):
                continue
            v = value_at({"values": s.get("values") or {}}, date, max_age)
            if v:
                out.append({"vendor": vendor, "chip": "B200", "tier": "index", "instance": s.get("label", ""), "hyperscaler": False,
                            "url": s.get("url", ""), "per_gpu_hr": v[1], "read_on": date, "as_of": v[0], "key": "%s_%s" % (block, k)})
    return out


def current(quotes, ref_date, max_age):
    """the quotes that count as current on ref_date: a rate, not ended or unverifiable, read within max_age days"""
    out = []
    for q in quotes:
        if not q.get("per_gpu_hr") or q.get("status") in ("ended", "unverifiable"):
            continue
        if q.get("read_on") and (_d(ref_date) - _d(q["read_on"])).days > max_age:
            continue
        out.append(q)
    return out


def near_options(quotes, RA, ref_date, max_age):
    """the near-term rental bases from a list of quotes (live or rebuilt for a past date). RA = assumptions.json rental."""
    TS = RA["term_structure"]
    chips_od, chips_spot = set(RA["chips_for_ondemand"]), set(TS["chips_for_spot"])
    chips_list = list(TS.get("chips_for_average", sorted(chips_spot)))
    chips_all = set(chips_list)
    cur = current(quotes, ref_date, max_age)
    all_rows = [q for q in cur if q["chip"] in chips_all and q["tier"] in TIERS_ALL]
    spot_rows = [q for q in cur if q["chip"] in chips_spot and q["tier"] == "spot"]
    od_rows = [q for q in cur if q["chip"] in chips_od and q["tier"] in ("on-demand", "capacity-block")]
    neo_rows = [q for q in od_rows if not q.get("hyperscaler")]
    idx = {(q["vendor"], q["chip"]): q for q in cur if q["tier"] == "index"}
    sd, orn = idx.get(("Silicon Data", "B200")), idx.get(("Ornn", "B200"))
    rows = lambda rs: [[q["vendor"], q["chip"], q["tier"], q["per_gpu_hr"], q.get("read_on")] for q in sorted(rs, key=lambda x: (x["chip"], x["tier"], x["vendor"]))]
    med = lambda rs: statistics.median([q["per_gpu_hr"] for q in rs]) if rs else None
    avg = lambda rs: sum(q["per_gpu_hr"] for q in rs) / len(rs) if rs else None
    chips_txt = "/".join(chips_list)
    return {
        "all_median": {"rate": med(all_rows), "n": len(all_rows), "providers": len({q["vendor"] for q in all_rows}),
                       "label": "Median of every current %s rate (spot, on-demand, capacity blocks), all providers" % chips_txt, "rows": rows(all_rows)},
        "all_avg": {"rate": avg(all_rows), "n": len(all_rows), "providers": len({q["vendor"] for q in all_rows}),
                    "label": "Average (mean) of every current %s rate (spot, on-demand, capacity blocks), all providers" % chips_txt, "rows": rows(all_rows)},
        "spot": {"rate": med(spot_rows), "n": len(spot_rows),
                 "label": "Spot / preemptible (median of current %s spot rates)" % "/".join(sorted(chips_spot)), "rows": rows(spot_rows)},
        "neocloud": {"rate": med(neo_rows), "n": len(neo_rows), "label": "Neocloud on-demand (median of non-hyperscaler GB200/GB300 quotes)", "rows": rows(neo_rows)},
        "ondemand": {"rate": med(od_rows), "n": len(od_rows), "label": "On-demand list (median of all published GB200/GB300 quotes)", "rows": rows(od_rows)},
        "sdb200": {"rate": sd["per_gpu_hr"] if sd else None, "n": 1 if sd else 0, "label": "Silicon Data B200 rental index (observed market rate, older part)",
                   "read_on": sd.get("as_of", sd.get("read_on")) if sd else None, "url": sd.get("url") if sd else None},
        "ornnb200": {"rate": orn["per_gpu_hr"] if orn else None, "n": 1 if orn else 0, "label": "Ornn B200 compute price index (transacted rates, older part)",
                     "read_on": orn.get("as_of", orn.get("read_on")) if orn else None, "url": orn.get("url") if orn else None},
    }


def coverage_start(hist, chips, tiers=("spot", "on-demand")):
    """the first date by which every one of `tiers` has a reading on `chips` (the year-1 rate's history starts there,
    so its first days are not an average of one tier only)"""
    firsts = []
    for t in tiers:
        ds = [d for s in ((hist.get("quotes") or {}).get("series") or {}).values() if s["chip"] in chips and s["tier"] == t for d in (s.get("values") or {})]
        if ds:
            firsts.append(min(ds))
    return max(firsts) if firsts else None


def near_history(hist, RA, max_age, start=None, end=None, meta=None):
    """the near-term bases on every day from the first reading to `end`: [[date, {basis: [rate, n]}], ...]"""
    series = ((hist.get("quotes") or {}).get("series") or {}).values()
    dates = sorted({p[0] for s in series for p in points(s)})
    if not dates:
        return []
    d0, d1 = _d(start or dates[0]), _d(end or dates[-1])
    out, d = [], d0
    while d <= d1:
        ds = d.isoformat()
        opts = near_options(quotes_as_of(hist, ds, max_age, meta), RA, ds, max_age)
        out.append([ds, {k: [round(o["rate"], 4) if o["rate"] is not None else None, o["n"]] for k, o in opts.items()}])
        d += datetime.timedelta(days=1)
    return out


def record(hist, quotes, log=print):
    """write each quote's latest reading into its series under the date it was read (collect_rentals calls this after
    every refresh); keeps the series' descriptive fields, announcements and status in step with the quote"""
    block = hist.setdefault("quotes", {"note": "", "series": {}})
    n = 0
    for q in quotes:
        if q.get("tier") == "index":
            continue
        k = key_of(q)
        if k not in block["series"] and not (q.get("per_gpu_hr") and q.get("read_on")):
            continue                                   # no series for a row that has never shown a price ('Contact sales')
        s = block["series"].setdefault(k, {"vendor": q["vendor"], "chip": q["chip"], "tier": q["tier"], "values": {}})
        for f in ("vendor", "chip", "tier", "instance", "url", "gpus"):
            if q.get(f) is not None:
                s[f] = q[f]
        s["hyperscaler"] = bool(q.get("hyperscaler"))
        s["pricing"] = q.get("pricing", s.get("pricing", "list"))
        if q.get("announced"):
            ann = s.setdefault("announced", [])
            a = q["announced"]
            if not any(x.get("effective") == a.get("effective") and abs(float(x.get("value", 0)) - float(a.get("value", 0))) < 1e-9 for x in ann):
                ann.append(a)
        if q.get("status") in ("ended", "unverifiable"):
            s["status"] = q["status"]
            if q.get("status") == "ended" and q.get("ended"):
                s["ended"] = q["ended"]
        if not q.get("per_gpu_hr") or not q.get("read_on") or q.get("status") in ("ended", "unverifiable"):
            continue
        v = round(float(q["per_gpu_hr"]), 4)
        if s["values"].get(q["read_on"]) != v:
            s["values"][q["read_on"]] = v
            n += 1
    return n


def changes_from_series(hist, dynamic_step=0.10):
    """the price changes a series shows, oldest first, by the collector's rule (list prices: any move; dynamically priced
    rows: a move of dynamic_step or more since the last logged value) - used to backfill data/rental_rates.json 'changes'"""
    out = []
    for k, s in ((hist.get("quotes") or {}).get("series") or {}).items():
        pts = points(s)
        if len(pts) < 2:
            continue
        dyn = s.get("pricing") == "dynamic"
        base, prev = pts[0][1], pts[0]
        for p in pts[1:]:
            ref = base if dyn else prev[1]
            moved = abs(p[1] / ref - 1) >= dynamic_step if dyn else abs(p[1] - ref) >= 0.005
            if moved:
                out.append({"date": p[0], "key": k, "vendor": s["vendor"], "chip": s["chip"], "tier": s["tier"], "instance": s.get("instance", ""),
                            "old": round(ref, 4), "new": round(p[1], 4), "pct": round(p[1] / ref - 1, 4), "prev_read": prev[0],
                            "kind": "stated" if p[2] == "stated" else "observed", "pricing": s.get("pricing", "list"), "url": s.get("url", ""),
                            "note": next((st[2] for st in s.get("stated") or [] if st[0] == p[0]), "")})
                base = p[1]
            prev = p
    return sorted(out, key=lambda c: (c["date"], c["vendor"], c["chip"], c["tier"]))
