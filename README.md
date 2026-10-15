# 1 GW of Blackwell: rent the GPUs out, or serve tokens on them?

One dashboard, one command, one assumptions file, in one self-contained folder that can be pushed to a GitHub
repository as it stands. Open **`dashboard.html`** (or `index.html`, the same page under the name GitHub Pages
serves first; double-click either, it works offline from `file://`). Run **`python update.py`** to refresh every
market input and rebuild it. Deploying to GitHub and running the daily update from a routine: see
[Deploying to GitHub](#deploying-to-github) below.

The page has six tabs. **Comparison** puts the six scenarios side by side: the headline cards (A rent
the GPUs out; B and C serve tokens on the Anthropic and OpenAI frontier baskets, with a dial for the share
of capacity given to training; D serve open-weight tokens only, the same fleet with no frontier share at all;
E is D with every model at its published InferenceX benchmark peak, the ceiling if the benchmark were the
whole story; F is "AWS ROIC", B's fleet earned as a landlord: the GPUs B allocates to Anthropic's tokens
rented to Anthropic at the rental scenario's path plus a 25% share of their token revenue, the rest serving
open-weight tokens as in B), the verdict, OpenRouter's closed- vs open-weight share of tokens week by week, the cash-flow charts, every dial, the
returns and sensitivity tables, and the capital and cash-flow block. **B · Anthropic serving** and **C · OpenAI serving** each carry the full workings of
that scenario: its KPIs and verdict, its cash-flow chart, what the fleet sells (frontier vs open-weight
tokens and GPU-hours), the model-by-model table with the excluded or estimated traffic, the cost per task
per model, the task framework and the task types. **Rental market** charts the weekly history of the
Silicon Data and Ornn Blackwell and Hopper rental indices and GetDeploying's weekly medians, every provider's
published rental rate through time (on-demand, spot, capacity blocks, reserved) with the year-1 rate the ROIC uses
and what a GPU-hour earns serving Anthropic's and OpenAI's closed-weight models on the same $/GPU-hour scale, the
closed-weight token prices themselves ($ per million output tokens) by build day, and every price change, announcement, pricing notice and disclosure, against the model's own rates, and below them carries the rental evidence (every basis the rental scenario
can run on, the rate path it uses, every published quote) and the classified list of every public multi-year
AI compute contract with the daily deal scan's review box. **ROIC history** charts and tabulates the ROIC each daily build computed for the four
scenarios, with the key inputs of that day (total cost to build, the model's year-1 and long-term rental
rates, the Silicon Data and Ornn B200 and H100 / H200 indices as references, the implied closed-weight token share
and the closed and open token prices); the same rows are written to `data/roic_history.csv`. **Token
prices** sets Silicon Data's LLM Token Expenditure indices (broad market SDLLMTK, open-weight, proprietary;
usage-weighted dollars per million tokens) against the prices this model serves at (open-weight, closed per
basket, fleet blended), current and by day, with a toggle between the indices' input-plus-output basis and
the dashboard's per-output-token bases. All three history pages grow with every run. The dials live on the comparison tab and drive every page at once;
`#anthropic`, `#openai`, `#market`, `#roic` and `#tokens` deep-link to the pages.

