// Interactive SVG topology canvas: pan, zoom, fit, drag nodes, select, link-drawing mode.

const SVG_NS = "http://www.w3.org/2000/svg";
const ICON = 88;                      // nominal icon size in world units
const SIZE = { pc: 92, switch: 128, router: 108, server: 100 };   // per-type art size (symbols have different padding)
const PORT_R = { pc: { rx: 34, ry: 44 }, switch: { rx: 56, ry: 24 }, router: { rx: 50, ry: 30 }, server: { rx: 28, ry: 48 } };  // ellipse where links meet the art
const MIN_K = 0.25, MAX_K = 3;

const el = (tag, attrs = {}, parent) => {
  const n = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parent) parent.appendChild(n);
  return n;
};

/** Layered layout: PCs on top, servers at the bottom, layers by hop distance from servers. */
export function autoLayout(devices, links) {
  const adj = new Map(devices.map((d) => [d.id, []]));
  for (const l of links) { adj.get(l.source)?.push(l.target); adj.get(l.target)?.push(l.source); }
  const type = new Map(devices.map((d) => [d.id, d.type]));

  const dist = new Map();
  const queue = devices.filter((d) => d.type === "server").map((d) => d.id);
  queue.forEach((id) => dist.set(id, 0));
  for (let i = 0; i < queue.length; i++) {
    for (const n of adj.get(queue[i])) if (!dist.has(n)) { dist.set(n, dist.get(queue[i]) + 1); queue.push(n); }
  }
  const maxD = Math.max(0, ...[...dist.entries()].filter(([id]) => type.get(id) !== "pc").map(([, d]) => d));
  const pcLayer = maxD + 1;
  const layerOf = (id) => {
    if (type.get(id) === "pc") return pcLayer;
    if (dist.has(id)) return dist.get(id);
    return type.get(id) === "server" ? 0 : Math.max(1, maxD);   // unreachable infra: middle-ish
  };

  const layers = new Map();
  for (const d of devices) {
    const L = layerOf(d.id);
    if (!layers.has(L)) layers.set(L, []);
    layers.get(L).push(d.id);
  }
  const pos = {};
  const GAP_X = 215, GAP_Y = 140;
  const ordered = [...layers.keys()].sort((a, b) => a - b);      // servers (0) first
  const maxLayer = Math.max(...ordered);
  for (const L of ordered) {
    const ids = layers.get(L);
    const bary = (id) => {
      const xs = adj.get(id).filter((n) => pos[n]).map((n) => pos[n].x);
      return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0;
    };
    ids.sort((a, b) => bary(a) - bary(b) || a.localeCompare(b, undefined, { numeric: true }));
    const gap = ids.length > 6 ? 150 : GAP_X;
    ids.forEach((id, i) => {
      pos[id] = { x: (i - (ids.length - 1) / 2) * gap, y: (maxLayer - L) * GAP_Y };
    });
  }
  return pos;
}

export class TopologyCanvas {
  constructor(host, handlers, options = {}) {
    this.host = host;
    this.h = handlers;   // onSelect(sel), onLinkCreate(a,b), onNodeMoved(id, from, to), onZoom(k), onFailDevice(id), onFailLink(id)
    this.opts = { showIp: false, ...options };
    this.overlay = null; // { failedNodes:Set, failedLink, affected:Set, cutoff:Set, altEdges:Set } from a simulation
    this.fitted = false;
    this.devices = [];
    this.links = [];
    this.pos = {};
    this.view = { x: 0, y: 0, k: 1 };
    this.mode = "select";
    this.selection = null;
    this.linkSource = null;

    this.svg = el("svg", { class: "topo-svg", role: "img", "aria-label": "Network topology" }, host);
    this.root = el("g", {}, this.svg);
    this.linkLayer = el("g", { class: "links" }, this.root);
    this.ghost = el("line", { class: "ghost-link", visibility: "hidden" }, this.root);
    this.nodeLayer = el("g", { class: "nodes" }, this.root);
    this._bind();
  }

  // ------------------------------------------------------------------ data
  setData(devices, links, positions) {
    this.devices = devices;
    this.links = links;
    this.pos = positions;
    if (this.selection && !this._exists(this.selection)) this.selection = null;
    if (this.linkSource && !this.pos[this.linkSource]) this.linkSource = null;
    this.render();
  }

  _exists(sel) {
    if (sel.kind === "devices") return sel.ids.every((id) => this.devices.some((d) => d.id === id));
    return sel.kind === "device" ? this.devices.some((d) => d.id === sel.id) : this.links.some((l) => l.id === sel.id);
  }

  setSelection(sel) { this.selection = sel; this.render(); }

  setOverlay(overlay) { this.overlay = overlay; this.render(); }

  setMode(mode) {
    this.mode = mode;
    this.linkSource = null;
    this.ghost.setAttribute("visibility", "hidden");
    this.host.classList.toggle("mode-link", mode === "link");
    this.host.classList.toggle("mode-fail", mode === "fail-device" || mode === "fail-link");
    this.host.classList.toggle("mode-fail-device", mode === "fail-device");
    this.host.classList.toggle("mode-fail-link", mode === "fail-link");
    this.render();
  }

