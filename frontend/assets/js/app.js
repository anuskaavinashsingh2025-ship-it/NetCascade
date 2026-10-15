import { api, ApiError } from "./api.js";
import { autoLayout, TopologyCanvas } from "./graph.js";
import { DEVICE_SYMBOLS, deviceIcon, icon, LOGO } from "./icons.js";

// ------------------------------------------------------------------ constants
const TYPES = ["pc", "switch", "router", "server"];
const TYPE_INFO = {
  pc: { name: "PC", role: "End device", long: "PC (End Device)", prefix: "PC", plural: ["PC", "PCs"] },
  switch: { name: "Switch", role: "Layer 2 device", long: "Switch (Layer 2 Device)", prefix: "SW", plural: ["switch", "switches"] },
  router: { name: "Router", role: "Layer 3 device", long: "Router (Layer 3 Device)", prefix: "R", plural: ["router", "routers"] },
  server: { name: "Server", role: "Destination device", long: "Server (Destination Device)", prefix: "SRV", plural: ["server", "servers"] },
};
const MODE_LABEL = { basic: "Basic Network", redundant: "Redundant Network", campus: "Campus Network" };
const MODE_PREFIX = { basic: "A simple network", redundant: "A redundant network", campus: "A campus network" };

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------------------------------------------------------------------- state
const state = {
  topo: null,
  conn: null,
  positions: {},
  selection: null,
  detail: null,          // GET /devices/<id> for the selected device
  tab: "details",
  history: { undo: [], redo: [] },
  loadError: null,
  page: "overview",
  tool: "select",
  sim: null,            // GET /simulation result (the backend runs it on a copy of the topology)
  rankings: null,       // devices + links merged from /analysis/rankings, highest impact first
  rankFilter: "all",
  analysisOpen: true,
  scenarioData: null,   // GET /scenarios for the loaded topology
  scenarioSel: null,    // selected scenario id
  compareWith: "",      // scenario id to compare against
  comparison: null,     // { key, loading, data, error } from /simulate/compare
  running: null,        // id of the scenario whose run is in flight
};

const canvases = {};
const cv = () => canvases[state.page] || canvases.overview;
const B = (key) => $$(`[data-bind="${key}"]`);
const setBind = (key, prop, value) => B(key).forEach((n) => (n[prop] = value));

// ===================================================================== helpers
function hydrateIcons(root = document) {
  $$("[data-icon]", root).forEach((n) => {
    if (n.dataset.hydrated) return;
    n.innerHTML = icon(n.dataset.icon, Number(n.dataset.size) || 20);
    n.dataset.hydrated = "1";
  });
}

function toast(message, kind = "success") {
  const t = document.createElement("div");
  t.className = `toast ${kind}`;
  t.setAttribute("role", kind === "error" ? "alert" : "status");
  t.textContent = message;
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), kind === "error" ? 6000 : 3200);
}

const plural = (n, [one, many]) => `${n} ${n === 1 ? one : many}`;
const countPhrase = (byType, joiner) => {
  const parts = TYPES.filter((t) => byType[t]).map((t) => plural(byType[t], TYPE_INFO[t].plural));
  if (!parts.length) return "";
  if (joiner === "and" && parts.length > 1) return `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}`;
  return parts.join(", ");
};
const fmtBandwidth = (v) => (v >= 1000 ? `${+(v / 1000).toFixed(2)} Gbps` : `${+v.toFixed(2)} Mbps`);
const fmtLatency = (v) => `${+v.toFixed(3)} ms`;
const linkKey = (a, b) => [a, b].sort().join("\u0000");

function deviceById(id) { return state.topo?.devices.find((d) => d.id === id); }
function linkById(id) { return state.topo?.links.find((l) => l.id === id); }
function linksOf(id) { return state.topo.links.filter((l) => l.source === id || l.target === id); }
function servers() { return state.topo.devices.filter((d) => d.type === "server").map((d) => d.id); }

function nextId(type) {
  const prefix = TYPE_INFO[type].prefix;
  const used = new Set(state.topo.devices.map((d) => d.id));
  let n = 1;
  while (used.has(`${prefix}${n}`)) n++;
  return `${prefix}${n}`;
}

function deviceStatus(id) {
  const d = deviceById(id);
  const conn = state.conn;
  if (!d || !conn) return { cls: "off", label: "Unknown" };
  if (conn.isolated_devices.includes(id)) return { cls: "off", label: "Isolated", note: "No links connected" };
  if (d.type === "pc") {
    const lost = conn.unreachable_required_pairs.filter((p) => p.client === id).map((p) => p.server);
    if (lost.length) return { cls: "warn", label: "Unreachable", note: `Cannot reach ${lost.join(", ")}` };
  }
  if (d.type === "server") {
    const lost = conn.unreachable_required_pairs.filter((p) => p.server === id).map((p) => p.client);
    if (lost.length) return { cls: "warn", label: "Partly unreachable", note: `Not reachable from ${lost.join(", ")}` };
  }
  return { cls: "ok", label: "Active" };
}

// ================================================================== positions
function posKey() { return `netcascade.positions.${state.topo.source || "custom"}.${state.topo.name}`; }

function loadPositions() {
  try { return JSON.parse(localStorage.getItem(posKey()) || "{}"); } catch { return {}; }
}
function savePositions() {
  try { localStorage.setItem(posKey(), JSON.stringify(state.positions)); } catch { /* storage unavailable */ }
}

function ensurePositions(relayout = false) {
  const { devices, links } = state.topo;
  const stored = relayout ? {} : { ...loadPositions(), ...state.positions };
  const missing = devices.filter((d) => !stored[d.id]);
  let pos = {};
  if (relayout || missing.length > devices.length / 2) {
    pos = autoLayout(devices, links);
  } else {
    devices.forEach((d) => { if (stored[d.id]) pos[d.id] = stored[d.id]; });
    for (const d of missing) {                       // place next to an already-placed neighbour
      const nb = linksOf(d.id).map((l) => (l.source === d.id ? l.target : l.source)).map((n) => pos[n]).filter(Boolean);
      const base = nb.length ? { x: nb.reduce((s, p) => s + p.x, 0) / nb.length, y: nb.reduce((s, p) => s + p.y, 0) / nb.length } : { x: 0, y: 0 };
      pos[d.id] = { x: base.x + 120, y: base.y + 40 };
    }
  }
  state.positions = pos;
  savePositions();
}

// ==================================================================== loading
async function refresh({ fit = false, relayout = false } = {}) {
  try {
    const [topo, conn, sim, scen] = await Promise.all([api.topology(), api.connectivity(), api.simulation(), api.scenarios()]);
    state.topo = topo;
    state.conn = conn;
    state.sim = sim.result;
    state.scenarioData = scen;
    state.loadError = null;
  } catch (e) {
    state.loadError = e;
    renderAll();
    toast(e.message, "error");
    return;
  }
  ensurePositions(relayout);
  const sel = state.selection;
  if (sel && !(sel.kind === "device" ? deviceById(sel.id) : linkById(sel.id))) state.selection = null;
  renderAll();
  if (fit) requestAnimationFrame(() => cv().fit());
  if (state.page === "topology") loadRankings();
  if (state.selection?.kind === "device") await loadDetail();
}

let detailToken = 0;
async function loadDetail() {
  const sel = state.selection;
  if (sel?.kind !== "device") { state.detail = null; return; }
  const token = ++detailToken;
  try {
    const d = await api.device(sel.id);
    if (token !== detailToken) return;
    state.detail = d;
  } catch (e) {
    if (token !== detailToken) return;
    state.detail = null;
    toast(e.message, "error");
  }
  renderInfo();
}

function select(sel, { center = false } = {}) {
  state.selection = sel;
  state.detail = null;
  if (sel?.kind === "device") state.tab = state.tab || "details";
  Object.values(canvases).forEach((c) => c.setSelection(sel));
  renderInfo();
  renderRanking();
  if (center && sel) centerOn(sel);
  if (sel?.kind === "device") loadDetail();
}

function centerOn(sel) {
  const r = cv().svg.getBoundingClientRect();
  let p;
  if (sel.kind === "device") p = state.positions[sel.id];
  else {
    const l = linkById(sel.id);
    const a = state.positions[l.source], b = state.positions[l.target];
    p = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  }
  if (!p) return;
  cv().view.x = r.width / 2 - p.x * cv().view.k;
  cv().view.y = r.height / 2 - p.y * cv().view.k;
  cv()._applyView();
}

// ================================================================== rendering
function renderAll() {
  renderMode();
  renderCards();
  renderScenarios();      // picks the default scenario before the preview canvas draws it
  renderCanvas();
  renderInfo();
  renderAnalysis();
  renderRanking();
  renderSimControls();
  updateHistoryButtons();
}

function renderMode() {
  const src = state.topo?.source;
  $$("[data-mode]").forEach((b) => {
    const active = b.dataset.mode === src;
    b.classList.toggle("active", active);
    b.setAttribute("aria-selected", active);
  });
}

function networkTitle() {
  const t = state.topo;
  return MODE_LABEL[t.source] || t.name;
}

function networkDescription() {
  const t = state.topo;
  if (!t.devices.length) return "No devices yet. Drag devices from the palette to build a network.";
  return `${MODE_PREFIX[t.source] || "A network"} with ${countPhrase(t.stats.by_type, "and")}.`;
}

function renderCards() {
  const t = state.topo;
  const connIcon = (ok) => B("c-conn-icon").forEach((n) => {
    n.className = `card-icon ${ok ? "green" : "amber"}`;
    n.innerHTML = `<span class="status-dot ${ok ? "ok" : "warn"}">${icon(ok ? "check" : "alert", 22)}</span>`;
  });
  if (!t) {
    setBind("c-devices", "textContent", "–");
    setBind("c-links", "textContent", "–");
    setBind("c-conn", "textContent", state.loadError ? "Backend unavailable" : "Loading…");
    setBind("c-conn-sub", "textContent", state.loadError ? "Start it with: python -m backend" : "");
    connIcon(false);
    return;
  }
  const s = t.stats, c = state.conn;
  setBind("c-devices", "textContent", s.device_count);
  setBind("c-devices-sub", "textContent", s.device_count ? `${countPhrase(s.by_type)}.` : "No devices yet");
  setBind("c-links", "textContent", s.link_count);
  setBind("c-links-sub", "textContent", s.link_count ? "All links active" : "No links yet");

  let ok, title, sub;
  const unreachable = c.unreachable_required_pairs.length;
  if (!s.device_count) { ok = false; title = "Empty network"; sub = "Add devices to check connectivity"; }
  else if (unreachable) {
    ok = false; title = "Disconnected";
    sub = `${plural(unreachable, ["client–server path", "client–server paths"])} unreachable · ${plural(c.components.length, ["component", "components"])}`;
  } else if (!c.required_pair_count) {
    ok = s.connected; title = s.connected ? "Connected" : "Disconnected";
    sub = `No client–server pairs to check · ${plural(c.components.length, ["component", "components"])}`;
  } else {
    ok = true; title = "Connected";
    sub = s.by_type.server === 1 ? "All clients can reach server" : "All clients can reach their servers";
    if (c.isolated_devices.length) sub += ` · ${plural(c.isolated_devices.length, ["isolated device", "isolated devices"])}`;
  }
  setBind("c-conn", "textContent", title);
  setBind("c-conn-sub", "textContent", sub);
  connIcon(ok);
  setBind("c-net", "textContent", networkTitle());
  setBind("c-net-sub", "textContent", networkDescription());
}