**To keep everything current automatically** on a PC, double-click `schedule_daily_11am.py` once (or, in a
terminal in this folder, `python update.py --schedule --at 11:00`); from a GitHub repository, see
[Deploying to GitHub](#deploying-to-github). The PC route registers a Windows Task
Scheduler task (`BlackwellROIC-daily`; cron on macOS/Linux) that runs the full refresh and rebuild every
day at 11:00 local time with no console window, then runs the first refresh straight away; a start missed
while the PC was asleep or off runs as soon as it is back on and has a network. `python update.py --status`
shows the age of every input and the last build; `update.log` records every run; `--unschedule` removes it.
Python 3.8+ must be installed on the PC (python.org, "Add python.exe to PATH"); nothing else is needed.

**The presentation view.** The `infographic/` subfolder holds `infographic.html`, a six-page presentation of
the same model (its own README explains it). It is built from this folder's engine and inputs, never typed: `update.py` rebuilds it as its last step (`infographic`) right after
`dashboard.html`, so the daily run leaves the two pages in agreement, and the "Presentation view" chip
under this page's header opens it. While both pages are open in the same browser, every dial move on
`dashboard.html` is published (localStorage and a BroadcastChannel) and the presentation view recomputes
itself with those dials within a second; its green strip lists the dials that differ from the defaults
and warns if the two pages were built from different data. Rebuild only ever from this folder
(`python update.py`, or `--only build` then `--only infographic` when offline): a rebuild of one page
from an older copy of the engine is how the two can drift apart.

```
blackwell-roic-tracker/
  dashboard.html        the page. Self-contained; every dial recomputes live in the browser
  index.html            the same page, written by every build, for GitHub Pages
  update.py             the only thing you run (its last step rebuilds infographic/infographic.html too)
  schedule_daily_11am.py  double-click once on a PC: registers the daily 11:00 run and does the first refresh
  assumptions.json      every dial and the task framework, each with a note on where it came from
  AI mastersheet.xlsx   copy of the workbook the fleet size, capital and power come from (assumptions.json
                        mastersheet.path points at it; save a new version over it to update the capital picture)
  .gitignore, .nojekyll keep caches and machine-specific files out of git; serve the folder as-is on GitHub Pages
  ROUTINE_PROMPT.md     the claude.ai cloud routine that runs the daily update and republishes the dashboard artifact
  infographic/          the presentation view: infographic.html and the files that build it (its README)
  tools/                run_cached.py and pull2.py: run update.py from browser-fetched responses where the machine
                        has no direct internet (tools/README.md)
  data/
    openrouter.json     usage by task type, weekly volume by model, every host's price, and per-model
                        effective price / delivered speed / cache-hit / activity stats   (fetched daily)
    openrouter_share.json  OpenRouter's closed- vs open-weight share of tokens: its weekly Top Models chart (53 weeks,
                        accumulating) and a model-by-model classified read of the full weekly ranking each run
    lab_prices.json     Anthropic and OpenAI list prices, any change applied (daily: OpenAI's own pricing page, Anthropic via OpenRouter)
    rental_rates.json   every provider's published quote (on-demand, spot, capacity block, reserved, indices), the log of
                        price changes, pricing notices on vendors' pages, price news, curated price actions, and every
                        public multi-year AI compute contract, classified (quotes refreshed daily; contracts curated)
    deal_candidates.json  announcements the daily deal scan queued for review, with the figures it read  (grows every run)
    throughput.json     InferenceX Pareto curves: output and input tok/s per GPU vs interactivity on GB300/GB200/B300/B200 (fetched daily)
    traces.json         measured agent token volumes per task family and model family (Exgentic agent-llm-traces-v2) (curated, reproducible)
    rate_history.json   daily Silicon Data and Ornn rental indices (B200, H200, H100), GetDeploying weekly medians, Silicon
                        Data token expenditure indices and every provider's rental rate by date (engine/rental_history.py) (grows every run)
    roic_history.csv    one row per build day, AS BUILT: the six ROICs, IRRs and revenues per GPU-hour, the day's key inputs,
                        its assumptions and its market primitives (grows every build)
    roic_history_restated.csv  every build day restated on today's assumptions (rewritten by every build)
    snapshots/          one .json.gz per build day: that day's market inputs, so later assumption changes reach it too
    vendor_throughput.json  vendor-reported Blackwell measurements for unbenchmarked models, shown as cross-checks   (curated, sourced)
    anchors.json        public disclosures the realisation factors can be judged against  (curated, sourced)
    models.json         model registry: which InferenceX name is which model, open/closed, aliases (curated, sourced)
    history.jsonl       one line per build: every scenario's headline numbers             (append-only)
  engine/
    model.py            the arithmetic (prepare + compute); template.html carries its JavaScript twin
    build.py            injects inputs and the Python result into the template, writes dashboard.html
    collect_openrouter.py, collect_or_share.py, collect_labprices.py, collect_inferencex.py, collect_rentals.py, collect_history.py, collect_traces.py, read_mastersheet.py
    net.py              every collector's GET, retried twice when a connection drops before the step keeps its last good data
    collect_deals.py    the daily deal scout (Google News RSS + SEC EDGAR full-text search); tests/test_deals.py runs it offline
    restate.py          puts every history row on one set of assumptions (restateRow() in template.html is its twin);
                        tests/test_restate.py checks it reproduces every as-built row at that row's own assumptions
    deals_seed.py       the research sweep behind the contracts list, one row per deal with its source and classification
    template.html
```

Standard library only, Python 3.8+, no API keys, no pip. Nothing in the folder is a `.bat`, `.sh` or `.exe`
(the only `.js` files are the presentation view's page code, inlined into `infographic.html` at build time), so it
can be zipped and emailed, or pushed to a repository as one unit.

## The question and how it is answered

The same 1 GW site, three uses. **A: rent** every GPU-hour at a market rate. **B: serve** tokens on the
same GPUs with the frontier tokens on Anthropic's models. **C: serve** with the frontier tokens on OpenAI's
models. All three carry the same capital, the same power bill (scaled by utilisation) and the same other
operating cost, all read from `AI mastersheet.xlsx`, so the whole comparison is revenue per GPU-hour.

**Rental has a term structure, checked against two daily indices.** A fleet rented out today earns what
the market charges now, not a five-year contract rate. The year-1 rate (default since 2026-10-12: the average
of every current published GB300 / B300 rate, spot, on-demand and capacity blocks across every provider tracked,
so any provider's price change moves it; a rate is current for 10 days after it was read and drops out when the
vendor stops publishing it; the median of the same rates, the spot median, neocloud or all on-demand quotes, or
the Silicon Data or Ornn B200 index are alternatives, or a typed figure) holds for a chosen number
of years (dial, default 1), then moves linearly to the long-term rate (default: the GPU-weighted median of
disclosed multi-year GB300 contracts) over a chosen number of years (dial, default 3; 0 = a step) and stays
there. The dial prints the resulting rate for every year, and the cash-flow table on the comparison tab
shows, year by year and for every scenario, the rate or revenue per GPU-hour assumed, the utilisation and
the GPU-hours it is applied to. The Silicon
Data B200 rental index (observed rates basis-adjusted across ~80% of the market) and the Ornn B200 Compute
Price Index (volume-weighted transacted rates, settled daily), both Bloomberg-listed, are drawn against the
path and quoted in the rent panel as the market references; no GB200/GB300 index exists, so they are a
level check on an older part, not a GB300 price, and they measure different universes and sit apart (on
2026-09-07, $5.69 and $6.75). IRR uses the whole path; ROIC is the life average
with year 1 shown beside it.

**Demand shape comes from the task framework, volumes from measured agent traces.** Twenty
knowledge-worker tasks are each a weighted mix of OpenRouter's task types. Each task's reasoning-depth
and consequence ratings set the share of its runs that needs frontier intelligence:
`clamp((max(reasoning, consequence) - 2) / 3, 0, 1)`. Six tasks map to a family of 10,057 real agent
sessions (Exgentic agent-llm-traces-v2: SWE-bench, BrowseComp-Plus, AppWorld, tau2-bench) and take their
measured output tokens, input tokens, LLM calls, cacheable share and success rate per run, by model family
(Anthropic, OpenAI, DeepSeek, Kimi, open-weight average), so a coding run on a DeepSeek model and on a
Claude model carry their own volumes and the frontier share of output tokens is an output of the model. The
other tasks keep the framework's per-call shapes. A toggle switches to pooled volumes (one measured volume
per task for every model, which removes provider differences in how reasoning tokens are counted) or to
the framework shapes. The fleet is supply-bound, so only the shape of demand matters, not its size. A
cost-per-task table prices every task on every model at that model's own volume and current price, with
the trace family's success rate.

**Three ways to set the frontier vs open-weight split**, a selector on the comparison tab. *Task framework +
cost dial* (the default) applies the rule above and then lets price pull volume out of the tasks whose need
is partial: the dial is a **frontier premium tolerance** in multiples of the open-weight price (1x to 20x,
far right = no limit = the framework as is). For each task the premium is the basket's price over the task's
routed open-weight mix for the task's own input:output shape, both on the price basis in force and the
frontier at its realised price; while the premium is inside the tolerance the task keeps its framework
share, above it the share becomes framework share x (tolerance / premium)^(1 - framework share), so a task
rated 5 never moves, a 4 moves a third as fast as a 3, and tasks rated 2 or below stay open. The premium is
recomputed per basket from the live prices on every run and every dial move, and the page prints it beside
the dial (on the seed date 8-23x across the substitutable tasks for the Anthropic basket, 10.5x weighted by
their frontier runs; 5-15x and 6.9x for OpenAI) and per task in the demand table, with the framework share
and the share applied. *OpenRouter's share this week* ignores the framework's split and gives both serving
scenarios the closed-weight share of completion tokens in OpenRouter's latest weekly ranking, every closed
lab counted (29.0% for the week of 2 September 2026), keeping the within-tier mixes; it is refreshed with
the OpenRouter feed each run and recorded daily in `roic_history.csv` as a reference whichever mode is in
force. *Manual* sets the frontier share of output tokens per basket with two sliders. The daily record also
carries the mode, the tolerance and each basket's weighted premium.

**Model choice comes from measured usage; two throughput bases, one toggle.** Within each task type the
open-weight runs go to the open models OpenRouter's users route that tag to, in proportion to 30-day
measured token share. Under *benchmarked models only* (the default) a model needs
its own SemiAnalysis InferenceX runs on Blackwell to carry tokens; the traffic of the rest is re-spread
within each task type and the page lists what was excluded and how much traffic it carried. On the seed
date that is most of it: InferenceX covers twelve display models, and the models that dominate
OpenRouter's open-weight traffic (DeepSeek V4 Flash, MiMo, Hy3, GLM 5.3 Flash, Nemotron 3 Ultra) are not
among them. Under *all OpenRouter models, gaps estimated* every routed model carries tokens and a model
without its own benchmark takes, in order, the InferenceX curve of the same architecture under another
name (GLM 5.2/5.3 from GLM 5, Kimi K2.6 from K2.5, MiniMax M2.7 from M2.5, DeepSeek V3.2 from R1), else a
log-log fit of output tokens/s per GPU on active parameters across every benchmarked model at that
model's interactivity; each row is flagged, the fit's slope, n and R² are printed, and any vendor-reported
measurement (NVIDIA's Dynamo figure for Nemotron 3 Ultra, CODEXIS's for V4 Flash) is shown beside the
estimate as a cross-check, not used. Frontier tokens go to the lab's current models (Anthropic: Fable 5.1,
Fable 5, Opus 5, Opus 5.5, Sonnet 5; OpenAI: GPT-6.1 Sol, GPT-6 Sol, GPT-6 Astra, GPT-5.6 Sol, Terra) in proportion to
their measured OpenRouter volume; the small tiers (Haiku, Luna) are outside both baskets. Opus 5.5 joined the Anthropic
basket on 28 September 2026 and the GPT-6 models the OpenAI basket on 15 October 2026; the ROIC history records each
day's basket and tags the change.