  // ---------------------------------------------------------------- render
  render() {
    this.linkLayer.replaceChildren();
    this.nodeLayer.replaceChildren();
    const sel = this.selection;
    const ov = this.overlay;
    const key = (a, b) => [a, b].sort().join("\u0000");
    this.host.classList.toggle("simulating", !!ov);

    for (const l of this.links) {
      const a = this.pos[l.source], b = this.pos[l.target];
      if (!a || !b) continue;
      const [p1, p2] = this._trim(a, b, this._type(l.source), this._type(l.target));
      const lc = ["link"];
      if (sel?.kind === "link" && sel.id === l.id) lc.push("selected");
      if (ov) {
        const k = key(l.source, l.target);
        if (ov.failedLink === k || ov.failedNodes.has(l.source) || ov.failedNodes.has(l.target)) lc.push("down");
        else if (ov.altEdges.has(k)) lc.push("alt");
      }
      const g = el("g", { class: lc.join(" "), "data-link": l.id }, this.linkLayer);
      el("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: "link-hit" }, g);
      el("line", { x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y, class: "link-line" }, g);
      el("circle", { cx: p1.x, cy: p1.y, r: 5, class: "port" }, g);
      el("circle", { cx: p2.x, cy: p2.y, r: 5, class: "port" }, g);
      const t = el("title", {}, g); t.textContent = `${l.source} ↔ ${l.target}`;
    }

    for (const d of this.devices) {
      const p = this.pos[d.id];
      if (!p) continue;
      const classes = ["node", `node-${d.type}`];
      if ((sel?.kind === "device" && sel.id === d.id) || (sel?.kind === "devices" && sel.ids.includes(d.id))) classes.push("selected");
      if (this.linkSource === d.id) classes.push("link-source");
      if (d._isolated) classes.push("isolated");
      const failed = !!ov?.failedNodes.has(d.id);
      const warn = !failed && (ov?.affected.has(d.id) || ov?.cutoff.has(d.id));
      if (failed) classes.push("failed");
      if (warn) classes.push("affected");
      const g = el("g", { class: classes.join(" "), transform: `translate(${p.x},${p.y})`, "data-node": d.id, tabindex: 0 }, this.nodeLayer);
      const S = SIZE[d.type];
      el("rect", { x: -ICON / 2 - 8, y: -ICON / 2 - 8, width: ICON + 16, height: ICON + 40, rx: 14, class: "node-halo" }, g);
      el("use", { href: `#dev-${d.type}`, x: -S / 2, y: -S / 2, width: S, height: S }, g);
      const label = el("text", { y: ICON / 2 + 20, class: "node-label" }, g);
      label.textContent = d.id;
      if (this.opts.showIp && d.ip_address) {
        const ip = el("text", { y: ICON / 2 + 37, class: "node-ip" }, g);
        ip.textContent = d.ip_address;
      }
      if (failed || warn) {
        const b = el("g", { class: `badge ${failed ? "badge-fail" : "badge-warn"}`, transform: `translate(${S / 2 - 16},${-S / 2 + 18})` }, g);
        el("circle", { r: 11 }, b);
        const t2 = el("text", { y: 4.5 }, b); t2.textContent = "!";
      }
      const t = el("title", {}, g); t.textContent = `${d.name} (${d.type})`;
    }
    this._applyView();
  }

  _type(id) { return this.devices.find((d) => d.id === id)?.type || "pc"; }

  _trim(a, b, ta, tb) {
    const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
    const ux = dx / len, uy = dy / len;
    const reach = (t) => { const r = PORT_R[t]; return 1 / Math.hypot(ux / r.rx, uy / r.ry); };
    const ra = Math.min(reach(ta), len / 2 - 4), rb = Math.min(reach(tb), len / 2 - 4);
    return [{ x: a.x + ux * ra, y: a.y + uy * ra }, { x: b.x - ux * rb, y: b.y - uy * rb }];
  }

  _applyView() {
    const { x, y, k } = this.view;
    this.root.setAttribute("transform", `translate(${x},${y}) scale(${k})`);
    const s = 28 * k;
    this.host.style.backgroundSize = `${s}px ${s}px`;
    this.host.style.backgroundPosition = `${x}px ${y}px`;
  }

  // ------------------------------------------------------------ view ops
  zoomBy(factor, cx, cy) {
    const r = this.svg.getBoundingClientRect();
    if (cx === undefined) { cx = r.width / 2; cy = r.height / 2; }
    const k = Math.min(MAX_K, Math.max(MIN_K, this.view.k * factor));
    const f = k / this.view.k;
    this.view.x = cx - (cx - this.view.x) * f;
    this.view.y = cy - (cy - this.view.y) * f;
    this.view.k = k;
    this._applyView();
    this.h.onZoom?.(k);
  }

  fit(padding = 36) {
    const pts = this.devices.map((d) => this.pos[d.id]).filter(Boolean);
    const r = this.svg.getBoundingClientRect();
    if (!pts.length || !r.width) { this.view = { x: r.width / 2, y: r.height / 2, k: 1 }; this._applyView(); this.h.onZoom?.(1); return; }
    const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
    const minX = Math.min(...xs) - ICON / 2, maxX = Math.max(...xs) + ICON / 2;
    const minY = Math.min(...ys) - ICON / 2, maxY = Math.max(...ys) + ICON / 2 + 28;
    const k = Math.min(1.25, Math.max(MIN_K, Math.min((r.width - padding * 2) / (maxX - minX), (r.height - padding * 2) / (maxY - minY))));
    this.view = { k, x: r.width / 2 - ((minX + maxX) / 2) * k, y: r.height / 2 - ((minY + maxY) / 2) * k };
    this._applyView();
    this.fitted = true;
    this.h.onZoom?.(k);
  }

  clientToWorld(clientX, clientY) {
    const r = this.svg.getBoundingClientRect();
    return { x: (clientX - r.left - this.view.x) / this.view.k, y: (clientY - r.top - this.view.y) / this.view.k };
  }

  // --------------------------------------------------------- interaction
  _bind() {
    let drag = null;
    const svg = this.svg;

    svg.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      const nodeEl = e.target.closest("[data-node]");
      const linkEl = e.target.closest("[data-link]");
      const start = { cx: e.clientX, cy: e.clientY };
      if (nodeEl) {
        const id = nodeEl.dataset.node;
        drag = { kind: "node", id, start, from: { ...this.pos[id] }, moved: false };
      } else if (linkEl) {
        drag = { kind: "link", id: linkEl.dataset.link, start, moved: false };
      } else {
        drag = { kind: "pan", start, view: { ...this.view }, moved: false };
        this.host.classList.add("panning");
      }
      svg.setPointerCapture(e.pointerId);
    });

