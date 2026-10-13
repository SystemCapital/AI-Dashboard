/* The presentation layer. Everything it shows is in DATA (written by build_infographic.py from the engine one folder up). */
(function () {
  // ---------- state: the page recomputes itself from INPUTS at the dials it is given
  const DEFAULTS = defaultDials(INPUTS);
  const computeData = d => assembleData(INPUTS, compute(INPUTS, d), d, EXTRA);
  let DIALS = Object.assign({}, DEFAULTS);
  let D = computeData(DIALS);
  let SC = D.scenarios;
  let byKey = Object.fromEntries(SC.map(s => [s.key, s]));
  const ORDER = ["build", ...SC.map(s => s.key), "summary"];
  const $ = (sel, el) => (el || document).querySelector(sel);
  const el = (tag, attrs, ...kids) => {
    const n = document.createElement(tag);
    for (const k in (attrs || {})) {
      if (k === "class") n.className = attrs[k];
      else if (k === "style") n.style.cssText = attrs[k];
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), attrs[k]);
      else if (k === "html") n.innerHTML = attrs[k];
      else n.setAttribute(k, attrs[k]);
    }
    for (const c of kids.flat()) if (c !== null && c !== undefined) n.append(c.nodeType ? c : document.createTextNode(String(c)));
    return n;
  };
  const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));

  // ---------- formatting
  const B = v => (Math.abs(v) >= 1e9 ? "$" + (v / 1e9).toFixed(Math.abs(v) >= 1e10 ? 1 : 2) + "B" : "$" + (v / 1e6).toFixed(0) + "M");
  const pct = (v, d) => (100 * v).toFixed(d === undefined ? 1 : d) + "%";
  const int = v => Math.round(v).toLocaleString("en-US");
  const fmt = (v, f) => {
    switch (f) {
      case "int": return int(v);
      case "usd2": return "$" + v.toFixed(2);
      case "usd2m": return "$" + v.toFixed(2);
      case "pct0": return pct(v, 0);
      case "pct1": return pct(v, 1);
      case "years": return v % 1 ? v.toFixed(1) : String(v);
      case "usdB": return B(v);
      case "tokens": return (v / 1e15).toFixed(2) + " quadrillion";
      default: return String(v);
    }
  };
  const unit = f => ({usd2: "/GPU-hr", usd2m: "/M tokens", years: "years", tokens: ""}[f] || "");
  const signed = v => (v >= 0 ? "" : "−") + Math.abs(100 * v).toFixed(1) + "%";

  // ---------- navigation
  const main = $("#main"), tabs = $("#tabs");
  let pages = {};
  let current = "build";
  function show(key, push, keepScroll) {
    if (!pages[key]) key = "build";
    current = key;
    for (const k in pages) pages[k].classList.toggle("on", k === key);
    for (const t of tabs.children) t.classList.toggle("on", t.dataset.key === key);
    if (push !== false) history.replaceState(null, "", "#" + key);
    if (!keepScroll) window.scrollTo({top: 0});
    if (key === "summary") drawSummaryCharts();
  }
  window.addEventListener("hashchange", () => show(location.hash.slice(1) || "build", false));
  document.addEventListener("keydown", e => {
    if ($("#mback").classList.contains("on")) { if (e.key === "Escape") closeModal(); return; }
    const i = ORDER.indexOf(location.hash.slice(1) || "build");
    if (e.key === "ArrowRight" || e.key === "PageDown") show(ORDER[Math.min(ORDER.length - 1, i + 1)]);
    if (e.key === "ArrowLeft" || e.key === "PageUp") show(ORDER[Math.max(0, i - 1)]);
  });
  function tab(key, label, colour, letter) {
    const t = el("button", {class: "tab", "data-key": key, style: colour ? "--c:" + colour : "", onclick: () => show(key)},
      colour ? el("span", {class: "dot"}) : null, letter ? el("b", {}, letter) : null, label);
    tabs.append(t);
  }
  tab("build", "The build");
  for (const s of SC) tab(s.key, s.short, s.colour, s.letter);
  tab("summary", "Summary");

  function navbtns(key) {
    const i = ORDER.indexOf(key);
    const prev = ORDER[i - 1], next = ORDER[i + 1];
    const name = k => k === "build" ? "The build" : k === "summary" ? "Summary" : byKey[k].letter + " · " + byKey[k].short;
    return el("div", {class: "navbtns"},
      prev ? el("button", {onclick: () => show(prev)}, "← " + name(prev)) : el("span"),
      next ? el("button", {onclick: () => show(next)}, name(next) + " →") : el("span"));
  }

  // ---------- modal (source panels)
  const mback = $("#mback"), modal = $("#modal");
  let openKey = null;
  function closeModal() { mback.classList.remove("on"); openKey = null; }
  mback.addEventListener("click", e => { if (e.target === mback) closeModal(); });
  function openSource(key, colour) {
    const s = D.sources[key];
    if (!s) return;
    const refresh = mback.classList.contains("on") && openKey === key;
    const keepScroll = refresh ? modal.scrollTop : 0;
    openKey = key;
    modal.innerHTML = "";
    modal.append(
      el("button", {class: "x", onclick: closeModal, "aria-label": "Close"}, "×"),
      el("span", {class: "pill " + s.kind}, el("i"), s.badge),
      el("h2", {}, s.title),
      el("p", {class: "sum"}, s.summary));
    for (const t of s.tables || []) {
      if (!t.rows.length) continue;
      modal.append(el("h4", {}, t.caption));
      const urlCol = t.columns.indexOf("url");
      const head = el("tr", {}, t.columns.filter((c, i) => i !== urlCol).map((c, i) => el("th", {class: i > 0 && /\$|%|GPUs|tok|Value|Share|n$/.test(c) ? "r" : ""}, c)), urlCol >= 0 ? el("th", {}, "Source") : null);
      const body = t.rows.map(r => el("tr", {}, r.map((c, i) => i === urlCol ? null : el("td", {class: i > 0 && /^\$|%$|^[\d,\.]+$|^\d+ yr/.test(String(c)) ? "r" : ""}, c === null ? "" : c)),
        urlCol >= 0 ? el("td", {}, r[urlCol] ? el("a", {class: "src", href: r[urlCol], target: "_blank", rel: "noopener"}, "↗") : "") : null));
      modal.append(el("table", {}, el("thead", {}, head), el("tbody", {}, body)));
    }
    if (s.links && s.links.length) modal.append(el("div", {class: "links"}, s.links.map(l => el("a", {href: l.url, target: "_blank", rel: "noopener"}, l.label + " ↗"))));
    if (s.note) modal.append(el("p", {class: "note"}, s.note));
    mback.classList.add("on");
    modal.scrollTop = keepScroll;
  }

  // ---------- tooltip
  const tip = $("#tip");
  function tipOn(html) { tip.innerHTML = html; tip.style.display = "block"; }
  function tipMove(e) { tip.style.left = Math.min(window.innerWidth - 300, e.clientX + 14) + "px"; tip.style.top = (e.clientY + 14) + "px"; }
  function tipOff() { tip.style.display = "none"; }

  // ---------- driver boxes
  function box(d, sc) {
    const v = fmt(d.value, d.fmt), u = unit(d.fmt);
    const b = el("button", {class: "box " + d.kind, onclick: () => openSource(d.source, sc.colour), title: "Click for the sources"},
      el("div", {class: "badge-row"}, el("span", {class: "pill " + d.kind}, el("i"), d.badge)),
      el("div", {class: "lbl"}, d.label),
      el("div", {class: "val num"}, v, u ? el("small", {}, u) : null),
      el("div", {class: "line"}, d.line));
    return b;
  }
  const op = s => el("div", {class: "op" + (s === "=" ? " eq" : "")}, s);
  const result = (label, value, f, mid, sub) => el("div", {class: "result" + (mid ? " mid" : "")}, el("div", {class: "lbl"}, label), el("div", {class: "val num"}, fmt(value, f)), sub ? el("div", {class: "sub"}, sub) : null);

  // ---------- scenario page
  function scenarioPage(sc) {
    const L = sc.ladder, drv = Object.fromEntries(sc.drivers.map(d => [d.id, d]));
    const pg = el("section", {class: "page", id: "p_" + sc.key, style: "--c:" + sc.colour});
    // header
    pg.append(el("div", {class: "phead"},
      el("div", {class: "t"},
        el("h1", {}, el("span", {class: "letter"}, sc.letter), sc.title),
        el("p", {class: "what"}, sc.what),
        el("div", {class: "stats"},
          el("div", {class: "stat"}, el("div", {class: "l"}, "Revenue / yr"), el("div", {class: "v num"}, B(L.revenue))),
          el("div", {class: "stat"}, el("div", {class: "l"}, "EBITDA / yr"), el("div", {class: "v num"}, B(L.ebitda))),
          el("div", {class: "stat"}, el("div", {class: "l"}, "Revenue per GPU-hour"), el("div", {class: "v num"}, "$" + L.rev_per_gpu_hr.toFixed(2))),
          el("div", {class: "stat"}, el("div", {class: "l"}, "Payback"), el("div", {class: "v num"}, L.payback_years ? L.payback_years.toFixed(1) + " yrs" : "never")))),
      el("div", {class: "heroes"},
        el("div", {class: "hero"}, el("div", {class: "l"}, "ROIC"), el("div", {class: "v num"}, signed(L.roic)), el("div", {class: "s"}, "(EBITDA − depreciation) ÷ cost to build, " + D.finance.horizon + "-yr average · year 1: " + signed(L.roic_y1))),
        el("div", {class: "hero"}, el("div", {class: "l"}, "IRR"), el("div", {class: "v num"}, L.irr === null ? "n/a" : signed(L.irr)), el("div", {class: "s"}, "pre-tax, " + D.finance.horizon + "-year cash flows" + (L.terminal ? " + book value at exit" : ", no terminal value"))))));
    // driver chain: one or two rows of linked boxes, laid out explicitly so nothing wraps mid-formula
    const chainBlock = el("div", {class: "block"}, el("h3", {}, "What drives the revenue \u00b7 click any box for its sources"));
    const OPS = {x: "\u00d7", "=": "=", ".": "\u00b7", "+": "+"};
    for (const row of sc.rows) {
      const chain = el("div", {class: "chain" + (row.length <= 5 ? " short" : "")});
      for (const it of row) {
        if (it.box) chain.append(box(drv[it.box], sc));
        else if (it.op) chain.append(op(OPS[it.op] || it.op));
        else if (it.result) chain.append(result(it.result.label, it.result.value, it.result.fmt, it.result.mid, it.result.sub));
      }
      chainBlock.append(chain);
    }
    if (sc.modifier) {
      const m = drv[sc.modifier];
      chainBlock.append(el("div", {class: "modrow"}, box(m, sc),
        el("div", {class: "arrow"}, "sets the closed / open blend inside \u201c" + drv.tps.label + "\u201d and \u201c" + drv.price.label + "\u201d")));
    }
    if (sc.dep_inputs) {
      const row = el("div", {class: "modrow"});
      row.append(box(drv[sc.dep_inputs[0]], sc), op("+"), box(drv[sc.dep_inputs[1]], sc), op("="),
        result("Depreciation per year", D.finance.dep_avg, "usdB", true),
        el("div", {class: "arrow"}, "$" + (D.finance.compute_cost / 1e9).toFixed(1) + "B of GPUs and racks over " + D.finance.compute_life + " years + $" + (D.finance.shell_cost / 1e9).toFixed(1) + "B of shell over " + D.finance.shell_life + " years"));
      chainBlock.append(row);
    }
    pg.append(chainBlock);
    // ladder + streams
    const two = el("div", {class: "two"});
    two.append(ladderBlock(sc), streamsBlock(sc));
    pg.append(two, navbtns(sc.key));
    return pg;
  }

  function ladderBlock(sc) {
    const L = sc.ladder, mx = L.revenue;
    const sB = v => (v < 0 ? "−" : "") + B(Math.abs(v));
    const w = v => Math.max(2, 100 * Math.abs(v) / mx) + "%";
    const row = (k, v, cls, opts) => el("div", {class: "r " + (cls || "")},
      el("div", {class: "k"}, k),
      el("div", {}, opts === "none" ? null : el("span", {class: "bar " + (opts || ""), style: "width:" + w(v)})),
      el("div", {class: "v num"}, sB(v)));
    const lad = el("div", {class: "ladder"},
      row("Revenue per year (" + D.finance.horizon + "-yr average)", L.revenue, "tot"),
      row("− Power at " + pct(L.util, 0) + " utilisation, $" + D.fleet.power_price_mwh + "/MWh", -L.power, "", "cost"),
      row("− Other operating costs", -L.other, "", "cost"),
      row("= EBITDA", L.ebitda, "tot"),
      row("− Depreciation (GPUs " + D.finance.compute_life + " yrs, shell " + D.finance.shell_life + " yrs)", -L.dep, "", "cost"),
      row("= Operating profit", L.op_profit, "tot", L.op_profit < 0 ? "neg" : ""),
      row("÷ Cost to build", L.capex, "last", "none"),
      el("div", {class: "note"}, "ROIC " + signed(L.roic) + " = " + sB(L.op_profit) + " ÷ " + B(L.capex) + ". Power and other operating costs are the mastersheet's site figures (assumptions); depreciation follows the two lifetimes."));
    const blk = el("div", {class: "block"}, el("h3", {}, "From revenue to return"), lad);
    // cash flows
    const cf = el("div", {class: "cf"});
    cf.append(el("h3", {}, "Cash flows behind the IRR (" + (sc.ladder.irr === null ? "n/a" : signed(sc.ladder.irr)) + ")"));
    cf.append(cashflowSvg(sc));
    blk.append(cf);
    return blk;
  }

  function cashflowSvg(sc) {
    const F = sc.ladder.flows, W = 600, H = 170, padL = 8, padR = 8, top = 22, bot = 40;
    const mx = Math.max(...F.map(Math.abs));
    const y0 = top + (H - top - bot) * (mx / (2 * mx));
    const sy = (H - top - bot) / (2 * mx);
    const n = F.length, slot = (W - padL - padR) / n, bw = Math.min(24, slot * 0.5);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    let g = `<line x1="${padL}" x2="${W - padR}" y1="${y0}" y2="${y0}" stroke="#d2d1cc" stroke-width="1"/>`;
    F.forEach((v, i) => {
      const x = padL + slot * i + slot / 2 - bw / 2, h = Math.abs(v) * sy;
      const y = v >= 0 ? y0 - h : y0;
      const c = v >= 0 ? sc.colour : "#e34948";
      const r = 4;
      const path = v >= 0
        ? `M${x},${y0} V${y + r} a${r},${r} 0 0 1 ${r},-${r} H${x + bw - r} a${r},${r} 0 0 1 ${r},${r} V${y0} Z`
        : `M${x},${y0} V${y0 + h - r} a${r},${r} 0 0 0 ${r},${r} H${x + bw - r} a${r},${r} 0 0 0 ${r},-${r} V${y0} Z`;
      g += `<path d="${path}" fill="${c}"><title>${i === 0 ? "Year 0: cost to build" : "Year " + i + ": EBITDA" + (i === n - 1 && sc.ladder.terminal ? " + book value" : "")} ${B(v)}</title></path>`;
      g += `<text x="${x + bw / 2}" y="${v >= 0 ? y - 5 : y0 + h + 14}" text-anchor="middle" font-size="11" fill="#52514e">${(v < 0 ? "−" : "") + B(Math.abs(v))}</text>`;
      g += `<text x="${x + bw / 2}" y="${H - 6}" text-anchor="middle" font-size="11" fill="#8a8985">${i === 0 ? "build" : "yr " + i}</text>`;
    });
    svg.innerHTML = g;
    return svg;
  }

  function ratePathSvg(sc) {
    const P = sc.extra.rate_path, W = 520, H = 170, left = 44, right = 16, top = 14, bot = 28;
    const refs = [["Silicon Data B200", sc.extra.sd_b200], ["Ornn B200", sc.extra.ornn_b200]].filter(r => r[1]);
    const mx = Math.max(...P, ...refs.map(r => r[1])) * 1.15;
    const n = P.length, slot = (W - left - right) / n, bw = Math.min(24, slot * 0.5);
    const Y = v => top + (H - top - bot) * (1 - v / mx);
    let g = "";
    for (let v = 0; v <= mx; v += 2) g += `<line x1="${left}" x2="${W - right}" y1="${Y(v)}" y2="${Y(v)}" stroke="${v === 0 ? "#8a8985" : "#e4e3df"}"/><text x="${left - 6}" y="${Y(v) + 4}" text-anchor="end" font-size="10.5" fill="#8a8985">$${v}</text>`;
    P.forEach((v, i) => {
      const x = left + slot * i + slot / 2 - bw / 2, y = Y(v);
      g += `<path d="M${x},${Y(0)} V${y + 4} a4,4 0 0 1 4,-4 H${x + bw - 4} a4,4 0 0 1 4,4 V${Y(0)} Z" fill="${sc.colour}"><title>Year ${i + 1}: $${v.toFixed(2)} per GPU-hour</title></path>`;
      g += `<text x="${x + bw / 2}" y="${y - 5}" text-anchor="middle" font-size="11.5" font-weight="600" fill="#0b0b0b">$${v.toFixed(2)}</text>`;
      g += `<text x="${x + bw / 2}" y="${H - 8}" text-anchor="middle" font-size="11" fill="#8a8985">yr ${i + 1}</text>`;
    });
    refs.forEach(([lab, v]) => { g += `<line x1="${left}" x2="${W - right}" y1="${Y(v)}" y2="${Y(v)}" stroke="#52514e" stroke-dasharray="4 4" stroke-width="1.2"/><text x="${W - right}" y="${Y(v) - 4}" text-anchor="end" font-size="10.5" fill="#52514e">${lab} $${v.toFixed(2)}</text>`; });
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.style.width = "100%"; svg.style.height = "auto"; svg.style.display = "block";
    svg.innerHTML = g;
    return svg;
  }

  function streamsBlock(sc) {
    const tot = sc.streams.reduce((a, s) => a + s.value, 0);
    const blk = el("div", {class: "block"}, el("h3", {}, sc.streams.length > 1 ? "Where the revenue comes from" : "Revenue"));
    const list = el("div", {class: "streams"});
    for (const s of sc.streams) {
      list.append(el("div", {class: "stream", style: "--sc:" + s.colour},
        el("div", {class: "l"}, el("i"), s.label),
        el("div", {class: "v num"}, B(s.value) + (sc.streams.length > 1 ? "  · " + pct(s.value / tot, 0) : "")),
        el("div", {class: "track"}, el("i", {style: "width:" + (100 * s.value / tot) + "%"})),
        s.formula ? el("div", {class: "f"}, s.formula) : null));
    }
    blk.append(list);
    // the input mix
    const c = sc.counts;
    blk.append(el("h3", {style: "margin-top:20px"}, "The inputs behind this page"));
    blk.append(el("div", {class: "leg", style: "gap:8px"},
      el("span", {class: "pill market"}, el("i"), c.market + " market"),
      el("span", {class: "pill assumption"}, el("i"), c.assumption + " assumption" + (c.assumption === 1 ? "" : "s")),
      el("span", {class: "pill fixed"}, el("i"), c.fixed + " fixed")));
    const notes = {
      rent: "Rent needs the fewest assumptions: the rate is what tenants pay today and what the disclosed multi-year deals cleared at. The return hinges on utilisation and on how long the kit is written off over.",
      lab: "Serving as a lab has the highest return and the most assumptions: how much of the work needs frontier models, how many tokens a chip really produces in production, and how busy the fleet is. Prices are market prices.",
      open: "Open-weight prices are set by a competitive host market, so a GPU-hour is made to earn only the year-1 rental rate plus a renter's margin: the realised throughput is backed out of the price, which is why it is an assumption.",
      aws: "AWS earns like a landlord on the Anthropic block (rent plus a share of the token dollars) and like a host on the rest. The revenue share and the size of the block are the assumptions that matter.",
    };
    blk.append(el("p", {class: "small muted", style: "margin-top:10px"}, notes[sc.key] || ""));
    if (sc.key === "lab" && sc.extra) {
      blk.append(el("p", {class: "tiny", style: "margin-top:10px"},
        int(sc.extra.frontier_gpus) + " GPUs serve closed-weight tokens (earning $" + sc.extra.frontier_rev_per_gpu_hr.toFixed(2) + " per busy GPU-hour); " +
        int(sc.extra.open_gpus) + " serve open-weight tokens ($" + sc.extra.open_rev_per_gpu_hr.toFixed(2) + ")."));
    }
    if (sc.key === "aws" && sc.extra) {
      blk.append(el("p", {class: "tiny", style: "margin-top:10px"},
        "Anthropic's models earn " + B(sc.extra.anthropic_token_rev) + " a year on the rented block; AWS keeps the rent plus " + pct(sc.extra.rev_share, 0) + " of that, and all of the open-weight revenue on its own chips."));
    }
    if (sc.key === "rent" && sc.extra) {
      blk.append(el("h3", {style: "margin-top:20px"}, "The rate path behind the $" + sc.extra.rate_avg.toFixed(2) + " average"));
      blk.append(ratePathSvg(sc));
      blk.append(el("div", {class: "cap small muted"}, "Year 1 at " + sc.extra.near_label.charAt(0).toLowerCase() + sc.extra.near_label.slice(1) + " ($" + sc.extra.rate_near.toFixed(2) + ", " + sc.extra.spot_n + " rates), converging to the contract median ($" + sc.extra.rate + ", " + sc.extra.contract_n + " disclosed deals). Dashed: today's B200 indices, Silicon Data $" + (sc.extra.sd_b200 || 0).toFixed(2) + " and Ornn $" + (sc.extra.ornn_b200 || 0).toFixed(2) + " (older part, reference only)."));
    }
    return blk;
  }

  // ---------- build page
  function buildPage() {
    const F = D.fleet, A = D.areas;
    const pg = el("section", {class: "page", id: "p_build"});
    pg.append(el("div", {class: "phead"},
      el("div", {class: "t"},
        el("h1", {}, "What it costs to build 1 GW of Blackwell"),
        el("p", {class: "what"}, "A " + int(F.site_mw) + " MW site filled with " + F.chip_label + " racks: " + int(F.gpus) + " GPUs in " + int(F.racks) + " racks. The same building is then used four ways, on the following pages."))));
    const grid = el("div", {class: "buildgrid"});
    const dc = el("div", {class: "block dc", style: "margin:0"}, el("h3", {}, "The site, and where the money goes"));
    dc.append(dcSvg());
    grid.append(dc);
    const tot = el("div", {class: "total"},
      el("div", {},
        el("div", {class: "l"}, "Total cost to build"),
        el("div", {class: "v num"}, "$" + (F.capex / 1e9).toFixed(1) + "B"),
        el("div", {class: "s"}, "$" + int(F.capex_per_gpu) + " per GPU, all-in · " + (F.mastersheet_found ? "AI mastersheet.xlsx, sheet GB300" : "fallback values (mastersheet not found)"))),
      el("div", {class: "facts"},
        el("div", {}, el("div", {class: "k"}, "GPUs"), el("div", {class: "n num"}, int(F.gpus))),
        el("div", {}, el("div", {class: "k"}, "NVL72 racks"), el("div", {class: "n num"}, int(F.racks))),
        el("div", {}, el("div", {class: "k"}, "Facility power"), el("div", {class: "n num"}, int(F.site_mw) + " MW")),
        el("div", {}, el("div", {class: "k"}, "IT power · PUE"), el("div", {class: "n num"}, int(F.it_mw) + " MW · " + F.pue.toFixed(2))),
        el("div", {}, el("div", {class: "k"}, "Power per rack"), el("div", {class: "n num"}, int(F.kw_per_rack) + " kW")),
        el("div", {}, el("div", {class: "k"}, "Electricity"), el("div", {class: "n num"}, "$" + F.power_price_mwh + "/MWh"))),
      el("div", {class: "leg", style: "margin-top:16px;color:rgba(255,255,255,.75)"}, el("span", {class: "pill assumption"}, el("i"), "Internal build estimate"), el("span", {}, "the bill of materials is the fund's own; every later page starts from it")));
    grid.append(tot);
    pg.append(grid);
    const areas = el("div", {class: "areas"});
    A.forEach((a, i) => {
      const c = el("div", {class: "area", "data-key": a.key,
        onmouseenter: () => hl(a.key, true), onmouseleave: () => hl(a.key, false)},
        el("div", {style: "display:flex;justify-content:space-between;align-items:center"}, el("span", {class: "n"}, i + 1), el("span", {class: "pill assumption", style: "font-size:10.5px"}, el("i"), "Internal estimate")),
        el("div", {class: "l"}, a.label),
        el("div", {class: "v num"}, "$" + (a.usd / 1e9).toFixed(1) + "B"),
        el("div", {class: "track"}, el("i", {style: "width:" + (100 * a.share) + "%"})),
        el("div", {class: "sh"}, pct(a.share, 0) + " of the build"),
        el("div", {class: "sub"}, a.sub),
        el("div", {class: "cells"}, a.cells.filter(Boolean).join(" · ")));
      areas.append(c);
    });
    pg.append(areas);
    // the four buttons
    const cta = el("div", {class: "cta"});
    for (const s of SC) {
      cta.append(el("button", {class: "btn", style: "--c:" + s.colour, onclick: () => show(s.key)},
        el("div", {class: "h"}, el("span", {class: "letter"}, s.letter), s.short),
        el("div", {class: "d"}, s.what),
        el("div", {class: "m"},
          el("div", {}, el("span", {}, "ROIC"), el("b", {class: "num"}, signed(s.ladder.roic))),
          el("div", {}, el("span", {}, "IRR"), el("b", {class: "num"}, s.ladder.irr === null ? "n/a" : signed(s.ladder.irr))),
          el("div", {}, el("span", {}, "Revenue / yr"), el("b", {class: "num"}, B(s.ladder.revenue)))),
        el("div", {class: "go"}, "See how it is calculated →")));
    }
    pg.append(el("h3", {style: "margin:26px 0 10px"}, "Four ways to use it · pick one"), cta, navbtns("build"));
    return pg;
  }
  function hl(key, on) {
    for (const n of document.querySelectorAll('[data-hl="' + key + '"]')) n.classList.toggle("hl", on);
    for (const n of document.querySelectorAll('.area[data-key="' + key + '"]')) n.classList.toggle("hl", on);
  }

  function dcSvg() {
    const F = D.fleet;
    const wrap = el("div");
    // a flat, stylised elevation: grid and substation on the left, the hall with two rack rows through a cutaway,
    // chillers on the roof, and one rack drawn large on the right with its cost areas numbered
    let racks = "";
    const rows = [{y: 214, x0: 292, n: 12, s: 1}, {y: 250, x0: 280, n: 13, s: 1.08}];
    for (const r of rows) {
      for (let i = 0; i < r.n; i++) {
        const x = r.x0 + i * 37 * r.s, w = 27 * r.s, h = 74 * r.s, y = r.y;
        racks += `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="2" fill="#3a3a38"/>`;
        for (let t = 0; t < 6; t++) racks += `<rect x="${x + 3}" y="${y + 5 + t * 11.5 * r.s}" width="${w - 6}" height="${7 * r.s}" rx="1" fill="#55554f"/><circle cx="${x + w - 6}" cy="${y + 8.5 + t * 11.5 * r.s}" r="1.2" fill="#6fdc8c"/>`;
      }
    }
    const marker = (n, x, y) => `<g><circle cx="${x}" cy="${y}" r="11" fill="#0b0b0b"/><text x="${x}" y="${y + 4}" text-anchor="middle" font-size="12" font-weight="700" fill="#fff">${n}</text></g>`;
    const lead = (x1, y1, x2, y2) => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#0b0b0b" stroke-width="1.2"/>`;
    const chillers = [290, 380, 470, 560, 650].map(x => `<g><rect x="${x}" y="108" width="62" height="32" rx="3" fill="#cfd4d9" stroke="#52514e" stroke-width="1.5"/><circle cx="${x + 18}" cy="124" r="10" fill="#f4f4f1" stroke="#52514e"/><circle cx="${x + 44}" cy="124" r="10" fill="#f4f4f1" stroke="#52514e"/><path d="M${x + 18} 116 v16 M${x + 10} 124 h16 M${x + 44} 116 v16 M${x + 36} 124 h16" stroke="#52514e" stroke-width="1"/></g>`).join("");
    const trays = Array.from({length: 8}, (_, t) => `<g data-hl="gpus" class="part"><rect x="8" y="${10 + t * 15}" width="74" height="11" rx="1.5" fill="#eb6834"/><text x="45" y="${18.5 + t * 15}" text-anchor="middle" font-size="8" fill="#fff" font-weight="600">GPU tray</text></g>`).join("");
    const svg = `
<svg viewBox="0 0 1000 400" xmlns="http://www.w3.org/2000/svg" font-family="-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
  <defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#eef3f8"/><stop offset="1" stop-color="#fbfbf9"/></linearGradient></defs>
  <rect x="0" y="0" width="1000" height="400" fill="url(#sky)" rx="14"/>
  <rect x="0" y="352" width="1000" height="48" fill="#e6ebe1"/>
  <line x1="0" y1="352" x2="1000" y2="352" stroke="#c9d1c2"/>
  <g stroke="#6b6b66" stroke-width="2.2" fill="none">
    <line x1="52" y1="352" x2="60" y2="120"/><line x1="76" y1="352" x2="68" y2="120"/>
    <line x1="60" y1="120" x2="68" y2="120"/><line x1="40" y1="160" x2="88" y2="160"/><line x1="36" y1="205" x2="92" y2="205"/><line x1="44" y1="250" x2="84" y2="250"/>
    <line x1="52" y1="352" x2="76" y2="290"/><line x1="76" y1="352" x2="52" y2="290"/>
  </g>
  <path d="M88 160 Q140 210 175 240" stroke="#6b6b66" stroke-width="1.4" fill="none"/>
  <path d="M92 205 Q140 245 175 266" stroke="#6b6b66" stroke-width="1.4" fill="none"/>
  <text x="64" y="106" text-anchor="middle" font-size="11.5" fill="#52514e">grid</text>
  <g data-hl="shell" class="part">
    <rect x="140" y="300" width="70" height="52" rx="3" fill="#8b8f95" stroke="#52514e"/>
    <rect x="146" y="292" width="14" height="10" fill="#6b6b66"/><rect x="166" y="292" width="14" height="10" fill="#6b6b66"/><rect x="186" y="292" width="14" height="10" fill="#6b6b66"/>
    <g stroke="#52514e" stroke-width="1"><line x1="148" y1="308" x2="148" y2="344"/><line x1="160" y1="308" x2="160" y2="344"/><line x1="172" y1="308" x2="172" y2="344"/><line x1="184" y1="308" x2="184" y2="344"/><line x1="196" y1="308" x2="196" y2="344"/></g>
    <text x="175" y="372" text-anchor="middle" font-size="11.5" fill="#52514e">substation · ${int(F.site_mw)} MW</text>
  </g>
  <line x1="210" y1="326" x2="232" y2="326" stroke="#52514e" stroke-width="2"/>
  <g data-hl="shell" class="part">
    <rect x="232" y="150" width="528" height="202" fill="#f4f4f1" stroke="#52514e" stroke-width="2"/>
    <rect x="232" y="140" width="528" height="12" fill="#dedcd6" stroke="#52514e" stroke-width="2"/>
    <rect x="248" y="166" width="496" height="186" fill="#ecece8" stroke="#c9c8c2" stroke-width="1"/>
    ${chillers}
    <text x="496" y="98" text-anchor="middle" font-size="11.5" fill="#52514e">chillers, switchgear, UPS, cabling, labour: the powered shell</text>
  </g>
  <g data-hl="other" class="part">
    <rect x="262" y="186" width="470" height="9" rx="2" fill="#b9b7b0" stroke="#8a8985" stroke-width="1"/>
    ${Array.from({length: 13}, (_, i) => `<rect x="${280 + i * 37}" y="196" width="10" height="16" fill="#7a7a74"/>`).join("")}
  </g>
  <g data-hl="gpus" class="part">${racks}</g>
  <text x="496" y="342" text-anchor="middle" font-size="12" fill="#52514e">${int(F.gpus)} GB300 GPUs in ${int(F.racks)} NVL72 racks (${int(F.kw_per_rack)} kW each) · two of the rows shown</text>
  ${marker(5, 258, 146)}${lead(269, 146, 300, 120)}
  ${marker(4, 262, 190)}
  <g transform="translate(790,150)">
    <rect x="0" y="0" width="90" height="202" rx="4" fill="#3a3a38"/>
    <text x="45" y="-8" text-anchor="middle" font-size="11.5" fill="#52514e">one NVL72 rack</text>
    ${trays}
    <g data-hl="memory" class="part"><rect x="8" y="132" width="74" height="18" rx="1.5" fill="#5598e7"/><text x="45" y="144" text-anchor="middle" font-size="8.5" fill="#fff" font-weight="600">DDR5 memory</text></g>
    <g data-hl="cpus" class="part"><rect x="8" y="154" width="74" height="16" rx="1.5" fill="#1baf7a"/><text x="45" y="165" text-anchor="middle" font-size="8.5" fill="#fff" font-weight="600">CPUs</text></g>
    <g data-hl="other" class="part"><rect x="8" y="174" width="74" height="22" rx="1.5" fill="#8a8985"/><text x="45" y="184" text-anchor="middle" font-size="7.5" fill="#fff" font-weight="600">NVLink · network</text><text x="45" y="193" text-anchor="middle" font-size="7.5" fill="#fff" font-weight="600">power delivery</text></g>
  </g>
  ${lead(880, 210, 905, 210)}${marker(1, 916, 210)}<text x="932" y="214" font-size="11.5" fill="#0b0b0b">GPUs</text>
  ${lead(880, 291, 905, 291)}${marker(2, 916, 291)}<text x="932" y="295" font-size="11.5" fill="#0b0b0b">memory</text>
  ${lead(880, 312, 905, 312)}${marker(3, 916, 312)}<text x="932" y="316" font-size="11.5" fill="#0b0b0b">CPUs</text>
  ${lead(880, 335, 905, 335)}${marker(4, 916, 335)}<text x="932" y="339" font-size="11.5" fill="#0b0b0b">other</text>
  <text x="790" y="372" font-size="11" fill="#52514e">4 also: the network spine over every row</text>
  <text x="258" y="380" font-size="11" fill="#52514e">5 the building, its power and cooling: everything that is not in a rack</text>
</svg>`;
    wrap.innerHTML = svg;
    return wrap;
  }

  // ---------- summary page
  function summaryPage() {
    const pg = el("section", {class: "page", id: "p_summary"});
    pg.append(el("div", {class: "phead"},
      el("div", {class: "t"},
        el("h1", {}, "The four ways to use 1 GW, side by side"),
        el("p", {class: "what"}, "Same building, same " + int(D.fleet.gpus) + " GPUs, same $" + (D.fleet.capex / 1e9).toFixed(1) + "B. What changes is who the customer is and how many assumptions stand between the market data and the return."))));
    const cards = el("div", {class: "cards"});
    for (const s of SC) {
      cards.append(el("div", {class: "card", style: "--c:" + s.colour, onclick: () => show(s.key)},
        el("div", {class: "h"}, el("span", {class: "letter", style: "width:26px;height:26px;font-size:13px;border-radius:7px;margin:0"}, s.letter), s.short),
        el("div", {class: "kv"},
          el("div", {}, el("div", {class: "k"}, "ROIC"), el("div", {class: "v num"}, signed(s.ladder.roic))),
          el("div", {}, el("div", {class: "k"}, "IRR"), el("div", {class: "v num"}, s.ladder.irr === null ? "n/a" : signed(s.ladder.irr))),
          el("div", {}, el("div", {class: "k"}, "Revenue / yr"), el("div", {class: "v num sm"}, B(s.ladder.revenue))),
          el("div", {}, el("div", {class: "k"}, "Per GPU-hour"), el("div", {class: "v num sm"}, "$" + s.ladder.rev_per_gpu_hr.toFixed(2)))),
        el("div", {class: "mix"}, s.drivers.map(d => el("span", {class: "pill " + d.kind, title: d.label + ": " + fmt(d.value, d.fmt) + " " + unit(d.fmt)}, el("i"), d.label.replace(/^Number of (GPUs|chips)$/, "Chips").replace("per hour per GPU", "").replace("Tokens per second per chip", "Tok/s per chip"))))));
    }
    pg.append(cards);
    const charts = el("div", {class: "charts"});
    charts.append(
      el("div", {class: "block chart", id: "ch_returns"}, el("h3", {}, "Return on the $" + (D.fleet.capex / 1e9).toFixed(1) + "B")),
      el("div", {class: "block chart", id: "ch_gpuhr"}, el("h3", {}, "Per busy GPU-hour: what it earns vs what it costs")),
      el("div", {class: "block chart", id: "ch_cum"}, el("h3", {}, "Cumulative cash flow, " + D.finance.horizon + " years")),
      el("div", {class: "block chart", id: "ch_mix"}, el("h3", {}, "How much of each answer is market data")));
    pg.append(charts);
    // table view
    const tv = el("div", {class: "block"}, el("div", {style: "display:flex;justify-content:space-between;align-items:center;margin-bottom:10px"}, el("h3", {style: "margin:0"}, "Every number, one table"),
      el("button", {class: "tvtoggle", onclick: e => { const t = $("#tvtab"); t.hidden = !t.hidden; e.target.textContent = t.hidden ? "Show table" : "Hide table"; }}, "Hide table")));
    const rows = [
      ["ROIC (" + D.finance.horizon + "-yr average)", s => signed(s.ladder.roic)], ["ROIC year 1", s => signed(s.ladder.roic_y1)], ["IRR", s => s.ladder.irr === null ? "n/a" : signed(s.ladder.irr)],
      ["Revenue per year", s => B(s.ladder.revenue)], ["Power cost", s => B(s.ladder.power)], ["Other operating costs", s => B(s.ladder.other)], ["EBITDA", s => B(s.ladder.ebitda)],
      ["EBITDA margin", s => pct(s.ladder.ebitda_margin, 0)], ["Depreciation", s => B(s.ladder.dep)], ["Operating profit", s => (s.ladder.op_profit < 0 ? "−" : "") + B(Math.abs(s.ladder.op_profit))],
      ["Revenue per GPU-hour (fleet average)", s => "$" + s.ladder.rev_per_gpu_hr.toFixed(2)], ["Payback (years)", s => s.ladder.payback_years ? s.ladder.payback_years.toFixed(1) : "never"],
      ["Utilisation", s => pct(s.ladder.util, 0)], ["Market inputs / assumptions / fixed", s => s.counts.market + " / " + s.counts.assumption + " / " + s.counts.fixed],
    ];
    const tab = el("table", {class: "tv", id: "tvtab"}, el("thead", {}, el("tr", {}, el("th", {}, ""), SC.map(s => el("th", {}, s.letter + " · " + s.short)))),
      el("tbody", {}, rows.map(([k, f]) => el("tr", {}, el("td", {}, k), SC.map(s => el("td", {class: "num"}, f(s)))))));
    tv.append(tab);
    pg.append(tv);
    pg.append(el("p", {class: "small muted", style: "margin-top:14px"},
      "The full model also runs C (the OpenAI basket: ROIC " + signed(D.also.openai.roic) + ", IRR " + signed(D.also.openai.irr) + ") and E (open-weight at the benchmark peak with no production haircut: ROIC " + signed(D.also.open_peak.roic) + "), the ceiling if the benchmarks were the whole story."));
    pg.append(navbtns("summary"));
    return pg;
  }

  function drawSummaryChart(id, fn) { const host = $("#" + id); if (!host || host.dataset.done) return; fn(host); host.dataset.done = 1; }
  function drawSummaryChars() {}
  function drawSummaryCharts() {
    drawSummaryChart("ch_returns", host => {
      // two small multiples on one axis each: ROIC and IRR by scenario, horizontal bars
      const W = 640, rowH = 34, top = 30, left = 150, right = 70, H = top + SC.length * rowH + 16;
      const draw = (metric, label) => {
        const vals = SC.map(s => s.ladder[metric] === null ? 0 : s.ladder[metric]);
        const mn = Math.min(0, ...vals), mx = Math.max(0.05, ...vals);
        const sx = (W - left - right) / (mx - mn);
        const x0 = left + (0 - mn) * sx;
        let g = `<text x="${left}" y="16" font-size="12.5" font-weight="600" fill="#52514e">${label}</text>`;
        // gridlines at clean steps
        const step = mx - mn > 0.6 ? 0.2 : 0.1;
        for (let v = Math.ceil(mn / step) * step; v <= mx + 1e-9; v += step) {
          const x = left + (v - mn) * sx;
          g += `<line x1="${x}" x2="${x}" y1="${top - 6}" y2="${H - 14}" stroke="${Math.abs(v) < 1e-9 ? "#8a8985" : "#e4e3df"}" stroke-width="1"/><text x="${x}" y="${H - 2}" text-anchor="middle" font-size="10.5" fill="#8a8985">${Math.round(100 * v)}%</text>`;
        }
        SC.forEach((s, i) => {
          const v = vals[i], y = top + i * rowH + 6, h = 22, r = 4;
          const x1 = Math.min(x0, x0 + v * sx), w = Math.max(2, Math.abs(v) * sx);
          const path = v >= 0
            ? `M${x0},${y} H${x0 + w - r} a${r},${r} 0 0 1 ${r},${r} V${y + h - r} a${r},${r} 0 0 1 -${r},${r} H${x0} Z`
            : `M${x0},${y} H${x1 + r} a${r},${r} 0 0 0 -${r},${r} V${y + h - r} a${r},${r} 0 0 0 ${r},${r} H${x0} Z`;
          g += `<text x="${left - 10}" y="${y + 15}" text-anchor="end" font-size="12.5" fill="#0b0b0b">${s.letter} · ${s.short}</text>`;
          g += `<path d="${path}" fill="${s.colour}" data-tip="${esc(s.title)}: ${label} ${signed(v)}"/>`;
          g += `<text x="${(v >= 0 ? x0 + w : x0) + 6}" y="${y + 15}" text-anchor="start" font-size="12.5" font-weight="600" fill="#0b0b0b">${signed(v)}</text>`;
        });
        return `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">${g}</svg>`;
      };
      host.insertAdjacentHTML("beforeend", draw("roic", "ROIC, " + D.finance.horizon + "-year average of (EBITDA − depreciation) ÷ cost to build") + draw("irr", "IRR, pre-tax, " + D.finance.horizon + "-year cash flows"));
      host.append(el("div", {class: "cap"}, "Bars are the scenario colours used throughout; a negative bar means the site does not earn its depreciation."));
    });
    drawSummaryChart("ch_gpuhr", host => {
      // per busy GPU-hour: revenue (scenario colour) beside cost (power + other + depreciation), grey
      const F = D.fleet, hrs = F.gpus * 8760;
      const rows = SC.map(s => ({s, rev: s.ladder.revenue / (hrs * s.ladder.util), cost: (s.ladder.power + s.ladder.other + s.ladder.dep) / (hrs * s.ladder.util)}));
      const W = 640, rowH = 54, top = 24, left = 150, right = 80, H = top + SC.length * rowH + 20;
      const mx = Math.max(...rows.map(r => Math.max(r.rev, r.cost))) * 1.08, sx = (W - left - right) / mx;
      let g = "";
      for (let v = 0; v <= mx; v += 2) g += `<line x1="${left + v * sx}" x2="${left + v * sx}" y1="${top - 6}" y2="${H - 14}" stroke="${v === 0 ? "#8a8985" : "#e4e3df"}"/><text x="${left + v * sx}" y="${H - 2}" text-anchor="middle" font-size="10.5" fill="#8a8985">$${v}</text>`;
      rows.forEach((r, i) => {
        const y = top + i * rowH;
        const bar = (v, yy, c, t) => `<path d="M${left},${yy} H${left + v * sx - 4} a4,4 0 0 1 4,4 V${yy + 14} a4,4 0 0 1 -4,4 H${left} Z" fill="${c}" data-tip="${t}"/>`;
        g += `<text x="${left - 10}" y="${y + 22}" text-anchor="end" font-size="12.5" fill="#0b0b0b">${r.s.letter} · ${r.s.short}</text>`;
        g += bar(r.rev, y + 4, r.s.colour, esc(r.s.title) + ": earns $" + r.rev.toFixed(2) + " per busy GPU-hour") + `<text x="${left + r.rev * sx + 6}" y="${y + 17}" font-size="12" font-weight="600" fill="#0b0b0b">$${r.rev.toFixed(2)}</text>`;
        g += bar(r.cost, y + 24, "#c9c8c2", "costs $" + r.cost.toFixed(2) + " per busy GPU-hour (power, other costs, depreciation)") + `<text x="${left + r.cost * sx + 6}" y="${y + 37}" font-size="12" fill="#52514e">$${r.cost.toFixed(2)} cost</text>`;
      });
      host.insertAdjacentHTML("beforeend", `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">${g}</svg>`);
      host.append(el("div", {class: "leg"}, el("span", {}, el("i", {class: "sq", style: "--sc:#0b0b0b"}), "revenue per busy GPU-hour (scenario colour)"), el("span", {}, el("i", {class: "sq", style: "--sc:#c9c8c2"}), "cost per busy GPU-hour: power + other costs + depreciation")));
      host.append(el("div", {class: "cap"}, "Rent sells a GPU-hour for less than the site's all-in cost of producing one; serving prices the same hour by the tokens it yields."));
    });
    drawSummaryChart("ch_cum", host => {
      const W = 640, H = 300, left = 70, right = 130, top = 16, bot = 30, n = D.finance.horizon;
      const series = SC.map(s => { let acc = 0; return {s, pts: s.ladder.flows.map(f => (acc += f))}; });
      const all = series.flatMap(x => x.pts);
      const mn = Math.min(...all), mx = Math.max(0, ...all);
      const sy = (H - top - bot) / (mx - mn), sx = (W - left - right) / n;
      const X = i => left + i * sx, Y = v => top + (mx - v) * sy;
      let g = "";
      const step = 1e10;
      for (let v = Math.ceil(mn / step) * step; v <= mx; v += step) g += `<line x1="${left}" x2="${W - right}" y1="${Y(v)}" y2="${Y(v)}" stroke="${v === 0 ? "#8a8985" : "#e4e3df"}"/><text x="${left - 8}" y="${Y(v) + 4}" text-anchor="end" font-size="10.5" fill="#8a8985">${v === 0 ? "0" : (v < 0 ? "−" : "") + "$" + Math.abs(v / 1e9).toFixed(0) + "B"}</text>`;
      for (let i = 0; i <= n; i++) g += `<text x="${X(i)}" y="${H - 8}" text-anchor="middle" font-size="10.5" fill="#8a8985">${i === 0 ? "build" : "yr " + i}</text>`;
      for (const {s, pts} of series) {
        const d = pts.map((v, i) => (i ? "L" : "M") + X(i) + "," + Y(v)).join("");
        g += `<path d="${d}" fill="none" stroke="${s.colour}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
        pts.forEach((v, i) => { g += `<circle cx="${X(i)}" cy="${Y(v)}" r="4" fill="${s.colour}" stroke="#fff" stroke-width="2" data-tip="${esc(s.title)}, ${i === 0 ? "at build" : "end of year " + i}: cumulative ${(v < 0 ? "−" : "") + B(Math.abs(v))}"/>`; });
        const last = pts[pts.length - 1];
        g += `<text x="${X(n) + 8}" y="${Y(last) + 4}" font-size="11.5" fill="#0b0b0b">${s.letter} ${(last < 0 ? "−" : "+") + B(Math.abs(last))}</text>`;
      }
      host.insertAdjacentHTML("beforeend", `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">${g}</svg>`);
      host.append(el("div", {class: "leg"}, SC.map(s => el("span", {}, el("i", {style: "--sc:" + s.colour}), s.letter + " · " + s.short))));
      host.append(el("div", {class: "cap"}, "Where a line crosses zero is the payback. Cash flows are pre-tax; token prices and rental rates held flat after the rental path settles."));
    });
    drawSummaryChart("ch_mix", host => {
      const W = 640, rowH = 46, top = 10, left = 150, H = top + SC.length * rowH + 10;
      let g = "";
      const cols = {market: "#008300", assumption: "#e34948", fixed: "#b5b4ae"};
      SC.forEach((s, i) => {
        const y = top + i * rowH, n = s.drivers.length, w = (W - left - 20) / n;
        g += `<text x="${left - 10}" y="${y + 20}" text-anchor="end" font-size="12.5" fill="#0b0b0b">${s.letter} · ${s.short}</text>`;
        s.drivers.forEach((d, j) => {
          g += `<rect x="${left + j * w + 1}" y="${y + 4}" width="${w - 2}" height="26" rx="4" fill="${cols[d.kind]}" opacity="${d.kind === "fixed" ? .7 : .9}" data-tip="${esc(d.label)}: ${esc(fmt(d.value, d.fmt) + " " + unit(d.fmt))} (${d.badge.toLowerCase()})"/>`;
          const short = d.label.replace(/^Number of (GPUs|chips)$/, "Chips").replace("Average rental price per hour per GPU", "Rent $/GPU-hr").replace("Tokens per second per chip", "Tok/s").replace("Token utilisation", "Util.").replace("Utilisation rate", "Util.").replace("% closed-weight tokens", "% closed").replace("% rented out to Anthropic", "% rented").replace("Anthropic revenue share", "Rev share").replace("% inference chips", "% infer.").replace("Lifetime of GPUs", "GPU life").replace("Lifetime of shell", "Shell life").replace("Hours per year", "Hours").replace("Seconds per year", "Seconds").replace("Token price", "Price");
          if (w > 44) g += `<text x="${left + j * w + w / 2}" y="${y + 21}" text-anchor="middle" font-size="${w > 70 ? 11 : 9.5}" fill="#fff" font-weight="600">${short}</text>`;
        });
      });
      host.insertAdjacentHTML("beforeend", `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">${g}</svg>`);
      host.append(el("div", {class: "leg"}, el("span", {}, el("i", {class: "sq", style: "--sc:#008300"}), "market data"), el("span", {}, el("i", {class: "sq", style: "--sc:#e34948"}), "assumption"), el("span", {}, el("i", {class: "sq", style: "--sc:#b5b4ae"}), "fixed constant")));
      host.append(el("div", {class: "cap"}, "One cell per driver box, in page order. The cost to build itself is an internal estimate on every page."));
    });
    for (const n of document.querySelectorAll("[data-tip]")) {
      n.addEventListener("mouseenter", e => { tipOn(n.dataset.tip); tipMove(e); });
      n.addEventListener("mousemove", tipMove);
      n.addEventListener("mouseleave", tipOff);
    }
  }

  // ---------- assemble, and rebuild whenever the dials change
  function buildPages(keepScroll) {
    main.innerHTML = "";
    pages = {};
    pages.build = buildPage();
    main.append(pages.build);
    for (const s of SC) { pages[s.key] = scenarioPage(s); main.append(pages[s.key]); }
    pages.summary = summaryPage();
    main.append(pages.summary);
    const fr = D.freshness;
    $("#foot-left").textContent = "Built " + GENERATED + " from the Blackwell ROIC tracker's inputs" + (selfCheckText()) + ". Market data read: OpenRouter " + fr.openrouter + " (week of " + fr.openrouter_week + "), InferenceX " + fr.inferencex + " (newest run " + fr.inferencex_newest_run + "), rental quotes " + fr.rental + ", Anthropic prices " + fr.lab_prices + ", Silicon Data token indices " + (fr.token_index || "n/a") + "; capital from " + fr.mastersheet + ".";
    show(keepScroll ? current : (location.hash.slice(1) || "build"), false, keepScroll);
    if (openKey && mback.classList.contains("on")) openSource(openKey);
  }
  function selfCheckText() {
    try {
      const R0 = compute(INPUTS, DEFAULTS);
      const pairs = [[R0.rent, PY.rent], [R0.serves.anthropic, PY.anthropic], [R0.serve_open, PY.open], [R0.serve_aws, PY.aws]];
      let worst = 0;
      for (const [a, b] of pairs) for (const k of Object.keys(b)) { if (a[k] === null || b[k] === null) { if (a[k] !== b[k]) worst = 1; continue; } worst = Math.max(worst, Math.abs(a[k] - b[k]) / Math.max(1e-9, Math.abs(b[k]))); }
      return worst < 1e-5 ? " (page arithmetic matches the Python builder at default dials)" : " (WARNING: page arithmetic differs from the Python builder, worst gap " + worst.toExponential(1) + "; rebuild)";
    } catch (e) { return ""; }
  }

  // ---------- the live link to the full model
  // The link to dashboard.html: this page sits in the project's infographic/ folder, so the full model is one folder up
  // (on disk and on GitHub Pages alike). A build with BLACKWELL_ROIC_DIR set records an absolute location instead, for
  // a copy of this page kept somewhere else.
  function dashboardUrl() {
    if (/\/infographic\/[^/]*$/i.test(decodeURIComponent(location.pathname))) return "../dashboard.html";
    if (typeof ROIC_DIR === "string" && ROIC_DIR) {
      const p = ROIC_DIR.replace(/\\/g, "/").replace(/\/$/, "") + "/dashboard.html";
      return (p.startsWith("/") ? "file://" : "file:///") + p.split("/").map(x => encodeURIComponent(x).replace(/%3A/gi, ":")).join("/");
    }
    return "../dashboard.html";
  }
  for (const a of document.querySelectorAll('a[href="../dashboard.html"]')) a.href = dashboardUrl();
  const LINK_KEY = "blackwell-roic.dials";
  const STAMP = [INPUTS.openrouter.read_on, INPUTS.rental_meta.read_on, INPUTS.throughput_meta.read_on, INPUTS.lab_prices_meta.read_on, (INPUTS.fleet.mastersheet || {}).fingerprint || ""].join("|");
  const DIAL_LABELS = {
    rent_util: ["Rental utilisation", "pct"], serve_util: ["Token utilisation", "pct"], training_share: ["Training share", "pct"], aws_rev_share: ["AWS revenue share", "pct"],
    power_price: ["Power $/MWh", "raw"], other_opex: ["Other opex", "usd"], life: ["Horizon (yrs)", "raw"], compute_life: ["GPU life (yrs)", "raw"], shell_life: ["Shell life (yrs)", "raw"],
    compute_residual: ["GPU residual", "pct"], shell_residual: ["Shell residual", "pct"], rent_decline: ["Rent decline /yr", "pct"], token_decline: ["Token price decline /yr", "pct"],
    rental_basis: ["Long-term rental basis", "raw"], near_basis: ["Near-term rental basis", "raw"], rental_rate_override: ["Long-term rate (typed)", "usd2"], near_rate_override: ["Near-term rate (typed)", "usd2"],
    converge_years: ["Convergence (yrs)", "raw"], spot_years: ["Years at the year-1 rate", "raw"], split_mode: ["Split mode", "raw"], premium_tolerance: ["Premium tolerance", "raw"],
    closed_override: ["Closed share override (B)", "pct"], closed_override_openai: ["Closed share override (C)", "pct"], price_basis: ["Price basis", "raw"], interactivity_basis: ["Interactivity basis", "raw"],
    interactivity: ["Interactivity tok/s/user", "raw"], workload: ["Benchmark shape", "raw"], tps_realisation: ["Throughput realisation", "raw"], implied_rate: ["Implied-rate basis", "raw"], renter_roic: ["Renter's ROIC", "pct"],
    frontier_realisation: ["Frontier realisation basis", "raw"], frontier_derate: ["Frontier derate", "raw"], realisation: ["Frontier price realisation", "pct"], cache_hit_rate: ["Cache-hit override", "pct"],
    throughput_scope: ["Throughput scope", "raw"], volumes: ["Volume basis", "raw"],
  };
  const fmtDial = (v, k) => v === null || v === undefined ? "none" : k === "pct" ? Math.round(100 * v) + "%" : k === "usd2" ? "$" + (+v).toFixed(2) : k === "usd" ? B(v) : String(v);
  function dialDiffs(d) {
    const out = [];
    for (const k in DIAL_LABELS) {
      const a = DEFAULTS[k], b = d[k];
      const same = (a === b) || (a === null && b === undefined) || (a === undefined && b === null) || (typeof a === "number" && typeof b === "number" && Math.abs(a - b) < 1e-9);
      if (!same) out.push(DIAL_LABELS[k][0] + " " + fmtDial(a, DIAL_LABELS[k][1]) + " \u2192 " + fmtDial(b, DIAL_LABELS[k][1]));
    }
    return out;
  }
  let live = null, pending = null, ignoredAt = null, received = null, fromStore = false, lastError = null;
  const strip = $("#live");
  function renderStatus() {
    strip.innerHTML = "";
    if (!live) {
      strip.className = "live idle";
      strip.append(el("span", {class: "dotl"}), el("span", {}, "Default settings. Open the full model (dashboard.html) in another window and move any dial: this page follows it live."),
        el("a", {href: dashboardUrl(), target: "_blank", rel: "noopener"}, "Open the full model \u2197"));
      return;
    }
    const diffs = dialDiffs(DIALS);
    const t = new Date(live.at);
    strip.className = "live on";
    strip.append(el("span", {class: "dotl"}), el("b", {}, "Following the full model"), el("span", {class: "muted"}, " \u00b7 last dial move " + t.toLocaleTimeString() + " \u00b7 received " + (received ? received.toLocaleTimeString() : "at page load") + (fromStore ? " (from memory)" : "")));
    if (lastError) strip.append(el("span", {class: "warn"}, "Update failed: " + lastError));
    strip.append(el("span", {class: "diffs"}, diffs.length ? diffs.map(x => el("span", {class: "diff"}, x)) : el("span", {class: "muted"}, "all dials at their defaults")));
    if (live.stamp !== STAMP) strip.append(el("span", {class: "warn"}, "The full model was built from different data than this page; run update.py so both share the same inputs."));
    strip.append(el("button", {class: "tvtoggle", onclick: useDefaults}, "Show defaults"));
  }
  function applyLink(msg, viaStore) {
    if (!msg || !msg.dials || msg.at === ignoredAt) return;
    ignoredAt = null;
    live = msg; received = new Date(); fromStore = !!viaStore;
    DIALS = Object.assign({}, DEFAULTS, msg.dials);
    if (pending) clearTimeout(pending);
    pending = setTimeout(() => {
      pending = null;
      try { D = computeData(DIALS); SC = D.scenarios; byKey = Object.fromEntries(SC.map(s => [s.key, s])); lastError = null; buildPages(true); }
      catch (e) { lastError = (e && e.message) || String(e); console.error("infographic update failed", e); }
      renderStatus();
    }, 60);
  }
  function useDefaults() {
    ignoredAt = live ? live.at : null;
    live = null; DIALS = Object.assign({}, DEFAULTS);
    D = computeData(DIALS); SC = D.scenarios; byKey = Object.fromEntries(SC.map(s => [s.key, s]));
    buildPages(true); renderStatus();
  }
  function readStored() { try { const v = localStorage.getItem(LINK_KEY); return v ? JSON.parse(v) : null; } catch (e) { return null; } }
  window.addEventListener("storage", e => { if (e.key === LINK_KEY && e.newValue) { try { applyLink(JSON.parse(e.newValue)); } catch (x) {} } });
  try { const ch = new BroadcastChannel("blackwell-roic"); ch.onmessage = e => applyLink(e.data); } catch (e) {}
  const pollStore = () => { const m = readStored(); if (m && (!live || m.at !== live.at)) applyLink(m, true); };
  setInterval(pollStore, 1000);
  window.addEventListener("focus", pollStore);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) pollStore(); });

  buildPages(false);
  const stored = readStored();
  if (stored) applyLink(stored, true); else renderStatus();
})();