function renderCanvas() {
  const t = state.topo;
  B("canvas-empty").forEach((n) => (n.hidden = !t || t.devices.length > 0));
  const isolated = new Set(state.conn?.isolated_devices || []);
  const devices = t ? t.devices.map((d) => ({ ...d, _isolated: isolated.has(d.id) })) : [];
  for (const [name, c] of Object.entries(canvases)) {
    if (name === "scenarios") {
      const sc = currentScenario();
      c.selection = sc && sc.status !== "completed" ? scenarioTargetSel(sc) : null;   // highlight the planned target
      c.overlay = sc?.status === "completed" ? overlayFrom(sc.result) : null;
    } else {
      c.selection = state.selection;
      c.overlay = name === "topology" ? simOverlay() : null;
    }
    c.setData(devices, t ? t.links : [], t ? state.positions : {});
  }
}

// ---------------------------------------------------------------- info panel
function renderInfo() {
  const box = state.page === "topology" ? $("#t-info") : $("#info");
  (box.id === "info" ? $("#t-info") : $("#info")).innerHTML = "";   // one panel at a time: no duplicate ids
  if (!state.topo) {
    box.innerHTML = `<div class="info-head"><h2>Topology Information</h2></div>
      <div class="rows"><p class="empty-note">${state.loadError ? esc(state.loadError.message) : "Loading topology…"}</p></div>`;
    return;
  }
  const sel = state.selection;
  if (sel?.kind === "device" && deviceById(sel.id)) box.innerHTML = deviceInfoHtml(deviceById(sel.id));
  else if (sel?.kind === "link" && linkById(sel.id)) box.innerHTML = linkInfoHtml(linkById(sel.id));
  else box.innerHTML = topologyInfoHtml();
  hydrateIcons(box);
}

const row = (label, value, { edit, info, muted } = {}) => `
  <div class="row">
    <div>
      <div class="row-label">${label}${info ? `<span title="${esc(info)}" aria-label="${esc(info)}">${icon("info", 17)}</span>` : ""}</div>
      <div class="row-value${muted ? " muted" : ""}">${value}</div>
    </div>
    ${edit ? `<button class="icon-btn" data-edit="${edit}" title="Edit" aria-label="Edit ${esc(label)}">${icon("pencil", 20)}</button>` : ""}
  </div>`;

const deviceChip = (id) => `<button class="chip" data-goto-device="${esc(id)}">${esc(id)}</button>`;

function statusHtml(st) {
  return `<span class="status-line"><span class="dot ${st.cls}"></span><span>${esc(st.label)}</span></span>${st.note ? `<div class="conn-sub" style="margin-top:6px">${esc(st.note)}</div>` : ""}`;
}

function topologyInfoHtml() {
  const t = state.topo, c = state.conn, s = t.stats;
  const counts = TYPES.map((ty) => `
    <div class="type-count">${deviceIcon(ty, 38)}<div><strong>${s.by_type[ty]}</strong><span>${TYPE_INFO[ty].plural[1].replace(/^./, (m) => m.toUpperCase())}</span></div></div>`).join("");
  const comps = c.components.length
    ? c.components.map((comp, i) => `<div class="conn-sub" style="margin-top:${i ? 10 : 4}px">Component ${i + 1} · ${comp.length} device${comp.length === 1 ? "" : "s"}</div><div class="chips">${comp.map(deviceChip).join("")}</div>`).join("")
    : `<span class="muted">None</span>`;
  const unreachable = c.unreachable_required_pairs;
  return `
    <div class="info-head"><h2>Topology Information</h2></div>
    <div class="info-scroll">
      <div class="hero">
        <span class="card-icon blue hero-art">${icon("topology", 34)}</span>
        <div><h3>${esc(networkTitle())}</h3><div class="hero-sub">${esc(networkDescription())}</div>
          <span class="pill ${t.modified ? "info" : "ok"}">${icon(t.modified ? "pencil" : "check", 16)}${t.modified ? "Edited" : "Original"}</span></div>
      </div>
      <div class="rows">
        ${row("Devices", `${s.device_count}<div class="type-counts">${counts}</div>`)}
        ${row("Links", `${s.link_count}`)}
        ${row("Connectivity", statusHtml(unreachable.length ? { cls: "warn", label: "Disconnected", note: `${unreachable.length} unreachable client–server path(s)` } : s.connected || !s.device_count ? { cls: s.device_count ? "ok" : "off", label: s.device_count ? "Connected" : "Empty" } : { cls: "warn", label: "Partly disconnected" }))}
        ${row(`Components (${c.components.length})`, comps)}
        ${c.isolated_devices.length ? row("Isolated Devices", `<div class="chips">${c.isolated_devices.map(deviceChip).join("")}</div>`) : ""}
        ${unreachable.length ? row("Unreachable Paths", unreachable.map((p) => `${esc(p.client)} → ${esc(p.server)}`).join("<br>")) : ""}
        ${row("Client–Server Pairs", `${c.required_pair_count}`, { info: "Each PC must reach the servers in its 'requires' list (all servers by default)." })}
      </div>
    </div>
    ${t.modified ? `<div class="info-actions"><button class="btn" data-action-info="restore">${icon("restore", 17)}Restore original</button></div>` : ""}`;
}

function deviceInfoHtml(d) {
  const st = simStatus(d.id) || deviceStatus(d.id);
  const detail = state.detail?.id === d.id ? state.detail : null;
  const neighbors = linksOf(d.id).map((l) => (l.source === d.id ? l.target : l.source)).sort();
  const tab = state.tab;
  const tabs = ["details", "connections", "properties"].map((k) =>
    `<button class="tab ${tab === k ? "active" : ""}" data-tab="${k}" role="tab" aria-selected="${tab === k}">${k[0].toUpperCase() + k.slice(1)}</button>`).join("");

  let body = "";
  if (tab === "details") {
    let req = "";
    if (d.type === "pc") {
      const all = servers();
      const val = d.requires ? d.requires.map(esc).join(", ") : all.length ? `${all.map(esc).join(", ")} (all)` : "All servers (none in topology)";
      req = row("Required Servers", val, { edit: "requires", info: "Servers this PC must be able to reach. By default, every server." });
    } else if (d.type === "server") {
      const by = detail ? detail.required_by : null;
      req = row("Required By", by === null ? "…" : by.length ? `<div class="chips">${by.map(deviceChip).join("")}</div>` : "No clients", { muted: by !== null && !by.length });
    }
    body = `<div class="rows">
      ${row("Device Name", esc(d.name), { edit: "name" })}
      ${row("Device Type", TYPE_INFO[d.type].name, { edit: "type" })}
      ${row("IP Address", d.ip_address ? esc(d.ip_address) : "Not assigned", { edit: "ip_address", muted: !d.ip_address })}
      ${req}
      ${row("Connected To", neighbors.length ? `<div class="chips" style="margin-top:0">${neighbors.map(deviceChip).join("")}</div>` : "No connections", { muted: !neighbors.length })}
      ${row("Status", statusHtml(st))}
    </div>`;
  } else if (tab === "connections") {
    const items = linksOf(d.id).map((l) => {
      const other = l.source === d.id ? l.target : l.source;
      const od = deviceById(other);
      return `<div class="conn-item">
        <div class="conn-main">${deviceIcon(od.type, 40)}<div><button class="linkish" data-goto-device="${esc(other)}">${esc(other)}</button>
          <div class="conn-sub">${TYPE_INFO[od.type].name} · ${fmtBandwidth(l.bandwidth_mbps)} · ${fmtLatency(l.latency_ms)}</div></div></div>
        <button class="btn" data-goto-link="${esc(l.id)}">Link</button></div>`;
    }).join("");
    body = `<div class="rows">${items || `<p class="empty-note">No links. Use the link tool to connect this device.</p>`}</div>`;
  } else {
    const attrs = Object.entries(d.attributes).filter(([k]) => k !== "requires");
    body = `<div class="rows">
      <table class="prop-table"><tbody>
        <tr><td>ID</td><td>${esc(d.id)}</td></tr>
        <tr><td>Type</td><td>${TYPE_INFO[d.type].long}</td></tr>
        <tr><td>Links</td><td>${d.degree}</td></tr>
        ${attrs.map(([k, v]) => `<tr><td>${esc(k)}</td><td style="display:flex;justify-content:space-between;gap:8px"><span>${esc(typeof v === "object" ? JSON.stringify(v) : v)}</span>
          <button class="icon-btn subtle" data-remove-attr="${esc(k)}" aria-label="Remove ${esc(k)}" title="Remove">${icon("x", 15)}</button></td></tr>`).join("")}
      </tbody></table>
      <form class="field-row" id="attr-form" style="margin-top:14px;grid-template-columns:1fr 1fr auto;align-items:end">
        <div class="field"><label for="attr-k">Property</label><input id="attr-k" placeholder="e.g. room" required></div>
        <div class="field"><label for="attr-v">Value</label><input id="attr-v" placeholder="e.g. B12"></div>
        <button class="btn" type="submit">Add</button>
      </form>
    </div>`;
  }

  return `
    ${infoHead("Device Information")}
    <div class="info-scroll">
      <div class="hero">
        <span class="hero-art">${deviceIcon(d.type, 104)}</span>
        <div><h3>${esc(d.id)}</h3><div class="hero-sub">${TYPE_INFO[d.type].long}</div>
          <span class="pill ${st.cls}">${icon(st.cls === "ok" ? "user" : "alert", 16)}${esc(st.label)}</span></div>
      </div>
      <div class="tabs" role="tablist">${tabs}</div>
      ${body}
    </div>
    ${infoFooter()}`;
}