**Prices are what the market actually paid this week.** For every model OpenRouter publishes the
traffic-weighted effective price its customers paid per input and output token across all hosts, with
cache hits already inside the input figure, and the same for Anthropic's and OpenAI's own endpoints;
that is the default price basis. The alternative is list price (cheapest host for open weights, the
lab's list for frontier) with cache hits blended at each model's measured rate. The panel "Provider
prices behind each model's token price" on each basket page shows the evidence for both: every host's
list price (input, output, cache read, quantisation, context) beside every provider's effective price
for the trailing week with its share of the week's tokens and delivered speed, and highlights the row the
scenario uses under the basis in force (the traffic-weighted blend under "effective"; the cheapest host,
or the lab's list row, under "list"). The cheapest listing is often a thin one, so the list basis can
sit well below what the week's traffic actually paid; the panel says how much traffic that host carried.

**Throughput is what Blackwell has been measured to do for that model, at the speed real hosts deliver,
scaled to what the market says that model realises.** InferenceX's public API returns every benchmark run
with its own measured input and output tokens/s per GPU (system-wide: every GPU of a disaggregated
deployment counted, and each row checked against its own total). For each model the Pareto frontier of
output tokens/s per GPU against interactivity is taken on GB300 directly, or on GB200/B300/B200 and scaled
by the GB300 ratio measured on the models that have both. Each curve is read at the output speed
OpenRouter measures that model's hosts actually delivering. Input is billed at the input:output ratio of
the same run, so throughput and billing describe the same request. Benchmarks use random data with
caching off and are peak points, so every model carries its own realisation factor: what a host renting
the GPU at the year-1 rental rate needs its GPU-hour to earn, that rate plus the renter's return (10%
by default, a dial), divided by what that GPU-hour would earn at the model's benchmark peak and its own
market price, capped at one. That is the condition of a competitive open-weight token market served on
rented GPUs, and it means every benchmarked open model earns the year-1 rate plus that return per GPU-hour
by construction; the model's job is then to say what the frontier tokens earn on top. The rate the factor
is built on can be switched to the spot median or the rental scenario's long-term basis. The frontier basket, which no lab benchmarks, borrows the largest measured open
model's curve at a stated derate and that model's realisation factor (the one proxy in the model, labelled
wherever it appears). `data/anchors.json` holds the public evidence to judge the factors against.

**Returns.** EBITDA = revenue − power − other opex. Depreciation is straight-line in two pools, each with
its own dial: compute (GPUs + racks, the mastersheet's rack cost × racks, $28.6B since the 24 September mastersheet; $26.4B before) over a compute life to a
residual, and the powered shell / mechanical / electrical ($16.2B) over a shell life. ROIC = (average annual
EBITDA over the horizon − average annual depreciation over the horizon) / capital, pre-tax. IRR on −capital,
then the horizon's years of EBITDA, plus whatever book value is still standing at the end of the horizon as a
terminal inflow (assets recovered at book; it is in IRR, not in ROIC). The defaults — 5-year horizon, 5-year
GPU/compute life, 20-year shell life, no residual — are the dashboard's own assumption (set 24 September 2026;
the builds before that had the shell on 5 years; the ROIC history page restates every day on today's
assumptions, see "Restating the history" below): the
mastersheet carries no depreciation life. For reference, hyperscalers depreciate servers over 5–6 years (Amazon
5 for its newer fleet since 2025, Microsoft and Alphabet 6, Meta 5.5; CoreWeave 6) and data-centre shells over
20–30 years with electrical and mechanical plant at 10–20. On a 20-year shell life a quarter of the shell
($4.05B) is depreciated inside the 5-year horizon and the remaining $12.15B is recovered as terminal value in
the IRRs. The horizon, both lives, the compute residual, the average
depreciation and the terminal value are recorded in `roic_history.csv`.

**Restating the history (28 September 2026, at Lev's request).** `data/roic_history.csv` keeps every day
exactly as its build computed it. The ROIC history page shows either that as-built record or every day
restated on one set of assumptions - by default today's `assumptions.json` and today's mastersheet - with
dials on the page to restate on any other set; `data/roic_history_restated.csv` holds the restatement at
today's assumptions and every build rewrites it, so changing an assumption restates the whole history
automatically. `engine/restate.py` splits each day into its market primitives (spot and long-term rental
rates; each serving scenario's revenue per serving GPU-hour at 100% token utilisation; F's Anthropic block
share of GPUs and the revenue per GPU-hour of its two sides) and the separable assumptions that act on them
linearly (fleet and capital, training share, utilisations, AWS revenue share, power price, other opex,
horizon, lives, residuals, rental term structure, price declines). Restating a day at its own as-built
assumptions reproduces every as-built ROIC, year-1 ROIC, IRR and revenue per GPU-hour
(`engine/tests/test_restate.py`), and 23 September's market data restated on 24 September's assumptions
reproduces what the full model computed on 24 September for all six scenarios. Assumptions of the market
model itself (baskets, split mode, premium tolerance, renter's ROIC, throughput and volume bases, rental
bases, the task framework, the model registry) need the day's full market inputs: from 28 September each
build saves them to `data/snapshots/<date>.json.gz` and every build re-runs the full model on every saved
day under today's assumptions. Days built before snapshots existed keep their as-built market model and are
tagged "not fully comparable" where one of those assumptions has since changed (today: 22-24 September,
built before Opus 5.5 joined the Anthropic basket; a basket model that launched after a day's OpenRouter
read carries no weight that day, so earlier days are unaffected). F did not exist before 15 September; for
8-14 September it is derived from B's frontier/open split that day, which reproduces the built F on
15-28 September to within 0.02 points. D starts on 9 September and E on 14 September, as built. Not modelled: demand at these
prices, price response to a 1 GW supply shock, training compute, sales cost, tax, financing, the ramp.

## Running it

```
python update.py                   # fetch everything, rebuild, append history
python update.py --offline         # rebuild from what is on disk (after editing assumptions.json)
python update.py --status          # how old is each input
python update.py --schedule        # daily at 07:30 via Task Scheduler (Windows) or cron; --at HH:MM; --unschedule
```

The daily run fetches OpenRouter's four ranking/catalogue/price feeds plus the three per-model stats feeds
behind every model page (effective pricing, delivered throughput, activity; all public JSON, CC BY 4.0),
checks the lab list prices against OpenRouter's lab endpoint rows (Anthropic rows are overwritten on a
change; OpenAI rows are logged, because OpenRouter's OpenAI standard tier has disagreed with OpenAI's own
pages), reads InferenceX's OpenAPI document for the list of accepted models and pulls every benchmark run
for each mapped model, refreshes every provider's published rental quotes (Oracle, Azure and Vultr price
APIs, AWS's Spot feed; CoreWeave, Nebius, Lambda, Verda, Together, Hyperbolic, AWS Capacity Blocks and Google
pages parsed label-then-price, a dated second price column or a dated announcement on the page handled as an
announced price that takes over on its date; Silicon Data, Ornn and GetDeploying indices), logs every price
change, records pricing notices on the vendors' pages and scans the news for provider price moves, appends the
rate history (the seven daily values each Silicon Data chart page carries, and every provider rate just read, into
`data/rate_history.json`, so a run at least weekly keeps the daily index series unbroken), runs the deal
scout (below), re-reads `AI mastersheet.xlsx` (the copy in this folder), and rebuilds the page. A step that fails keeps the old data and its date; the header chips
turn amber past seven days. `update.log` records every run, including any model InferenceX has added that
`data/models.json` does not yet map.

