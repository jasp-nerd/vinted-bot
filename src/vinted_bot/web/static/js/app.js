/* vinted-bot dashboard: progressive enhancement. Pages render and forms post without
 * this file; it adds the live feed (Server-Sent Events), item actions, previews, the
 * search builder's pickers, Telegram pairing, test sends and small comforts. */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
  };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const icon = (name, cls = "") => `<svg class="i ${cls}" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  async function post(url, data, opts = {}) {
    const body = data instanceof FormData ? data : new URLSearchParams(data || {});
    const res = await fetch(url, { method: "POST", body, headers: { Accept: "application/json" }, credentials: "same-origin" });
    if (res.status === 401) { location.reload(); throw new Error("signed out"); }
    let json = {};
    try { json = await res.json(); } catch (e) { json = {}; }
    if (!res.ok && !opts.quiet) json.ok = false;
    json.status = res.status;
    return json;
  }

  /* ── Toasts ───────────────────────────────────────── */
  function toast(text, opts = {}) {
    const box = $("#toasts");
    if (!box) return;
    const t = document.createElement("div");
    t.className = "toast" + (opts.ok ? " toast--ok" : "") + (opts.bad ? " toast--bad" : "");
    t.setAttribute("role", "status");
    t.innerHTML = (opts.img ? `<img src="${esc(opts.img)}" alt="">` : icon(opts.icon || (opts.ok ? "circle-check-big" : opts.bad ? "circle-alert" : "info"))) +
      "<span></span>" + (opts.action ? `<button type="button">${esc(opts.action)}</button>` : "");
    t.querySelector("span").textContent = text;
    if (opts.action && opts.onAction) t.querySelector("button").addEventListener("click", () => { opts.onAction(); t.remove(); });
    box.appendChild(t);
    while (box.children.length > 3) box.firstElementChild.remove();
    setTimeout(() => t.remove(), opts.ms || 5000);
  }
  window.vsToast = toast;
  const flashBox = $("#toasts[data-flash]");
  if (flashBox) toast(flashBox.dataset.flash, { ok: true });

  /* ── Theme ────────────────────────────────────────── */
  const root = document.documentElement;
  const isDark = () => root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  function paintThemeButtons() {
    $$("[data-theme-toggle]").forEach((b) => {
      const dark = isDark();
      b.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
      const use = b.querySelector("use");
      if (use) use.setAttribute("href", dark ? "#i-sun" : "#i-moon");
    });
  }
  function setTheme(theme, save) {
    if (theme === "system") delete root.dataset.theme; else root.dataset.theme = theme;
    store.set("vs-theme", theme);
    paintThemeButtons();
    if (save) post("/settings", { key: "theme", value: theme }).catch(() => {});
  }
  paintThemeButtons();
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-theme-toggle]")) setTheme(isDark() ? "light" : "dark", true);
  });

  /* ── Dialogs and confirmations ────────────────────── */
  function openDialog(id, from) {
    const d = document.getElementById(id);
    if (!d || !d.showModal) return;
    d._from = from || document.activeElement;
    d.showModal();
  }
  document.addEventListener("click", (e) => {
    const o = e.target.closest("[data-open]");
    if (o) { e.preventDefault(); openDialog(o.dataset.open, o); return; }
    const c = e.target.closest("[data-close]");
    if (c) { const d = c.closest("dialog"); if (d) d.close(); }
  });
  $$("dialog.modal").forEach((d) => {
    d.addEventListener("click", (e) => { if (e.target === d) d.close(); });
    d.addEventListener("close", () => { if (d._from && d._from.focus) d._from.focus(); });
  });
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-confirm]");
    if (!b) return;
    e.preventDefault();
    const d = document.getElementById(b.dataset.confirm);
    if (!d) return;
    $$("[data-fill=name]", d).forEach((n) => { n.textContent = b.dataset.name || ""; });
    const f = $("[data-confirm-form]", d);
    if (f && b.dataset.action) f.action = b.dataset.action;
    const menu = b.closest("details"); if (menu) menu.open = false;
    openDialog(b.dataset.confirm, b);
  });
  // Row menus close when something else is clicked.
  document.addEventListener("click", (e) => {
    $$("details.rowmenu[open], details.chip-pop[open]").forEach((m) => { if (!m.contains(e.target)) m.open = false; });
  });

  /* ── Tabs ─────────────────────────────────────────── */
  $$("[role=tablist]").forEach((list) => {
    const tabs = $$("[role=tab]", list);
    const select = (t, focus) => {
      tabs.forEach((x) => {
        const on = x === t;
        x.setAttribute("aria-selected", on);
        x.tabIndex = on ? 0 : -1;
        const p = document.getElementById(x.getAttribute("aria-controls"));
        if (p) p.hidden = !on;
      });
      if (focus) t.focus();
    };
    tabs.forEach((t, i) => {
      t.addEventListener("click", () => select(t));
      t.addEventListener("keydown", (e) => {
        const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
        if (d) select(tabs[(i + d + tabs.length) % tabs.length], true);
      });
    });
    const want = location.hash && tabs.find((t) => "#" + t.id === location.hash);
    if (want) select(want, false);
  });

  /* ── Small things ─────────────────────────────────── */
  $$("input[data-reveal]").forEach((r) => {
    const sync = () => $$(`input[name="${r.name}"][data-reveal]`).forEach((x) => {
      const p = document.getElementById(x.dataset.reveal); if (p) p.hidden = !x.checked;
    });
    r.addEventListener("change", sync);
  });
  $$("[data-autosubmit]").forEach((s) => s.addEventListener("change", () => s.form && s.form.requestSubmit()));
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-copy]");
    if (!b) return;
    if (navigator.clipboard) navigator.clipboard.writeText(b.dataset.copy).catch(() => {});
    toast("Copied", { ok: true, icon: "copy" });
  });
  document.addEventListener("click", (e) => { if (e.target.closest("[data-reload]")) location.reload(); });
  $$("[data-bookmarklet]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); toast("Drag this button to your bookmarks bar, then click it on a Vinted search."); }));
  $$("[data-band-toggle]").forEach((b) => b.addEventListener("click", () => {
    const band = b.closest("[data-band]"); const open = !band.classList.contains("is-open");
    band.classList.toggle("is-open", open); b.setAttribute("aria-expanded", open);
  }));
  const upd = $("[data-update]");
  if (upd && !upd.dataset.updateBusy && store.get("vs-hide-update") === upd.dataset.update) upd.hidden = true;
  document.addEventListener("click", (e) => {
    if (!e.target.closest("[data-dismiss-update]")) return;
    store.set("vs-hide-update", upd.dataset.update); upd.hidden = true;
  });

  /* ── Updating from the dashboard ──────────────────── */
  /* The upgrade runs in the app; this only shows its progress. When the app restarts
   * into the new version the status answers with a different boot id, and the page
   * reloads into it. */
  function paintUpdate(s) {
    const underway = ["upgrading", "restarting", "installed"].includes(s.phase);
    $$("[data-update-text]").forEach((el) => { if (s.message) el.textContent = s.message; });
    $$("[data-update-log]").forEach((el) => {
      el.hidden = !s.output.length; el.textContent = s.output.join("\n"); el.scrollTop = el.scrollHeight;
    });
    $$("[data-update-now]").forEach((b) => {
      b.hidden = underway; b.disabled = underway;
      if (s.phase === "failed") b.lastChild.textContent = "Try again";
    });
  }
  let watchingUpdate = false;
  function watchUpdate(boot) {
    if (watchingUpdate) return;
    watchingUpdate = true;
    const since = Date.now();
    const tick = async () => {
      let s = null;
      try {
        const res = await fetch("/api/update", { headers: { Accept: "application/json" }, credentials: "same-origin", cache: "no-store" });
        if (res.ok) s = await res.json();
      } catch (e) { s = null; /* down while it restarts */ }
      if (s && s.boot !== boot) { store.set("vs-updated", "1"); location.reload(); return; }
      if (s) paintUpdate(s);
      if (s && !["upgrading", "restarting"].includes(s.phase)) { watchingUpdate = false; return; }
      if (!s && Date.now() - since > 120000) {
        $$("[data-update-text]").forEach((el) => { el.textContent = "vinted-bot hasn't come back yet. If it still isn't back in a few minutes, start it again the way you usually do."; });
      }
      setTimeout(tick, 1500);
    };
    tick();
  }
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-update-now]");
    if (!b || b.disabled) return;
    b.disabled = true;
    const r = await post("/api/update").catch(() => ({ ok: false, error: "Couldn't reach vinted-bot. Is it still running?" }));
    if (!r.ok) { b.disabled = false; toast(r.error || "That didn't work.", { bad: true }); return; }
    paintUpdate(r);
    watchUpdate(r.boot);
  });
  const updBusy = $("[data-update-busy]");
  if (updBusy) watchUpdate(updBusy.dataset.updateBusy);
  if (store.get("vs-updated")) {
    store.set("vs-updated", "");
    fetch("/api/update", { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then((res) => res.json())
      .then((s) => { if (s.last) toast(s.last.message, { ok: s.last.ok, bad: !s.last.ok, ms: 8000 }); })
      .catch(() => {});
  }
  $$("[data-steps-toggle]").forEach((g) => g.addEventListener("click", (e) => {
    const b = e.target.closest("[data-steps]"); if (!b) return;
    $$("[data-steps]", g).forEach((x) => x.setAttribute("aria-pressed", x === b));
    const scope = g.parentElement;
    $$("[data-steps-for]", scope).forEach((l) => { l.hidden = l.dataset.stepsFor !== b.dataset.steps; });
  }));
  $$("[data-qr]").forEach((box) => {
    const draw = () => {
      if (!window.qrcode) return setTimeout(draw, 100);
      const qr = window.qrcode(0, "M"); qr.addData(box.dataset.qr); qr.make();
      box.innerHTML = qr.createSvgTag({ cellSize: 4, margin: 0, scalable: true });
    };
    draw();
  });

  /* ── Money fields accept 12,50 and 12.50 ──────────── */
  $$("[data-money]").forEach((inp) => {
    const help = inp.closest(".field").querySelector("[data-money-help]");
    const base = help ? help.innerHTML : "";
    const check = () => {
      const raw = inp.value.trim().replace(/[€£$\s]/g, "");
      if (!raw) { inp.removeAttribute("aria-invalid"); if (help) { help.className = "help"; help.innerHTML = base; } return; }
      const n = Number(raw.replace(",", "."));
      if (!Number.isFinite(n) || n < 0) {
        inp.setAttribute("aria-invalid", "true");
        if (help) { help.className = "help help--error"; help.innerHTML = icon("circle-alert") + "<span>Type a price like 35 or 12,50.</span>"; }
      } else {
        inp.removeAttribute("aria-invalid");
        if (help) { help.className = "help"; help.innerHTML = base; }
      }
    };
    inp.addEventListener("input", check);
  });

  /* ── Discord link checked as you paste ────────────── */
  $$("[data-discord-url]").forEach((inp) => {
    inp.addEventListener("input", () => {
      const field = inp.closest(".field");
      let msg = field.querySelector("[data-discord-help], .help--error");
      if (!msg) { msg = document.createElement("p"); field.appendChild(msg); }
      msg.setAttribute("data-discord-help", "");
      const v = inp.value.trim();
      if (!v) { inp.removeAttribute("aria-invalid"); msg.className = "help"; msg.textContent = "Starts with discord.com/api/webhooks/."; return; }
      const ok = /^(https?:\/\/)?(ptb\.|canary\.)?discord(app)?\.com\/api\/webhooks\/\d+\/[\w-]+/i.test(v);
      const channel = /discord(app)?\.com\/channels\//i.test(v);
      inp.setAttribute("aria-invalid", ok ? "false" : "true");
      msg.className = ok ? "help help--ok" : "help help--error";
      msg.innerHTML = ok ? icon("circle-check-big") + "<span>That's a Discord webhook link.</span>"
        : icon("circle-alert") + (channel ? "<span>That's a link to the channel itself. Use Copy Webhook URL from the steps above.</span>" : "<span>That isn't a Discord webhook link. It starts with discord.com/api/webhooks/.</span>");
    });
  });

  /* ── Token inputs: words, "or" groups, tags, brands ── */
  const labelsInput = $("[data-labels]");
  let labels = {};
  try { labels = JSON.parse((labelsInput && labelsInput.value) || "{}"); } catch (e) { labels = {}; }
  const saveLabels = () => { if (labelsInput) labelsInput.value = JSON.stringify(labels); };
  const editorEl = $("[data-editor]");
  const tld = () => { const s = $("#site") || $("input[name=tld]"); return s ? s.value : (editorEl ? editorEl.dataset.tld : "fr"); };
  const changed = () => document.dispatchEvent(new CustomEvent("vs:changed"));

  $$("[data-tokens]").forEach((box) => {
    const hidden = $("[data-token-value]", box);
    const input = $("input:not([type=hidden])", box);
    const kind = box.dataset.tokens;
    const orMode = box.hasAttribute("data-or");
    const combo = box.closest("[data-combo]");
    const list = combo ? $(".combo__list", combo) : null;
    const isBrand = kind === "brand";
    let active = -1;
    const values = () => (hidden.value ? hidden.value.split(",").filter(Boolean) : []);
    const show = (v) => (isBrand ? (labels["brand:" + v] || "Brand #" + v) : orMode ? v.split("|").join(" or ") : v);
    const render = () => {
      $$(".token", box).forEach((t) => t.remove());
      values().forEach((v) => {
        const t = document.createElement("span");
        t.className = "token" + (kind === "no" ? " token--no" : "");
        t.innerHTML = `<span></span><button type="button">${icon("x")}</button>`;
        t.firstChild.textContent = show(v);
        t.lastChild.setAttribute("aria-label", "Remove " + show(v));
        t.lastChild.addEventListener("click", () => { hidden.value = values().filter((x) => x !== v).join(","); render(); changed(); input.focus(); });
        box.insertBefore(t, input);
      });
    };
    const add = (raw, label) => {
      let v = String(raw).trim().replace(/,/g, " ");
      if (!v) return;
      if (orMode) v = v.split(/\s+or\s+|\|/i).map((p) => p.trim()).filter(Boolean).join("|");
      if (isBrand && label) { labels["brand:" + v] = label; saveLabels(); }
      if (!values().includes(v)) hidden.value = [...values(), v].join(",");
      input.value = ""; close(); render(); changed();
    };
    const close = () => { if (list) { list.hidden = true; input.setAttribute("aria-expanded", "false"); } active = -1; };
    const suggest = debounce(async () => {
      const q = input.value.trim();
      if (!list || q.length < 2 || editorEl.dataset.builder !== "1") return close();
      const cats = ($("[data-cattree] [data-ids]") || {}).value || "";
      let data = {};
      try { data = await (await fetch(`/api/filters/${encodeURIComponent(tld())}/brands?q=${encodeURIComponent(q)}&catalog_ids=${encodeURIComponent(cats)}`)).json(); } catch (e) { data = {}; }
      if (input.value.trim() !== q) return;
      const hits = (data.brands || []).slice(0, 8);
      list.innerHTML = "";
      hits.forEach((b, i) => {
        const li = document.createElement("li");
        li.setAttribute("role", "option"); li.id = `opt-${i}`; li.dataset.v = b.id; li.dataset.label = b.title;
        li.setAttribute("aria-selected", "false");
        li.textContent = b.title;
        if (b.count != null) { const s = document.createElement("small"); s.textContent = `${b.count.toLocaleString()} listings`; li.appendChild(s); }
        list.appendChild(li);
      });
      if (!hits.length) { const li = document.createElement("li"); li.setAttribute("aria-disabled", "true"); li.textContent = data.error ? "Couldn't ask Vinted just now. Try again in a moment." : `No brand called "${q}" on this site.`; list.appendChild(li); }
      list.hidden = false; input.setAttribute("aria-expanded", "true");
    }, 250);
    render();
    box.addEventListener("click", (e) => { if (e.target === box) input.focus(); });
    if (isBrand) input.addEventListener("input", suggest);
    input.addEventListener("keydown", (e) => {
      const opts = list ? $$("li[data-v]", list) : [];
      if (e.key === "ArrowDown" && opts.length) { e.preventDefault(); active = (active + 1) % opts.length; }
      else if (e.key === "ArrowUp" && opts.length) { e.preventDefault(); active = (active - 1 + opts.length) % opts.length; }
      else if (e.key === "Enter" || e.key === ",") {
        e.preventDefault();
        if (isBrand) { const o = opts[active >= 0 ? active : 0]; if (o) add(o.dataset.v, o.dataset.label); }
        else add(input.value);
        return;
      } else if (e.key === "Escape") { close(); return; }
      else if (e.key === "Backspace" && !input.value) { const v = values(); v.pop(); hidden.value = v.join(","); render(); changed(); return; }
      else return;
      opts.forEach((o, i) => o.setAttribute("aria-selected", i === active));
      if (opts[active]) input.setAttribute("aria-activedescendant", opts[active].id);
    });
    if (!isBrand) input.addEventListener("blur", () => { if (input.value.trim()) add(input.value); });
    if (list) list.addEventListener("mousedown", (e) => { const li = e.target.closest("li[data-v]"); if (li) { e.preventDefault(); add(li.dataset.v, li.dataset.label); } });
    input.addEventListener("blur", () => setTimeout(close, 150));
  });

  /* ── Category tree ────────────────────────────────── */
  const tree = $("[data-cattree]");
  let treeData = null; let path = [];
  const byId = {};
  function walk(nodes, parents) { nodes.forEach((n) => { byId[n.id] = { node: n, parents }; walk(n.children || [], [...parents, n]); }); }
  async function loadTree() {
    if (!tree || editorEl.dataset.builder !== "1") return;
    const status = $("[data-cattree-status]", tree);
    try {
      const data = await (await fetch(`/api/filters/${encodeURIComponent(tld())}/categories`)).json();
      if (!data.categories) throw new Error(data.error || "no tree");
      treeData = data.categories; walk(treeData, []);
      const first = ($("[data-ids]", tree).value || "").split(",").filter(Boolean)[0];
      path = first && byId[first] ? byId[first].parents : [];
      drawTree();
    } catch (e) { status.textContent = "Couldn't load Vinted's categories just now. Paste a search link instead, or try again later."; }
  }
  function drawTree() {
    const hidden = $("[data-ids]", tree);
    const picked = (hidden.value || "").split(",").filter(Boolean);
    const level = path.length ? path[path.length - 1].children : treeData;
    const crumbs = ['<nav class="crumbtrail" aria-label="Category path"><button type="button" data-crumb="-1">All</button>',
      ...path.map((n, i) => `${icon("chevron-right")}<button type="button" data-crumb="${i}"${i === path.length - 1 ? ' aria-current="true"' : ""}>${esc(n.title)}</button>`), "</nav>"].join("");
    const chips = level.map((n) => `<span class="chip chip--sm${picked.includes(String(n.id)) ? " is-on" : ""}"><label style="display:inline-flex;gap:6px;align-items:center;cursor:pointer"><input type="checkbox" value="${esc(n.id)}"${picked.includes(String(n.id)) ? " checked" : ""}>${esc(n.title)}</label>${n.children && n.children.length ? `<button type="button" class="chip__x" data-into="${esc(n.id)}" aria-label="Open ${esc(n.title)}">${icon("chevron-right")}</button>` : ""}</span>`).join("");
    const names = picked.map((id) => (byId[id] ? byId[id].node.title : "#" + id));
    $$(".crumbtrail, .chips, [data-cattree-status]", tree).forEach((x) => x.remove());
    tree.insertAdjacentHTML("beforeend", crumbs + `<div class="chips">${chips}</div><p class="t-sm" data-cattree-status>${picked.length ? "Picked: " + esc(names.join(", ")) : "Any category. Open one to narrow it down."}</p>`);
  }
  if (tree) {
    tree.addEventListener("click", (e) => {
      const c = e.target.closest("[data-crumb]"); const into = e.target.closest("[data-into]");
      if (c) { path = path.slice(0, Number(c.dataset.crumb) + 1); drawTree(); }
      if (into) { path = [...byId[into.dataset.into].parents, byId[into.dataset.into].node]; drawTree(); }
    });
    tree.addEventListener("change", (e) => {
      const box = e.target.closest("input[type=checkbox]"); if (!box) return;
      const hidden = $("[data-ids]", tree);
      let picked = (hidden.value || "").split(",").filter(Boolean);
      picked = box.checked ? [...new Set([...picked, box.value])] : picked.filter((x) => x !== box.value);
      hidden.value = picked.join(","); drawTree(); loadFacets(); changed();
    });
    loadTree();
  }

  /* ── Sizes, condition, colours ────────────────────── */
  async function loadFacet(set) {
    if (editorEl.dataset.builder !== "1") return;
    const code = set.dataset.facet; const hidden = $("[data-ids]", set); const box = $("[data-facet-chips]", set);
    const cats = ($("[data-cattree] [data-ids]") || {}).value || "";
    if (code === "size" && !cats) { box.innerHTML = `<span class="t-sm">${hidden.value ? hidden.value.split(",").length + " picked. " : ""}Pick a category first for its sizes.</span>`; return; }
    let data = {};
    try { data = await (await fetch(`/api/filters/${encodeURIComponent(tld())}/facets/${code}?catalog_ids=${encodeURIComponent(cats)}`)).json(); } catch (e) { data = {}; }
    const opts = (data.options || []).slice(0, 80);
    const picked = (hidden.value || "").split(",").filter(Boolean);
    if (!opts.length) { box.innerHTML = `<span class="t-sm">${picked.length ? picked.length + " picked. " : ""}Couldn't load the choices from Vinted just now.</span>`; return; }
    box.innerHTML = opts.map((o) => `<label class="chip chip--sm"><input type="checkbox" value="${esc(o.id)}"${picked.includes(String(o.id)) ? " checked" : ""}>${esc(o.title)}${o.group && code === "size" ? ` <small class="t-sm">${esc(o.group)}</small>` : ""}</label>`).join("");
  }
  function loadFacets() { $$("[data-facet]").forEach(loadFacet); }
  $$("[data-facet]").forEach((set) => set.addEventListener("change", (e) => {
    const box = e.target.closest("input[type=checkbox]"); if (!box) return;
    const hidden = $("[data-ids]", set);
    let picked = (hidden.value || "").split(",").filter(Boolean);
    picked = box.checked ? [...new Set([...picked, box.value])] : picked.filter((x) => x !== box.value);
    hidden.value = picked.join(","); changed();
  }));
  if (editorEl) loadFacets();
  const site = $("#site");
  if (site) site.addEventListener("change", () => {
    path = []; treeData = null; const h = $("[data-cattree] [data-ids]"); if (h) h.value = "";
    if (tree) loadTree(); loadFacets(); changed();
  });

  /* ── Live preview: one real search, debounced, cached by the server ── */
  const preview = $("[data-preview]");
  const form = editorEl ? editorEl.closest("form") : null;
  let previewTimer = null;
  async function runPreview() {
    if (!preview || !form || editorEl.dataset.previews !== "1") return;
    const data = new FormData(form);
    const mode = data.get("mode");
    if (mode === "build") data.set("link", "");
    if (mode === "paste" && !String(data.get("link") || "").trim()) return;
    if (!String(data.get("link") || "").trim() && !data.get("search_text") && !data.get("catalog_ids") && !data.get("brand_ids")) return;
    const count = $("[data-preview-count]", preview); const label = $("[data-preview-label]", preview);
    label.textContent = "Asking Vinted…";
    const qs = editorEl.dataset.search ? `?search=${editorEl.dataset.search}` : "";
    let r;
    try { r = await post("/api/preview" + qs, data, { quiet: true }); } catch (e) { return; }
    if (r.status === 429 && r.wait) { clearTimeout(previewTimer); previewTimer = setTimeout(runPreview, r.wait * 1000 + 200); label.textContent = "One moment…"; return; }
    if (r.error || r.count == null) {
      count.textContent = "–";
      const first = r.errors ? Object.values(r.errors)[0] : null;
      label.textContent = r.error || first || "Fill in the search to see what matches";
      return;
    }
    count.textContent = r.count; count.hidden = false;
    label.textContent = r.count === 1 ? "listing matches right now" : "listings match right now";
    // The phone layout has a second set of thumbnails above the Continue button.
    const thumbHtml = r.thumbs.map((t) => `<a class="t" href="${esc(t.url)}" target="_blank" rel="noopener" title="${esc(t.title)}">${t.photo ? `<img src="${esc(t.photo)}" alt="" referrerpolicy="no-referrer">` : ""}<span>${esc(t.total)}</span></a>`).join("");
    $$("[data-preview-thumbs]").forEach((box) => { box.innerHTML = thumbHtml; });
    const receipt = $("[data-preview-receipt]", preview);
    receipt.innerHTML = `<div class="receipt__row">${icon("search")}<span>Newest on ${esc(r.site)}</span><b>${r.seen}</b></div>` +
      r.receipt.map((x) => `<div class="receipt__row">${icon(x.icon)}<span>${esc(x.label)}</span><b>−${x.removed}</b></div>`).join("") +
      `<div class="receipt__row receipt__row--total">${icon("check")}<span>Match your filters</span><b>${r.count}</b></div>`;
    const note = $("[data-preview-note]", preview); if (note) note.hidden = !r.seller_filters;
    const live = $("[data-livecount]"); if (live) live.innerHTML = `<b class="num">${esc(r.count)}</b> ${r.count === 1 ? "listing" : "listings"} on ${esc(r.site)} match right now.${r.newest ? " Newest " + esc(r.newest) + "." : ""}${r.understood ? `<br><span class="t-sm">Got it: ${esc(r.understood)}</span>` : ""}`;
    const sb = $("[data-savebar-count]"); if (sb) sb.textContent = `${r.count} match now`;
  }
  const schedule = debounce(runPreview, 900);
  if (form && preview) {
    form.addEventListener("input", (e) => { if (!e.target.closest(".tokens")) schedule(); });
    form.addEventListener("change", schedule);
    document.addEventListener("vs:changed", schedule);
    const again = $("[data-preview-refresh]"); if (again) again.addEventListener("click", runPreview);
    runPreview();
  }

  /* ── Finds: layout, older, save, menu, quick view ─── */
  const feed = $("#feed");
  $$("[data-view]").forEach((b) => b.addEventListener("click", () => {
    $$("[data-view]").forEach((x) => x.setAttribute("aria-pressed", x === b));
    if (feed) feed.classList.toggle("is-list", b.dataset.view === "list");
    store.set("vs-view", b.dataset.view);
  }));
  if (feed && store.get("vs-view") === "list") { const lb = $("[data-view=list]"); if (lb) lb.click(); }
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-older]");
    if (!b) return;
    b.disabled = true;
    const params = new URLSearchParams(location.search); params.set("before", b.dataset.older);
    try {
      const r = await (await fetch("/api/finds?" + params)).json();
      feed.insertAdjacentHTML("beforeend", r.html);
      if (r.more) { b.dataset.older = r.more; b.disabled = false; } else b.parentElement.remove();
    } catch (err) { b.disabled = false; toast("Couldn't load older finds. Try again.", { bad: true }); }
  });

  const itemId = (card) => card && card.dataset.itemId;
  async function mark(card, value) {
    const r = await post(`/api/items/${itemId(card)}/mark`, { mark: value });
    if (!r.ok) toast(r.error || "That didn't save. Try again.", { bad: true });
    return r.ok;
  }
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-toggle-save]");
    if (!b) return;
    const qv = b.closest("#quickview");
    const card = qv ? qv._card : b.closest(".item");
    if (!card) return;
    const on = b.getAttribute("aria-pressed") !== "true";
    if (!(await mark(card, on ? "saved" : "none"))) return;
    [...$$("[data-toggle-save]", card), ...(qv ? [b] : [])].forEach((x) => x.setAttribute("aria-pressed", on));
    toast(on ? "Saved. Find it under Saved." : "Removed from saved", { ok: on, icon: on ? "heart" : "info" });
  });

  const menu = $("#item-menu");
  let menuFor = null;
  function closeMenu() { if (!menu || menu.hidden) return; menu.hidden = true; if (menuFor) { menuFor.setAttribute("aria-expanded", "false"); menuFor.focus(); } }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-menu]");
    if (b && menu) {
      e.preventDefault();
      if (menuFor === b && !menu.hidden) return closeMenu();
      closeMenu(); menuFor = b;
      b.setAttribute("aria-expanded", "true"); menu.hidden = false;
      const r = b.getBoundingClientRect(); const w = menu.offsetWidth;
      menu.style.top = (window.scrollY + r.bottom + 6) + "px";
      menu.style.left = Math.max(8, Math.min(window.scrollX + r.right - w, document.documentElement.clientWidth - w - 8)) + "px";
      const card = b.closest(".item"); const link = $("[data-act=open]", menu);
      if (link && card) link.href = $(".item__open", card).href;
      const first = $("button, a", menu); if (first) first.focus();
      return;
    }
    if (menu && !menu.hidden && !e.target.closest("#item-menu")) closeMenu();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });

  let blockFor = null;
  async function act(name, card) {
    if (!card) return;
    if (name === "watch" || name === "follow") {
      const r = await post(`/api/items/${itemId(card)}/${name === "watch" ? "watch" : "follow-seller"}`);
      toast(r.ok ? (name === "watch" ? "Watching the price. See Watchlist." : "Following this seller. See Watchlist.") : (r.error || "That didn't work."), { ok: r.ok, bad: !r.ok, icon: "eye" });
    } else if (name === "copy") {
      const u = $(".item__open", card).href;
      if (navigator.clipboard) navigator.clipboard.writeText(u).catch(() => {});
      toast("Link copied", { ok: true, icon: "link" });
    } else if (name === "hide") {
      if (!(await mark(card, "hidden"))) return;
      card.hidden = true;
      const qv = $("#quickview"); if (qv && qv.open) qv.close();
      toast("Hidden from your finds", { action: "Undo", onAction: async () => { if (await mark(card, "none")) card.hidden = false; } });
    } else if (name === "block") {
      blockFor = card;
      const qv = $("#quickview"); if (qv && qv.open) qv.close();
      openDialog("block-confirm");
    }
  }
  document.addEventListener("click", (e) => {
    const a = e.target.closest("[data-act]");
    if (!a || a.dataset.act === "open") return;
    e.preventDefault();
    const qv = a.closest("#quickview");
    const card = qv ? qv._card : (menuFor ? menuFor.closest(".item") : null);
    closeMenu();
    act(a.dataset.act, card);
  });
  const bc = $("[data-block-confirm]");
  if (bc) bc.addEventListener("click", async () => {
    const d = bc.closest("dialog");
    if (!blockFor) return d.close();
    const r = await post(`/api/items/${itemId(blockFor)}/block-seller`);
    d.close();
    if (!r.ok) return toast(r.error || "That didn't work.", { bad: true });
    // Everything from that seller goes, not just the card the block came from.
    const seller = blockFor.dataset.seller;
    $$(".item").forEach((c) => { if (c === blockFor || (seller && c.dataset.seller === seller)) c.hidden = true; });
    toast(`Blocked ${r.seller}. Their finds are hidden. Undo in Settings.`, { ok: true, icon: "ban" });
  });

  const qv = $("#quickview");
  function quickview(card, from) {
    if (!qv || !card) return;
    qv._card = card;
    const a = $(".item__open", card); const img = $(".item__media img", card);
    const set = (k, v) => { const n = $(`[data-qv=${k}]`, qv); if (n) n.innerHTML = v; };
    $("[data-qv=img]", qv).src = img ? img.src : "";
    set("title", esc($(".item__title", card).textContent));
    set("search", $(".schip", card) ? $(".schip", card).outerHTML : "");
    set("price", "Item price " + esc($(".item__base > span", card).textContent));
    set("total", $(".item__total", card).innerHTML);
    const deal = $(".item__flags .badge--deal", card);
    set("deal", deal ? `<span class="badge badge--deal">${deal.innerHTML}</span>` : "");
    const meta = $(".item__meta", card); const seller = $(".item__seller", card);
    set("dl", (meta ? `<dt>Details</dt><dd>${esc(meta.textContent)}</dd>` : "") +
      `<dt>Found</dt><dd>${esc($(".item__foot time", card).textContent)}</dd>` +
      (seller ? `<dt>Seller rating</dt><dd>${esc(seller.textContent.trim())}</dd>` : `<dt>Seller rating</dt><dd class="t-muted">Vinted didn't share it for this listing</dd>`));
    const id = itemId(card); const t = card.dataset.tld;
    $("[data-qv=url]", qv).href = a.href;
    $("[data-qv=buy]", qv).href = `https://www.vinted.${t}/transaction/buy/new?source_screen=item&transaction%5Bitem_id%5D=${id}`;
    $("[data-qv=message]", qv).href = `https://www.vinted.${t}/items/${id}/want_it/new`;
    $("[data-toggle-save]", qv).setAttribute("aria-pressed", $(".item__save", card).getAttribute("aria-pressed"));
    openDialog("quickview", from);
  }
  document.addEventListener("click", (e) => {
    const a = e.target.closest("[data-quickview]");
    if (!a || !qv || e.metaKey || e.ctrlKey || e.shiftKey) return;
    e.preventDefault();
    quickview(a.closest(".item"), a);
  });

  /* ── Keyboard shortcuts on Finds ──────────────────── */
  let cursor = -1;
  const visibleCards = () => (feed ? $$(".item", feed).filter((c) => !c.hidden) : []);
  function moveCursor(d) {
    const cards = visibleCards(); if (!cards.length) return;
    cards.forEach((c) => c.classList.remove("is-cursor"));
    cursor = Math.max(0, Math.min(cards.length - 1, cursor + d));
    const c = cards[cursor]; c.classList.add("is-cursor");
    c.scrollIntoView({ block: "nearest", behavior: reduced ? "auto" : "smooth" });
    // Real focus, so a screen reader follows the cursor too.
    const open = $(".item__open", c); if (open) open.focus({ preventScroll: true });
  }
  // The same letters work on the find whose details are open.
  document.addEventListener("keydown", (e) => {
    if (!qv || !qv.open || !qv._card || e.metaKey || e.ctrlKey || e.altKey || e.target.closest("input, textarea, select")) return;
    const card = qv._card;
    const keys = {
      o: () => window.open($(".item__open", card).href, "_blank", "noopener"),
      s: () => $("[data-toggle-save]", qv).click(),
      h: () => act("hide", card), b: () => act("block", card), w: () => act("watch", card),
    };
    if (keys[e.key]) { e.preventDefault(); keys[e.key](); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey || e.target.closest("input, textarea, select, [contenteditable], dialog[open]")) return;
    if (e.key === "/") { const q = $("#q"); if (q && q.offsetParent) { e.preventDefault(); q.focus(); } return; }
    if (!feed) return;
    const card = visibleCards()[cursor];
    const keys = {
      j: () => moveCursor(1), k: () => moveCursor(-1),
      o: () => card && window.open($(".item__open", card).href, "_blank", "noopener"),
      Enter: () => card && quickview(card, $(".item__open", card)),
      s: () => card && $(".item__save", card).click(),
      h: () => card && act("hide", card), b: () => card && act("block", card), w: () => card && act("watch", card),
      "?": () => openDialog("keys"),
    };
    if (keys[e.key]) { e.preventDefault(); keys[e.key](); }
  });

  /* ── Sound and pop-ups ────────────────────────────── */
  let soundOn = store.get("vs-sound") === "1";
  let actx = null;
  function chirp() {
    try {
      actx = actx || new (window.AudioContext || window.webkitAudioContext)();
      const t = actx.currentTime;
      [880, 1320].forEach((f, i) => {
        const o = actx.createOscillator(); const g = actx.createGain();
        o.type = "sine"; o.frequency.value = f;
        g.gain.setValueAtTime(0.0001, t + i * 0.09);
        g.gain.exponentialRampToValueAtTime(0.18, t + i * 0.09 + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, t + i * 0.09 + 0.16);
        o.connect(g).connect(actx.destination); o.start(t + i * 0.09); o.stop(t + i * 0.09 + 0.18);
      });
    } catch (e) { /* no audio on this device */ }
  }
  function paintSound() {
    $$("[data-sound]").forEach((b) => {
      b.setAttribute("aria-pressed", soundOn);
      b.setAttribute("aria-label", soundOn ? "Sound in this tab is on. Turn off" : "Sound in this tab is off. Turn on");
      const u = b.querySelector("use"); if (u) u.setAttribute("href", soundOn ? "#i-volume-2" : "#i-volume-x");
      const l = $("[data-sound-label]", b); if (l) l.textContent = soundOn ? "Sound on" : "Sound off";
    });
    $$("[data-sound-switch]").forEach((s) => { s.checked = soundOn; });
  }
  function setSound(on) { soundOn = on; store.set("vs-sound", on ? "1" : "0"); paintSound(); if (on) chirp(); }
  paintSound();
  document.addEventListener("click", (e) => {
    if (!e.target.closest("[data-sound]")) return;
    setSound(!soundOn);
    toast(soundOn ? "Sound on. You'll hear new finds while this tab is open." : "Sound off", { icon: soundOn ? "volume-2" : "volume-x" });
  });
  $$("[data-sound-switch]").forEach((s) => s.addEventListener("change", () => setSound(s.checked)));
  function paintNotify() {
    const ok = "Notification" in window;
    $$("[data-notify-state]").forEach((n) => {
      n.textContent = !ok ? "This browser can't show pop-ups." : Notification.permission === "granted" ? "Allowed. Pop-ups show while this tab is in the background." : Notification.permission === "denied" ? "Off in this browser. Not needed if your phone gets the alerts; to turn on, allow notifications in the browser's site settings." : "Your browser asks once for permission.";
    });
    $$("[data-notify-allow]").forEach((b) => { b.hidden = !ok || Notification.permission !== "default"; });
  }
  paintNotify();
  document.addEventListener("click", (e) => {
    if (!e.target.closest("[data-notify-allow]") || !("Notification" in window)) return;
    Notification.requestPermission().then(paintNotify);
  });

  /* ── Live feed over Server-Sent Events ────────────── */
  let unseen = 0;
  const baseTitle = document.title;
  function bumpNew(n) {
    unseen += n;
    $$("[data-new-count]").forEach((c) => { c.textContent = unseen; c.hidden = !unseen; });
    if (document.hidden) document.title = `(${unseen}) New finds · vinted-bot`;
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) document.title = baseTitle; });
  const liveFrom = feed && feed.dataset.live;
  if (liveFrom !== undefined && liveFrom !== null && "EventSource" in window) {
    let failures = 0;
    const banner = $("#offline-banner");
    const es = new EventSource(`/api/live?after=${encodeURIComponent(liveFrom)}`);
    es.addEventListener("open", () => { failures = 0; if (banner) banner.hidden = true; });
    es.addEventListener("error", () => { failures += 1; if (banner && failures >= 3) banner.hidden = false; });
    es.addEventListener("item", (ev) => {
      let it; try { it = JSON.parse(ev.data); } catch (e) { return; }
      if (feed.hidden) { location.reload(); return; }
      if (!feed.hasAttribute("data-filtered")) {
        const tpl = document.createElement("template"); tpl.innerHTML = it.html.trim();
        const card = tpl.content.firstElementChild;
        if (card) {
          if (!reduced) card.classList.add("is-arriving");
          $$(".item.is-fresh", feed).forEach((c) => c.classList.remove("is-fresh"));
          feed.prepend(card); if (cursor >= 0) cursor += 1;
        }
        const today = $("[data-today]"); if (today) today.textContent = String(Number(today.textContent) + 1);
      }
      bumpNew(1);
      const text = `New find: ${it.title}, ${it.total}`;
      toast(text, { img: it.photo, ms: 6000, action: "Show", onAction: () => { const c = $(`.item[data-item-id="${it.id}"]`, feed); if (c) quickview(c); } });
      if (soundOn) chirp();
      if (document.hidden && "Notification" in window && Notification.permission === "granted") {
        try { new Notification(it.deal_pct ? `${it.deal_pct}% under typical: ${it.title}` : it.title, { body: `${it.total} incl. fees · ${it.search}`, icon: it.photo || undefined, tag: "vs-" + it.id }); } catch (e) { /* some browsers only allow this from a service worker */ }
      }
    });
  }

  /* ── The logo ring counts down to the next check ──── */
  const ring = $("[data-tick]");
  if (ring && ring.dataset.tick !== "" && !reduced) {
    let left = Number(ring.dataset.tick); const total = Math.max(left / Math.max(1 - Number(getComputedStyle(ring).getPropertyValue("--tick") || 0), 0.01), 30);
    setInterval(() => {
      left = left <= 0 ? total : left - 1;
      ring.style.setProperty("--tick", (1 - left / total).toFixed(3));
      ring.title = left > 0 ? `Next check in about ${Math.round(left)} seconds` : "Checking now";
    }, 1000);
  }
  $$("[data-ago]").forEach((t) => {
    let s = Number(t.dataset.ago);
    setInterval(() => { s += 10; t.textContent = s < 45 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.floor(s / 3600)} h ago`; }, 10000);
  });

  /* ── Searches list: select, bulk bar, filter ──────── */
  const bulk = $("[data-bulkbar]");
  function syncBulk() {
    const boxes = $$("[data-select-row]");
    const n = boxes.filter((b) => b.checked).length;
    boxes.forEach((b) => b.closest(".srow").classList.toggle("is-selected", b.checked));
    if (bulk) bulk.hidden = n === 0;
    $$("[data-bulk-count]").forEach((c) => { c.textContent = n === 1 ? "1 search" + (c.closest(".bulkbar") ? " selected" : "") : `${n} searches` + (c.closest(".bulkbar") ? " selected" : ""); });
    const all = $("[data-select-all]");
    if (all) { all.checked = n === boxes.length && n > 0; all.indeterminate = n > 0 && n < boxes.length; }
  }
  $$("[data-select-row]").forEach((b) => b.addEventListener("change", syncBulk));
  const all = $("[data-select-all]");
  if (all) all.addEventListener("change", () => { $$("[data-select-row]").forEach((b) => { b.checked = all.checked; }); syncBulk(); });
  $$("[data-bulk-clear]").forEach((b) => b.addEventListener("click", () => { $$("[data-select-row]").forEach((x) => { x.checked = false; }); syncBulk(); }));
  const sq = $("#search-filter");
  if (sq) sq.addEventListener("input", () => { const q = sq.value.toLowerCase(); $$(".srow").forEach((r) => { r.hidden = !r.textContent.toLowerCase().includes(q); }); });
  $$("[data-status-filter]").forEach((chip) => chip.addEventListener("click", () => {
    $$("[data-status-filter]").forEach((c) => c.setAttribute("aria-pressed", c === chip));
    const st = chip.dataset.statusFilter;
    $$(".srow").forEach((r) => { r.hidden = st !== "all" && !(r.dataset.filters || "").split(" ").includes(st); });
  }));

  /* ── Alerts: test sends, options, adding a place ──── */
  async function busy(b, work) {
    if (b.dataset.busy) return; b.dataset.busy = "1";
    const label = b.innerHTML;
    b.innerHTML = '<span class="spinner" style="width:16px;height:16px;border-width:2px"></span>Sending';
    try { await work(); } finally { b.innerHTML = label; delete b.dataset.busy; }
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-test-dest]");
    if (!b) return;
    busy(b, async () => {
      const r = await post(`/destinations/${b.dataset.testDest}/test`);
      const text = r.ok ? r.message : r.message + (r.detail ? " " + r.detail : "");
      // Reload so the card's badge shows how the test went; the toast follows the reload.
      try { sessionStorage.setItem("vs-after", JSON.stringify({ text, bad: !r.ok })); location.reload(); }
      catch (err) { toast(text, { ok: r.ok, bad: !r.ok, ms: 9000 }); }
    });
  });
  $$("form[data-autosave]").forEach((f) => {
    const save = debounce(async () => {
      const r = await post(f.dataset.autosave, new FormData(f));
      $$("[data-error-for]", f).forEach((p) => { p.hidden = true; });
      if (r.ok) toast("Saved", { ok: true });
      else {
        const p = $(`[data-error-for="${r.field}"]`, f);
        if (p) { p.hidden = false; p.innerHTML = icon("circle-alert") + `<span>${esc(r.error)}</span>`; } else toast(r.error || "That didn't save.", { bad: true });
      }
    }, 500);
    f.addEventListener("change", save);
    f.addEventListener("submit", (e) => { e.preventDefault(); save(); });
  });
  const addForm = $("[data-add-dest]");
  // A problem shows under the field it is about; only the rest goes to the bottom line.
  function clearAddErrors() {
    if (!addForm) return;
    $$("[data-field-error]", addForm).forEach((n) => n.remove());
    $$("[aria-invalid=true]", addForm).forEach((n) => n.removeAttribute("aria-invalid"));
    const err = $("[data-add-error]", addForm); if (err) err.hidden = true;
  }
  function showAddError(fieldName, message) {
    clearAddErrors();
    const picked = $(".choice:has(input[data-kind-pick]:checked)", addForm);
    const input = fieldName && picked ? $(`[name="${fieldName}"]`, picked) : null;
    const field = input && input.closest(".field");
    if (field) {
      input.setAttribute("aria-invalid", "true");
      const own = $("[data-discord-help]", field); if (own) own.remove();
      const p = document.createElement("p"); p.className = "help help--error"; p.dataset.fieldError = "";
      p.innerHTML = icon("circle-alert") + `<span>${esc(message)}</span>`;
      field.appendChild(p); input.focus();
      return;
    }
    const err = $("[data-add-error]", addForm);
    err.hidden = false; err.innerHTML = icon("circle-alert") + `<span>${esc(message)}</span>`;
  }
  if (addForm) addForm.addEventListener("change", (e) => { if (e.target.matches("[data-kind-pick]")) clearAddErrors(); });
  if (addForm) addForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearAddErrors();
    const err = $("[data-add-error]", addForm);
    const data = new FormData(addForm);
    if (data.get("kind") === "telegram") {
      if (!data.get("telegram_id")) { err.hidden = false; err.textContent = "Connect your chat first with the button above."; return; }
      location.reload(); return;
    }
    const btn = $("button[type=submit]", addForm);
    await busy(btn, async () => {
      const r = await post("/destinations", data);
      if (!r.ok) { showAddError(r.field, r.error); return; }
      const t = await post(`/destinations/${r.id}/test`);
      sessionStorage.setItem("vs-after", JSON.stringify({ text: (t.ok ? "Added, and a test is on its way. " : "Added, but the test didn't arrive: ") + t.message, bad: !t.ok }));
      location.reload();
    });
  });
  try {
    const after = sessionStorage.getItem("vs-after");
    if (after) { sessionStorage.removeItem("vs-after"); const a = JSON.parse(after); toast(a.text, { ok: !a.bad, bad: a.bad, ms: 9000 }); }
  } catch (e) { /* no storage, or an old plain-text value */ }
  $$("[data-kind-pick]").forEach((r) => r.addEventListener("change", () => {
    $$("[data-preview-for]").forEach((p) => { p.hidden = !p.dataset.previewFor.split(" ").includes(r.value); });
  }));
  const picked = $("[data-kind-pick]:checked");
  if (picked) $$("[data-preview-for]").forEach((p) => { p.hidden = !p.dataset.previewFor.split(" ").includes(picked.value); });

  /* ── Telegram pairing: code, then wait for the bot to claim it ── */
  document.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-pair-start]");
    if (!b) return;
    const wrap = b.closest("[data-pair]");
    const r = await post("/destinations/telegram/pair");
    if (r.error) return toast(r.error, { bad: true, ms: 9000 });
    $("[data-pair-command]", wrap).textContent = r.command;
    const link = $("[data-pair-link]", wrap); if (r.link) { link.href = r.link; link.hidden = false; }
    $("[data-pair-id]", wrap).value = r.id;
    $$("[data-pair-step]", wrap).forEach((s) => { s.hidden = s.dataset.pairStep !== "wait"; });
    const started = Date.now();
    const poll = async () => {
      if (Date.now() - started > 30 * 60 * 1000) return;
      let st = {};
      try { st = await (await fetch(`/destinations/telegram/pair/${r.id}`)).json(); } catch (err) { st = {}; }
      if (st.connected) {
        $$("[data-pair-step]", wrap).forEach((s) => { s.hidden = s.dataset.pairStep !== "done"; });
        toast("Found your chat. Telegram is connected.", { ok: true, icon: "send" });
      } else setTimeout(poll, 2500);
    };
    poll();
  });

  /* ── Settings that save as you change them ────────── */
  $$("[data-setting]").forEach((el) => {
    const key = el.dataset.setting;
    const value = () => (el.type === "checkbox" ? (el.checked ? "1" : "0") : el.value);
    const save = async () => {
      if (el.type === "radio" && !el.checked) return;
      if (key === "theme") setTheme(el.value, false);
      const r = await post("/settings", { key, value: value() });
      const help = $(`[data-setting-help="${key}"]`);
      if (r.ok) { el.removeAttribute("aria-invalid"); toast("Saved", { ok: true }); if (help) { help.className = "help"; help.textContent = value() ? "Saved." : "Off."; } }
      else { el.setAttribute("aria-invalid", "true"); if (help) { help.className = "help help--error"; help.innerHTML = icon("circle-alert") + `<span>${esc(r.error)}</span>`; } else toast(r.error, { bad: true }); }
    };
    el.addEventListener("change", save);
  });
  const diag = $("[data-diagnose]");
  if (diag) diag.addEventListener("click", () => busy(diag, async () => {
    const sel = $("#diag-tld");
    const r = await post("/api/diagnose", { tld: sel ? sel.value : "" });
    const row = $("[data-diag-result]"); row.hidden = false;
    $("[data-diag-text]").textContent = r.message || r.error || "No answer.";
    const ms = $("[data-diag-ms]"); ms.textContent = r.elapsed_ms != null ? `${(r.elapsed_ms / 1000).toFixed(1)} s` : "";
    ms.className = r.catalog_ok ? "ok-ink" : "bad-ink";
  }));

  /* ── Chart tooltips: any [data-tip] inside a .chart ── */
  /* A tip reads "<b>headline</b><br>detail". It is built from text nodes only, never
   * parsed as HTML: the detail can be a search name, which is whatever was typed or
   * pasted (or sent to the Telegram bot), and the browser has already decoded the
   * attribute's escaping by the time it is read here. */
  function fillTip(tip, raw) {
    tip.replaceChildren();
    const parts = /^<b>([\s\S]*?)<\/b><br>([\s\S]*)$/.exec(raw || "");
    if (!parts) { tip.textContent = raw || ""; return; }
    const head = document.createElement("b"); head.textContent = parts[1];
    tip.append(head, document.createElement("br"), document.createTextNode(parts[2]));
  }
  $$(".chart").forEach((chart) => {
    const tip = document.createElement("div");
    tip.className = "tip"; tip.hidden = true; tip.setAttribute("role", "status");
    chart.appendChild(tip);
    const show = (el) => {
      const r = el.getBoundingClientRect(); const c = chart.getBoundingClientRect();
      fillTip(tip, el.dataset.tip); tip.hidden = false;
      tip.style.left = Math.max(60, Math.min(c.width - 60, r.left - c.left + r.width / 2)) + "px";
      tip.style.top = (r.top - c.top) + "px";
      $$(".is-hot", chart).forEach((x) => x.classList.remove("is-hot"));
      const bar = el.previousElementSibling; if (bar && bar.classList.contains("bar")) bar.classList.add("is-hot");
    };
    const hide = () => { tip.hidden = true; $$(".is-hot", chart).forEach((x) => x.classList.remove("is-hot")); };
    chart.addEventListener("mouseover", (e) => { const t = e.target.closest("[data-tip]"); if (t) show(t); });
    chart.addEventListener("focusin", (e) => { const t = e.target.closest("[data-tip]"); if (t) show(t); });
    chart.addEventListener("mouseleave", hide);
    chart.addEventListener("focusout", hide);
  });

  /* ── Onboarding: focus the question, guard double clicks ── */
  const h = $("[data-autofocus]");
  if (h) h.focus({ preventScroll: true });
  const obf = $("#ob-form");
  if (obf) obf.addEventListener("submit", (e) => {
    if (obf.dataset.sent) { e.preventDefault(); return; }
    obf.dataset.sent = "1";
    setTimeout(() => { delete obf.dataset.sent; }, 8000);
  });
  /* ── Time zone: told once by the browser when the computer's own couldn't be read ── */
  if (document.body.hasAttribute("data-guess-tz")) {
    try {
      const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (zone) post("/settings", { key: "timezone_guess", value: zone }, { quiet: true }).catch(() => {});
    } catch (e) { /* no Intl: the setting stays as it is */ }
  }
  // Long option lists start folded on a phone; a computer has room to show them.
  if (matchMedia("(max-width: 760px)").matches) $$("details[data-collapse-sm]").forEach((d) => { d.open = false; });
  // The mail server only matters for "Something else".
  $$("[data-smtp-field]").forEach((f) => {
    const sel = $("select[name=email_provider]", f.closest(".stack") || document);
    if (sel) sel.addEventListener("change", () => { f.hidden = sel.value !== "other"; });
  });
  // Show what was typed in a password field, for long made-up passwords.
  $$("[data-show-password]").forEach((b) => b.addEventListener("click", () => {
    const input = document.getElementById(b.dataset.showPassword); if (!input) return;
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    b.setAttribute("aria-pressed", show);
    const label = $("span", b); if (label) label.textContent = show ? "Hide" : "Show";
    input.focus();
  }));
  // Typed-but-not-entered words still count when a form is saved.
  $$("form").forEach((f) => f.addEventListener("submit", () => {
    $$("[data-tokens]:not([data-tokens=brand]) input:not([type=hidden])", f).forEach((i) => i.dispatchEvent(new Event("blur")));
  }));
})();