function linkInfoHtml(l) {
  const a = deviceById(l.source), b = deviceById(l.target);
  const ls = linkStatus(l);
  const attrs = Object.entries(l.attributes);
  const endpoint = (d) => `<div class="conn-main" style="margin-top:2px">${deviceIcon(d.type, 36)}<div><button class="linkish" data-goto-device="${esc(d.id)}">${esc(d.id)}</button><div class="conn-sub">${TYPE_INFO[d.type].name}${d.ip_address ? ` · ${esc(d.ip_address)}` : ""}</div></div></div>`;
  return `
    ${infoHead("Link Information")}
    <div class="info-scroll">
      <div class="hero">
        <span class="card-icon purple hero-art">${icon("link", 34)}</span>
        <div><h3>${esc(l.source)} ↔ ${esc(l.target)}</h3><div class="hero-sub">Network link</div>
          <span class="pill ${ls.cls}">${icon(ls.cls === "fail" ? "alert" : "check", 16)}${esc(ls.label)}</span></div>
      </div>
      <div class="rows">
        ${row("Endpoint A", endpoint(a))}
        ${row("Endpoint B", endpoint(b))}
        ${row("Bandwidth", fmtBandwidth(l.bandwidth_mbps), { edit: "bandwidth_mbps" })}
        ${row("Latency", fmtLatency(l.latency_ms), { edit: "latency_ms" })}
        ${attrs.length ? row("Properties", `<table class="prop-table"><tbody>${attrs.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(typeof v === "object" ? JSON.stringify(v) : v)}</td></tr>`).join("")}</tbody></table>`) : ""}
        ${row("Status", statusHtml(ls))}
      </div>
    </div>
    ${infoFooter()}`;
}

// ============================================================ undo / redo
function updateHistoryButtons() {
  $('[data-action="undo"]').disabled = !state.history.undo.length;
  $('[data-action="redo"]').disabled = !state.history.redo.length;
  $('[data-action="undo"]').title = state.history.undo.length ? `Undo ${state.history.undo.at(-1).label} (⌘Z)` : "Nothing to undo";
  $('[data-action="redo"]').title = state.history.redo.length ? `Redo ${state.history.redo.at(-1).label} (⇧⌘Z)` : "Nothing to redo";
}

function clearHistory() { state.history = { undo: [], redo: [] }; updateHistoryButtons(); }

async function exec(cmd) {
  await cmd.do();                     // throws on API error; nothing recorded
  state.history.undo.push(cmd);
  state.history.redo = [];
  await refresh();
}

async function undo() {
  const cmd = state.history.undo.pop();
  if (!cmd) return;
  try {
    await cmd.undo();
    state.history.redo.push(cmd);
    toast(`Undone: ${cmd.label}`, "info");
  } catch (e) {
    toast(`Could not undo ${cmd.label}: ${e.message}`, "error");
  }
  await refresh();
}

async function redo() {
  const cmd = state.history.redo.pop();
  if (!cmd) return;
  try {
    await cmd.do();
    state.history.undo.push(cmd);
    toast(`Redone: ${cmd.label}`, "info");
  } catch (e) {
    toast(`Could not redo ${cmd.label}: ${e.message}`, "error");
  }
  await refresh();
}

// Commands -----------------------------------------------------------------
function cmdAddDevice(body, pos) {
  return {
    label: `add ${body.id}`,
    do: async () => { await api.createDevice(body); state.positions[body.id] = pos; savePositions(); },
    undo: async () => { await api.deleteDevice(body.id); },
  };
}

async function cmdDeleteDevice(id) {
  const d = await api.device(id);
  const pos = state.positions[id];
  const { requires, ...attributes } = d.attributes;
  const body = { id: d.id, type: d.type, name: d.name, ip_address: d.ip_address, attributes };
  if (requires) body.requires = requires;
  const links = d.links.map((l) => ({ source: l.source, target: l.target, bandwidth_mbps: l.bandwidth_mbps, latency_ms: l.latency_ms, attributes: l.attributes }));
  return {
    label: `delete ${id}`,
    do: async () => { await api.deleteDevice(id); },
    undo: async () => {
      await api.createDevice(body);
      for (const l of links) await api.createLink(l);
      if (pos) { state.positions[id] = pos; savePositions(); }
    },
  };
}

function cmdEditDevice(d, patch) {
  const inverse = {};
  for (const k of Object.keys(patch)) {
    if (k === "attributes") {
      inverse.attributes = {};
      for (const ak of Object.keys(patch.attributes)) inverse.attributes[ak] = d.attributes[ak] ?? null;
    } else if (k === "requires") inverse.requires = d.requires ?? null;
    else inverse[k] = d[k] ?? null;
  }
  return {
    label: `edit ${d.id}`,
    do: async () => { await api.updateDevice(d.id, patch); },
    undo: async () => { await api.updateDevice(d.id, inverse); },
  };
}

function cmdAddLink(body) {
  return {
    label: `link ${body.source}–${body.target}`,
    do: async () => { await api.createLink(body); },
    undo: async () => { await api.deleteLink(body.source, body.target); },
  };
}

function cmdDeleteLink(l) {
  const body = { source: l.source, target: l.target, bandwidth_mbps: l.bandwidth_mbps, latency_ms: l.latency_ms, attributes: l.attributes };
  return {
    label: `delete link ${l.id}`,
    do: async () => { await api.deleteLink(l.source, l.target); },
    undo: async () => { await api.createLink(body); },
  };
}

function cmdEditLink(l, patch) {
  const inverse = {};
  for (const k of Object.keys(patch)) {
    if (k === "attributes") {
      inverse.attributes = {};
      for (const ak of Object.keys(patch.attributes)) inverse.attributes[ak] = l.attributes[ak] ?? null;
    } else inverse[k] = l[k];
  }
  return {
    label: `edit link ${l.id}`,
    do: async () => { await api.updateLink(l.source, l.target, patch); },
    undo: async () => { await api.updateLink(l.source, l.target, inverse); },
  };
}

function cmdPositions(label, before, after) {
  return {
    label,
    do: async () => { state.positions = { ...after }; savePositions(); },
    undo: async () => { state.positions = { ...before }; savePositions(); },
  };
}

// =================================================================== modals
let modalSubmit = null;
let modalReturnFocus = null;

function openModal({ title, html, submitLabel = "Save", danger = false, onSubmit, focus }) {
  modalReturnFocus = document.activeElement;
  $("#modal-title").textContent = title;
  const form = $("#modal-form");
  form.innerHTML = `${html}<div class="form-error" hidden></div>
    <div class="modal-actions"><button type="button" class="btn" data-close>Cancel</button>
    <button type="submit" class="btn ${danger ? "danger-solid" : "primary"}">${esc(submitLabel)}</button></div>`;
  modalSubmit = onSubmit;
  $("#modal").hidden = false;
  hydrateIcons($("#modal"));
  requestAnimationFrame(() => (form.querySelector(focus || "input:not([readonly]),select,button[type=submit]"))?.focus());
}

function closeModal() {
  $("#modal").hidden = true;
  modalSubmit = null;
  modalReturnFocus?.focus?.();
}

function showFormError(msg) {
  const box = $("#modal-form .form-error");
  box.textContent = msg;
  box.hidden = false;
}

function deviceFormHtml(d, { create }) {
  const srv = servers();
  const req = d.requires;
  return `
    <div class="field-row">
      <div class="field"><label for="f-id">Device ID</label><input id="f-id" name="id" value="${esc(d.id)}" ${create ? "" : "readonly"} maxlength="64" autocomplete="off"></div>
      <div class="field"><label for="f-type">Type</label><select id="f-type" name="type">${TYPES.map((t) => `<option value="${t}" ${t === d.type ? "selected" : ""}>${TYPE_INFO[t].name}</option>`).join("")}</select></div>
    </div>
    <div class="field"><label for="f-name">Name</label><input id="f-name" name="name" value="${esc(create ? "" : d.name)}" placeholder="Defaults to the ID" autocomplete="off"></div>
    <div class="field"><label for="f-ip">IP address</label><input id="f-ip" name="ip_address" value="${esc(d.ip_address || "")}" placeholder="e.g. 192.168.1.20 (optional)" autocomplete="off"></div>
    <div class="field" id="f-req-wrap" ${d.type === "pc" ? "" : "hidden"}>
      <label>Required servers</label>
      <div class="checks">
        <label><input type="radio" name="req-mode" value="all" ${req ? "" : "checked"}> All servers (default)</label>
        <label><input type="radio" name="req-mode" value="some" ${req ? "checked" : ""}> Only these servers:</label>
        ${srv.length ? srv.map((s) => `<label style="padding-left:24px"><input type="checkbox" name="req" value="${esc(s)}" ${req?.includes(s) ? "checked" : ""}> ${esc(s)}</label>`).join("") : `<span class="hint" style="padding-left:24px">No servers in this topology yet.</span>`}
      </div>
    </div>`;
}

function bindDeviceForm() {
  const form = $("#modal-form");
  form.type.addEventListener("change", () => { $("#f-req-wrap").hidden = form.type.value !== "pc"; });
  $$('input[name="req"]', form).forEach((cb) => cb.addEventListener("change", () => { if (cb.checked) form.querySelector('input[value="some"]').checked = true; }));
}

function readRequires(form) {
  if (form.type.value !== "pc" || form.querySelector('input[name="req-mode"]:checked')?.value !== "some") return null;
  const picked = $$('input[name="req"]:checked', form).map((c) => c.value);
  if (!picked.length) throw new ApiError("Choose at least one server, or select “All servers”.", 0);
  return picked;
}

function openCreateDevice(type, pos) {
  const draft = { id: nextId(type), type, name: "", ip_address: "", requires: null };
  openModal({
    title: `Add ${TYPE_INFO[type].name}`,
    html: deviceFormHtml(draft, { create: true }),
    submitLabel: "Add device",
    focus: "#f-id",
    onSubmit: async (form) => {
      const body = { id: form.id.value.trim(), type: form.type.value };
      if (form.name.value.trim()) body.name = form.name.value.trim();
      if (form.ip_address.value.trim()) body.ip_address = form.ip_address.value.trim();
      const requires = readRequires(form);
      if (requires) body.requires = requires;
      await exec(cmdAddDevice(body, pos));
      select({ kind: "device", id: body.id });
      toast(`${body.id} added`);
    },
  });
  bindDeviceForm();
}

function openEditDevice(id, focusField) {
  const d = deviceById(id);
  if (!d) return;
  const focusMap = { name: "#f-name", ip_address: "#f-ip", type: "#f-type", requires: 'input[name="req-mode"]:checked' };
  openModal({
    title: `Edit ${d.id}`,
    html: deviceFormHtml(d, { create: false }),
    focus: focusMap[focusField] || "#f-name",
    onSubmit: async (form) => {
      const patch = {};
      const name = form.name.value.trim() || d.id;
      if (name !== d.name) patch.name = name;
      const ip = form.ip_address.value.trim() || null;
      if (ip !== (d.ip_address || null)) patch.ip_address = ip;
      if (form.type.value !== d.type) patch.type = form.type.value;
      const requires = readRequires(form);
      if (JSON.stringify(requires) !== JSON.stringify(d.requires ?? null)) patch.requires = requires;
      if (!Object.keys(patch).length) return;
      await exec(cmdEditDevice(d, patch));
      toast(`${d.id} updated`);
    },
  });
  bindDeviceForm();
}

function openEditLink(id, focusField) {
  const l = linkById(id);
  if (!l) return;
  openModal({
    title: `Edit link ${l.source} ↔ ${l.target}`,
    html: `<div class="field-row">
      <div class="field"><label for="f-bw">Bandwidth (Mbps)</label><input id="f-bw" name="bandwidth_mbps" type="number" min="0" step="any" value="${l.bandwidth_mbps}"></div>
      <div class="field"><label for="f-lat">Latency (ms)</label><input id="f-lat" name="latency_ms" type="number" min="0" step="any" value="${l.latency_ms}"></div>
    </div><p class="hint" style="margin:0;color:var(--muted);font-size:12.5px">Both values must be positive numbers.</p>`,
    focus: focusField === "latency_ms" ? "#f-lat" : "#f-bw",
    onSubmit: async (form) => {
      const patch = {};
      for (const k of ["bandwidth_mbps", "latency_ms"]) {
        const raw = form[k].value.trim();
        const v = raw === "" ? NaN : Number(raw);
        if (v !== l[k]) patch[k] = Number.isFinite(v) ? v : raw;   // let the API report invalid values
      }
      if (!Object.keys(patch).length) return;
      await exec(cmdEditLink(l, patch));
      toast(`Link ${l.id} updated`);
    },
  });
}

function confirmDelete(sel) {
  if (sel.kind === "device") {
    const d = deviceById(sel.id);
    const n = linksOf(sel.id).length;
    openModal({
      title: `Delete ${d.id}?`,
      html: `<p class="modal-text">This removes the ${d.type === "pc" ? "PC" : d.type} ${esc(d.id)}${n ? ` and its ${plural(n, ["link", "links"])}` : ""}. You can undo this.</p>`,
      submitLabel: "Delete", danger: true,
      onSubmit: async () => {
        const cmd = await cmdDeleteDevice(d.id);
        await exec(cmd);
        select(null);
        toast(`${d.id} deleted`);
      },
    });
  } else {
    const l = linkById(sel.id);
    openModal({
      title: "Delete link?",
      html: `<p class="modal-text">This removes the link between ${esc(l.source)} and ${esc(l.target)}. You can undo this.</p>`,
      submitLabel: "Delete", danger: true,
      onSubmit: async () => { await exec(cmdDeleteLink(l)); select(null); toast(`Link ${l.id} deleted`); },
    });
  }
}

// ================================================================= actions
async function createLink(a, b) {
  try {
    await exec(cmdAddLink({ source: a, target: b }));
    toast(`Linked ${a} ↔ ${b}`);
  } catch (e) {
    toast(e.message, "error");
  }
}

async function switchMode(mode) {
  if (state.topo?.source === mode && !state.topo.modified) return;
  const go = async () => {
    const buttons = $$("[data-mode]");
    buttons.forEach((b) => (b.disabled = true));
    try {
      await api.loadTopology(mode);
      clearHistory();
      state.selection = null;
      state.positions = {};
      state.rankings = null;
      Object.values(canvases).forEach((c) => (c.fitted = false));
      state.scenarioSel = null;
      state.compareWith = "";
      state.comparison = null;
      await refresh({ fit: true });
    } catch (e) {
      toast(e.message, "error");
    } finally {
      buttons.forEach((b) => (b.disabled = false));
    }
  };
  if (state.topo?.modified) {
    openModal({
      title: `Switch to ${MODE_LABEL[mode]}?`,
      html: `<p class="modal-text">Your edits to the current topology will be discarded and the ${esc(MODE_LABEL[mode])} will be loaded from the backend.</p>`,
      submitLabel: "Switch network",
      onSubmit: go,
    });
  } else {
    await go();
  }
}

function setTool(tool) {
  state.tool = tool;
  $$("[data-tool]").forEach((b) => b.classList.toggle("active", b.dataset.tool === tool));
  $$("[data-tool-sim]").forEach((b) => b.classList.toggle("active", b.dataset.toolSim === tool));
  Object.values(canvases).forEach((c) => c.setMode(tool));
  const hints = {
    link: "Click a device, then another device to connect them. Esc to finish.",
    "fail-device": "Click a device to simulate its failure. Esc to cancel.",
    "fail-link": "Click a link to simulate its failure. Esc to cancel.",
  };
  B("canvas-hint").forEach((h) => { h.hidden = !hints[tool]; h.textContent = hints[tool] || ""; });
}

function editSelection() {
  const sel = state.selection;
  if (!sel) return toast("Select a device or link to edit.", "info");
  if (sel.kind === "device") openEditDevice(sel.id); else openEditLink(sel.id);
}

function deleteSelection() {
  if (!state.selection) return toast("Select a device or link to delete.", "info");
  confirmDelete(state.selection);
}

async function runAutoLayout() {
  if (!state.topo?.devices.length) return;
  const before = { ...state.positions };
  const after = autoLayout(state.topo.devices, state.topo.links);
  await exec(cmdPositions("auto layout", before, after));
  requestAnimationFrame(() => cv().fit());
}

// ============================================================== simulation
function simOverlay() { return overlayFrom(state.sim); }

function overlayFrom(s) {
  if (!s) return null;
  const altEdges = new Set();
  for (const p of s.alternate_paths) {
    p.alternate_path.slice(1).forEach((n, i) => altEdges.add(linkKey(p.alternate_path[i], n)));
  }
  return {
    failedNode: s.kind === "device" ? s.component : null,
    failedLink: s.kind === "link" ? linkKey(s.component.source, s.component.target) : null,
    affected: new Set(s.affected_clients),
    cutoff: new Set(s.disconnected_devices),
    altEdges,
  };
}

/** Status of a device under the current simulation (Topology page only), or null when unaffected. */
function simStatus(id) {
  const s = state.page === "topology" ? state.sim : null;
  if (!s) return null;
  if (s.kind === "device" && s.component === id) return { cls: "fail", label: "Failed", note: "Simulated failure" };
  const lost = s.lost_pairs.filter((p) => p.client === id).map((p) => p.server);
  if (lost.length) return { cls: "warn", label: "Affected", note: `Lost connection to ${lost.join(", ")}` };
  if (s.disconnected_devices.includes(id)) return { cls: "warn", label: "Cut off", note: "Disconnected from the main network" };
  const from = s.lost_pairs.filter((p) => p.server === id).map((p) => p.client);
  if (from.length) return { cls: "warn", label: "Unreachable", note: `Unreachable from ${from.join(", ")}` };
  return null;
}

function linkStatus(l) {
  const s = state.page === "topology" ? state.sim : null;
  if (s?.kind === "link" && linkKey(s.component.source, s.component.target) === linkKey(l.source, l.target)) {
    return { cls: "fail", label: "Failed", note: "Simulated failure" };
  }
  if (s?.kind === "device" && (l.source === s.component || l.target === s.component)) {
    return { cls: "fail", label: "Down", note: `${s.component} has failed` };
  }
  if (s && simOverlay().altEdges.has(linkKey(l.source, l.target))) return { cls: "ok", label: "Active", note: "Carries rerouted traffic" };
  return { cls: "ok", label: "Active" };
}

function infoHead(title) {
  if (state.page !== "topology") {
    return `<div class="info-head"><h2>${title}</h2><button class="icon-btn" data-close-info aria-label="Close">${icon("x", 22)}</button></div>`;
  }
  return `<div class="info-head"><h2>Component Information</h2><div class="info-head-tools">
    <button class="icon-btn" data-action-info="edit" title="Edit" aria-label="Edit component">${icon("pencil", 18)}</button>
    <button class="icon-btn danger-ic" data-action-info="delete" title="Delete" aria-label="Delete component">${icon("trash", 18)}</button>
    <button class="icon-btn" data-close-info title="Close" aria-label="Close">${icon("x", 20)}</button></div></div>`;
}

function infoFooter() {
  if (state.page === "topology") return "";
  return `<div class="info-actions"><button class="btn" data-action-info="edit">${icon("pencil", 17)}Edit</button><button class="btn danger" data-action-info="delete">${icon("trash", 17)}Delete</button></div>`;
}

function renderSimControls() {
  $$('[data-sim="reset"]').forEach((b) => {
    b.disabled = !state.sim;
    b.title = state.sim ? `Clear the simulated failure of ${state.sim.label}` : "No simulation running";
  });
  const noDevices = !state.topo?.devices.length;
  $$('[data-sim="device"]').forEach((b) => (b.disabled = noDevices));
  $$('[data-sim="link"]').forEach((b) => (b.disabled = !state.topo?.links.length));
}

function startSim(kind) {
  const sel = state.selection;
  if (kind === "device" && sel?.kind === "device") return simulateDevice(sel.id);
  if (kind === "link" && sel?.kind === "link") return simulateLink(sel.id);
  setTool(state.tool === `fail-${kind}` ? "select" : `fail-${kind}`);
}

async function runSimulation(call, sel) {
  try {
    state.sim = await call();
  } catch (e) {
    toast(e.message, "error");
    return;
  }
  setTool("select");
  state.analysisOpen = true;
  select(sel);
  renderCanvas();
  renderAnalysis();
  renderSimControls();
  const s = state.sim;
  toast(`${s.label} failed: ${s.severity} impact · ${s.affected_client_count}/${s.total_clients} clients affected`, "info");
}

function simulateDevice(id) {
  return runSimulation(() => api.simulateDevice(id), { kind: "device", id });
}

function simulateLink(id) {
  const l = linkById(id);
  if (!l) return toast(`Unknown link ${id}`, "error");
  return runSimulation(() => api.simulateLink(l.source, l.target), { kind: "link", id });
}

async function resetSim() {
  try {
    await api.resetSimulation();
  } catch (e) {
    toast(e.message, "error");
    return;
  }
  state.sim = null;
  renderCanvas();
  renderInfo();
  renderAnalysis();
  renderSimControls();
  renderRanking();
  toast("Simulation cleared. Topology edits are kept.", "info");
}

const SEV_CLASS = { Low: "low", Medium: "medium", High: "high", Critical: "critical" };
const fmtScore = (v) => (Number.isInteger(v) ? `${v}` : v.toFixed(2));
const fmtMs = (ms) => (ms < 1 ? `${ms.toFixed(3)} ms` : `${ms.toFixed(1)} ms`);

function renderAnalysis() {
  const panel = $("#t-analysis"), body = $("#t-analysis-body");
  panel.classList.toggle("collapsed", !state.analysisOpen);
  $("#t-analysis-toggle").setAttribute("aria-expanded", state.analysisOpen);
  $("#t-analysis-toggle").title = state.analysisOpen ? "Collapse" : "Expand";
  const s = state.sim;
  if (!s) {
    body.innerHTML = `<div class="an-empty">${icon("info", 22)}<div><strong>No simulation running</strong>
      <p>Select a device or link and choose <b>Simulate Device Failure</b> or <b>Simulate Link Failure</b>, or double-click a row in the ranking.</p></div></div>`;
    return;
  }
  const sev = SEV_CLASS[s.severity];
  const pct = s.total_clients ? fmtScore(Math.round((s.affected_client_count / s.total_clients) * 10000) / 100) : "0";
  const lost = s.lost_pairs.length
    ? `<ul class="an-pairs">${s.lost_pairs.map((p) => `<li><span>${esc(p.client)}</span><span class="x">${icon("x", 14)}</span><span>${esc(p.server)}</span></li>`).join("")}</ul>`
    : `<p class="an-note">No client lost its connection.</p>`;
  let alt;
  if (s.alternate_paths.length) {
    alt = `<ul class="an-paths">${s.alternate_paths.map((p) => `<li><b>${esc(p.client)} → ${esc(p.server)}</b><span>${p.alternate_path.map(esc).join(" → ")}</span></li>`).join("")}</ul>`;
  } else if (s.lost_pairs.length) {
    alt = `<p class="an-note">No alternate path available.${s.is_single_point_of_failure ? ` ${esc(s.label)} is a single point of failure.` : ""}</p>`;
  } else {
    alt = `<p class="an-note">No client–server path used ${esc(s.label)}, so nothing needed rerouting.</p>`;
  }
  body.innerHTML = `
    <div class="an-target">Simulated ${s.kind} failure: <button class="linkish" data-an-goto>${esc(s.kind === "link" ? `${s.component.source} ↔ ${s.component.target}` : s.component)}</button>${s.execution_ms != null ? `<span class="an-time" title="Server-side time to analyse this failure">Analysed in ${fmtMs(s.execution_ms)}</span>` : ""}</div>
    <div class="an-metric"><span class="an-ic blue">${icon("users", 22)}</span><div><div class="an-label">Affected Clients</div><div class="an-value sev-text-${sev}">${s.affected_client_count} / ${s.total_clients} (${pct}%)</div></div></div>
    <div class="an-metric"><span class="an-ic orange">${icon("target", 22)}</span><div><div class="an-label">Impact Score</div><div class="an-value sev-text-${sev}">${fmtScore(s.impact_score)} / 100</div></div></div>
    <div class="an-metric"><span class="an-ic red">${icon("alert", 22)}</span><div><div class="an-label">Severity</div><div class="an-value big sev-text-${sev}">${esc(s.severity)}</div></div></div>
    <h3 class="an-h">Lost Communication <span class="an-count">${s.lost_pairs.length}</span></h3>
    ${lost}
    <h3 class="an-h">Alternate Paths <span title="Client–server pairs whose shortest path used the failed component but that still connect over another route." aria-label="About alternate paths">${icon("info", 15)}</span><span class="an-count">${s.alternate_paths.length}</span></h3>
    ${alt}
    ${s.disconnected_devices.length ? `<h3 class="an-h">Cut Off From Network</h3><div class="chips">${s.disconnected_devices.map((d) => `<button class="chip" data-goto-device="${esc(d)}">${esc(d)}</button>`).join("")}</div>` : ""}`;
  const goto = $("[data-an-goto]", body);
  goto.addEventListener("click", () => select(s.kind === "device" ? { kind: "device", id: s.component } : { kind: "link", id: s.label }, { center: true }));
  $$("[data-goto-device]", body).forEach((b) => b.addEventListener("click", () => select({ kind: "device", id: b.dataset.gotoDevice }, { center: true })));
}

let rankToken = 0;
async function loadRankings() {
  if (!state.topo) return;
  const token = ++rankToken;
  try {
    const r = await api.rankings();
    if (token !== rankToken) return;
    state.rankings = [...r.devices, ...r.links].sort((a, b) =>
      b.impact_score - a.impact_score || b.lost_pair_count - a.lost_pair_count || a.label.localeCompare(b.label, undefined, { numeric: true }));
  } catch (e) {
    if (token !== rankToken) return;
    state.rankings = [];
    toast(e.message, "error");
  }
  renderRanking();
}

function renderRanking() {
  const body = $("#t-ranking-body");
  if (!body) return;
  const all = state.rankings || [];
  const spofCount = all.filter((r) => r.is_single_point_of_failure).length;
  $$("[data-rank-filter]").forEach((b) => {
    const active = b.dataset.rankFilter === state.rankFilter;
    b.classList.toggle("active", active);
    b.setAttribute("aria-pressed", active);
    b.querySelector(".rk-n").textContent = b.dataset.rankFilter === "spof" ? spofCount : all.length;
  });
  if (!state.topo || state.rankings === null) {
    body.innerHTML = `<tr><td colspan="7" class="rk-empty">Calculating criticality…</td></tr>`;
    return;
  }
  const rows = state.rankFilter === "spof" ? all.filter((r) => r.is_single_point_of_failure) : all;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="7" class="rk-empty">${state.rankFilter === "spof"
      ? "No single points of failure: every working client keeps a path to its servers after any single failure."
      : "Add devices to rank their criticality."}</td></tr>`;
    return;
  }
  const total = state.topo.stats.by_type.pc;
  const sel = state.selection, sim = state.sim;
  body.innerHTML = rows.map((r, i) => {
    const isLink = r.kind === "link";
    const id = isLink ? r.label : r.component;
    const dev = isLink ? null : deviceById(r.component);
    const selected = sel && sel.kind === r.kind && sel.id === id;
    const simulated = sim && sim.kind === r.kind && sim.label === r.label;
    const art = isLink ? `<span class="rk-link-ic">${icon("link", 14)}</span>` : deviceIcon(dev?.type || "pc", 26);
    const name = isLink ? `${esc(r.component.source)} ↔ ${esc(r.component.target)}` : esc(r.component);
    const sev = SEV_CLASS[r.severity];
    return `<tr data-rank-kind="${r.kind}" data-rank-id="${esc(id)}" tabindex="0" class="${selected ? "selected" : ""}${simulated ? " simulated" : ""}" title="Click to select · double-click to simulate this failure">
      <td>${i + 1}</td>
      <td><span class="rk-comp">${art}<span>${name}</span>${simulated ? `<span class="rk-sim">simulated</span>` : ""}</span></td>
      <td>${isLink ? "Link" : TYPE_INFO[dev?.type]?.name || ""}</td>
      <td class="${r.affected_client_count ? `sev-text-${sev}` : ""}">${r.affected_client_count} / ${total}</td>
      <td class="${r.affected_client_count ? `sev-text-${sev}` : ""}">${fmtScore(r.impact_score)}</td>
      <td><span class="sev sev-${sev}">${r.severity}</span></td>
      <td><span class="spof ${r.is_single_point_of_failure ? "yes" : "no"}">${r.is_single_point_of_failure ? "Yes" : "No"}</span></td>
    </tr>`;
  }).join("");
}

