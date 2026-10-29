#!/usr/bin/env python3
"""
The one command.   python update.py

Steps, in order (a failing step never stops the run; the page shows what is stale):
  1. openrouter   usage by task type, every host's price, and per-model effective price / delivered
                  speed / cache-hit / activity stats                                     (network)
  2. orshare      OpenRouter's closed- vs open-weight share of tokens: the weekly Top Models chart (53 weeks) and
                  a classified read of every model in the weekly ranking -> data/openrouter_share.json  (network)
  2b. tokrev      what OpenRouter's traffic paid for tokens, week by week: every model's daily tokens (31-day window)
                  times its effective price, older weeks from the weekly charts -> data/token_revenue.json  (network)
  3. labprices    Anthropic and OpenAI list prices, applied on every change: OpenAI's from its own API pricing page
                  (Standard tier), Anthropic's from OpenRouter's Anthropic endpoint rows (step 1)        (network)
  4. inferencex   published Blackwell throughput curves from SemiAnalysis InferenceX's API  (network)
  5. rentals      every provider's published rental quotes (Oracle, Azure incl. spot, AWS spot feed and Capacity
                  Blocks, Google spot page, CoreWeave, Nebius, Lambda, Verda, Together, Hyperbolic, Vultr API,
                  Silicon Data, Ornn, GetDeploying); logs every price change, reads dated price announcements
                  and pricing notices on the vendors' pages, and scans the news for provider price moves  (network)
  6. history      Silicon Data rental and token-expenditure index series (7 daily values per read), Ornn's
                  index series (3 months per read), GetDeploying's weekly medians, and every provider rate just
                  refreshed, appended to data/rate_history.json                                (network)
  7. deals        scan Google News and SEC EDGAR for newly announced multi-year GPU / AI-compute
                  contracts; queue candidates in data/deal_candidates.json for review          (network)
  8. build        re-read AI mastersheet.xlsx, run the model, write dashboard.html (and index.html, the same page, for
                  GitHub Pages), append history, save the day's market snapshot and restate the whole ROIC history on
                  today's assumptions
  9. infographic  rebuild the presentation view infographic/infographic.html from the same inputs

Flags:
  --offline            skip the fetches; rebuild from what is on disk
  --only STEP          run one step (openrouter | orshare | tokrev | labprices | inferencex | rentals | history | deals | build | infographic)
  --status             how old is each input? changes nothing
  --schedule [--at HH:MM]   run daily via Task Scheduler (Windows) or cron (macOS/Linux), e.g. --schedule --at 11:00; --unschedule to stop
  --scheduled          what the scheduled task passes: a full run with no "Press Enter" prompt

Standard library only. Python 3.8+. No API keys.
"""
import sys, os, json, datetime, subprocess, traceback
from pathlib import Path

# The daily record is kept on Sydney dates. On Windows the scheduled run already uses local time; a run inside a
# Linux sandbox (whose clock is UTC) would otherwise date a 9 am Sydney build to the previous day.
if os.environ.get("TZ") in (None, "", "UTC", "Etc/UTC", "UTC0"):
    import time as _time
    if hasattr(_time, "tzset"):
        os.environ["TZ"] = "Australia/Sydney"
        _time.tzset()

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
LOG = ROOT / "update.log"