Disclosed contracts, the model registry and the realisation anchors change when something is published,
not daily, so they are curated by hand in `data/` with a URL and read date on every row. The **deal scout**
(`engine/collect_deals.py`, step `deals`) keeps the contracts list from going stale: every run it reads three
Google News RSS searches for the last seven days (GPU / AI-cloud / data-centre-lease agreements with a
dollar figure) and, once `deals.sec_user_agent` in `assumptions.json` carries your name and a contact email
(the SEC requires every automated EDGAR client to identify itself; the pass is skipped while it is blank),
SEC EDGAR's full-text search of the week's 8-K and 6-K filings for GPU / AI-cloud / compute-capacity
agreements, fetching each hit's press-release exhibit. A headline or filing is queued when it names an
agreement, is about compute and carries a figure, and is not a stock, financing or acquisition story; the
scout reads the value, term, GPU count, MW, chip and the companies named, collapses the write-ups of one
announcement, and marks the listed contract it probably describes. The queue (`data/deal_candidates.json`,
kept 90 days) is shown at the top of the contracts panel; nothing in it touches the model. A confirmed deal
is added to `data/rental_rates.json` `contracts` with its classification (kind, value, term, GPUs, chip, MW,
source quality, status), after which `update.py` recomputes the medians; set a candidate's `status` to
`added` or `dismissed` to clear it from the page.

## Deploying to GitHub

This folder is the repository. Everything the page, the daily update and the history need is inside it, every path
between files is relative, and no machine's path is written into either page, so it can be pushed as it stands.

**First push.** Create an empty repository on GitHub (no README or licence, so nothing conflicts), then in a terminal
in this folder:

```
git init -b main
git add .
git commit -m "Blackwell ROIC tracker"
git remote add origin https://github.com/<account>/<repository>.git
git push -u origin main
```

(Uploading through the GitHub website also works, but drag-and-drop can drop the two hidden files `.gitignore` and
`.nojekyll`; add them afterwards if so.)

