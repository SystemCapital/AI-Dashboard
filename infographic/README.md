# 1 GW of Blackwell: the presentation view

Open **`infographic.html`** (double-click; it works offline from `file://`). Six pages, switched with the tabs at
the top, the four buttons on the first page, the arrows at the foot of every page, or the keyboard (← →):

1. **The build**: a stylised 1 GW site with the five cost areas numbered (GPUs, DDR5 system memory, CPUs,
   other rack hardware, powered shell / mechanical / electrical), the $ total, and the four scenario buttons.
2. **A · Rent**: ROIC and IRR of renting every GPU-hour out, with six linked driver boxes.
3. **B · Serve Lab**: ROIC and IRR of the Anthropic token-serving scenario, seven driver boxes.
4. **D · Serve Open Weight**: the open-weight-only scenario, five driver boxes.
5. **F · Serve AWS**: the AWS-as-landlord scenario (rent the Anthropic block plus a token revenue share, serve
   open-weight tokens on the rest), eight driver boxes.
6. **Summary**: the four scenarios side by side (returns, per-GPU-hour economics, cumulative cash flow, the
   market-versus-assumption mix) and one table with every number.

Every driver box carries a badge: **green = market data**, **red = assumption**, **grey = fixed constant**.
Clicking any box opens a panel with the numerical sources behind it (quotes, contracts, list prices, benchmark
runs, index readings, mastersheet cells), each with its read date and a link. Assumption boxes open a note saying
where the assumption comes from and what market cross-check exists.

## It follows the full model's dials, live

Open `../dashboard.html` (the full model, one folder up) in another window (the "Presentation view" chip on its header opens this
page) and move any dial: this page recomputes every scenario and redraws within a second. The green strip under
the header says which dials differ from their defaults (e.g. "Rental utilisation 80% -> 60%"); **Show defaults**
puts the page back on the default settings until the next dial move. The link is one-way (full model -> this page)
and works while both pages are open in the same browser; the last dial settings are also remembered, so reopening
this page picks them up. If the strip warns that the two pages were built from different data, run `update.py`
so both share the same inputs. Chrome and Edge share the link between two local files; Firefox keeps local files
in separate compartments and will not.

## Where the numbers come from

Nothing is typed into this folder. `build_infographic.py` imports the model's engine one folder up
(`../engine`), runs its `prepare()` (every market input resolved once, with provenance) and embeds that
block, reads the five capital cost areas from the same `AI mastersheet.xlsx` (the copy in the project folder), and lifts
the JavaScript twin of the model verbatim out of `../engine/template.html`. `assemble.js` turns one run of that model into the
boxes, ladders and source panels; `app.js` draws them. At default dials the page checks its own arithmetic against
the Python builder's result and says so in the footer.

Scenario letters match the full model: A rent, B Anthropic serving, D open-weight only, F AWS. C (OpenAI basket)
and E (open-weight at benchmark peak) are only mentioned in the summary footnote; they stay on the full dashboard.

## Keeping it current

`../update.py` runs this build as its last step (`infographic`), so the daily refresh rebuilds both pages from the
same inputs and they can never disagree. To rebuild by hand, from the project folder:

    python update.py --only infographic
    python infographic/build_infographic.py

Standard library only, Python 3.8+.

```
infographic/
  infographic.html      the page (self-contained, rebuilt by the script; recomputes itself when dials move)
  build_infographic.py  reads the model one folder up and writes infographic.html
  template.html         page skeleton and styles
  assemble.js           one model run -> the boxes, ladders, streams and source panels
  app.js                the rendering code and the live link (inlined into the page at build time)
```