// ================================================================ scenarios
const STATUS_INFO = {
  completed: { label: "Completed", cls: "ok", icon: "checkcircle" },
  not_run: { label: "Not run", cls: "off", icon: "circle" },
  outdated: { label: "Outdated", cls: "warn", icon: "clock" },
  invalid: { label: "Target missing", cls: "fail", icon: "alert" },
};
const SEV_RANK = { Low: 0, Medium: 1, High: 2, Critical: 3 };
const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }) : "Never");

function scenarios() { return state.scenarioData?.scenarios || []; }
function scenarioById(id) { return scenarios().find((s) => s.id === id) || null; }
function currentScenario() { return scenarioById(state.scenarioSel); }
function scenarioTargetSel(sc) {
  return sc.kind === "device" ? { kind: "device", id: sc.target.device_id } : { kind: "link", id: `${sc.target.source}--${sc.target.target}` };
}
function scenarioTypeLabel(sc) { return sc.kind === "link" ? "Link Failure" : "Device Failure"; }
function scenarioShortTarget(sc) { return sc.kind === "link" ? `${sc.target.source} – ${sc.target.target}` : sc.target.device_id; }
function scenarioArt(sc, size = 44) {
  if (sc.kind === "link") return `<span class="sc-link-art">${icon("link", Math.round(size * 0.5))}</span>`;
  const d = deviceById(sc.target.device_id);
  return d ? deviceIcon(d.type, size) : `<span class="sc-link-art">${icon("alert", Math.round(size * 0.5))}</span>`;
}
function statusOf(sc) { return state.running === sc.id ? { label: "Running…", cls: "info", icon: "clock" } : STATUS_INFO[sc.status]; }