**Viewing the page from the repository.** Settings > Pages > "Deploy from a branch", branch `main`, folder `/ (root)`.
The dashboard is then served at `https://<account>.github.io/<repository>/` (that is `index.html`; `dashboard.html`
is the same page) and the presentation view at `.../infographic/infographic.html`, with the links between them
working. On GitHub's free plan Pages only serves public repositories, and a public repository publishes the data
files too; a private repository needs a paid plan for Pages, or open the HTML files from a local clone instead.

**The daily update from your routine.** Nothing in this folder runs on GitHub (there is no Actions workflow). The
routine that runs the update needs Python 3.8+, git, push access to the repository and an internet connection
that reaches the hosts listed below. Each run:

```
git clone https://github.com/<account>/<repository>.git    # or: git pull, in a clone kept between runs
cd <repository>
python update.py --scheduled
git add -A
git commit -m "Daily update"
git push
```

For this repository that routine is a claude.ai cloud routine, "AI Dashboard daily update", which does the above
every morning (Sydney time), pushes to `main` and republishes `dashboard.html` to a private claude.ai artifact.
`ROUTINE_PROMPT.md` holds its schedule and the exact instructions it runs.

A run rewrites `dashboard.html`, `index.html`, `infographic/infographic.html`, `update.log` and the files in
`data/`, and adds the day's market snapshot `data/snapshots/<date>.json.gz`. Commit all of it: `data/history.jsonl`
and `data/roic_history.csv` are the append-only record of every build, `data/rate_history.json` and
`data/openrouter_share.json` accumulate series the sources only serve for a trailing window, and the snapshots are
what lets a later change of assumptions restate the past days. The repository is about 7 MB today and grows by
roughly 0.3 MB a day compressed, mostly the rebuilt pages. When the clock of the machine running the update is on
UTC (most cloud runners), `update.py` dates the daily record on Sydney time, as on the PC. A second run on the same
day replaces that day's row rather than adding one.

Hosts the update reads (allow them if the routine's network is restricted): `openrouter.ai`,
`inferencex.semianalysis.com`, `portal.silicondata.com`, `www.silicondata.com`, `api.ornnai.com`, `data.ornn.com`,
`getdeploying.com`, `news.google.com`, `prices.azure.com`, `azure.microsoft.com`, `website.spot.ec2.aws.a2z.com`,
`aws.amazon.com`, `apexapps.oracle.com`, `cloud.google.com`, `www.coreweave.com`, `nebius.com`, `lambda.ai`,
`verda.com`, `www.together.ai`, `www.hyperbolic.ai`, `api.vultr.com`, `www.vultr.com`, `developers.openai.com`, and
`efts.sec.gov` / `www.sec.gov` only if `deals.sec_user_agent` is set. A dropped connection (a reset, a TLS stream cut
off, a 429 or 50x) is retried twice a few seconds apart; a step that still cannot reach its host keeps the last good data
and `update.log` ends with `failed: <step>`: check that line after the routine's first run. (The scheduled runs
inside the desktop's sandbox on 8, 10 and 13 Oct 2026 reached none of these hosts, through a proxy that refused
them, so those days carried the previous readings; `tools/README.md` describes the browser-fed fallback used
since.) If you set `deals.sec_user_agent` (your name and email, for SEC EDGAR), it is committed with
`assumptions.json`, so it is public in a public repository.

## Where every number comes from

| Input | Source | Refresh |
| --- | --- | --- |
| Fleet size, capital, kW/GPU, PUE, $/MWh, utilisation, other opex | `AI mastersheet.xlsx`, sheets `GB300 ` and `ROIC Dashboard`, by cell label | every build |
| Which open model carries which task type | OpenRouter `rankings/task-spend` (30-day, by tokens) | daily |
| Frontier basket weights | OpenRouter `rankings/models` (weekly) | daily |
| Open vs closed weights | OpenRouter `catalog/models` (published HF repo) + `data/models.json` | daily |
| Closed- vs open-weight share of OpenRouter tokens | OpenRouter `rankings/model-rankings-chart` (weekly Top Models chart: 53 weeks of named top models plus an unsplit 'Others') and `rankings/models?view=week` (every model, trailing seven days), classified as above | daily, accumulating |
| Open-weight prices, every host | OpenRouter `models/<slug>/endpoints` | daily |
| Frontier prices | OpenAI: its API pricing page, Standard tier (developers.openai.com/api/docs/pricing). Anthropic: the Anthropic pricing page's list price as carried by OpenRouter's 'Anthropic' endpoint rows. Any change is applied the day it is read; a move of more than 3x in one read is kept and logged as a likely misread | daily |
| Rental quotes, every provider and tier | vendor pages and price APIs (URL per row): CoreWeave, Nebius, Lambda, Verda, Together AI, Hyperbolic, Vultr (plan API), Oracle (price-list API), Azure (Retail Prices API incl. Spot meters), AWS (Capacity Blocks page, public EC2 Spot feed), Google (Spot VM page) | daily where machine-readable |
| Price changes, announcements, notices | the daily read (change log), dated columns and announcements on vendors' pages, a notice scan of the same pages, Google News (headlines, unverified), and a curated list of disclosures with sources (`data/rental_rates.json`) | daily; disclosures curated |
| Contract rates | every public multi-year AI compute contract Jan 2025 - Sep 2026 (URL, source quality and classification per row); $/GPU-hr = value / (term x 8,760 x GPUs) where all three are disclosed, per-MW rates likewise | curated; new announcements queued daily by the deal scout |
| New contract announcements | Google News RSS (three searches, last 7 days) and SEC EDGAR full-text search of 8-K / 6-K exhibits (needs `deals.sec_user_agent`) | daily, for review |
| Effective token prices, cache-hit rates, delivered tok/s per user, in:out and cached shares | OpenRouter per-model stats feeds (effective-pricing, throughput-comparison, model-activity) | daily |
| Output and input tok/s per GPU vs interactivity on GB300 / GB200 / B300 / B200 | SemiAnalysis InferenceX API, every run, Pareto frontier per model (Apache-2.0) | daily |
| Realisation anchors (DeepSeek fleet disclosure, Z.ai / MiniMax margins) | `data/anchors.json` (URL per row) | curated |
| Parameter counts (shown; used only by the fit under "gaps estimated") | Hugging Face model cards (URL per model) | curated |
| Token volumes, calls, cacheable share and success per task family and model family | Exgentic agent-llm-traces-v2 on Hugging Face, aggregated with the DuckDB query in `engine/collect_traces.py` | curated, reproducible |
| Silicon Data rental indices (B200, H200, H100 neo-cloud and hyperscaler), daily history | portal.silicondata.com public chart page per index (last seven daily values per read); older points from Silicon Data's monthly index posts | daily, accumulating |
| Ornn Compute Price Index (B200, H200, H100 SXM), daily history | api.ornnai.com public keyless API (trailing three months per read; volume-weighted transacted rates, settled daily 20:00 UTC, Bloomberg-listed) | daily, accumulating |
| Silicon Data LLM Token Expenditure indices (broad SDLLMTK, open-weight, proprietary), daily history | portal.silicondata.com public chart page per series (last seven daily values per read); usage-weighted $ per M tokens, input/output blended at the observed mix | daily, accumulating |
| Provider rental rate history (every quote above) | each run's readings by read date, backfilled from 3 Sep 2026 from the project's own records; documented price changes at their effective dates | daily, accumulating |
| GetDeploying weekly medians across providers (B300, B200 on-demand and spot; GB200 on-demand) | getdeploying.com public price dataset (CC-BY-4.0) | weekly, from Nov 2025 |