def log(msg):
    print(msg)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("%s  %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))


def step(name, fn):
    log("== %s" % name)
    try:
        fn()
        return True
    except Exception as ex:
        log("   %s FAILED: %s" % (name, ex))
        for line in traceback.format_exc().splitlines()[-3:]:
            log("   " + line)
        return False


def do_openrouter():
    from engine import collect_openrouter as c
    lab = json.load(open(ROOT / "data" / "lab_prices.json", encoding="utf-8"))
    snap = c.fetch_live([m["slug"] for m in lab["models"].values()], extra_slugs=("google/gemini-3.7-flash",), log=log)
    c.OUT.write_text(json.dumps(snap, indent=1), encoding="utf-8")
    log("   %d task types, %d model rows, %d models priced, %d with stats, week of %s" % (len(snap["task_spend"]["tokens"]), len(snap["models_week"]["rows"]), len(snap["endpoints"]), len(snap.get("stats", {})), snap.get("week_date")))


def do_orshare():
    from engine import collect_or_share as c
    c.refresh(ROOT, log=log)


def do_tokrev():
    """What OpenRouter's traffic paid for tokens, week by week (engine/collect_token_revenue.py -> data/token_revenue.json)."""
    from engine import collect_token_revenue as c
    c.refresh(ROOT, log=log)


def do_labprices():
    """The labs' list prices in data/lab_prices.json, applied whenever they change.
    OpenAI rows: OpenAI's own API pricing page, Standard tier (engine/collect_labprices.py). OpenRouter's OpenAI rows are
    not used for these because its tier labels have not matched OpenAI's: on 2026-10-14 its 'standard' row for GPT-5.6
    Sol carried OpenAI's Flex / Batch price ($2 / $10) while OpenAI's Standard tab said $4 / $20.
    Anthropic rows: the 'Anthropic' provider row on OpenRouter (step 1's snapshot), which carries the list price.
    A row marked "confirm": "manual" is left as it is. A price that moves more than 3x in one read is kept and logged as
    a likely misread; a row whose source could not be read keeps its price and its old read_on, so the page shows its age."""
    from engine import collect_labprices as cl
    p = ROOT / "data" / "lab_prices.json"
    lab = json.load(open(p, encoding="utf-8"))
    snap = json.load(open(ROOT / "data" / "openrouter.json", encoding="utf-8"))
    or_day = (snap.get("read_on") or datetime.date.today().isoformat())      # an OpenRouter row is only as fresh as the snapshot it reads
    rows = [m for m in lab["models"].values() if m.get("confirm") != "manual"]
    oa = None
    if any((m.get("lab") or "").lower() == "openai" for m in rows):
        try:
            oa = cl.openai_prices()
        except Exception as ex:
            log("   OpenAI pricing page not read (%s): OpenAI rows keep their prices" % str(ex)[:120])
    n = moved = 0
    for m in rows:
        if (m.get("lab") or "Anthropic").lower() == "openai":
            if oa is None:
                continue
            row = oa.get(m.get("page_name") or m["slug"].split("/")[-1])
            if not row or not row["in"] or not row["out"]:
                log("   %s: not on OpenAI's pricing page (Standard tier); price kept at $%s / $%s" % (m["name"], m["in"], m["out"]))
                continue
            new, day, via = row, datetime.date.today().isoformat(), "OpenAI API pricing page, Standard tier"
        else:
            ep = snap["endpoints"].get(m["slug"])
            lab_name = (m.get("lab") or "Anthropic").lower()
            hosts = [h for h in (ep or {}).get("hosts", []) if h[0].lower().startswith(lab_name) and h[2]]
            if not hosts:
                continue
            h = sorted(hosts, key=lambda r: r[2])[0]
            new, day, via = {"in": h[1], "out": h[2], "cache_read": h[3]}, or_day, "OpenRouter endpoint row for provider %s" % m["lab"]
        if any(not new[k] or max(new[k], m[k]) / min(new[k], m[k]) > 3 for k in ("in", "out")):
            log("   %s: read $%s in / $%s out against $%s / $%s, more than a 3x move: kept as a likely misread (edit lab_prices.json if it is real)" % (m["name"], new["in"], new["out"], m["in"], m["out"]))
            continue
        before = (m["in"], m["out"], m.get("cache_read"), m.get("cache_write"))
        m["in"], m["out"] = new["in"], new["out"]
        for k in ("cache_read", "cache_write"):
            if new.get(k) is not None:
                m[k] = new[k]
        m["read_on"], m["confirmed_via"] = day, via
        n += 1
        if (m["in"], m["out"], m.get("cache_read"), m.get("cache_write")) != before:
            moved += 1
            log("   %s list price moved: $%s in / $%s out (cache read $%s) -> $%s / $%s (cache read $%s), applied (%s)" % (
                m["name"], before[0], before[1], before[2], m["in"], m["out"], m.get("cache_read"), via))
    json.dump(lab, open(p, "w", encoding="utf-8"), indent=1)
    log("   %d lab prices checked, %d moved and applied" % (n, moved))


def do_inferencex():
    from engine import collect_inferencex as ix
    ix.refresh(log=log)


def do_rentals():
    from engine import collect_rentals as r
    r.refresh(log=log)


def do_history():
    from engine import collect_history as h
    h.refresh(log=log)


def do_deals():
    from engine import collect_deals as d
    a = json.load(open(ROOT / "assumptions.json", encoding="utf-8"))
    d.refresh(log=log, sec_user_agent=(a.get("deals") or {}).get("sec_user_agent", ""))


def do_build():
    from engine import build
    build.build(log=log)


def do_infographic():
    """Rebuilds the presentation view (infographic/infographic.html) from the same inputs. It imports this project's
    engine, so the two pages can only disagree if one was built without the other."""
    script = ROOT / "infographic" / "build_infographic.py"
    if not script.exists():
        log("   no infographic/build_infographic.py in this folder; presentation view not rebuilt")
        return
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_infographic", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.build(log=log)


def status():
    D = ROOT / "data"
    today = datetime.date.today()
    def age(s):
        try:
            return (today - datetime.date.fromisoformat(s[:10])).days
        except Exception:
            return None
    o = json.load(open(D / "openrouter.json", encoding="utf-8"))
    lab = json.load(open(D / "lab_prices.json", encoding="utf-8"))
    rent = json.load(open(D / "rental_rates.json", encoding="utf-8"))
    tp = json.load(open(D / "throughput.json", encoding="utf-8"))
    print("OpenRouter usage & prices : read %s (%s days old)" % (o["read_on"], age(o["read_on"])))
    sp = D / "openrouter_share.json"
    if sp.exists():
        sh = json.load(open(sp, encoding="utf-8"))
        wk, rd = sorted(sh.get("weeks", {})), sorted(sh.get("reads", {}))
        print("OpenRouter closed share   : %d weeks %s to %s; %d full-ranking reads, last %s" % (len(wk), wk[0] if wk else "-", wk[-1] if wk else "-", len(rd), rd[-1] if rd else "-"))
    lp = max(m["read_on"] for m in lab["models"].values())
    print("Lab list prices           : read %s (%s days old)" % (lp, age(lp)))
    rq = max(q["read_on"] for q in rent["quotes"])
    stale = [q for q in rent["quotes"] if q.get("refresh") and (age(q["read_on"]) or 0) > 7]
    print("Rental quotes             : newest %s; %d refreshable rows older than a week; %d price changes logged (latest %s); %d pricing notices" % (
        rq, len(stale), len(rent.get("changes", [])), max((c["date"] for c in rent.get("changes", [])), default="-"), len(rent.get("notices", []))))
    print("InferenceX curves         : %d curves, read %s (newest benchmark run %s)" % (len(tp["curves"]), tp.get("read_on"), max(c[4] for c in tp["curves"])))
    print("OpenRouter model stats    : %d models (effective price, delivered speed, cache hit)" % len(o.get("stats", {})))
    tr = D / "traces.json"
    if tr.exists():
        t = json.load(open(tr, encoding="utf-8"))
        print("Agent traces              : %s sessions, read %s (curated; see engine/collect_traces.py)" % (t.get("sessions"), t.get("read_on")))
    rh = D / "rate_history.json"
    if rh.exists():
        h = json.load(open(rh, encoding="utf-8"))
        si = h["silicon_index"]["series"]
        n_days = len({d for s in si.values() for d in s["values"]})
        last = max(d for s in si.values() for d in s["values"])
        qs = (h.get("quotes") or {}).get("series", {})
        n_spot = len({d for s in qs.values() for d in s["values"]})
        oi = h.get("ornn_index", {}).get("series", {})
        o_days = len({d for s in oi.values() for d in s["values"]})
        print("Rate history              : Silicon Data %d daily dates to %s (%d series, read %s); Ornn %d daily dates%s; provider rental rates (%d series) read on %d dates" % (
            n_days, last, len(si), h["silicon_index"].get("read_on"), o_days, (" to %s" % max(d for s in oi.values() for d in s["values"])) if o_days else "", len(qs), n_spot))
        ti = h.get("token_index", {}).get("series", {})
        if ti:
            t_days = len({d for s in ti.values() for d in s["values"]})
            print("Token indices             : Silicon Data LLM / open / proprietary, %d daily dates to %s (read %s)" % (t_days, max(d for s in ti.values() for d in s["values"]), h["token_index"].get("read_on")))
    dc = D / "deal_candidates.json"
    if dc.exists():
        c = json.load(open(dc, encoding="utf-8"))
        new = [x for x in c.get("candidates", []) if x.get("status") == "new"]
        print("Deal scout                : scanned %s; %d candidates awaiting review (%d not matched to a listed contract)%s" % (
            c.get("scanned_on"), len(new), sum(1 for x in new if not x.get("matched_contract")), "" if c.get("edgar_phrases") else "; EDGAR pass off (deals.sec_user_agent blank)"))
    from engine import read_mastersheet as rm
    a = json.load(open(ROOT / "assumptions.json", encoding="utf-8"))
    ms = rm.read(ROOT, a["mastersheet"]["cells"], a["mastersheet"].get("path"))
    print("AI mastersheet.xlsx       : %s" % (("%s (saved %s)" % (ms["path"], ms["modified"])) if ms["found"] else "NOT FOUND - fallback values would be used"))
    h = D / "history.jsonl"
    lines = [json.loads(l) for l in open(h, encoding="utf-8") if l.strip()] if h.exists() else []
    if lines:
        last = lines[-1]
        print("Last build                : %s  rent $%.2f/GPU-hr ROIC %.1f%%  %s" % (
            last["built_at"], last["rent"]["rev_per_gpu_hr"], 100 * last["rent"]["roic"],
            "  ".join("serve/%s $%.2f ROIC %.1f%%" % (k, v["rev_per_gpu_hr"], 100 * v["roic"]) for k, v in last.get("serves", {"": last["serve"]}).items())))
    dash = ROOT / "dashboard.html"
    print("dashboard.html            : %s" % (datetime.datetime.fromtimestamp(dash.stat().st_mtime).strftime("%Y-%m-%d %H:%M") if dash.exists() else "not built"))


TASK_NAME = "BlackwellROIC-daily"
TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Blackwell ROIC dashboard: refresh every market input and rebuild dashboard.html (python update.py --scheduled)</Description></RegistrationInfo>
  <Triggers><CalendarTrigger><StartBoundary>%(start)s</StartBoundary><Enabled>true</Enabled><ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay></CalendarTrigger></Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <WakeToRun>false</WakeToRun>
  </Settings>
  <Actions Context="Author"><Exec><Command>%(py)s</Command><Arguments>"%(script)s" --scheduled</Arguments><WorkingDirectory>%(cwd)s</WorkingDirectory></Exec></Actions>
</Task>
"""


def schedule(at="07:30", remove=False):
    """Daily run. Windows: a Task Scheduler task defined by XML so that a start missed while the PC was asleep or off
    runs as soon as it is back ('StartWhenAvailable'), the run waits for a network, and pythonw.exe (no console
    window) is used when it sits beside the interpreter. macOS/Linux: a crontab line."""
    py = sys.executable
    script = str(ROOT / "update.py")
    if os.name == "nt":
        if remove:
            subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], check=False)
            print("unscheduled %s" % TASK_NAME)
            return
        pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
        if os.path.exists(pyw):
            py = pyw
        hh, mm = at.split(":")
        start = datetime.datetime.now().replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        if start < datetime.datetime.now():
            start += datetime.timedelta(days=1)
        xml = TASK_XML % {"start": start.strftime("%Y-%m-%dT%H:%M:%S"), "py": py, "script": script, "cwd": str(ROOT)}
        xml_path = ROOT / "data" / "scheduled_task.xml"
        xml_path.write_text(xml, encoding="utf-16")
        r = subprocess.run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(xml_path), "/F"], capture_output=True, text=True)
        if r.returncode != 0:
            print("Task Scheduler XML registration failed (%s); falling back to the simple form" % (r.stderr or r.stdout).strip())
            cmd = '"%s" "%s" --scheduled' % (py, script)
            subprocess.run(["schtasks", "/Create", "/SC", "DAILY", "/TN", TASK_NAME, "/TR", cmd, "/ST", at, "/F"], check=True)
        q = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST"], capture_output=True, text=True)
        print("scheduled %s daily at %s (Task Scheduler, runs with %s; a missed start runs when the PC is next awake). Log: %s" % (TASK_NAME, at, os.path.basename(py), LOG))
        print("\n".join(l for l in q.stdout.splitlines() if l.strip().startswith(("Next Run Time", "Status", "TaskName"))))
    else:
        tag = "# blackwell-roic"
        cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        lines = [l for l in cur.splitlines() if tag not in l]
        if not remove:
            hh, mm = at.split(":")
            lines.append('%s %s * * * cd "%s" && "%s" "%s" >> "%s" 2>&1 %s' % (int(mm), int(hh), ROOT, py, script, LOG, tag))
        subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True)
        print("%s cron entry" % ("removed" if remove else "installed"))


def main(argv):
    if "--status" in argv:
        return status()
    if "--schedule" in argv or "--unschedule" in argv:
        at = argv[argv.index("--at") + 1] if "--at" in argv else "07:30"
        return schedule(at, remove="--unschedule" in argv)
    only = argv[argv.index("--only") + 1] if "--only" in argv else None
    offline = "--offline" in argv
    steps = [("openrouter", do_openrouter, True), ("orshare", do_orshare, True), ("tokrev", do_tokrev, True), ("labprices", do_labprices, True), ("inferencex", do_inferencex, True), ("rentals", do_rentals, True), ("history", do_history, True), ("deals", do_deals, True), ("build", do_build, False), ("infographic", do_infographic, False)]
    results = {}
    log("run: %s" % (" ".join(argv) or "full"))
    for name, fn, needs_net in steps:
        if only and name != only:
            continue
        if offline and needs_net:
            log("== %s skipped (--offline)" % name)
            continue
        results[name] = step(name, fn)
    if not only or only == "build":
        pass
    bad = [k for k, v in results.items() if not v]
    log("done. %s" % ("all steps clean" if not bad else "failed: " + ", ".join(bad) + " (rebuilt from what is on disk)"))
    if os.name == "nt" and sys.stdin and sys.stdin.isatty() and not argv and "--scheduled" not in argv:
        try:
            input("Press Enter to close.")
        except Exception:
            pass


if __name__ == "__main__":
    main(sys.argv[1:])