    svg.addEventListener("pointermove", (e) => {
      if (this.mode === "link" && this.linkSource) {
        const w = this.clientToWorld(e.clientX, e.clientY), a = this.pos[this.linkSource];
        Object.entries({ x1: a.x, y1: a.y, x2: w.x, y2: w.y }).forEach(([k, v]) => this.ghost.setAttribute(k, v));
        this.ghost.setAttribute("visibility", "visible");
      }
      if (!drag) return;
      const dx = e.clientX - drag.start.cx, dy = e.clientY - drag.start.cy;
      if (Math.hypot(dx, dy) > 3) drag.moved = true;
      if (!drag.moved) return;
      if (drag.kind === "pan") {
        this.view.x = drag.view.x + dx;
        this.view.y = drag.view.y + dy;
        this._applyView();
      } else if (drag.kind === "node" && this.mode === "select") {
        this.pos[drag.id] = { x: drag.from.x + dx / this.view.k, y: drag.from.y + dy / this.view.k };
        this.render();
      }
    });

    const end = (e) => {
      this.host.classList.remove("panning");
      if (!drag) return;
      const d = drag;
      drag = null;
      if (d.kind === "pan") {
        if (!d.moved) {
          if (this.linkSource) { this.linkSource = null; this.ghost.setAttribute("visibility", "hidden"); this.render(); }
          this.h.onSelect?.(null);
        }
        return;
      }
      if (d.kind === "node") {
        if (this.mode === "link") return this._linkClick(d.id);
        if (this.mode === "fail-device" && !d.moved) return this.h.onFailDevice?.(d.id);
        if (d.moved) this.h.onNodeMoved?.(d.id, d.from, { ...this.pos[d.id] });
        else this.h.onSelect?.({ kind: "device", id: d.id });
        return;
      }
      if (d.kind === "link" && !d.moved) {
        if (this.mode === "fail-link") return this.h.onFailLink?.(d.id);
        this.h.onSelect?.({ kind: "link", id: d.id });
      }
    };
    svg.addEventListener("pointerup", end);
    svg.addEventListener("pointercancel", end);

    svg.addEventListener("wheel", (e) => {
      e.preventDefault();
      const r = svg.getBoundingClientRect();
      if (e.ctrlKey || e.metaKey || Math.abs(e.deltaY) >= Math.abs(e.deltaX)) {
        this.zoomBy(Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0018)), e.clientX - r.left, e.clientY - r.top);
      } else {
        this.view.x -= e.deltaX; this._applyView();
      }
    }, { passive: false });

    svg.addEventListener("keydown", (e) => {
      const id = e.target.closest?.("[data-node]")?.dataset.node;
      if (id && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); this.h.onSelect?.({ kind: "device", id }); }
    });

    new ResizeObserver(() => this._applyView()).observe(this.host);
  }

  _linkClick(id) {
    if (!this.linkSource) { this.linkSource = id; this.render(); return; }
    if (this.linkSource === id) { this.linkSource = null; this.ghost.setAttribute("visibility", "hidden"); this.render(); return; }
    const a = this.linkSource;
    this.linkSource = null;
    this.ghost.setAttribute("visibility", "hidden");
    this.render();
    this.h.onLinkCreate?.(a, id);
  }
}
