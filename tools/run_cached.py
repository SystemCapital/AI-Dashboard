"""
Runs Blackwell-ROIC's update.py with urllib served from a URL-keyed cache filled by the browser pane.
A miss is recorded in misses.txt and raised (the collectors treat it like any network failure).
Usage: python run_cached.py <root> <cachedir> [update.py args...]
"""
import sys, io, json, urllib.request, urllib.parse, urllib.error
from pathlib import Path

ROOT, CACHE = Path(sys.argv[1]), Path(sys.argv[2])
ARGS = sys.argv[3:]
INDEX = json.load(open(CACHE / "index.json", encoding="utf-8")) if (CACHE / "index.json").exists() else {}
MISS = CACHE / "misses.txt"
HITS = []


def norm(url):
    return urllib.parse.unquote(url).strip()


class _Resp(io.BytesIO):
    def __init__(self, data, url):
        super().__init__(data)
        self.url, self.status, self.code = url, 200, 200
    def geturl(self):
        return self.url
    def getcode(self):
        return 200
    def info(self):
        import email.message
        return email.message.Message()
    def __enter__(self):
        return self
    def __exit__(self, *a):
        self.close()


def fake_urlopen(req, timeout=None, **kw):
    url = req.full_url if hasattr(req, "full_url") else req
    key = norm(url)
    fn = INDEX.get(key)
    if fn is None:
        with open(MISS, "a", encoding="utf-8") as f:
            f.write(key + "\n")
        raise urllib.error.URLError("not in the browser cache: " + key[:120])
    HITS.append(key)
    return _Resp((CACHE / fn).read_bytes(), url)


urllib.request.urlopen = fake_urlopen
sys.path.insert(0, str(ROOT))
import importlib.util
spec = importlib.util.spec_from_file_location("update", ROOT / "update.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.main(ARGS)
print("cache hits: %d" % len(HITS))