function renderScenarios() {
  if (!$("#s-list")) return;
  const data = state.scenarioData;
  const sm = data?.summary;
  setBind("s-total", "textContent", sm ? sm.total : "–");
  setBind("s-total-sub", "textContent", sm ? `${plural(sm.by_kind.device, ["device failure", "device failures"])}, ${plural(sm.by_kind.link, ["link failure", "link failures"])}` : " ");
  setBind("s-completed", "textContent", sm ? sm.completed : "–");
  setBind("s-pending", "textContent", sm ? sm.pending : "–");
  setBind("s-notrun", "textContent", sm ? sm.not_run : "–");
  if (!scenarioById(state.scenarioSel)) state.scenarioSel = scenarios()[0]?.id || null;
  if (state.compareWith && (!scenarioById(state.compareWith) || state.compareWith === state.scenarioSel)) state.compareWith = "";
  renderScenarioList();
  renderScenarioDetails();
  renderScenarioResults();
  renderComparison();
  const sc = currentScenario();
  $("#s-preview-title").textContent = sc ? `Topology - ${sc.name}` : "Topology";
  const note = $("#s-canvas-note");
  note.hidden = !sc || sc.status === "completed";
  if (sc && sc.status !== "completed") {
    note.textContent = sc.status === "invalid" ? `Target ${scenarioShortTarget(sc)} no longer exists in this topology`
      : sc.status === "outdated" ? "Topology changed since the last run. Run again to refresh the preview"
      : `Target ${scenarioShortTarget(sc)} is highlighted. Run the scenario to see its impact`;
  }
}

function renderScenarioList() {
  const list = $("#s-list");
  const items = scenarios();
  if (!items.length) {
    list.innerHTML = `<p class="empty-note sc-empty">No scenarios for this network yet. Use <b>New Scenario</b> to create one.</p>`;
    return;
  }
  list.innerHTML = items.map((sc) => {
    const st = statusOf(sc);
    const sel = sc.id === state.scenarioSel;
    const sev = sc.status === "completed" ? ` · ${sc.result.severity}` : "";
    return `<div class="sc-item${sel ? " selected" : ""}" role="option" aria-selected="${sel}" tabindex="0" data-scenario="${esc(sc.id)}">
      <span class="sc-art">${scenarioArt(sc)}</span>
      <div class="sc-text"><strong>${esc(sc.name)}</strong><small>${sc.kind === "link" ? "Link" : "Device"} failure • ${esc(scenarioShortTarget(sc))}</small></div>
      <span class="sc-status st-${st.cls}${state.running === sc.id ? " spin" : ""}" title="${esc(st.label + sev)}" aria-label="${esc(st.label + sev)}">${icon(st.icon, 20)}</span>
    </div>`;
  }).join("");
}

function renderScenarioDetails() {
  const box = $("#s-details");
  const sc = currentScenario();
  if (!sc) {
    box.innerHTML = `<div class="sc-details-head"><h2 class="sc-h">Scenario Details</h2></div><p class="empty-note sc-pad">Select a scenario, or create one with <b>New Scenario</b>.</p>`;
    return;
  }
  const st = statusOf(sc);
  const runnable = sc.status !== "invalid" && !state.running;
  const runLabel = state.running === sc.id ? "Running…" : sc.result ? "Run Scenario Again" : "Run Scenario";
  box.innerHTML = `
    <div class="sc-details-head"><h2 class="sc-h">Scenario Details</h2>
      <div class="sc-menu-wrap"><button class="icon-btn" data-sc="menu" aria-haspopup="menu" aria-expanded="false" aria-label="More actions">${icon("more", 20)}</button>
        <div class="sc-menu" role="menu" hidden>
          <button role="menuitem" data-sc="edit">${icon("pencil", 16)}Rename / edit description</button>
          <button role="menuitem" data-sc="delete" class="danger">${icon("trash", 16)}Delete scenario</button>
        </div></div></div>
    <div class="sc-pad">
      <div class="sc-field"><div class="sc-label">Scenario Name</div>
        <div class="sc-box sc-name"><span>${esc(sc.name)}</span><button class="icon-btn" data-sc="edit" aria-label="Rename scenario" title="Rename">${icon("pencil", 17)}</button></div></div>
      <div class="sc-field"><div class="sc-label">Type</div><div class="sc-value sc-type">${scenarioArt(sc, 26)}${scenarioTypeLabel(sc)}</div></div>
      <div class="sc-field"><div class="sc-label">${sc.kind === "link" ? "Target Link" : "Target Device"}</div><div class="sc-value">${esc(sc.target_label)}</div></div>
      <div class="sc-field"><div class="sc-label">Description</div><div class="sc-box sc-desc${sc.description ? "" : " muted"}">${esc(sc.description || "No description")}</div></div>
      <div class="sc-two">
        <div><div class="sc-label">Status</div><div class="sc-value"><span class="status-line"><span class="dot ${st.cls === "info" ? "ok" : st.cls}"></span>${esc(st.label)}</span></div></div>
        <div><div class="sc-label">Last Run</div><div class="sc-value${sc.last_run_at ? "" : " muted"}">${esc(fmtTime(sc.last_run_at))}</div></div>
      </div>
      <button class="btn primary sc-run" data-sc="run" ${runnable ? "" : "disabled"} ${sc.status === "invalid" ? 'title="The target no longer exists in this topology"' : ""}>${icon("play", 17)}${runLabel}</button>
      <button class="btn sc-copy" data-sc="copy" ${state.running ? "disabled" : ""}>${icon("copy", 17)}Copy Scenario</button>
    </div>`;
}

function affectedRows(sc) {
  const r = sc.result;
  const rows = [];
  const typeOf = (id) => TYPE_INFO[deviceById(id)?.type]?.name || "Device";
  const artOf = (id) => (deviceById(id) ? deviceIcon(deviceById(id).type, 22) : "");
  if (r.kind === "device") rows.push({ art: artOf(r.component), name: r.component, type: typeOf(r.component), cls: "fail", status: "Failed", reason: "Simulated failure" });
  else rows.push({ art: `<span class="rk-link-ic">${icon("link", 13)}</span>`, name: `${r.component.source} – ${r.component.target}`, type: "Link", cls: "fail", status: "Failed", reason: "Simulated failure" });
  const servers = [...new Set(r.lost_pairs.map((p) => p.server))].filter((s) => s !== r.component);
  for (const s of servers) {
    const from = r.lost_pairs.filter((p) => p.server === s).map((p) => p.client);
    rows.push({ art: artOf(s), name: s, type: typeOf(s), cls: "fail", status: "Unreachable", reason: `No route from ${from.join(", ")}` });
  }
  for (const c of r.affected_clients.filter((c) => c !== r.component)) {
    const lost = r.lost_pairs.filter((p) => p.client === c).map((p) => p.server);
    rows.push({ art: artOf(c), name: c, type: typeOf(c), cls: "warn", status: "No connectivity", reason: `Cannot reach ${lost.join(", ")}` });
  }
  const listed = new Set(rows.map((x) => x.name));
  for (const d of r.disconnected_devices.filter((d) => !listed.has(d))) {
    rows.push({ art: artOf(d), name: d, type: typeOf(d), cls: "warn", status: "Cut off", reason: "Disconnected from the main network" });
  }
  return rows;
}

