import json, sys, re, base64, gzip, hashlib, urllib.parse
from pathlib import Path
f, cache = sys.argv[1], Path(sys.argv[2])
txt = ''.join(x['text'] for x in json.load(open(f)) if x.get('type') == 'text')
m = re.search(r'"([A-Za-z0-9+/=]{40,})\|PAD\|', txt) or re.search(r'"([A-Za-z0-9+/=]{500,})"', txt)
payload = json.loads(gzip.decompress(base64.b64decode(m.group(1))).decode('utf-8'))
idx_p = cache / 'index.json'
idx = json.load(open(idx_p)) if idx_p.exists() else {}
for url, body in payload.items():
    key = urllib.parse.unquote(url).strip()
    fn = hashlib.sha1(key.encode()).hexdigest() + '.body'
    (cache / fn).write_text(body, encoding='utf-8')
    idx[key] = fn
json.dump(idx, open(idx_p, 'w'), indent=0)
print('ingested %d bodies; index now %d' % (len(payload), len(idx)))
