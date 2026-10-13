"""
Offline check of the lab-prices step against OpenAI's pricing page as captured on 2026-10-14:
    python engine/tests/test_labprices.py
Reads the Standard and Batch tables from the sample, then runs update.py's labprices step on temporary copies of
data/lab_prices.json and data/openrouter.json with the page read faked: a moved OpenAI price is applied, a 10x move
is kept as a misread, an unreadable page keeps every OpenAI price, and the Anthropic rows still come from OpenRouter.
The real data/ files and update.log are untouched.
"""
import sys, json, shutil, tempfile, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
from engine import collect_labprices as cl
import update

PAGE = (HERE / "samples" / "openai_pricing_2026-10-14.html").read_text(encoding="utf-8")


def main():
    std = cl.parse_openai(PAGE)
    assert std["gpt-5.6-sol"] == {"in": 4.0, "cache_read": 0.4, "cache_write": 5.0, "out": 20.0}, std["gpt-5.6-sol"]
    assert std["gpt-5.6-terra"] == {"in": 2.0, "cache_read": 0.2, "cache_write": 2.5, "out": 12.0}, std["gpt-5.6-terra"]
    assert std["gpt-5.6-luna"]["out"] == 1.2 and std["gpt-5.5"]["cache_write"] is None      # '-' on the page; '(<272K ...)' dropped
    assert cl.parse_openai(PAGE, "batch")["gpt-5.6-sol"]["out"] == 10.0                     # Batch is half of Standard
    try:
        cl.parse_openai("<html></html>")
        raise AssertionError("a page with no table must raise")
    except ValueError:
        pass

    tmp = Path(tempfile.mkdtemp())
    (tmp / "data").mkdir()
    for f in ("lab_prices.json", "openrouter.json"):
        shutil.copy(ROOT / "data" / f, tmp / "data" / f)
    update.ROOT, update.LOG = tmp, tmp / "update.log"
    real = cl.openai_prices
    today = datetime.date.today().isoformat()
    lab = lambda: json.load(open(tmp / "data" / "lab_prices.json", encoding="utf-8"))["models"]
    try:
        # a price cut on the page is applied, with its date and source
        page = json.loads(json.dumps(std))
        page["gpt-5.6-sol"].update({"in": 3.0, "out": 15.0, "cache_read": 0.3})
        page["gpt-5.6-terra"].update({"in": 20.0, "out": 120.0})                               # a 10x jump: a misread
        cl.openai_prices = lambda tier="standard", timeout=60: page
        update.do_labprices()
        m = lab()
        assert (m["gpt-5.6-sol"]["in"], m["gpt-5.6-sol"]["out"], m["gpt-5.6-sol"]["cache_read"]) == (3.0, 15.0, 0.3), m["gpt-5.6-sol"]
        assert m["gpt-5.6-sol"]["read_on"] == today and m["gpt-5.6-sol"]["confirmed_via"].startswith("OpenAI API pricing page")
        assert (m["gpt-5.6-terra"]["in"], m["gpt-5.6-terra"]["out"]) == (2.0, 12.0), m["gpt-5.6-terra"]
        assert m["claude-opus-5.5"]["confirmed_via"].startswith("OpenRouter endpoint row")
        # the page cannot be read: every OpenAI price stays as it is
        def down(tier="standard", timeout=60):
            raise OSError("Tunnel connection failed: 403 Forbidden")
        cl.openai_prices = down
        update.do_labprices()
        assert (lab()["gpt-5.6-sol"]["in"], lab()["gpt-5.6-sol"]["out"]) == (3.0, 15.0)
    finally:
        cl.openai_prices = real
    logs = (tmp / "update.log").read_text(encoding="utf-8")
    assert "GPT-5.6 Sol list price moved" in logs and "likely misread" in logs and "OpenAI pricing page not read" in logs, logs
    print(logs)
    print("lab prices OK: Standard tier read from the 2026-10-14 sample, moves applied, misreads and outages kept")


if __name__ == "__main__":
    main()