function renderScenarioResults() {
  const box = $("#s-results");
  const sc = currentScenario();
  const head = (extra = "") => `<div class="sc-results-head"><h2 class="sc-h">Scenario Results</h2>${extra}</div>`;
  if (!sc) { box.innerHTML = head() + `<p class="empty-note sc-pad">No scenario selected.</p>`; return; }
  if (state.running === sc.id) { box.innerHTML = head() + `<div class="sc-results-empty">${icon("clock", 28)}<strong>Running ${esc(sc.name)}…</strong></div>`; return; }
  if (sc.status === "invalid" && !sc.result) {
    box.innerHTML = head() + `<div class="sc-results-empty">${icon("alert", 28)}<strong>Target ${esc(scenarioShortTarget(sc))} no longer exists</strong><span>Restore the topology or create a new scenario.</span></div>`;
    return;
  }
  if (!sc.result) {
    box.innerHTML = head() + `<div class="sc-results-empty">${icon("play", 28)}<strong>${esc(sc.name)} has not been run yet</strong>
      <span>Run it to analyse affected clients, impact and connectivity.</span><button class="btn primary" data-sc="run" ${state.running ? "disabled" : ""}>${icon("play", 16)}Run Scenario</button></div>`;
    return;
  }
  const r = sc.result;
  const sev = SEV_CLASS[r.severity];
  const pct = r.total_clients ? fmtScore(Math.round((r.affected_client_count / r.total_clients) * 10000) / 100) : "0";
  const banner = sc.status === "outdated"
    ? `<div class="sc-banner">${icon("clock", 16)}The topology changed after this run (${esc(fmtTime(sc.last_run_at))}). These are the results from that run. <button class="linkish" data-sc="run">Run again</button></div>`
    : sc.status === "invalid" ? `<div class="sc-banner">${icon("alert", 16)}The target was removed from the topology. These results are from the last run (${esc(fmtTime(sc.last_run_at))}).</div>` : "";
  const lostText = r.lost_pairs.length ? r.lost_pairs.map((p) => `${p.client}–${p.server}`).join(", ") : "No connections lost";
  const tiles = `
    <div class="sc-tiles">
      <div class="sc-tile tone-${sev}"><span class="sc-tile-ic">${icon("users", 26)}</span><div><b>${r.affected_client_count} / ${r.total_clients}</b><span>Affected Clients</span><small>${r.affected_client_count === 0 ? "Every client still reaches its servers" : r.affected_client_count === r.total_clients ? "No client can reach every required server" : `${pct}% of clients lost a server`}</small></div></div>
      <div class="sc-tile tone-${sev}"><span class="sc-tile-ic">${icon("target", 26)}</span><div><b>${fmtScore(r.impact_score)} / 100</b><span>Impact Score</span><small>${r.impact_score === 100 ? "Maximum network impact" : r.impact_score === 0 ? "No client impact" : `${pct}% of clients affected`}</small></div></div>
      <div class="sc-tile tone-${sev}"><span class="sc-tile-ic">${icon("alert", 26)}</span><div><b class="sev-text-${sev}">${esc(r.severity)}</b><span>Severity</span><small>${r.is_single_point_of_failure ? "Single point of failure" : "Not a single point of failure"}</small></div></div>
      <div class="sc-tile tone-blue"><span class="sc-tile-ic">${icon("link", 26)}</span><div><b>${r.lost_pairs.length}</b><span>Lost Connections</span><small title="${esc(lostText)}">${esc(lostText)}</small></div></div>
    </div>`;
  const rows = affectedRows(sc);
  const table = `<table class="rk-table sc-table"><thead><tr><th>#</th><th>Device</th><th>Type</th><th>Status</th><th>Reason</th></tr></thead><tbody>
    ${rows.map((x, i) => `<tr><td>${i + 1}</td><td><span class="rk-comp">${x.art}${esc(x.name)}</span></td><td>${esc(x.type)}</td>
      <td><span class="status-line"><span class="dot ${x.cls}"></span>${esc(x.status)}</span></td><td>${esc(x.reason)}</td></tr>`).join("")}
  </tbody></table>`;
  const alt = r.alternate_paths.length
    ? `<ul class="an-paths">${r.alternate_paths.map((p) => `<li><b>${esc(p.client)} → ${esc(p.server)}</b><span>${p.alternate_path.map(esc).join(" → ")}</span></li>`).join("")}</ul>`
    : `<p class="an-note">${r.lost_pairs.length ? `No alternate path available.${r.is_single_point_of_failure ? ` ${esc(r.label)} is a single point of failure.` : ""}` : `No client–server path used ${esc(r.label)}.`}</p>`;
  const m = r.matrix;
  const matrix = `<table class="sc-matrix"><thead><tr><th>From / To</th>${m.nodes.map((n) => `<th>${esc(n)}</th>`).join("")}</tr></thead><tbody>
    ${m.nodes.map((a, i) => `<tr><th>${esc(a)}</th>${m.reachable[i].map((v, j) => v === null ? `<td class="mx-self" title="${esc(a)}">–</td>`
      : `<td class="${v ? "mx-ok" : "mx-no"}" title="${esc(a)} → ${esc(m.nodes[j])}: ${v ? "reachable" : "not reachable"}">${icon(v ? "check" : "x", 14)}</td>`).join("")}</tr>`).join("")}
  </tbody></table>`;
  const ranText = `Last run ${esc(fmtTime(sc.last_run_at))}${r.execution_ms != null ? ` · analysed in ${fmtMs(r.execution_ms)}` : ""}`;
  box.innerHTML = head(`<span class="sc-ran">${ranText}</span>`) + banner + tiles + `
    <div class="sc-results-grid">
      <div class="sc-col">
        <h3 class="an-h">Affected Devices <span title="Devices whose state changed in this scenario, with the reason." aria-label="About affected devices">${icon("info", 15)}</span><span class="an-count">${rows.length}</span></h3>
        <div class="rk-scroll sc-scroll">${table}</div>
        <h3 class="an-h">Surviving Alternate Paths <span class="an-count">${r.alternate_paths.length}</span></h3>
        ${alt}
      </div>
      <div class="sc-col">
        <h3 class="an-h">Connectivity Matrix <span title="Which PCs and servers can still reach each other with the component failed." aria-label="About the connectivity matrix">${icon("info", 15)}</span></h3>
        <div class="sc-matrix-wrap">${matrix}</div>
        <div class="sc-legend"><span><i class="lg-dot normal"></i>Reachable</span><span><i class="lg-dot failed"></i>Not reachable</span></div>
      </div>
    </div>`;
}

function renderComparison() {
  const select = $("#s-compare-select"), body = $("#s-compare-body");
  const a = currentScenario();
  const others = scenarios().filter((s) => s.id !== state.scenarioSel);
  select.innerHTML = `<option value="">Select a scenario</option>` + others.map((s) =>
    `<option value="${esc(s.id)}" ${s.id === state.compareWith ? "selected" : ""}>${esc(s.name)}${s.status === "completed" ? "" : ` (${STATUS_INFO[s.status].label.toLowerCase()})`}</option>`).join("");
  select.disabled = !a || !others.length;
  const b = scenarioById(state.compareWith);
  const empty = (msg, btn = "") => `<div class="sc-compare-empty">${icon("scenarios", 30)}<p>${msg}</p>${btn}</div>`;
  if (!a) { body.innerHTML = empty("Select a scenario to compare."); return; }
  if (!b) { body.innerHTML = empty(others.length ? "Select another scenario to compare results." : "Create another scenario to compare results."); return; }
  for (const s of [a, b]) {
    if (s.status !== "completed") {
      const why = s.status === "not_run" ? "has not been run yet" : s.status === "outdated" ? "has results from an older version of the topology" : "targets a component that no longer exists";
      const btn = s.status === "invalid" ? "" : `<button class="btn primary" data-sc-run="${esc(s.id)}" ${state.running ? "disabled" : ""}>${icon("play", 16)}Run ${esc(s.name)}</button>`;
      body.innerHTML = empty(`<b>${esc(s.name)}</b> ${why}, so there is nothing to compare yet.`, btn);
      return;
    }
  }
  const key = `${a.id}:${a.last_run_at}|${b.id}:${b.last_run_at}`;
  if (state.comparison?.key !== key) { loadComparison(a, b, key); return; }
  const c = state.comparison;
  if (c.loading) { body.innerHTML = `<p class="empty-note">Comparing…</p>`; return; }
  if (c.error) { body.innerHTML = `<div class="form-error">${esc(c.error)}</div>`; return; }
  const A = c.data.scenarios.A, Bv = c.data.scenarios.B, cmp = c.data.comparison;
  const delta = (x, y, lowerIsBetter = true, fmt = (v) => v) => {
    const d = Math.round((y - x) * 100) / 100;
    if (d === 0) return `<span class="dl same">Same</span>`;
    const better = lowerIsBetter ? d < 0 : d > 0;
    return `<span class="dl ${better ? "better" : "worse"}">${d < 0 ? "▼" : "▲"} ${fmt(Math.abs(d))} ${better ? "better" : "worse"}</span>`;
  };
  const sevDelta = () => {
    const d = SEV_RANK[Bv.severity] - SEV_RANK[A.severity];
    return d === 0 ? `<span class="dl same">Same</span>` : `<span class="dl ${d < 0 ? "better" : "worse"}">${d < 0 ? "▼ Less severe" : "▲ More severe"}</span>`;
  };
  const spofDelta = () => (A.is_single_point_of_failure === Bv.is_single_point_of_failure ? `<span class="dl same">Same</span>`
    : `<span class="dl ${Bv.is_single_point_of_failure ? "worse" : "better"}">${Bv.is_single_point_of_failure ? "▲ Becomes SPOF" : "▼ Not a SPOF"}</span>`);
  const verdict = cmp.higher_impact === "equal"
    ? `<div class="sc-verdict same">Both scenarios have the same impact.</div>`
    : cmp.higher_impact === "A"
      ? `<div class="sc-verdict better">${icon("check", 16)}<span><b>Improvement:</b> ${esc(b.name)} is less disruptive than ${esc(a.name)} (${fmtScore(Math.abs(cmp.impact_score_difference))} points lower).</span></div>`
      : `<div class="sc-verdict worse">${icon("alert", 16)}<span><b>Regression:</b> ${esc(b.name)} is more disruptive than ${esc(a.name)} (${fmtScore(Math.abs(cmp.impact_score_difference))} points higher).</span></div>`;
  body.innerHTML = `${verdict}
    <table class="sc-cmp"><thead><tr><th>Metric</th><th title="${esc(a.name)}">A</th><th title="${esc(b.name)}">B</th><th>B vs A</th></tr></thead><tbody>
      <tr><td>Affected clients</td><td>${A.affected_client_count}/${A.total_clients}</td><td>${Bv.affected_client_count}/${Bv.total_clients}</td><td>${delta(A.affected_client_count, Bv.affected_client_count)}</td></tr>
      <tr><td>Impact score</td><td>${fmtScore(A.impact_score)}</td><td>${fmtScore(Bv.impact_score)}</td><td>${delta(A.impact_score, Bv.impact_score, true, fmtScore)}</td></tr>
      <tr><td>Severity</td><td><span class="sev sev-${SEV_CLASS[A.severity]}">${A.severity}</span></td><td><span class="sev sev-${SEV_CLASS[Bv.severity]}">${Bv.severity}</span></td><td>${sevDelta()}</td></tr>
      <tr><td>Lost connections</td><td>${A.lost_pairs.length}</td><td>${Bv.lost_pairs.length}</td><td>${delta(A.lost_pairs.length, Bv.lost_pairs.length)}</td></tr>
      <tr><td>Surviving rerouted paths</td><td>${A.alternate_paths.length}</td><td>${Bv.alternate_paths.length}</td><td><span class="dl same">${Bv.alternate_paths.length - A.alternate_paths.length >= 0 ? "+" : ""}${Bv.alternate_paths.length - A.alternate_paths.length}</span></td></tr>
      <tr><td>Single point of failure</td><td>${A.is_single_point_of_failure ? "Yes" : "No"}</td><td>${Bv.is_single_point_of_failure ? "Yes" : "No"}</td><td>${spofDelta()}</td></tr>
    </tbody></table>
    <div class="sc-cmp-legend"><span><b>A</b> ${esc(a.name)}</span><span><b>B</b> ${esc(b.name)}</span></div>
    ${cmp.shared_affected_clients.length ? `<p class="an-note">Affected in both: ${cmp.shared_affected_clients.map(esc).join(", ")}</p>` : ""}`;
}

