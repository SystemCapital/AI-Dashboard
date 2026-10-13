#!/usr/bin/env python3
"""
Builds infographic.html: the presentation view of the Blackwell-ROIC model.

Every number on the page comes from the model one folder up (../engine, ../data). This script imports that engine, runs
prepare() (every market input, resolved once) and embeds that INPUTS block, the five capital cost areas read from
the same AI mastersheet.xlsx, and the JavaScript twin of the model lifted verbatim out of
../engine/template.html. The page then computes every scenario itself (assemble.js + app.js), at the
default dials on load and again whenever dashboard.html publishes a dial move, so the two pages always agree.
The Python result at default dials is embedded too, so the page can check its arithmetic against the builder.

Run it directly (python infographic/build_infographic.py) or let ../update.py run it as its last step.
Standard library only.
"""
import json, sys, os, datetime, re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROIC = HERE.parent                      # the model: ../engine, ../data, ../assumptions.json
if not (ROIC / "engine" / "model.py").exists():
    print("engine/model.py not found one folder up; nothing to build from.")
    sys.exit(1)
sys.path.insert(0, str(ROIC))
from engine import model, read_mastersheet as rm  # noqa: E402

# extra mastersheet cells for the capital picture (same sheet the engine reads; fallback = the values read 2026-09-15)
EXTRA_CELLS = {
    "memory_per_rack_musd": {"sheet": "GB300 ", "label": "Memory Contribution (DDR5)"},
    "cpu_per_rack_musd": {"sheet": "GB300 ", "label": "CPU Contribution"},
    "other_per_rack_musd": {"sheet": "GB300 ", "label": "Other Contribution"},
    "racks": {"sheet": "GB300 ", "label": "Number of Racks"},
    "shell_per_mw_musd": {"sheet": "GB300 ", "label": "Cost per MW ($M)"},
}
EXTRA_FALLBACK = {"memory_per_rack_musd": 0.9499392, "cpu_per_rack_musd": 0.18, "other_per_rack_musd": 0.9062116666666675, "racks": 5698.005698005697, "shell_per_mw_musd": 16.2}


def engine_js():
    """The arithmetic block of the dashboard template: from the 'arithmetic' banner to just before its formatters."""
    t = (ROIC / "engine" / "template.html").read_text(encoding="utf-8")
    a = t.index("// ====")
    a = t.index("arithmetic", a)
    a = t.rindex("\n", 0, a) + 1
    b = t.index("\nconst fmt = {", a)
    block = t[a:b]
    for name in ("function compute(", "function defaultDials(", "function resolveTps(", "function irr("):
        assert name in block, "engine block lacks " + name
    return block


def build(log=print):
    inp = model.prepare(ROIC, log=lambda *a: None)
    dials = model.default_dials(inp)
    res = model.compute(inp, dials)
    ms = rm.read(ROIC, EXTRA_CELLS, (json.load(open(ROIC / "assumptions.json", encoding="utf-8")).get("mastersheet") or {}).get("path"))
    X = {}
    for k in EXTRA_CELLS:
        v = ms["values"].get(k, {}).get("value") if ms["found"] else None
        X[k] = {"value": (v if v is not None else EXTRA_FALLBACK[k]), "cell": (ms["values"].get(k, {}).get("cell") if ms["found"] and v is not None else None),
                "basis": ("mastersheet" if (ms["found"] and v is not None) else "fallback")}
    # headline numbers at default dials, for the page's self-check against this (Python) run
    def head(sc):
        return {k: sc.get(k) for k in ("roic", "irr", "revenue", "ebitda", "rev_per_gpu_hr", "power")}
    py = {"rent": head(res["rent"]), "anthropic": head(res["serves"]["anthropic"]), "open": head(res["serve_open"]), "aws": head(res["serve_aws"]),
          "capex": res["capex"], "depreciation": res["depreciation"], "built_at": inp["built_at"]}
    dumps = lambda o: json.dumps(o, default=(lambda x: round(x, 6) if isinstance(x, float) else str(x)))
    tpl = (HERE / "template.html").read_text(encoding="utf-8")
    assert "/*__DATA__*/" in tpl and "/*__APP__*/" in tpl, "template.html lacks the markers"
    # the full model is ../dashboard.html; BLACKWELL_ROIC_DIR (a folder holding dashboard.html) makes the link absolute, for
    # a copy of this page kept somewhere else. Not set by default, so no machine's path is written into the page.
    roic_dir = os.environ.get("BLACKWELL_ROIC_DIR") or ""
    blob = "/*__DATA__*/\nconst INPUTS = %s;\nconst EXTRA = %s;\nconst PY = %s;\nconst GENERATED = %s;\nconst ROIC_DIR = %s;" % (
        dumps(inp), dumps(X), dumps(py), json.dumps(datetime.datetime.now().strftime("%Y-%m-%d %H:%M")), json.dumps(roic_dir))
    out = tpl.replace("/*__DATA__*/\nconst DATA = {};", blob, 1) if "/*__DATA__*/\nconst DATA = {};" in tpl else tpl.replace("/*__DATA__*/", blob, 1)
    app = "// ---- engine: lifted from ../engine/template.html at build time\n" + engine_js() + "\n// ---- assembly\n" + (HERE / "assemble.js").read_text(encoding="utf-8") + "\n// ---- page\n" + (HERE / "app.js").read_text(encoding="utf-8")
    out = out.replace("/*__APP__*/", app, 1)
    (HERE / "infographic.html").write_text(out, encoding="utf-8")
    log("   infographic.html written: capex $%.1fB, ROIC rent %.1f%% / lab %.1f%% / open %.1f%% / AWS %.1f%% at default dials" % (
        res["capex"] / 1e9, 100 * res["rent"]["roic"], 100 * res["serves"]["anthropic"]["roic"], 100 * res["serve_open"]["roic"], 100 * res["serve_aws"]["roic"]))


if __name__ == "__main__":
    build()