## Verification

`build.py` embeds the Python result in the page; on load the page recomputes from the same inputs in
JavaScript and prints the worst relative gap across all six scenarios (it should read `0.0e+0` or
float noise). `python engine/tests/test_rental_history.py` checks that today's year-1 rate from `data/rental_rates.json` equals the one rebuilt from the rate history, the rate-in-force rule, and that every list-price change is logged. `python engine/tests/test_deals.py` exercises the deal scout offline against feed samples
captured on 2026-09-09. `python engine/tests/test_labprices.py` reads OpenAI's Standard tier from a 2026-10-14 sample of its
pricing page and checks that a moved list price is applied, a 10x jump is kept as a misread and an unreadable page keeps every price. If the two ever disagree the page says so in red.

## What changed on 13 Oct 2026: median rental rate, token lines, OpenRouter share, one folder

Lev asked for four things, done as follows.

**The year-1 rental rate is the median, not the mean,** of every current published GB300 / B300 rate (spot,
on-demand and capacity blocks, every provider: 11 rates from 6 providers today, median $9.52 against a mean of
$10.26). It feeds scenario A's year-1 rate and, with the renter's 10% on top, what every open-weight GPU-hour is made
to earn, so every scenario except E moves with it: today A 20.0% (22.0% on the mean), B 39.5% (43.8%), C 26.1%
(29.3%), D 45.4% (50.0%), F 53.1% (57.9%), E unchanged at 89.7%. The ROIC history restates on it (the year-1 rate on
every past day is the median of the rates in force that day). The mean stays one click away in the dials.

**Rental market page: the closed-weight token lines.** The provider rental chart carries two thick dash-dot lines on
the same $/GPU-hour scale: what a GPU-hour earns serving Anthropic's (scenario B) and OpenAI's (scenario C)
closed-weight basket at market token prices, per busy hour like a rental rate (data/roic_history.csv
`frontier_rev_gpu_hr_anthropic` / `_openai`, new as-built columns, backfilled for earlier rows from
data/history.jsonl; restated in data/roic_history_restated.csv). Below it, a new chart of the token prices themselves:
each basket's all-in and output-only price per million output tokens by build day, with the open-weight price for
contrast and markers where a basket's models changed. On every day the values are on today's assumptions: from 28 Sep
re-run on the day's market snapshot; before that as built, the per-GPU-hour lines scaled with the open-weight GPU-hour
target exactly as the serving revenues are. The per-GPU-hour line is price x the tokens a GPU delivers, and that
throughput is the benchmark scaled by the realisation the reference open model needs to earn the GPU-hour target,
so the line also moves with the rental rate and against the reference model's price; the note under the price
chart says so.

**Comparison page: OpenRouter's closed- vs open-weight share of tokens, week by week.** New collector step
`orshare` (engine/collect_or_share.py -> data/openrouter_share.json) reads OpenRouter's weekly Top Models chart (53
weeks from 13 Oct 2025, all tokens; named models classified by published weights, 'Others' unsplit, so each week's
closed share is a range) and classifies every model in the full weekly ranking (the complete split on each read).
Backfilled with the reads the project kept: the 4 Sep archive (top 76 models) and the daily snapshots from 28 Sep (top
250), classified with today's catalog. Corrected on the way: the model counted any open-weight model it did not map
as closed when the catalog carried an hf_slug instead of the legacy "(published)" flag, and the collector only
catalogued the top 80 rows, so OpenRouter's closed share of output tokens read 58-68% from 28 Sep to 12 Oct where the
corrected figure is 39-54% (today 37.1% of output tokens, 34.7% of all tokens). The as-built readings of 17-24 Sep
(41-43%) carried the same error and cannot be recomputed, because no copy of those days' ranking was kept; the as-built
column `or_closed_share_week` in data/roic_history.csv keeps what each day's build computed. The share is only
used by the 'openrouter' split mode, which is not the default, so no ROIC moved.

