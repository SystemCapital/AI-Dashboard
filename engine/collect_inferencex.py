"""
InferenceX collector: published tokens/s per GPU on Blackwell, from SemiAnalysis's public API.

  GET https://inferencex.semianalysis.com/api/v1/benchmarks?model=<name>
      every latest benchmark row for one display model: hardware, framework, precision, parallelism recipe,
      ISL/OSL (or agentic traces), concurrency, and a metrics block with median interactivity (tok/s per
      user), input / output / total throughput per GPU, TTFT and power. Apache-2.0.
  GET https://inferencex.semianalysis.com/api/openapi.json
      the list of display models the endpoint accepts (parameters[model].enum). Read every run so a newly
      published model is reported in the log; it becomes usable once data/models.json maps a registry row
      to it ('inferencex').

For each model named in data/models.json ('inferencex'), each Blackwell part (GB300, GB200, B300, B200) and
each workload (8k/1k, 1k/1k, agentx) the rows are reduced to the Pareto frontier of OUTPUT tokens/s per GPU
against interactivity, thinned to at most 14 log-spaced points. Every point carries that run's own measured
system-wide output and input rates per GPU, taken from the row's input_tput_per_gpu / output_tput_per_gpu
and its prefill / decode GPU counts:

    disaggregated:  output tok/s per GPU = output_tput_per_gpu x num_decode_gpu  / (num_prefill_gpu + num_decode_gpu)
                    input  tok/s per GPU = input_tput_per_gpu  x num_prefill_gpu / (num_prefill_gpu + num_decode_gpu)
    aggregated:     output = output_tput_per_gpu,  input = input_tput_per_gpu

Each row is checked against its own tput_per_gpu (the sum must reconstruct it within 2%); rows that do not
reconstruct are skipped and counted. Nothing is assumed about the input:output split.

Writes data/throughput.json. Reference points and the comment block are preserved. Standard library only.
"""
import json, math, datetime, urllib.request, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "data" / "throughput.json"
BASE = "https://inferencex.semianalysis.com/api/v1/benchmarks?model="
SPEC = "https://inferencex.semianalysis.com/api/openapi.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; blackwell-roic/1.0; +local research tool)", "Accept": "application/json"}
HW = ["gb300", "gb200", "b300", "b200"]
WORKLOADS = [("8k/1k", lambda r: r.get("benchmark_type") == "single_turn" and r.get("isl") == 8192 and r.get("osl") == 1024),
             ("1k/1k", lambda r: r.get("benchmark_type") == "single_turn" and r.get("isl") == 1024 and r.get("osl") == 1024),
             ("agentx", lambda r: r.get("benchmark_type") == "agentic_traces")]
COLUMNS = ["model", "hw", "workload", "n", "date", "precisions", "frameworks", "points[inter, out_tps_per_gpu, in_tps_per_gpu]"]


def get_json(url, timeout=120):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_rows(name, timeout=120):
    return get_json(BASE + urllib.parse.quote(name), timeout)


def accepted_models():
    """Display-model names the public endpoint accepts, from the OpenAPI document."""
    spec = get_json(SPEC)
    for p in spec["paths"]["/api/v1/benchmarks"]["get"]["parameters"]:
        if p["name"] == "model":
            return list(p["schema"]["enum"])
    return []


def sys_rates(r):
    """(output tok/s per GPU, input tok/s per GPU) system-wide for one row, or None if the row's own
    total cannot be reconstructed from its input/output figures and GPU counts."""
    m = r.get("metrics") or {}
    tput, i, o = m.get("tput_per_gpu"), m.get("input_tput_per_gpu"), m.get("output_tput_per_gpu")
    if not tput or i is None or o is None:
        return None
    npre, ndec = r.get("num_prefill_gpu") or 0, r.get("num_decode_gpu") or 0
    if r.get("disagg"):
        n = npre + ndec
        if n and abs((i * npre + o * ndec) / n - tput) <= 0.02 * tput:
            return o * ndec / n, i * npre / n
    if abs(i + o - tput) <= 0.02 * tput:
        return o, i
    return None