async function loadComparison(a, b, key) {
  state.comparison = { key, loading: true };
  renderComparison();
  try {
    const data = await api.compare([a.target, b.target]);
    if (state.comparison?.key !== key) return;
    state.comparison = { key, data };
  } catch (e) {
    if (state.comparison?.key !== key) return;
    state.comparison = { key, error: e.message };
  }
  renderComparison();
}

function selectScenario(id) {
  if (id === state.scenarioSel) return;
  state.scenarioSel = id;
  if (state.compareWith === id) state.compareWith = "";
  renderScenarios();
  renderCanvas();
}

async function runScenario(id) {
  const sc = scenarioById(id);
  if (!sc || state.running) return;
  state.running = id;
  renderScenarios();
  try {
    const res = await api.runScenario(id);
    toast(`${res.name}: ${res.result.severity} impact · ${res.result.affected_client_count}/${res.result.total_clients} clients affected`, "info");
  } catch (e) {
    toast(e.message, "error");
  } finally {
    state.running = null;
  }
  await refresh();
}

function scenarioFormHtml(sc, { create }) {
  const devices = state.topo.devices;
  const links = state.topo.links;
  const kind = sc.kind;
  return `
    <div class="field"><label for="f-sc-name">Scenario name</label><input id="f-sc-name" name="name" maxlength="80" value="${esc(sc.name)}" autocomplete="off" required></div>
    ${create ? `
    <div class="field"><label>Failure type</label>
      <div class="checks sc-kind">
        <label><input type="radio" name="kind" value="device" ${kind === "device" ? "checked" : ""} ${devices.length ? "" : "disabled"}> Device failure</label>
        <label><input type="radio" name="kind" value="link" ${kind === "link" ? "checked" : ""} ${links.length ? "" : "disabled"}> Link failure</label>
      </div>
      <div class="hint">Multiple-device failures need backend support that does not exist yet.</div></div>
    <div class="field"><label for="f-sc-target">Target</label><select id="f-sc-target" name="target"></select></div>` : ""}
    <div class="field"><label for="f-sc-desc">Description</label><textarea id="f-sc-desc" name="description" rows="3" maxlength="500" placeholder="What does this scenario test? (optional)">${esc(sc.description || "")}</textarea></div>`;
}

function openNewScenario() {
  if (!state.topo) return;
  if (!state.topo.devices.length) { toast("Add devices to the topology before creating scenarios.", "info"); return; }
  openModal({
    title: "New Scenario",
    html: scenarioFormHtml({ name: "", kind: "device", description: "" }, { create: true }),
    submitLabel: "Create scenario",
    focus: "#f-sc-target",
    onSubmit: async (form) => {
      const kind = form.querySelector('input[name="kind"]:checked')?.value;
      const body = { name: form.name.value, kind, description: form.description.value };
      const t = form.target.value;
      if (!t) throw new ApiError("Choose a target.", 0);
      if (kind === "device") body.device_id = t;
      else { const l = linkById(t); body.source = l.source; body.target = l.target; }
      const created = await api.createScenario(body);
      state.scenarioSel = created.id;
      await refresh();
      toast(`Scenario “${created.name}” created`);
    },
  });
  const form = $("#modal-form");
  let nameTouched = false;
  form.name.addEventListener("input", () => (nameTouched = true));
  const fillTargets = () => {
    const kind = form.querySelector('input[name="kind"]:checked')?.value;
    form.target.innerHTML = kind === "link"
      ? state.topo.links.map((l) => `<option value="${esc(l.id)}">${esc(l.source)} – ${esc(l.target)}</option>`).join("")
      : state.topo.devices.map((d) => `<option value="${esc(d.id)}">${esc(d.id)} (${TYPE_INFO[d.type].name})</option>`).join("");
    suggest();
  };
  const suggest = () => {
    if (nameTouched) return;
    const kind = form.querySelector('input[name="kind"]:checked')?.value;
    const t = form.target.value;
    let base = kind === "link" ? `${t.replace("--", "–")} Link Failure` : `${t} Failure`;
    let name = base, n = 2;
    while (scenarios().some((s) => s.name.toLowerCase() === name.toLowerCase())) name = `${base} ${n++}`;
    form.name.value = name;
  };
  $$('input[name="kind"]', form).forEach((r) => r.addEventListener("change", fillTargets));
  form.target.addEventListener("change", suggest);
  fillTargets();
}

function openEditScenario() {
  const sc = currentScenario();
  if (!sc) return;
  openModal({
    title: "Edit scenario",
    html: scenarioFormHtml(sc, { create: false }),
    focus: "#f-sc-name",
    onSubmit: async (form) => {
      const body = {};
      if (form.name.value.trim() !== sc.name) body.name = form.name.value;
      if (form.description.value.trim() !== sc.description) body.description = form.description.value;
      if (!Object.keys(body).length) return;
      await api.updateScenario(sc.id, body);
      await refresh();
      toast("Scenario updated");
    },
  });
}

function confirmDeleteScenario() {
  const sc = currentScenario();
  if (!sc) return;
  openModal({
    title: `Delete “${sc.name}”?`,
    html: `<p class="modal-text">The scenario${sc.result ? " and its saved results" : ""} will be permanently removed. The topology is not affected.</p>`,
    submitLabel: "Delete", danger: true,
    onSubmit: async () => {
      await api.deleteScenario(sc.id);
      state.scenarioSel = null;
      await refresh();
      toast(`Scenario “${sc.name}” deleted`);
    },
  });
}

async function copyScenario() {
  const sc = currentScenario();
  if (!sc) return;
  try {
    const copy = await api.copyScenario(sc.id);
    state.scenarioSel = copy.id;
    await refresh();
    toast(`Copied as “${copy.name}”. Run it to get results.`);
  } catch (e) {
    toast(e.message, "error");
  }
}

function bindScenarios() {
  $("#s-new").addEventListener("click", openNewScenario);
  const list = $("#s-list");
  list.addEventListener("click", (e) => { const it = e.target.closest("[data-scenario]"); if (it) selectScenario(it.dataset.scenario); });
  list.addEventListener("keydown", (e) => {
    const it = e.target.closest("[data-scenario]");
    if (!it) return;
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectScenario(it.dataset.scenario); }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const sib = e.key === "ArrowDown" ? it.nextElementSibling : it.previousElementSibling;
      if (sib) { selectScenario(sib.dataset.scenario); $(`[data-scenario="${CSS.escape(sib.dataset.scenario)}"]`)?.focus(); }
    }
  });
  const menuClose = () => $$(".sc-menu").forEach((m) => { m.hidden = true; m.previousElementSibling?.setAttribute("aria-expanded", "false"); });
  const actions = { run: () => runScenario(state.scenarioSel), copy: copyScenario, edit: openEditScenario, delete: confirmDeleteScenario };
  for (const sel of ["#s-details", "#s-results"]) {
    $(sel).addEventListener("click", (e) => {
      const b = e.target.closest("[data-sc]");
      if (!b) return;
      if (b.dataset.sc === "menu") {
        const m = b.nextElementSibling;
        const open = m.hidden;
        menuClose();
        m.hidden = !open;
        b.setAttribute("aria-expanded", String(open));
        if (open) m.querySelector("button")?.focus();
        return;
      }
      menuClose();
      actions[b.dataset.sc]?.();
    });
  }
  document.addEventListener("click", (e) => { if (!e.target.closest(".sc-menu-wrap")) menuClose(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") menuClose(); });
  $("#s-compare-select").addEventListener("change", (e) => { state.compareWith = e.target.value; renderComparison(); });
  $("#s-compare-body").addEventListener("click", (e) => { const b = e.target.closest("[data-sc-run]"); if (b) runScenario(b.dataset.scRun); });
}

// ================================================================== search
let searchIndex = -1;
function searchResults(q) {
  q = q.trim().toLowerCase();
  if (!q || !state.topo) return [];
  const devices = state.topo.devices
    .filter((d) => [d.id, d.name, d.ip_address, d.type, TYPE_INFO[d.type].name].some((v) => v && String(v).toLowerCase().includes(q)))
    .slice(0, 8)
    .map((d) => ({ group: "Devices", sel: { kind: "device", id: d.id }, html: `${deviceIcon(d.type, 36)}<div><div class="sr-main">${esc(d.id)}</div><div class="sr-sub">${TYPE_INFO[d.type].name}${d.name !== d.id ? ` · ${esc(d.name)}` : ""}${d.ip_address ? ` · ${esc(d.ip_address)}` : ""}</div></div>` }));
  const links = state.topo.links
    .filter((l) => [l.id, `${l.source} ${l.target}`, `${l.target} ${l.source}`, `${l.target}--${l.source}`].some((v) => v.toLowerCase().includes(q)))
    .slice(0, 8)
    .map((l) => ({ group: "Links", sel: { kind: "link", id: l.id }, html: `<span class="sr-link-ic">${icon("link", 18)}</span><div><div class="sr-main">${esc(l.source)} ↔ ${esc(l.target)}</div><div class="sr-sub">${fmtBandwidth(l.bandwidth_mbps)} · ${fmtLatency(l.latency_ms)}</div></div>` }));
  const scen = (state.scenarioData?.scenarios || [])
    .filter((sc) => [sc.name, sc.target_label, sc.description, sc.kind === "link" ? "link failure" : "device failure"].some((v) => v && v.toLowerCase().includes(q)))
    .slice(0, 6)
    .map((sc) => ({ group: "Scenarios", scenario: sc.id, html: `<span class="sr-link-ic sr-scen-ic">${icon("scenarios", 18)}</span><div><div class="sr-main">${esc(sc.name)}</div><div class="sr-sub">${sc.kind === "link" ? "Link" : "Device"} failure · ${esc(sc.target_label)} · ${STATUS_INFO[sc.status].label}</div></div>` }));
  return [...devices, ...links, ...scen];
}

function renderSearch() {
  const input = $("#search-input"), box = $("#search-results");
  const q = input.value;
  if (!q.trim()) { box.hidden = true; input.setAttribute("aria-expanded", "false"); return; }
  const results = searchResults(q);
  let html = "", group = null;
  results.forEach((r, i) => {
    if (r.group !== group) { group = r.group; html += `<div class="sr-group">${group}</div>`; }
    html += `<div class="sr-item" role="option" id="sr-${i}" data-i="${i}" aria-selected="${i === searchIndex}">${r.html}</div>`;
  });
  if (!results.length) html = `<div class="sr-empty">No devices, links or scenarios match “${esc(q)}”.</div>`;
  box.innerHTML = html;
  box.hidden = false;
  input.setAttribute("aria-expanded", "true");
  box._results = results;
}

function chooseSearch(i) {
  const r = $("#search-results")._results?.[i];
  if (!r) return;
  $("#search-input").value = "";
  $("#search-results").hidden = true;
  if (r.scenario) {
    selectScenario(r.scenario);
    if (state.page !== "scenarios") location.hash = "#scenarios";
    return;
  }
  if (state.page === "scenarios") location.hash = "#overview";
  select(r.sel, { center: true });
}

// ================================================================ routing
function route() {
  const page = (location.hash || "#overview").slice(1);
  const valid = ["overview", "topology", "scenarios"].includes(page) ? page : "overview";
  $$(".nav-item").forEach((a) => a.classList.toggle("active", a.dataset.page === valid));
  $$(".page").forEach((p) => (p.hidden = p.id !== `page-${valid}`));
  const prev = state.page;
  state.page = valid;
  if (valid !== "topology" && state.tool !== "select") setTool("select");
  if (prev !== valid && state.topo) { renderCanvas(); renderInfo(); renderScenarios(); }
  requestAnimationFrame(() => { const c = cv(); if (!c.fitted && state.topo) c.fit(); else c._applyView(); });
  if (valid === "topology" && state.topo) loadRankings();
  if (valid === "scenarios" && prev !== valid && state.topo) loadScenarios();
}

async function loadScenarios() {
  try {
    state.scenarioData = await api.scenarios();   // statuses depend on the current topology
  } catch (e) {
    toast(e.message, "error");
    return;
  }
  renderScenarios();
  renderCanvas();
}

// =================================================================== init
function buildPalette() {
  const paletteHtml = TYPES.map((t) => `
    <div class="palette-item" draggable="true" tabindex="0" role="button" data-type="${t}" aria-label="Add ${TYPE_INFO[t].name}">
      ${deviceIcon(t, 78)}<div><strong>${TYPE_INFO[t].name}</strong><small>${TYPE_INFO[t].role}</small></div>
    </div>`).join("");
  $$(".palette-list").forEach((list) => (list.innerHTML = paletteHtml));

  $$(".palette-item").forEach((item) => {
    item.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("application/x-netcascade-device", item.dataset.type);
      e.dataTransfer.setData("text/plain", item.dataset.type);
      e.dataTransfer.effectAllowed = "copy";
    });
    const addAtCenter = () => {
      if (!state.topo) return;
      const r = cv().svg.getBoundingClientRect();
      const p = cv().clientToWorld(r.left + r.width / 2, r.top + r.height / 2);
      openCreateDevice(item.dataset.type, { x: p.x + (Math.random() - 0.5) * 60, y: p.y + (Math.random() - 0.5) * 60 });
    };
    item.addEventListener("dblclick", addAtCenter);
    item.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); addAtCenter(); } });
  });

  for (const c of Object.values(canvases)) {
  const host = c.host;
  host.addEventListener("dragover", (e) => {
    if (![...e.dataTransfer.types].includes("application/x-netcascade-device")) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    host.classList.add("drop-target");
  });
  host.addEventListener("dragleave", (e) => { if (!host.contains(e.relatedTarget)) host.classList.remove("drop-target"); });
  host.addEventListener("drop", (e) => {
    host.classList.remove("drop-target");
    const type = e.dataTransfer.getData("application/x-netcascade-device");
    if (!TYPES.includes(type) || !state.topo) return;
    e.preventDefault();
    openCreateDevice(type, c.clientToWorld(e.clientX, e.clientY));
  });
  }

  $("#palette-toggle").addEventListener("click", () => {
    $(".workspace").classList.add("palette-collapsed");
    showPaletteButton(true);
    requestAnimationFrame(() => cv()._applyView());
  });
}

