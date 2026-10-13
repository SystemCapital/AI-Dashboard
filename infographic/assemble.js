/* Turns one run of the engine (compute(INPUTS, dials)) into the DATA block the page renders: the five cost areas,
   the four scenarios with their driver boxes, and the source panels. A JavaScript port of what build_infographic.py
   used to assemble in Python, so the page can redo it whenever the full model's dials move. */
function assembleData(I, R, dials, X) {
  const HOURS = 8760, SECONDS = 365 * 24 * 3600;
  const F = I.fleet, P = F.provenance, gpus = F.gpus, racks = F.racks, capex = F.capex_usd;
  const n0 = v => Math.round(v).toLocaleString("en-US");
  const f2 = v => (+v).toFixed(2), f1 = v => (+v).toFixed(1), f0 = v => (+v).toFixed(0);
  const pc = (v, d) => (100 * v).toFixed(d === undefined ? 1 : d) + "%";
  const r0 = v => Math.round(100 * v);
  const B1 = v => (v / 1e9).toFixed(1) + "B", B2 = v => (v / 1e9).toFixed(2) + "B";
  const cellOf = k => (P[k] && P[k].cell) || null;
  const xv = k => X[k].value, xc = k => X[k].cell;

  // --- the five cost areas
  const a_gpu = gpus * F.gpu_cost, a_mem = xv("memory_per_rack_musd") * 1e6 * racks, a_cpu = xv("cpu_per_rack_musd") * 1e6 * racks, a_shell = F.shell_cost_usd;
  const a_other = capex - a_gpu - a_mem - a_cpu - a_shell;
  const areas = [
    {key: "gpus", label: "GPUs", sub: `${n0(gpus)} GB300 GPUs x $${n0(F.gpu_cost)} each`, usd: a_gpu, cells: [cellOf("gpus"), cellOf("gpu_cost")]},
    {key: "memory", label: "System memory (DDR5)", sub: `$${f2(xv("memory_per_rack_musd"))}M per rack x ${n0(racks)} racks`, usd: a_mem, cells: [xc("memory_per_rack_musd"), xc("racks")]},
    {key: "cpus", label: "CPUs", sub: `$${f2(xv("cpu_per_rack_musd"))}M per rack x ${n0(racks)} racks`, usd: a_cpu, cells: [xc("cpu_per_rack_musd"), xc("racks")]},
    {key: "other", label: "Other rack hardware", sub: `NVLink, networking, power delivery, chassis: $${f2(xv("other_per_rack_musd"))}M per rack`, usd: a_other, cells: [xc("other_per_rack_musd"), cellOf("rack_cost_musd")]},
    {key: "shell", label: "Powered shell, mechanical & electrical", sub: `$${f1(xv("shell_per_mw_musd"))}M per MW x ${n0(F.site_mw)} MW, incl. labour and materials`, usd: a_shell, cells: [cellOf("shell_cost_musd"), xc("shell_per_mw_musd")]},
  ];
  for (const a of areas) a.share = a.usd / capex;

  const Rn = R.rent, S = R.serves.anthropic, Dn = R.serve_open, W = R.serve_aws, dep = R.dep, life = dep.horizon;
  const rental = I.rental, spot = rental.near_options.spot, contract = rental.options.contract, nearOpt = rental.near_options[dials.near_basis] || spot;
  const quotesBy = {}; for (const q of rental.quotes) quotesBy[q.vendor + "|" + q.chip + "|" + q.per_gpu_hr] = q;
  const contractsBy = {}; for (const c of rental.contracts) contractsBy[c.parties] = c;
  const idx = {}; for (const q of rental.indices) idx[q.vendor + "|" + q.chip] = q;
  const tok = ((I.history || {}).token_index || {}).series || {};
  const latest = ser => { const v = (ser && ser.values) || {}; const ks = Object.keys(v).sort(); return ks.length ? [v[ks[ks.length - 1]], ks[ks.length - 1]] : [null, null]; };
  const tokLatest = {}; for (const k in tok) tokLatest[k] = latest(tok[k]);
  const OR = I.openrouter, ms = F.mastersheet || {};
  const msLabel = ms.found ? `AI mastersheet.xlsx (${ms.fingerprint}, modified ${ms.modified})` : "assumptions.json fallback (mastersheet not found)";
  const rateOverridden = dials.rental_rate_override !== null && dials.rental_rate_override !== undefined || dials.near_rate_override !== null && dials.near_rate_override !== undefined;
  const priceRealised = Math.abs((dials.realisation || 1) - 1) > 1e-9;

  const ladder = (sc, util) => ({revenue: sc.revenue, revenue_y1: sc.revenue_y1, revenue_path: sc.revenue_path, power: sc.power, other: sc.other,
    ebitda: sc.ebitda, ebitda_path: sc.ebitda_path, dep: dep.avg, op_profit: sc.ebitda - dep.avg, capex, roic: sc.roic, roic_y1: sc.roic_y1, roic_path: sc.roic_path,
    irr: sc.irr, flows: sc.flows, terminal: sc.terminal, payback_years: sc.payback_years, rev_per_gpu_hr: sc.rev_per_gpu_hr, ebitda_margin: sc.ebitda_margin, util, cash_yield: sc.cash_yield});

  // --- source panels
  const src = {};
  src.gpus = {
    title: `Number of GPUs: how 1 GW becomes ${n0(gpus)} GPUs`, kind: "market", badge: "Spec sheet",
    summary: `A 1 GW site at PUE ${f2(F.pue)} gives ${n0(F.it_mw)} MW of IT power; a GB300 NVL72 rack draws ${n0(P.kw_per_rack.value)} kW for 72 GPUs, so the site holds ${n0(racks)} racks and ${n0(gpus)} GPUs.`,
    tables: [{caption: `Derivation (${msLabel})`, columns: ["Step", "Value", "Cell"], rows: [
      ["Site power", `${n0(F.site_mw)} MW`, cellOf("site_mw")], ["Power usage effectiveness (PUE)", f2(F.pue), cellOf("pue")], ["IT power = site / PUE", `${F.it_mw.toFixed(1)} MW`, "derived"],
      ["Power per NVL72 rack", `${n0(P.kw_per_rack.value)} kW`, cellOf("kw_per_rack")], ["GPUs per rack", String(Math.round(P.gpus_per_rack.value)), cellOf("gpus_per_rack")],
      ["Power per GPU", `${F.kw_per_gpu.toFixed(3)} kW`, "derived"], ["Racks = IT power / rack power", n0(racks), xc("racks")], ["GPUs = racks x 72", n0(gpus), cellOf("gpus")]]}],
    links: [{label: "NVIDIA GB300 NVL72 (72 Blackwell Ultra GPUs per rack)", url: "https://www.nvidia.com/en-us/data-center/gb300-nvl72/"}],
    note: "Rack power and GPU count per rack are the vendor's published rack specification; PUE is the mastersheet's site assumption. Every scenario uses the same fleet.",
  };
  const nearRows = (nearOpt.rows || []).map(([vendor, chip, tier, rate, read_on]) => { const q = quotesBy[vendor + "|" + chip + "|" + rate] || {}; return [vendor, chip, tier, "$" + f2(rate), q.instance || "", read_on, q.url || ""]; });
  const ctRows = contract.rows.map(([parties, rate, n]) => { const c = contractsBy[parties] || {}; return [parties, "$" + f2(rate), n ? n0(n) : "n/a (weighted as 10,000)", c.term_years ? c.term_years + " yr" : "", c.value_usd_b ? "$" + f1(c.value_usd_b) + "B" : "", c.announced || "", c.url || ""]; });
  const pathRows = Rn.rate_path.map((r, t) => ["Year " + (t + 1), "$" + f2(r), t < Rn.spot_years ? "year-1 rate" : (Rn.rate_weights[t] > 0 ? "converging to contract" : "long-term contract")]);
  const rentBasisLabel = (rental.options[dials.rental_basis] || contract).label, nearLabel = (rental.near_options[dials.near_basis] || spot).label;
  src.rent_price = {
    title: `Average rental price: $${f2(Rn.rate_avg)} per GPU-hour over ${life} years`, kind: rateOverridden ? "assumption" : "market", badge: rateOverridden ? "Typed rate" : "Market",
    summary: rateOverridden
      ? `A rental rate has been typed into the full model (${dials.near_rate_override != null ? "near-term $" + f2(Rn.rate_near) : ""}${dials.near_rate_override != null && dials.rental_rate_override != null ? ", " : ""}${dials.rental_rate_override != null ? "long-term $" + f2(Rn.rate) : ""}), replacing the published quotes and deals below. The average of the ${life}-year path is $${f2(Rn.rate_avg)}.`
      : `Year 1 rents at the near-term basis "${nearLabel}" ($${f2(Rn.rate_near)}); the rate then converges over ${Rn.converge_years} years to the long-term basis "${rentBasisLabel}" ($${f2(Rn.rate)}${Rn.n ? ", " + Rn.n + " data points" : ""}). The average of the ${life}-year path is $${f2(Rn.rate_avg)}${dials.rent_decline ? " including a " + pc(dials.rent_decline, 0) + " a year decline" : ""}.`,
    tables: [
      {caption: "Rate path used", columns: ["Year", "$/GPU-hr", "Basis"], rows: pathRows},
      {caption: `Published rates behind the year-1 rate (${nearOpt.label}: $${f2(nearOpt.rate)}, n=${nearOpt.n || 0})`, columns: ["Vendor", "Chip", "Tier", "$/GPU-hr", "Instance", "Read on", "url"], rows: nearRows},
      {caption: `Disclosed multi-year contracts (GPU-weighted median $${f2(contract.rate)}, simple median $${f2(rental.options.contract_median.rate)}, n=${contract.n})`, columns: ["Parties", "$/GPU-hr", "GPUs", "Term", "Value", "Announced", "url"], rows: ctRows},
      {caption: "Other bases the full model can run on", columns: ["Basis", "$/GPU-hr", "n"], rows: [
        ["On-demand list, GB200/GB300 median", "$" + f2(rental.options.ondemand.rate), rental.options.ondemand.n],
        ["Neocloud on-demand median", "$" + f2(rental.near_options.neocloud.rate), rental.near_options.neocloud.n],
        ["Spot / preemptible GB300/B300 median", "$" + f2(spot.rate), spot.n],
        ["GPU-rental deals priced per MW, MW-weighted median", "$" + f2(rental.options.mw_deals.rate), rental.options.mw_deals.n],
        ["2026 new-deal ACV per IT-MW (IREN, Nebius)", rental.options.acv2026.rate ? "$" + f2(rental.options.acv2026.rate) : "", rental.options.acv2026.n]]},
      {caption: "Daily market indices (older B200 part; references, not inputs)", columns: ["Index", "$/GPU-hr", "As of", "url"], rows: rental.indices.filter(q => q.chip === "B200").map(q => [q.instance, "$" + f2(q.rate), q.as_of || q.read_on, q.url])},
    ],
    links: [],
    note: `Rental utilisation (${r0(Rn.util)}%) is applied separately. No GB300 rental index exists yet; the B200 indices show where the cleared Blackwell market sits.`,
  };
  src.hours = {title: "Hours per year", kind: "fixed", badge: "Fixed", summary: "365 days x 24 hours = 8,760 hours. A calendar constant; utilisation below scales it to hours actually sold.", tables: [], links: [], note: ""};
  src.seconds = {title: "Seconds per year", kind: "fixed", badge: "Fixed", summary: "365 x 24 x 3,600 = 31,536,000 seconds. A calendar constant; tokens per second per chip x seconds gives tokens per chip-year at 100% utilisation.", tables: [], links: [], note: ""};
  src.rent_util = {title: `Utilisation rate: ${r0(Rn.util)}% of hours sold`, kind: "assumption", badge: "Assumption",
    summary: `Share of GPU-hours that earn rent. The default comes from the ROIC Dashboard sheet of the mastersheet (${cellOf("rent_util") || "fallback"}: ${pc(F.rent_util, 0)}); no public data reports the sold share of a rented Blackwell fleet.` + (Math.abs(Rn.util - F.rent_util) > 1e-9 ? ` Currently set to ${pc(Rn.util, 0)} on the full model.` : ""),
    tables: [], links: [], note: `Every 10 points of utilisation moves rental revenue by $${B2(gpus * Rn.rate_avg * HOURS * 0.1)} a year at the average rate.`};
  src.serve_util = {title: `Token utilisation: ${r0(S.util)}% of chip-seconds producing tokens`, kind: "assumption", badge: "Assumption",
    summary: `Share of every chip-second that is busy generating billable tokens (the rest is idle capacity, failover and demand troughs). The default comes from the mastersheet's ROIC Dashboard sheet (${cellOf("serve_util") || "fallback"}: ${pc(F.serve_util, 0)}).` + (Math.abs(S.util - F.serve_util) > 1e-9 ? ` Currently set to ${pc(S.util, 0)} on the full model.` : ""),
    tables: [], links: [], note: "Applied on top of the realised tokens per second, which already reflects production efficiency (see that box)."};
  src.gpu_life = {title: `Lifetime of GPUs: ${dep.compute_life} years`, kind: "assumption", badge: "Assumption",
    summary: `GPUs and racks ($${B1(dep.compute_cost)}) are depreciated straight-line over ${dep.compute_life} years to ${r0(dep.compute_residual)}% residual; the analysis horizon is ${life} years. This is the dashboard's own assumption (assumptions.json 'finance'); the mastersheet carries no depreciation life.`,
    tables: [{caption: "Context from the assumptions file", columns: ["Owner", "Server depreciation life"], rows: [["Amazon (newer fleet, since 2025)", "5 years"], ["Microsoft", "6 years"], ["Alphabet", "6 years"], ["Meta", "5.5 years"], ["CoreWeave", "6 years"]]}],
    links: [], note: `Annual depreciation of the compute pool: $${B2(dep.compute_path[0])}${dep.terminal_compute ? "; book value recovered at the end of year " + life + ": $" + B1(dep.terminal_compute) : ""}.`};
  src.shell_life = {title: `Lifetime of shell: ${dep.shell_life} years`, kind: "assumption", badge: "Assumption",
    summary: `The powered shell, mechanical and electrical plant ($${B1(dep.shell_cost)}) is depreciated over ${dep.shell_life} years to ${r0(dep.shell_residual)}% residual against a ${life}-year horizon. The assumptions file notes shells are commonly depreciated over 20-30 years and M&E over 10-20, so a 15-year shell life is the defensible alternative; any life beyond the horizon is recovered as book value at the end of year ${life} (it raises the IRR, not the ROIC).`,
    tables: [], links: [], note: `Annual depreciation of the shell pool: $${B2(dep.shell_path[0])}${dep.terminal_shell ? "; book value recovered at exit: $" + B1(dep.terminal_shell) : ""}.`};
  src.pct_inference = {title: `Share of chips serving inference: ${r0(1 - S.training_share)}%`, kind: "assumption", badge: "Assumption",
    summary: `The 'training share' dial of the full model gives part of the fleet to training, which earns no token revenue. It is set to ${r0(S.training_share)}%${S.training_share ? ", so " + n0(S.training_gpus) + " chips train and " + n0(S.serving_gpus) + " serve tokens" : ", so every chip serves tokens"}.`,
    tables: [], links: [], note: "Chips given to training still draw power and carry depreciation in the model."};
  const orw = OR.closed_share_week || {};
  const modeText = {cost: "the model's task framework: 20 knowledge-work task types, each rated 1-5 on reasoning depth and consequence; frontier share = clamp((max(reasoning, consequence) - 2) / 3, 0, 1)" + (R.premium_tolerance ? `, pulled down where the frontier basket costs more than ${R.premium_tolerance}x the open-weight mix` : ""),
    openrouter: "the closed-weight share OpenRouter routed in its latest weekly ranking, applied as an override", manual: "a manual override dial on the full model"}[S.split_mode] || S.split_mode;
  src.pct_closed = {title: `Closed-weight share of tokens: ${pc(S.closed_share)}`, kind: "assumption", badge: "Assumption",
    summary: `Set by ${modeText}. Weighted by each task's measured token volume this gives ${pc(S.closed_share)} of output tokens to Anthropic's models and ${pc(1 - S.closed_share)} to open-weight models.`,
    tables: [{caption: "Market cross-check (reference, not the input)", columns: ["Measure", "Value", "As of"], rows: [
      ["OpenRouter weekly ranking: closed-weight share of completion tokens, every closed lab", orw.out != null ? pc(orw.out) : "", String(orw.week_date || "").slice(0, 10)],
      ["Same, share of all tokens (input + output)", orw.total != null ? pc(orw.total) : "", String(orw.week_date || "").slice(0, 10)]]}],
    links: [{label: "OpenRouter rankings", url: "https://openrouter.ai/rankings"}],
    note: `Because frontier tokens are slower per chip, ${pc(S.closed_share)} of tokens takes ${pc(S.frontier_share_of_gpus)} of the serving chips (${n0(S.frontier_gpus)} GPUs).`};

  const tpsSource = (sc, prefix) => {
    const rows = sc.rows.filter(r => r.share > 0).map(r => [r.name, r.tier === "frontier" ? "closed" : "open", pc(r.share), n0(r.tps_bench || 0), pc(r.f, 0), n0(r.tps), n0(r.gpus), r.tps_basis, r.tps_url || ""]);
    const basis = sc.tps_realisation_basis;
    const how = basis === "market-implied per model"
      ? `for open models the factor that makes a GPU-hour serving that model earn the ${sc.rate_f_label} plus a ${r0(sc.renter_roic)}% renter margin ($${f2(sc.rate_f)}/GPU-hr); the closed models borrow the largest measured open model's curve at a ${r0(dials.frontier_derate)}% derate and ${sc.f_frontier_basis} (${pc(sc.f_frontier, 0)})`
      : basis === "manual" ? `a manual factor of ${pc(sc.f_gpu_weighted, 0)} set on the full model` : "no haircut at all: every model at its published benchmark peak";
    return {title: `${prefix}: ${n0(sc.eff_tps)} output tokens per second per chip`, kind: "assumption", badge: "Assumption",
      summary: `Fleet-average output tokens per busy chip-second. Each model starts from its own SemiAnalysis InferenceX benchmark on GB300 at the ${dials.workload} request shape and ${dials.interactivity_basis === "measured" ? "its measured interactivity" : dials.interactivity + " tok/s per user"}, then takes a realisation factor: ${how}. Chips are allocated so every model gets its share of tokens.`,
      tables: [{caption: `Per model (InferenceX read ${I.throughput_meta.read_on}, newest run ${I.throughput_meta.newest_run})`, columns: ["Model", "Weights", "Share of tokens", "Benchmark tok/s/GPU", "Realisation", "Realised tok/s/GPU", "GPUs", "Basis", "url"], rows}],
      links: [{label: "SemiAnalysis InferenceX", url: "https://inferencex.semianalysis.com/"}],
      note: `The benchmark points are market data; the realisation factor and the frontier proxy are the model's assumptions, which is why this box is red. At benchmark peak with no realisation haircut the open-weight fleet would earn $${f2(R.serve_open_peak.rev_per_gpu_hr)} per GPU-hour (scenario E in the full model).`};
  };
  src.tps_lab = tpsSource(S, "Tokens per second per chip, Anthropic scenario");
  src.tps_open = tpsSource(Dn, "Tokens per second per chip, open-weight scenario");

  const priceSource = (sc, prefix, closed) => {
    const rows = sc.rows.filter(r => r.share > 0).map(r => { const p = r.price; return [r.name, r.tier === "frontier" ? "closed" : "open", pc(r.share), "$" + f2(p.out), "$" + f2(p.in),
      p.eff_out != null ? "$" + f2(p.eff_out) : "", p.eff_in != null ? "$" + (+p.eff_in).toFixed(3) : "", "$" + f2(r.blended_per_m_out), p.provider || "", p.read_on || "", p.url || ""]; });
    const tables = [{caption: "Per model: list price, OpenRouter traffic-weighted effective price (cache discounts embedded), and the all-in price per million output tokens with input billed at the request's own ratio" + (priceRealised && closed ? `; frontier prices x ${pc(dials.realisation, 0)} realisation` : ""),
      columns: ["Model", "Weights", "Share of tokens", "List out $/M", "List in $/M", "Effective out $/M", "Effective in $/M", "All-in $/M output", "Price source", "Read on", "url"], rows}];
    const ref = [];
    for (const [k, lab] of [["llm", "Silicon Data LLM Token Expenditure Index (broad market)"], ["proprietary", "Silicon Data Proprietary LLM index"], ["open", "Silicon Data Open LLM index"]]) {
      const [v, d] = tokLatest[k] || [null, null]; if (v != null) ref.push([lab, "$" + f2(v), d, (tok[k] || {}).url || ""]);
    }
    ref.push(["This scenario, same basis (per M tokens, input + output)", "$" + f2(sc.blended_per_m_total), I.built_at.slice(0, 10), ""]);
    if (closed) { ref.push(["  of which closed models", "$" + f2(sc.frontier_per_m_total), "", ""]); ref.push(["  of which open models", "$" + f2(sc.open_per_m_total), "", ""]); }
    tables.push({caption: "Market cross-check: usage-weighted dollars per million tokens (input + output)", columns: ["Index", "$/M tokens", "As of", "url"], rows: ref});
    const pb = dials.price_basis === "effective" ? "OpenRouter traffic-weighted effective prices" : "list prices";
    const summ = closed
      ? `Token-weighted across the fleet: closed models at $${f2(sc.frontier_blended_per_m_out)} per million output tokens all-in (${pc(sc.closed_share, 0)} of tokens) and open-weight models at $${f2(sc.open_blended_per_m_out)} (${pc(1 - sc.closed_share, 0)}) blend to $${f2(sc.blended_per_m_out)}. Prices are what the market charges today: Anthropic's list prices (read ${I.lab_prices_meta.read_on}) and the ${pb} of every open model (read ${OR.read_on}).` + (priceRealised ? ` The full model applies a ${pc(dials.realisation, 0)} price realisation to the frontier basket.` : "")
      : `Token-weighted across the ${sc.n_open_models} open-weight models the framework routes to, at each model's ${pb} (read ${OR.read_on}): $${f2(sc.blended_per_m_out)} per million output tokens all-in, with input billed at the request's own ratio.`;
    return {title: `${prefix}: $${f2(sc.blended_per_m_out)} per million output tokens`, kind: priceRealised && closed ? "assumption" : "market", badge: priceRealised && closed ? "Market x realisation" : "Market", summary: summ, tables,
      links: [{label: "Anthropic pricing", url: "https://platform.claude.com/docs/en/about-claude/pricing"}, {label: "OpenRouter models", url: "https://openrouter.ai/models"}],
      note: `'All-in per million output tokens' = output price + the request's input:output ratio x effective input price, so one number prices a whole request. Token prices ${dials.token_decline ? "fall " + pc(dials.token_decline, 0) + " a year" : "are held flat"} over the ${life} years.`};
  };
  src.price_lab = priceSource(S, "Token price, Anthropic scenario", true);
  src.price_open = priceSource(Dn, "Token price, open-weight scenario", false);
  src.pct_rented = {title: `Share of chips rented to Anthropic: ${pc(W.frontier_gpus / gpus)}`, kind: "assumption", badge: "Assumption",
    summary: `The chips the Anthropic serving scenario allocates to Anthropic's own models (${n0(W.frontier_gpus)} of ${n0(gpus)} GPUs) are the block AWS rents to Anthropic. It follows from the closed-weight token share (${pc(W.closed_share)}) and the closed models' slower throughput per chip; the remaining ${n0(W.open_gpus)} GPUs serve open-weight tokens for AWS's own account.`,
    tables: [], links: [], note: `The block earns the rental scenario's rate path ($${f2(Rn.rate_avg)} average) at ${r0(W.rent_util)}% rental utilisation, plus the revenue share.`};
  src.rev_share = {title: `Anthropic revenue share: ${r0(W.rev_share)}%`, kind: "assumption", badge: "Assumption",
    summary: `The fleet owner's share of every token dollar Anthropic's models earn on the rented block (the 'AWS scenario' dial; default ${r0((I.aws || {}).rev_share || 0.25)}% from assumptions.json). No public disclosure of the AWS-Anthropic commercial split exists.`,
    tables: [], links: [], note: `Anthropic's token revenue on the block: $${B1(W.frontier_token_rev_hr * HOURS)} a year at ${r0(W.util)}% token utilisation; the owner's share is $${B1(W.rev_share * W.frontier_token_rev_hr * HOURS)}.`};

  // --- scenarios
  const driver = (id, label, value, fmt, line, source, kind, badge) => { const s = src[source]; return {id, label, value, fmt, line, source, kind: kind || s.kind, badge: badge || s.badge}; };
  const wavg = (rows, tot) => tot ? rows.reduce((a, r) => a + r.gpus * r.tps, 0) / tot : 0;
  const tpsF = wavg(S.frontier_rows, S.frontier_gpus), tpsO = wavg(S.open_rows, S.open_gpus);
  const rent_sc = {
    key: "rent", letter: "A", title: "Rent the GPUs out", short: "Rent", colour: "#2a78d6",
    what: "Build the site, rent every GPU-hour to tenants at market rates and run the building.",
    drivers: [
      driver("gpus", "Number of GPUs", gpus, "int", `${n0(gpus)} GB300 GPUs in ${n0(racks)} NVL72 racks`, "gpus"),
      driver("rate", "Average rental price per hour per GPU", Rn.rate_avg, "usd2", `$${f2(Rn.rate_near)} in year 1, $${f2(Rn.rate_path[Rn.rate_path.length - 1])} in year ${life}`, "rent_price"),
      driver("hours", "Hours per year", HOURS, "int", "365 days x 24 hours", "hours"),
      driver("util", "Utilisation rate", Rn.util, "pct0", "share of GPU-hours sold", "rent_util"),
      driver("gpu_life", "Lifetime of GPUs", dep.compute_life, "years", `straight-line on $${B1(dep.compute_cost)} of GPUs and racks`, "gpu_life"),
      driver("shell_life", "Lifetime of shell", dep.shell_life, "years", `straight-line on $${B1(dep.shell_cost)} of shell and M&E`, "shell_life"),
    ],
    rows: [[{box: "gpus"}, {op: "x"}, {box: "rate"}, {op: "x"}, {box: "hours"}, {op: "x"}, {box: "util"}, {op: "="}, {result: {label: "Rental revenue per year", value: Rn.revenue, fmt: "usdB"}}]],
    dep_inputs: ["gpu_life", "shell_life"], ladder: ladder(Rn, Rn.util), streams: [{label: "Rent", value: Rn.revenue, colour: "#2a78d6"}],
    extra: {rate_path: Rn.rate_path, rate_near: Rn.rate_near, rate: Rn.rate, rate_avg: Rn.rate_avg, spot_n: nearOpt.n || 0, contract_n: contract.n, near_label: nearLabel, basis_label: rentBasisLabel,
      sd_b200: (idx["Silicon Data|B200"] || {}).rate, ornn_b200: (idx["Ornn|B200"] || {}).rate},
  };
  const tokRes = sc => ({label: "Tokens per year", value: sc.tokens_yr, fmt: "tokens", mid: true});
  const lab_sc = {
    key: "lab", letter: "B", title: "Serve tokens as a frontier lab", short: "Serve Lab", colour: "#eb6834",
    what: "Own the site and sell tokens: Anthropic's models where the work needs frontier intelligence, open-weight models for the rest.",
    drivers: [
      driver("gpus", "Number of chips", gpus, "int", `${n0(gpus)} GB300 GPUs`, "gpus"),
      driver("pct_inf", "% inference chips", 1 - S.training_share, "pct0", `${r0(S.training_share)}% of the fleet given to training`, "pct_inference"),
      driver("pct_closed", "% closed-weight tokens", S.closed_share, "pct1", `${pc(S.closed_share, 0)} closed at $${f2(S.frontier_blended_per_m_out)}/M, ${pc(1 - S.closed_share, 0)} open at $${f2(S.open_blended_per_m_out)}/M`, "pct_closed"),
      driver("tps", "Tokens per second per chip", S.eff_tps, "int", `closed models ~${n0(tpsF)}, open models ~${n0(tpsO)} tok/s per chip`, "tps_lab"),
      driver("util", "Token utilisation", S.util, "pct0", "share of chip-seconds producing billable tokens", "serve_util"),
      driver("price", "Token price", S.blended_per_m_out, "usd2m", `per M output tokens, input billed at the request ratio; blend of $${f2(S.frontier_blended_per_m_out)} closed and $${f2(S.open_blended_per_m_out)} open`, "price_lab"),
      driver("seconds", "Seconds per year", SECONDS, "int", "365 x 24 x 3,600", "seconds"),
    ],
    rows: [[{box: "gpus"}, {op: "x"}, {box: "pct_inf"}, {op: "x"}, {box: "tps"}, {op: "x"}, {box: "util"}, {op: "x"}, {box: "seconds"}, {op: "="}, {result: tokRes(S)}],
           [{result: tokRes(S)}, {op: "x"}, {box: "price"}, {op: "="}, {result: {label: "Token revenue per year", value: S.revenue, fmt: "usdB"}}]],
    modifier: "pct_closed", ladder: ladder(S, S.util),
    streams: [{label: "Closed-weight tokens (Anthropic models)", value: S.frontier_revenue_hr * HOURS, colour: "#eb6834"}, {label: "Open-weight tokens", value: S.open_revenue_hr * HOURS, colour: "#1baf7a"}],
    extra: {frontier_gpus: S.frontier_gpus, open_gpus: S.open_gpus, closed_share: S.closed_share, frontier_rev_per_gpu_hr: S.frontier_rev_per_gpu_hr, open_rev_per_gpu_hr: S.open_rev_per_gpu_hr},
  };
  const open_sc = {
    key: "open", letter: "D", title: "Serve open-weight tokens only", short: "Serve Open Weight", colour: "#1baf7a",
    what: "Own the site and sell tokens from open-weight models only, at today's market prices for those models.",
    drivers: [
      driver("gpus", "Number of chips", gpus, "int", `${n0(gpus)} GB300 GPUs, all serving`, "gpus"),
      driver("tps", "Tokens per second per chip", Dn.eff_tps, "int", `${Dn.n_open_models} open models: ` + Dn.open_rows.filter(r => r.share > 0).map(r => `${r.name} ${n0(r.tps)}`).join(", "), "tps_open"),
      driver("util", "Token utilisation", Dn.util, "pct0", "share of chip-seconds producing billable tokens", "serve_util"),
      driver("price", "Token price", Dn.blended_per_m_out, "usd2m", `per M output tokens all-in; output alone $${f2(Dn.open_p_out)}/M`, "price_open"),
      driver("seconds", "Seconds per year", SECONDS, "int", "365 x 24 x 3,600", "seconds"),
    ],
    rows: [[{box: "gpus"}, {op: "x"}, {box: "tps"}, {op: "x"}, {box: "util"}, {op: "x"}, {box: "seconds"}, {op: "="}, {result: tokRes(Dn)}],
           [{result: tokRes(Dn)}, {op: "x"}, {box: "price"}, {op: "="}, {result: {label: "Token revenue per year", value: Dn.revenue, fmt: "usdB"}}]],
    ladder: ladder(Dn, Dn.util), streams: [{label: "Open-weight tokens", value: Dn.revenue, colour: "#1baf7a"}],
  };
  const avg = xs => xs.reduce((a, b) => a + b, 0) / xs.length;
  const rentBlock = avg(W.rent_block_path), tokBlock = avg(W.token_share_path), openBlock = avg(W.open_rev_path);
  const aws_sc = {
    key: "aws", letter: "F", title: "Serve as AWS: landlord to Anthropic", short: "Serve AWS", colour: "#4a3aa7",
    what: "Own the site, rent the block Anthropic's models need to Anthropic (rent plus a share of their token revenue) and serve open-weight tokens on the rest.",
    drivers: [
      driver("gpus", "Number of chips", gpus, "int", `${n0(gpus)} GB300 GPUs`, "gpus"),
      driver("pct_rented", "% rented out to Anthropic", W.frontier_gpus / gpus, "pct1", `${n0(W.frontier_gpus)} GPUs at $${f2(Rn.rate_avg)}/GPU-hr average, ${r0(W.rent_util)}% rental utilisation`, "pct_rented"),
      driver("rev_share", "Anthropic revenue share", W.rev_share, "pct0", `of the $${B1(W.frontier_token_rev_hr * HOURS)} Anthropic's models earn on the block`, "rev_share"),
      driver("pct_closed", "% closed-weight tokens", W.closed_share, "pct1", "same task framework as the lab scenario", "pct_closed"),
      driver("tps", "Tokens per second per chip", S.eff_tps, "int", `closed ~${n0(tpsF)} on the rented block, open ~${n0(tpsO)} on AWS's own chips`, "tps_lab"),
      driver("util", "Token utilisation", W.util, "pct0", "share of chip-seconds producing billable tokens", "serve_util"),
      driver("price", "Token price", S.blended_per_m_out, "usd2m", `closed $${f2(S.frontier_blended_per_m_out)}/M (Anthropic's revenue, shared), open $${f2(S.open_blended_per_m_out)}/M (AWS's own)`, "price_lab"),
      driver("seconds", "Seconds per year", SECONDS, "int", "365 x 24 x 3,600", "seconds"),
    ],
    rows: [[{box: "gpus"}, {op: "."}, {box: "pct_rented"}, {op: "."}, {box: "rev_share"}, {op: "."}, {box: "pct_closed"}, {op: "."}, {box: "tps"}],
           [{box: "util"}, {op: "."}, {box: "price"}, {op: "."}, {box: "seconds"}, {op: "="}, {result: {label: "AWS revenue per year", value: W.revenue, fmt: "usdB", sub: "three streams, below"}}]],
    ladder: ladder(W, W.util),
    streams: [{label: `Rent from Anthropic on ${n0(W.frontier_gpus)} GPUs`, value: rentBlock, colour: "#2a78d6", formula: `${n0(W.frontier_gpus)} GPUs x $${f2(Rn.rate_avg)} x 8,760 h x ${r0(W.rent_util)}%`},
              {label: `${r0(W.rev_share)}% share of Anthropic's token revenue`, value: tokBlock, colour: "#eb6834", formula: `${r0(W.rev_share)}% x $${B1(W.frontier_token_rev_hr * HOURS)}`},
              {label: `Open-weight tokens on AWS's ${n0(W.open_gpus)} GPUs`, value: openBlock, colour: "#1baf7a", formula: `${n0(W.open_gpus)} GPUs x ${n0(tpsO)} tok/s x ${r0(W.util)}% x 31.5M s x $${f2(S.open_blended_per_m_out)}/M`}],
    extra: {frontier_gpus: W.frontier_gpus, open_gpus: W.open_gpus, rev_share: W.rev_share, rent_util: W.rent_util, rate_avg: Rn.rate_avg, anthropic_token_rev: W.frontier_token_rev_hr * HOURS},
  };
  const scenarios = [rent_sc, lab_sc, open_sc, aws_sc];
  for (const sc of scenarios) { const n = {market: 0, assumption: 0, fixed: 0}; for (const d of sc.drivers) n[d.kind]++; sc.counts = n; }
  return {
    built_at: I.built_at,
    fleet: {gpus, racks, gpus_per_rack: F.gpus_per_rack, site_mw: F.site_mw, it_mw: F.it_mw, pue: F.pue, kw_per_gpu: F.kw_per_gpu, kw_per_rack: P.kw_per_rack.value, chip: F.chip, chip_label: F.chip_label,
      capex, capex_per_gpu: F.capex_per_gpu, gpu_cost: F.gpu_cost, rack_cost: F.rack_cost_usd, power_price_mwh: dials.power_price, other_opex: dials.other_opex, mastersheet: msLabel, mastersheet_found: !!ms.found},
    areas,
    finance: {horizon: life, compute_life: dep.compute_life, shell_life: dep.shell_life, dep_avg: dep.avg, compute_cost: dep.compute_cost, shell_cost: dep.shell_cost, dep_compute: dep.compute_path[0], dep_shell: dep.shell_path[0],
      terminal: dep.terminal, rent_decline: dials.rent_decline, token_decline: dials.token_decline},
    scenarios, sources: src,
    freshness: {openrouter: OR.read_on, openrouter_week: String(OR.week_date || "").slice(0, 10), inferencex: I.throughput_meta.read_on, inferencex_newest_run: I.throughput_meta.newest_run, rental: I.rental_meta.read_on,
      lab_prices: I.lab_prices_meta.read_on, token_index: (tokLatest.llm || [null, null])[1], mastersheet: msLabel},
    also: {openai: {roic: R.serves.openai.roic, irr: R.serves.openai.irr, rev_per_gpu_hr: R.serves.openai.rev_per_gpu_hr}, open_peak: {roic: R.serve_open_peak.roic, irr: R.serve_open_peak.irr, rev_per_gpu_hr: R.serve_open_peak.rev_per_gpu_hr}},
  };
}