**One self-contained folder for GitHub** (this one, `blackwell-roic-tracker`): the presentation view moved into
`infographic/` with its links made relative to this folder, a copy of `AI mastersheet.xlsx` sits here and
`assumptions.json` points at it, every build also writes `index.html`, and `.gitignore`, `.nojekyll` and `tools/`
were added. The update does not run on GitHub; see [Deploying to GitHub](#deploying-to-github) for the routine.

## What changed on 12 Oct 2026: rental rates, provider by provider

Lev asked for accurate current and historical rental rates for every provider, for any vendor's price update
to be visible, and for every rental rate change to reach the ROIC. Done as follows. `data/rate_history.json`
now keeps one series per published quote (every vendor, chip and tier), backfilled from 3 Sep 2026 from the
project's own records (archived data files of 3, 4 and 8 Sep, update.log, snapshots), with documented price
changes at their effective dates (AWS Capacity Blocks 1 Jul and 7 Oct, Nebius 1 Oct) and the end of Nebius's
preemptible rate (23 Sep). Corrected: Nebius's on-demand rows read the old column after its dated 1 Oct column
came into force (B300 $7.85 -> $9.50, B200 $7.15 -> $8.50; readings of 1-12 Oct corrected, audit kept). Added:
Together AI B300 and B200, Vultr B200 (plan API), Lambda B200 1-Click Cluster, Hyperbolic refreshed, GetDeploying's
weekly aggregator medians. The collector now logs every price change, reads dated price columns and dated
announcements, records pricing notices on vendors' pages and scans the news; the rental market page shows all
of it (provider chart and table, price changes table). The year-1 rental rate became the average of every current
GB300 / B300 rate (spot, on-demand, capacity blocks; Lev's choice; the median since 13 Oct), and it is also what an open-weight GPU-hour is
made to earn (implied_rate 'near'), so every scenario but E moves with rental prices. The ROIC history restates
on it: each snapshot day's quotes are rebuilt from the corrected history; days before 28 Sep get the year-1 rate
from the history and their serving revenues scaled with the open-weight GPU-hour target.

## What changed in v4

**Training share and scenario F, AWS ROIC** (15 September): a dial gives a share of the fleet's capacity
to training in the token-selling scenarios B and C (default 50% since 24 September 2026; 0% before); token revenue falls linearly with it (the serving fleet
is the remainder), power does not. Scenario F takes B's fleet with 0% training and monetises it the way a
hyperscaler landlord does: the GPUs B allocates to Anthropic's frontier tokens (64% of the fleet on the seed
date, because frontier tokens are slow per GPU) are rented to Anthropic at the rental scenario's rate path
times rental utilisation, the owner keeps a dial-set share (default 25%) of the Anthropic token revenue
those GPUs generate at B's realisation, and the remaining GPUs serve open-weight tokens as in B; power and
other opex as in B. On the seed date that is $4.28 per GPU-hour ($1.76 rent + $1.31 token share + $1.21
open-weight), ROIC 12.2%, IRR 19.1%, against B's $6.46 and 30.6% and rent's $2.76 and −0.8%. The cash-flow
table shows the block, the rent, the token revenue and the share year by year; F is in the charts, the ROIC
history page and `roic_history.csv` (with the share and the training setting). A dedicated take-or-pay
block would bill 100% of its GPU-hours rather than the rental utilisation; the card states which is used.

**Scenario E, the benchmark ceiling** (14 September): a fifth card, D re-run with every open model at its
published InferenceX peak throughput (realisation factor 100% instead of the market-implied per-model
factors), same mix, prices and token utilisation. It answers "how high would the returns be if InferenceX
were the whole story": on the seed date $12.76 per GPU-hour (3.8x scenario D) and 84% ROIC against D's
4%. It is a ceiling by construction — InferenceX runs random data with prefix caching off, saturating
load and a single request shape, and says so — and the market-implied factors (18–36% for the routed open
models) are what reconcile that ceiling with what open-weight tokens actually sell for. E is in the
cash-flow charts, the returns chart, the cash-flow table, the ROIC history page and `roic_history.csv`.

**Depreciation in two pools with dials** (14 September): compute (GPUs + racks) and shell / mechanical /
electrical each get their own straight-line life, the compute pool a residual, and the cash-flow horizon is
its own dial; book value left at the end of the horizon returns as a terminal inflow in the IRR. The capital
table and the cash-flow table show each pool's charge, the average used in ROIC and the terminal value.
Defaults reproduce the previous single 5-year line; see "Returns" above for the benchmarks.

**Rental rates and utilisation made explicit** (14 September): the cash-flow table on the comparison tab
now states, for every year of every scenario, the rental rate assumed (and whether it is the spot year, a
convergence year or the long-term rate), the utilisation, the GPU-hours it applies to and the revenue that
follows; for the token scenarios the revenue per serving GPU-hour and the fleet-average figure beside it.
The near-term (spot) rate now holds for a chosen number of years before converging (a new dial beside the
convergence dial, default 1 year, so the default path is unchanged), the dial prints the year-by-year path,
and utilisation is now two separate 0-100% dials: **Rental utilisation** (scenario A only) and **Token
utilisation** (B, C and D only, scaling token revenue and power linearly; read relative to the marginal
competitive host, whose own load the market-implied realisation factor already carries). Hyperscaler spot prices join the spot median where they
are published: AWS's EC2 Spot price for p6-b300 ($5.59/GPU-hr, us-east-1, from AWS's public spot feed) is
in the GB300/B300 median (now $4.31, from $4.30); AWS p6-b200 Spot ($5.26) and Google Cloud's A4 Spot VM
($4.95, B200) join the spot history chart; Azure's GB200 Spot meter is recorded but currently equals
pay-as-you-go ($27.04) in every region, and Oracle has no preemptible bare-metal GPU shapes.

