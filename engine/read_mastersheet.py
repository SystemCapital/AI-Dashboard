"""
Reads the capital and power build-up out of AI mastersheet.xlsx with the standard library only.

An .xlsx is a zip of XML. Two sheets are read by label so that the workbook can be edited freely:

  'GB300 '           the rack build-up: GPUs per rack, cost per GPU, kW per rack, PUE, $/MWh, GPUs required,
                     shell cost, total data-centre cost. Labels sit in column B, the value is the FIRST number
                     to the right on the same row (column F carries a scenario strip that must not be read).
  'ROIC Dashboard'   two blocks ('Rental economics', 'Token economics'), each a header row of column names
                     and one row per chip; the GB300 row gives utilisation, power price and other costs.

Every value comes back with its cell address so the page can cite it. If the workbook is missing, the
caller falls back to assumptions.json:fallback_if_mastersheet_missing and says so on the page.
"""
import re, zipfile, hashlib, datetime, os
import xml.etree.ElementTree as ET
from pathlib import Path

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NAME = "AI mastersheet.xlsx"


def find_workbook(root, explicit=None):
    """Explicit path first; then this folder, then up to three parents and their subfolders (bounded walk)."""
    if explicit:
        p = Path(explicit)
        if not p.is_absolute():
            p = root / p
        return p if p.exists() else None
    here = root / NAME
    if here.exists():
        return here
    base = root
    for _ in range(3):
        base = base.parent
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "__pycache__")]
            if dirpath.count(os.sep) - str(base).count(os.sep) > 3:
                dirnames[:] = []
            if NAME in filenames:
                return Path(dirpath) / NAME
    return None


def col_index(ref):
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


class Workbook:
    def __init__(self, path):
        self.path = Path(path)
        self.z = zipfile.ZipFile(self.path)
        self.shared = []
        if "xl/sharedStrings.xml" in self.z.namelist():
            sst = ET.fromstring(self.z.read("xl/sharedStrings.xml"))
            for si in sst.findall(NS + "si"):
                self.shared.append("".join(t.text or "" for t in si.iter(NS + "t")))
        wb = ET.fromstring(self.z.read("xl/workbook.xml"))
        rels = ET.fromstring(self.z.read("xl/_rels/workbook.xml.rels"))
        rid2t = {r.get("Id"): r.get("Target") for r in rels}
        self.sheets = {}
        for s in wb.iter(NS + "sheet"):
            tgt = rid2t[s.get(RNS + "id")]
            self.sheets[s.get("name")] = tgt if tgt.startswith("xl/") else "xl/" + tgt.lstrip("/")
        self._cache = {}

    def sheet_names(self):
        return list(self.sheets)

    def rows(self, name):
        """Yields (row_number, [(ref, value), ...]) with strings resolved and numbers as float."""
        key = None
        for n in self.sheets:
            if n.strip() == name.strip():
                key = n
                break
        if key is None:
            raise KeyError("sheet %r not in workbook (have %s)" % (name, list(self.sheets)))
        if key in self._cache:
            return self._cache[key]
        root = ET.fromstring(self.z.read(self.sheets[key]))
        out = []
        for row in root.iter(NS + "row"):
            cells = []
            for c in row.findall(NS + "c"):
                v = c.find(NS + "v")
                if v is None:
                    continue
                if c.get("t") == "s":
                    val = self.shared[int(v.text)]
                elif c.get("t") == "str":
                    val = v.text
                else:
                    try:
                        val = float(v.text)
                    except (TypeError, ValueError):
                        val = v.text
                cells.append((c.get("r"), val))
            if cells:
                out.append((int(row.get("r")), cells))
        self._cache[key] = out
        return out

    def label_value(self, sheet, label):
        """First number to the right of the first cell whose text starts with `label` (case-insensitive)."""
        lab = label.strip().lower()
        for rn, cells in self.rows(sheet):
            for i, (ref, val) in enumerate(cells):
                if isinstance(val, str) and val.strip().lower().startswith(lab):
                    for ref2, val2 in cells[i + 1:]:
                        if isinstance(val2, float):
                            return val2, "%s!%s" % (sheet.strip(), ref2)
                    return None, "%s!%s" % (sheet.strip(), ref)
        return None, None

    def block_value(self, sheet, block, row_label, col):
        """In a sheet of stacked blocks: find the block title, then its header row, then the row whose first
        text equals row_label, and return the value under the header `col`."""
        rows = self.rows(sheet)
        in_block, header = False, None
        for rn, cells in rows:
            texts = [(ref, v) for ref, v in cells if isinstance(v, str)]
            if not in_block:
                if any(v.strip().lower() == block.lower() for _, v in texts):
                    in_block = True
                continue
            if header is None:
                if any(v.strip().lower() == col.lower() for _, v in texts):
                    header = {v.strip().lower(): col_index(ref) for ref, v in texts}
                continue
            if texts and texts[0][1].strip().lower() == row_label.lower():
                want = header.get(col.lower())
                for ref, v in cells:
                    if col_index(ref) == want and isinstance(v, float):
                        return v, "%s!%s" % (sheet.strip(), ref)
                return None, "%s!row %d" % (sheet.strip(), rn)
            if any(v.strip().lower() in ("token economics", "rental economics") for _, v in texts) and header is not None:
                break
        return None, None


def read(root, spec, explicit_path=None):
    """spec: assumptions['mastersheet']['cells']. Returns dict of {key: {value, cell}} plus provenance."""
    path = find_workbook(Path(root), explicit_path)
    if path is None:
        return {"found": False, "path": None, "values": {}}
    wb = Workbook(path)
    values = {}
    for key, c in spec.items():
        try:
            if "label" in c:
                v, cell = wb.label_value(c["sheet"], c["label"])
            else:
                v, cell = wb.block_value(c["sheet"], c["block"], c["row_label"], c["col"])
        except KeyError as ex:
            v, cell = None, str(ex)
        values[key] = {"value": v, "cell": cell}
    st = path.stat()
    digest = hashlib.sha1(json.dumps({k: v["value"] for k, v in values.items()}, sort_keys=True).encode()).hexdigest()[:12]
    try:
        rel = os.path.relpath(path, Path(root))
    except ValueError:
        rel = str(path)
    return {
        "found": True,
        "path": rel,
        "modified": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
        "size": st.st_size,
        "fingerprint": digest,
        "values": values,
    }


import json  # noqa: E402  (used in read())

if __name__ == "__main__":
    import sys
    root = Path(__file__).resolve().parent.parent
    a = json.load(open(root / "assumptions.json", encoding="utf-8"))
    r = read(root, a["mastersheet"]["cells"], a["mastersheet"].get("path"))
    print(json.dumps(r, indent=1))
