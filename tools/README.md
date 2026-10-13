# tools/: refreshing through a browser when the machine has no direct internet

`update.py` fetches every market input with Python's `urllib`. Where the machine that runs it cannot reach those
sites (a sandbox whose proxy blocks them, as on 8, 10 and 13 Oct 2026 when the scheduled run in the desktop VM got
"Tunnel connection failed: 403 Forbidden"), the same run can be served from responses fetched in a browser:

1. In a browser tab on each site (openrouter.ai, inferencex.semianalysis.com, each rental vendor's page, ...), fetch the
   URLs the collectors ask for and save the responses as one JSON object `{url: response text}`, gzipped and
   base64-encoded (the format `pull2.py` reads; see its source).
2. `python tools/pull2.py <saved payload> <cache folder>` adds the responses to a URL-keyed cache
   (`<cache folder>/index.json` plus one `.body` file per URL).
3. `python tools/run_cached.py . <cache folder> [update.py arguments]` runs `update.py` with `urllib` answered from
   that cache. A URL missing from the cache is recorded in `<cache folder>/misses.txt` and fails like any network
   error (the collector keeps the last good value and the page shows what is stale).

Neither script is needed when `update.py` has a working connection. Standard library only.