**The split selector replaces the cost filter** (14 September): the old cap on open-weight output price,
which only re-ordered models inside the open tier, is gone; in its place the comparison tab has a three-way
selector for how the frontier vs open-weight split is set (task framework + a frontier-premium-tolerance
dial in multiples of the open-weight price; OpenRouter's measured closed-weight share this week; manual
sliders), described under "Three ways to set the split" above. The default (framework, no tolerance set)
reproduces the previous numbers exactly. `prepare()` now computes OpenRouter's weekly closed share from the
ranking rows (registry flag where a model is mapped, catalog published-weights flag otherwise), the routing
is one volume-independent pass per task reused by every scenario (scenario D now routes every task's runs
to open weights rather than re-normalising the framework's open mix), and the demand table on each scenario
page shows each task's reasoning / consequence ratings, its frontier premium and the share applied.

**Scenario D, open-weight only**: a fourth box on the comparison tab (and a fourth cash-flow chart, a
fourth line on the returns chart, columns in the ROIC history and `roic_history.csv`) for the same fleet
serving only open-weight tokens: the open-weight mix of the Anthropic basket's task framework at the
market-implied realisation, no frontier share. At the seed values it earns $3.31 per GPU-hour, ROIC 4.1%
and IRR 6.5%, between renting ($2.76, -0.9%) and the OpenAI-basket serve ($4.33, 12.7%).

**The contracts list is now the full public record**: 108 multi-year AI compute contracts from January
2025 to September 2026 found in a two-pass research sweep (`engine/deals_seed.py` holds every row with its
URL, source quality, status and classification), grouped on the page into neocloud GPU rentals, cloud
compute commitments (a lab committing spend to a hyperscaler), data-centre and powered-shell leases, and
backstops / references / stated ACV. Only GPU-rental rows with a disclosed value, term (3+ years) and GPU
count on GB300 / B300, active and not cancellable, enter the long-term **contract** basis, now the
GPU-weighted median ($2.88 per GPU-hour: Nebius-Microsoft, Nscale-Microsoft Narvik, IREN-Microsoft, Sharon
AI, HIVE, Axe Compute and the SemiAnalysis reference, so the 100,000-GPU deals set the level; the simple
median is $3.96) with a new **per-MW** basis ($3.25) from the deals disclosed as value / term / MW converted
at this fleet's density. The rows behind both bases are tabulated above the full list, on the rental market page. Under the previous
five-row list the contract rate was $3.08. Single-source rows (Bloomberg-only figures, assumed terms) are
marked and kept out of the medians.

**A daily deal scout** (`engine/collect_deals.py`, step `deals` of `update.py`) scans Google News RSS and
SEC EDGAR full-text search for newly announced multi-year GPU / AI-compute contracts and queues them, with
the figures it read, in `data/deal_candidates.json` and at the top of the contracts panel on the rental
market page for review;
nothing enters the model until a row is added to `data/rental_rates.json`. The first scan (2-9 September
2026) queued eight items, five of them write-ups of contracts already listed (Crusoe-Jane Street, Nscale-
Figure, Firmus-OpenAI, the $35B Anthropic deal) and three for review. The EDGAR pass needs
`deals.sec_user_agent` in `assumptions.json`.

A **Token prices** page: Silicon Data's three LLM Token Expenditure indices (collected daily from the
public chart pages, seven values per read) charted and tabulated against the dashboard's own open-weight,
closed (per basket) and fleet-blended prices by build day, on the indices' basis (dollars per million
tokens counting input and output: the all-in price per million output tokens divided by the tokens billed
per output token at each model's InferenceX ratio) or on the per-output-token bases; the indices and the
dashboard prices are added to `roic_history.csv` each build. On the seed date the dashboard's open-weight
price ($0.29 per M tokens) sits at about half Silicon Data's open index ($0.54), its closed price on the
Anthropic basket ($3.35) at 1.8x the proprietary index ($1.86), and its fleet blend ($1.12) at 1.1x the
broad index ($0.98).

A **ROIC history** page and `data/roic_history.csv`: every build writes one row for its calendar day (a
later build the same day replaces it) with the six ROICs, IRRs and revenues per GPU-hour at the default
dials and the inputs behind them: total cost to build, the model's spot and long-term rental rates, the
Silicon Data and Ornn B200 (Blackwell) and H100 / H200 (Hopper) indices as references, the implied closed-weight
share of output tokens and the closed and open token prices per basket (all-in per million output tokens,
output-only alongside), plus the open-weight GPU-hour target and the data dates. The page charts ROIC,
IRR or revenue per GPU-hour by build day and tabulates every row, newest first. The record starts on
2026-09-08, when the realisation basis changed; earlier builds stay in `data/history.jsonl`. The
scheduler now writes a Task Scheduler XML definition (missed starts run when the PC is next awake, no
console window, waits for a network) and the scheduled run skips the "Press Enter" prompt.

A **Rental market** page (v4 "Market history"): the weekly history of the Silicon Data and Ornn Blackwell (B200) and Hopper (H100,
H200) rental indices and of every published spot Blackwell rate, one interactive chart each, with the model's
year-1 and long-term rates and the open-weight GPU-hour target drawn as reference lines; a weekly / every-
reading toggle, hover on every point, click-to-hide legends, and a table of latest value and 1- and 4-week
changes. Both series grow on every run of `update.py` (`data/rate_history.json`); the Silicon Data series
is seeded with the seven daily values the public chart pages carried on 2026-09-08 and the dated values
Silicon Data stated in its own monthly index posts (hollow markers).

The market-implied realisation is now built on the **published spot rate plus a renter's return**: each
open model's factor makes a GPU-hour serving it earn what a host renting that GPU at spot needs to clear a
10% return on the rent (dial, 0–50%; the rate can be switched to the rental scenario's near-term or
long-term basis). At the seed values that is $4.30 × 1.10 = $4.74 per open-weight GPU-hour against the
$3.08 long-term contract rate the factor used before, so serving returns rise for both baskets.

The OpenAI scenario has its own page with the same workings as the Anthropic one (see the tabs
above); the frontier-share overlay has a separate slider for each serving scenario.

Three labelled cash-flow charts sit under the verdict, one per scenario: the year-0 capital outlay,
then revenue, the power and other-opex stack and EBITDA for each year, the depreciation line that EBITDA
must clear to return capital, the cumulative cash line with the payback crossing, and a hover bridge per
year (revenue → EBITDA → year ROIC). The cash-flow table in the capital panel carries the same rows.

A throughput-basis toggle: benchmarked models only, or every OpenRouter-routed model with gaps estimated
from a same-architecture curve or a parameter fit, every estimate flagged and vendor measurements shown as
cross-checks; measured agent-trace volumes per task per model family, with a pooled and a framework
alternative, and a cost-per-task-per-model table with success rates; and the Silicon Data B200 index drawn
against the rental path and offered as a near-term basis.

## What changed in v3

Rental now follows a term structure (spot today, converging to the contract rate) instead of one flat
rate; only models InferenceX has benchmarked under their own name enter the mix, with GB300 rates implied
from other Blackwell parts by the measured chip ratio where needed, and the family-curve and
parameter-count proxies are gone; throughput curves carry each run's own measured output and input rates
per GPU rather than a share of the total, and input is billed at that ratio; the throughput realisation
factor is market-implied per model instead of one median for all; and a third scenario serves the same
open-weight side with OpenAI's models and prices.