function showPaletteButton(show) {
  let btn = $("#palette-show");
  if (!btn) {
    btn = document.createElement("button");
    btn.id = "palette-show";
    btn.className = "tool wide";
    btn.innerHTML = `${icon("plus", 20)}Devices`;
    btn.title = "Show device palette";
    btn.addEventListener("click", () => {
      $(".workspace").classList.remove("palette-collapsed");
      showPaletteButton(false);
      requestAnimationFrame(() => cv()._applyView());
    });
    $(".toolbar").prepend(btn);
  }
  btn.hidden = !show;
}

function bindUi() {
  $$("[data-mode]").forEach((b) => b.addEventListener("click", () => switchMode(b.dataset.mode)));
  $$("[data-tool]").forEach((b) => b.addEventListener("click", () => setTool(b.dataset.tool)));

  const actions = {
    edit: editSelection,
    delete: deleteSelection,
    undo, redo,
    layout: runAutoLayout,
    "zoom-in": () => cv().zoomBy(1.2),
    "zoom-out": () => cv().zoomBy(1 / 1.2),
    fit: () => cv().fit(),
    fullscreen: () => {
      const panel = cv().host.closest(".canvas-panel");
      if (document.fullscreenElement) document.exitFullscreen();
      else panel.requestFullscreen?.().catch((e) => toast(`Full screen unavailable: ${e.message}`, "error"));
    },
  };
  $$("[data-action]").forEach((b) => b.addEventListener("click", () => actions[b.dataset.action]?.()));

  // Simulation controls, ranking table, analysis panel
  $$("[data-sim]").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.sim === "reset") resetSim(); else startSim(b.dataset.sim);
  }));
  $$("[data-rank-filter]").forEach((b) => b.addEventListener("click", () => { state.rankFilter = b.dataset.rankFilter; renderRanking(); }));
  const rankBody = $("#t-ranking-body");
  const rankSel = (tr) => (tr.dataset.rankKind === "device" ? { kind: "device", id: tr.dataset.rankId } : { kind: "link", id: tr.dataset.rankId });
  rankBody.addEventListener("click", (e) => { const tr = e.target.closest("tr[data-rank-id]"); if (tr) select(rankSel(tr), { center: true }); });
  rankBody.addEventListener("dblclick", (e) => {
    const tr = e.target.closest("tr[data-rank-id]");
    if (!tr) return;
    if (tr.dataset.rankKind === "device") simulateDevice(tr.dataset.rankId); else simulateLink(tr.dataset.rankId);
  });
  rankBody.addEventListener("keydown", (e) => {
    const tr = e.target.closest("tr[data-rank-id]");
    if (tr && e.key === "Enter") { e.preventDefault(); select(rankSel(tr), { center: true }); }
  });
  $("#t-analysis-toggle").addEventListener("click", () => { state.analysisOpen = !state.analysisOpen; renderAnalysis(); });
  document.addEventListener("fullscreenchange", () => requestAnimationFrame(() => cv().fit()));

  // Info panel delegation (both pages)
  document.addEventListener("click", async (e) => {
    if (!e.target.closest(".info")) return;
    const t = e.target.closest("button");
    if (!t) return;
    if (t.dataset.tab) { state.tab = t.dataset.tab; renderInfo(); return; }
    if (t.dataset.gotoDevice) return select({ kind: "device", id: t.dataset.gotoDevice }, { center: true });
    if (t.dataset.gotoLink) return select({ kind: "link", id: t.dataset.gotoLink }, { center: true });
    if (t.hasAttribute("data-close-info")) return select(null);
    if (t.dataset.edit) {
      if (state.selection.kind === "device") openEditDevice(state.selection.id, t.dataset.edit);
      else openEditLink(state.selection.id, t.dataset.edit);
      return;
    }
    if (t.dataset.removeAttr) {
      const d = deviceById(state.selection.id);
      try { await exec(cmdEditDevice(d, { attributes: { [t.dataset.removeAttr]: null } })); } catch (err) { toast(err.message, "error"); }
      return;
    }
    const act = t.dataset.actionInfo;
    if (act === "edit") editSelection();
    else if (act === "delete") deleteSelection();
    else if (act === "restore") {
      openModal({
        title: "Restore original topology?",
        html: `<p class="modal-text">All edits to ${esc(networkTitle())} will be discarded.</p>`,
        submitLabel: "Restore",
        onSubmit: async () => { await api.resetTopology(); clearHistory(); state.selection = null; await refresh(); toast("Original topology restored"); },
      });
    }
  });
  document.addEventListener("submit", async (e) => {
    if (e.target.id !== "attr-form") return;
    e.preventDefault();
    const key = $("#attr-k").value.trim();
    const raw = $("#attr-v").value.trim();
    if (!key) return;
    let value = raw;
    try { if (raw !== "" && /^(-?\d+(\.\d+)?|true|false|null)$/.test(raw)) value = JSON.parse(raw); } catch { /* keep string */ }
    const d = deviceById(state.selection.id);
    try {
      await exec(cmdEditDevice(d, { attributes: { [key]: value } }));
      toast(`Property “${key}” saved`);
    } catch (err) { toast(err.message, "error"); }
  });

  // Modal
  $("#modal").addEventListener("click", (e) => {
    if (e.target.id === "modal" || e.target.closest("[data-close]")) closeModal();
  });
  $("#modal-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!modalSubmit) return;
    const btn = $("#modal-form button[type=submit]");
    btn.disabled = true;
    try {
      await modalSubmit($("#modal-form"));
      closeModal();
    } catch (err) {
      showFormError(err.message);
    } finally {
      btn.disabled = false;
    }
  });

  // Search
  const input = $("#search-input");
  input.addEventListener("input", () => { searchIndex = -1; renderSearch(); });
  input.addEventListener("focus", renderSearch);
  input.addEventListener("keydown", (e) => {
    const n = $("#search-results")._results?.length || 0;
    if (e.key === "ArrowDown" && n) { e.preventDefault(); searchIndex = (searchIndex + 1) % n; renderSearch(); }
    else if (e.key === "ArrowUp" && n) { e.preventDefault(); searchIndex = (searchIndex - 1 + n) % n; renderSearch(); }
    else if (e.key === "Enter") { e.preventDefault(); chooseSearch(Math.max(0, searchIndex)); }
    else if (e.key === "Escape") { input.value = ""; renderSearch(); input.blur(); }
  });
  $("#search-results").addEventListener("mousedown", (e) => {
    const item = e.target.closest(".sr-item");
    if (item) { e.preventDefault(); chooseSearch(Number(item.dataset.i)); }
  });
  input.addEventListener("blur", () => setTimeout(() => ($("#search-results").hidden = true), 120));

  // Keyboard shortcuts
  document.addEventListener("keydown", (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); input.focus(); input.select(); return; }
    if (!$("#modal").hidden) { if (e.key === "Escape") closeModal(); return; }
    if (e.target.closest?.("input, select, textarea")) return;
    if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
    if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); redo(); return; }
    if (mod) return;
    if (state.page === "scenarios" && !["+", "=", "-", "0"].includes(e.key)) return;   // preview only: no editing shortcuts
    if (e.key === "Escape") { if (state.tool !== "select") setTool("select"); else select(null); }
    else if (e.key === "Delete" || e.key === "Backspace") { if (state.selection) { e.preventDefault(); deleteSelection(); } }
    else if (e.key.toLowerCase() === "v") setTool("select");
    else if (e.key.toLowerCase() === "l") setTool("link");
    else if (e.key === "+" || e.key === "=") cv().zoomBy(1.2);
    else if (e.key === "-") cv().zoomBy(1 / 1.2);
    else if (e.key === "0") cv().fit();
  });

  window.addEventListener("hashchange", route);
}

function canvasHandlers(page) {
  return {
    onSelect: (sel) => select(sel),
    onLinkCreate: createLink,
    onFailDevice: (id) => simulateDevice(id),
    onFailLink: (id) => simulateLink(id),
    onNodeMoved: (id, from, to) => {
      const before = { ...state.positions, [id]: from };
      const after = { ...state.positions, [id]: to };
      state.positions = after;
      savePositions();
      Object.values(canvases).forEach((c) => (c.pos = after));
      state.history.undo.push(cmdPositions(`move ${id}`, before, after));
      state.history.redo = [];
      updateHistoryButtons();
    },
    onZoom: (k) => $$(`#page-${page} [data-bind="zoom"]`).forEach((n) => (n.textContent = `${Math.round(k * 100)}%`)),
  };
}

async function init() {
  $("#device-symbols").innerHTML = DEVICE_SYMBOLS;
  $("#brand-logo").innerHTML = LOGO;
  hydrateIcons();
  canvases.overview = new TopologyCanvas($("#canvas"), canvasHandlers("overview"));
  canvases.topology = new TopologyCanvas($("#t-canvas"), canvasHandlers("topology"), { showIp: true });
  canvases.scenarios = new TopologyCanvas($("#s-canvas"), { ...canvasHandlers("scenarios"), onSelect: () => {} }, { showIp: true });
  buildPalette();
  bindUi();
  bindScenarios();
  route();
  renderAll();
  await refresh({ fit: true });
}

init();