def frontier(pts):
    """Pareto frontier of output tok/s/GPU (index 1) against interactivity (index 0)."""
    pts = sorted((p for p in pts if p[0] > 0 and p[1] > 0), key=lambda p: -p[0])
    out, best = [], 0.0
    for p in pts:
        if p[1] > best:
            out.append(p)
            best = p[1]
    return sorted(out, key=lambda p: p[0])


def thin(pts, n=14):
    if len(pts) <= n:
        return pts
    lo, hi = math.log(pts[0][0]), math.log(pts[-1][0])
    keep = []
    for i in range(n):
        target = math.exp(lo + (hi - lo) * i / (n - 1))
        best = min(pts, key=lambda p: abs(math.log(p[0]) - math.log(target)))
        if best not in keep:
            keep.append(best)
    return keep


def reduce_rows(name, rows):
    curves, skipped = [], 0
    for hw in HW:
        for wl, pred in WORKLOADS:
            sel = [r for r in rows if r.get("hardware") == hw and pred(r) and r.get("metrics") and (r["metrics"].get("median_intvty") or 0) > 0]
            pts = []
            for r in sel:
                sr = sys_rates(r)
                if sr is None:
                    skipped += 1
                    continue
                pts.append([r["metrics"]["median_intvty"], sr[0], sr[1]])
            if len(pts) < 2:
                continue
            fr = thin(frontier(pts))
            curves.append([name, hw.upper(), wl, len(pts), max(r.get("date", "") for r in sel),
                           "+".join(sorted({r.get("precision", "") for r in sel})), "+".join(sorted({r.get("framework", "") for r in sel})),
                           [[round(p[0], 1), round(p[1], 1), round(p[2], 1)] for p in fr]])
    return curves, skipped


def refresh(log=print):
    reg = json.load(open(ROOT / "data" / "models.json", encoding="utf-8"))
    names = sorted({m["inferencex"] for m in reg["models"] if m.get("inferencex")})
    old = json.load(open(PATH, encoding="utf-8"))
    old_by = {}
    for row in old.get("curves", []):
        old_by.setdefault(row[0], []).append(row)
    try:
        acc = accepted_models()
        new = [n for n in acc if n not in names]
        if new:
            log("   InferenceX also publishes: %s (not mapped in data/models.json)" % ", ".join(new))
        bad = [n for n in names if n not in acc]
        if bad:
            log("   WARNING: data/models.json names not accepted by the API: %s" % ", ".join(bad))
    except Exception as ex:
        log("   (could not read the API's model list: %s)" % str(ex)[:60])
    new_curves, ok, failed = [], 0, 0
    for name in names:
        try:
            rows = fetch_rows(name)
            if not isinstance(rows, list):
                raise ValueError(str(rows)[:80])
            cur, skipped = reduce_rows(name, rows)
            new_curves.extend(cur)
            ok += 1
            log("   %-22s %5d rows -> %2d curves (newest %s%s)" % (name, len(rows), len(cur), max((c[4] for c in cur), default="-"),
                                                                    (", %d rows skipped: totals do not reconstruct" % skipped) if skipped else ""))
        except Exception as ex:
            failed += 1
            new_curves.extend(old_by.get(name, []))
            log("   %-22s FAILED (%s) - kept %d old curves" % (name, str(ex)[:70], len(old_by.get(name, []))))
    if ok == 0:
        log("inferencex: nothing fetched; file left unchanged")
        return ok, failed
    old["curves"] = new_curves
    old["columns"] = COLUMNS
    old["read_on"] = datetime.date.today().isoformat()
    json.dump(old, open(PATH, "w", encoding="utf-8"), indent=1)
    log("inferencex: %d models refreshed, %d failed, %d curves -> %s" % (ok, failed, len(new_curves), PATH.name))
    return ok, failed


if __name__ == "__main__":
    refresh()
