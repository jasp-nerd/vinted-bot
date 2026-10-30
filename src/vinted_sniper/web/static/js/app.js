/* vinted-sniper: small progressive enhancements. Every page works without this file;
 * it adds theme switching, toasts, dialogs, tabs, chip inputs and the live feed.
 * In the real app the live feed listens to Server-Sent Events (/api/events) instead of
 * the demo timer below. Look for "REAL APP" comments. */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
  };
  const icon = (name, cls = "") => `<svg class="i ${cls}" aria-hidden="true"><use href="#i-${name}"></use></svg>`;

  /* ── Toasts ───────────────────────────────────────── */
  function toast(text, opts = {}) {
    const box = $("#toasts");
    if (!box) return;
    const t = document.createElement("div");
    t.className = "toast" + (opts.ok ? " toast--ok" : "");
    t.setAttribute("role", "status");
    t.innerHTML = (opts.img ? `<img src="${opts.img}" alt="">` : icon(opts.icon || (opts.ok ? "circle-check-big" : "info"))) +
      `<span></span>` + (opts.action ? `<button type="button">${opts.action}</button>` : "");
    t.querySelector("span").textContent = text;
    if (opts.action && opts.onAction) t.querySelector("button").addEventListener("click", () => { opts.onAction(); t.remove(); });
    box.appendChild(t);
    while (box.children.length > 3) box.firstElementChild.remove();
    setTimeout(() => t.remove(), opts.ms || 4200);
  }
  window.vsToast = toast;
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-toast]");
    if (b) toast(b.dataset.toast, { ok: true });
  });

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
  paintThemeButtons();
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-theme-toggle]");
    if (!b) return;
    const next = isDark() ? "light" : "dark";
    root.dataset.theme = next;
    store.set("vs-theme", next);
    paintThemeButtons();
    // REAL APP: also POST /settings/theme so the choice follows you to other devices.
  });
  $$("input[name=theme]").forEach((r) => r.addEventListener("change", () => {
    if (r.value === "system") { delete root.dataset.theme; store.set("vs-theme", ""); }
    else { root.dataset.theme = r.value; store.set("vs-theme", r.value); }
    paintThemeButtons();
    toast("Theme saved", { ok: true });
  }));

  /* ── Dialogs ──────────────────────────────────────── */
  function openDialog(id, from) {
    const d = document.getElementById(id);
    if (!d || !d.showModal) return;
    d._from = from || document.activeElement;
    d.showModal();
  }
  window.vsOpen = openDialog;
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

  /* Delete confirmations: data-confirm="dialog-id" data-name="..." */
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-confirm]");
    if (!b) return;
    e.preventDefault();
    const d = document.getElementById(b.dataset.confirm);
    if (!d) return;
    $$("[data-fill=name]", d).forEach((n) => { n.textContent = b.dataset.name || ""; });
    openDialog(b.dataset.confirm, b);
  });

  /* ── Tabs ─────────────────────────────────────────── */
  $$("[role=tablist]").forEach((list) => {
    const tabs = $$("[role=tab]", list);
    const select = (t) => {
      tabs.forEach((x) => {
        const on = x === t;
        x.setAttribute("aria-selected", on);
        x.tabIndex = on ? 0 : -1;
        const p = document.getElementById(x.getAttribute("aria-controls"));
        if (p) p.hidden = !on;
      });
    };
    tabs.forEach((t, i) => {
      t.addEventListener("click", () => select(t));
      t.addEventListener("keydown", (e) => {
        const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
        if (!d) return;
        const n = tabs[(i + d + tabs.length) % tabs.length];
        n.focus(); select(n);
      });
    });
    // Deep link: page.html#tab-rejected opens that tab.
    const want = location.hash && tabs.find((t) => "#" + t.id === location.hash);
    if (want) select(want);
  });

  /* ── Radios that reveal a panel ───────────────────── */
  $$("input[data-reveal]").forEach((r) => {
    const sync = () => {
      $$(`input[name="${r.name}"][data-reveal]`).forEach((x) => {
        const p = document.getElementById(x.dataset.reveal);
        if (p) p.hidden = !x.checked;
      });
    };
    r.addEventListener("change", sync);
    if (r.checked) sync();
  });

  /* ── Money fields accept 12,50 and 12.50 ──────────── */
  $$("[data-money]").forEach((inp) => {
    const help = inp.closest(".field").querySelector("[data-money-help]");
    const base = help ? help.textContent : "";
    const check = () => {
      const raw = inp.value.trim().replace(/[€£\s]/g, "");
      if (!raw) { inp.removeAttribute("aria-invalid"); if (help) { help.className = "help"; help.textContent = base; } return; }
      const norm = raw.replace(/\.(?=\d{3}(\D|$))/g, "").replace(",", ".");
      const n = Number(norm);
      if (!Number.isFinite(n) || n <= 0) {
        inp.setAttribute("aria-invalid", "true");
        if (help) { help.className = "help help--error"; help.innerHTML = icon("circle-alert") + "<span>Type a price like 35 or 12,50.</span>"; }
      } else {
        inp.removeAttribute("aria-invalid");
        if (help) { help.className = raw.includes(",") ? "help help--ok" : "help"; help.innerHTML = raw.includes(",") ? icon("circle-check-big") + `<span>Read as €${n.toFixed(2)}, including fees.</span>` : base; }
      }
    };
    inp.addEventListener("input", check);
    check();
  });

  /* ── Token inputs (brands, words) with autocomplete ── */
  const BRANDS = ["Levi's", "Lee", "Lacoste", "Lululemon", "Le Temps des Cerises", "Wrangler", "Carhartt", "Diesel", "Mango", "Zara", "Arket", "COS", "Uniqlo", "Petit Bateau", "& Other Stories", "Patagonia", "The North Face", "Ralph Lauren"];
  $$("[data-tokens]").forEach((box) => {
    const input = $("input", box);
    const combo = box.closest("[data-combo]");
    const list = combo ? $(".combo__list", combo) : null;
    let active = -1;
    const add = (txt) => {
      txt = txt.trim();
      if (!txt) return;
      const t = document.createElement("span");
      t.className = "token" + (box.dataset.tokens === "no" ? " token--no" : "");
      t.innerHTML = `<span></span><button type="button">${icon("x")}</button>`;
      t.firstChild.textContent = txt;
      t.lastChild.setAttribute("aria-label", "Remove " + txt);
      box.insertBefore(t, input);
      input.value = "";
      close();
    };
    const close = () => { if (list) { list.hidden = true; input.setAttribute("aria-expanded", "false"); } active = -1; };
    const render = () => {
      if (!list) return;
      const q = input.value.trim().toLowerCase();
      if (!q) return close();
      const hits = BRANDS.filter((b) => b.toLowerCase().includes(q)).slice(0, 6);
      list.innerHTML = hits.map((b, i) => {
        const at = b.toLowerCase().indexOf(q);
        const label = b.slice(0, at) + "<mark>" + b.slice(at, at + q.length) + "</mark>" + b.slice(at + q.length);
        return `<li role="option" id="opt-${i}" data-v="${b.replace(/"/g, "&quot;")}" aria-selected="false">${label}<small>${(i + 1) * 1371 % 9000 + 400} listings</small></li>`;
      }).join("") || `<li aria-disabled="true">No brand called "${q.replace(/</g, "")}". Press Enter to add it as a word instead.</li>`;
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
    };
    box.addEventListener("click", (e) => {
      const x = e.target.closest(".token button");
      if (x) { x.parentElement.remove(); input.focus(); return; }
      if (e.target === box) input.focus();
    });
    input.addEventListener("input", render);
    input.addEventListener("keydown", (e) => {
      const opts = list ? $$("li[data-v]", list) : [];
      if (e.key === "ArrowDown" && opts.length) { e.preventDefault(); active = (active + 1) % opts.length; }
      else if (e.key === "ArrowUp" && opts.length) { e.preventDefault(); active = (active - 1 + opts.length) % opts.length; }
      else if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(active >= 0 && opts[active] ? opts[active].dataset.v : input.value); return; }
      else if (e.key === "Escape") { close(); return; }
      else if (e.key === "Backspace" && !input.value) { const last = input.previousElementSibling; if (last && last.classList.contains("token")) last.remove(); return; }
      else return;
      opts.forEach((o, i) => o.setAttribute("aria-selected", i === active));
      if (opts[active]) input.setAttribute("aria-activedescendant", opts[active].id);
    });
    if (list) list.addEventListener("mousedown", (e) => { const li = e.target.closest("li[data-v]"); if (li) { e.preventDefault(); add(li.dataset.v); } });
    input.addEventListener("blur", () => setTimeout(close, 120));
  });

  /* ── Feed: filters, layout, save, menu, quick view ─── */
  const feed = $("#feed");
  $$("[data-view]").forEach((b) => b.addEventListener("click", () => {
    $$("[data-view]").forEach((x) => x.setAttribute("aria-pressed", x === b));
    if (feed) feed.classList.toggle("is-list", b.dataset.view === "list");
    store.set("vs-view", b.dataset.view);
  }));
  if (feed && store.get("vs-view") === "list") { const lb = $("[data-view=list]"); if (lb) lb.click(); }

  $$("[data-filter]").forEach((chip) => chip.addEventListener("click", () => {
    const group = $$("[data-filter]");
    const f = chip.dataset.filter;
    if (f === "all") group.forEach((c) => c.setAttribute("aria-pressed", c === chip));
    else {
      chip.setAttribute("aria-pressed", chip.getAttribute("aria-pressed") !== "true");
      const any = group.some((c) => c.dataset.filter !== "all" && c.getAttribute("aria-pressed") === "true");
      group.find((c) => c.dataset.filter === "all").setAttribute("aria-pressed", !any);
    }
    applyFilters();
  }));
  function applyFilters() {
    if (!feed) return;
    const on = (f) => { const c = $(`[data-filter=${f}]`); return c && c.getAttribute("aria-pressed") === "true"; };
    let n = 0;
    $$(".item", feed).forEach((it) => {
      const saved = $(".item__save", it).getAttribute("aria-pressed") === "true";
      const show = (!on("deal") || it.dataset.deal === "1") && (!on("saved") || saved);
      it.hidden = !show;
      if (show) n++;
    });
    const c = $("[data-count]"); if (c) c.textContent = n;
  }

  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-toggle-save]");
    if (!b) return;
    const on = b.getAttribute("aria-pressed") !== "true";
    const card = b.closest(".item");
    (card ? $$("[data-toggle-save]", card) : [b]).forEach((x) => x.setAttribute("aria-pressed", on));
    toast(on ? "Saved. Find it under Saved." : "Removed from saved", { ok: on, icon: on ? "heart" : "info" });
    // REAL APP: POST /items/{id}/mark {mark: "saved"} or DELETE.
  });

  const menu = $("#item-menu");
  let menuFor = null;
  function closeMenu() { if (!menu || menu.hidden) return; menu.hidden = true; if (menuFor) { menuFor.setAttribute("aria-expanded", "false"); menuFor.focus(); } menuFor = null; }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-menu]");
    if (b && menu) {
      e.preventDefault();
      if (menuFor === b) return closeMenu();
      closeMenu();
      menuFor = b;
      b.setAttribute("aria-expanded", "true");
      menu.hidden = false;
      const r = b.getBoundingClientRect();
      const w = menu.offsetWidth;
      menu.style.top = (window.scrollY + r.bottom + 6) + "px";
      menu.style.left = Math.max(8, Math.min(window.scrollX + r.right - w, document.documentElement.clientWidth - w - 8)) + "px";
      const link = $("[data-act=open]", menu); const card = b.closest(".item");
      if (link && card) link.href = $(".item__open", card).href;
      const first = $("button, a", menu); if (first) first.focus();
      return;
    }
    if (menu && !menu.hidden && !e.target.closest("#item-menu")) closeMenu();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });
  document.addEventListener("click", (e) => {
    const a = e.target.closest("[data-act]");
    if (!a) return;
    const act = a.dataset.act;
    const card = menuFor ? menuFor.closest(".item") : null;
    if (act === "open") return;
    e.preventDefault();
    if (act === "watch") toast("Watching for price drops. See Watchlist.", { ok: true, icon: "eye" });
    if (act === "copy") { const u = card ? $(".item__open", card).href : location.href; if (navigator.clipboard) navigator.clipboard.writeText(u).catch(() => {}); toast("Link copied", { ok: true, icon: "link" }); }
    if (act === "hide") { if (card) card.hidden = true; toast("Hidden from your finds", { action: "Undo", onAction: () => { if (card) card.hidden = false; } }); }
    if (act === "block") { const qv = $("#quickview"); if (qv && qv.open) qv.close(); closeMenu(); openDialog("block-confirm"); return; }
    closeMenu();
  });

  const qv = $("#quickview");
  document.addEventListener("click", (e) => {
    const a = e.target.closest("[data-quickview]");
    if (!a || !qv || e.metaKey || e.ctrlKey) return;
    e.preventDefault();
    const card = a.closest(".item");
    const img = $(".item__media img", card);
    const set = (k, v) => { const n = $(`[data-qv=${k}]`, qv); if (n) n.innerHTML = v; };
    $("[data-qv=img]", qv).src = img ? img.src : "";
    set("title", $(".item__title", card).textContent);
    set("search", $(".schip", card).outerHTML);
    set("price", "Item price " + $(".item__base > span", card).textContent);
    set("total", $(".item__total", card).innerHTML);
    const deal = $(".badge--deal", card);
    set("deal", deal ? `<span class="badge badge--deal">${deal.innerHTML}</span>` : "");
    const meta = $(".item__meta", card);
    const seller = $(".item__seller", card);
    set("dl", (meta ? `<dt>Size and condition</dt><dd>${meta.textContent}</dd>` : "") +
      `<dt>Found</dt><dd>${$(".item__foot time", card).textContent}</dd>` +
      (seller ? `<dt>Seller rating</dt><dd>${seller.textContent.trim()}</dd>` : `<dt>Seller rating</dt><dd class="t-muted">Vinted didn't share it for this listing</dd>`));
    $("[data-qv=url]", qv).href = a.href;
    const sv = $(".item__save", card);
    const qsv = $("[data-toggle-save]", qv);
    qsv.setAttribute("aria-pressed", sv.getAttribute("aria-pressed"));
    openDialog("quickview", a);
  });

  /* ── Sound ────────────────────────────────────────── */
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
    } catch (e) { /* no audio */ }
  }
  function paintSound() {
    $$("[data-sound]").forEach((b) => {
      b.setAttribute("aria-pressed", soundOn);
      b.setAttribute("aria-label", soundOn ? "Sound on for new finds. Turn off" : "Sound off. Turn on for new finds");
      const u = b.querySelector("use"); if (u) u.setAttribute("href", soundOn ? "#i-volume-2" : "#i-volume-x");
    });
  }
  paintSound();
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-sound]");
    if (!b) return;
    soundOn = !soundOn; store.set("vs-sound", soundOn ? "1" : "0"); paintSound();
    if (soundOn) chirp();
    toast(soundOn ? "Sound on. You'll hear new finds while this tab is open." : "Sound off", { icon: soundOn ? "volume-2" : "volume-x" });
  });

  /* ── Live feed (demo). REAL APP: new EventSource("/api/events") → "item" events. ── */
  const tpl = $("#arrivals");
  if (feed && tpl && !/still/.test(location.search)) {
    const pool = Array.from(tpl.content.querySelectorAll(".item"));
    let i = 0;
    const tick = () => {
      if (i >= pool.length) return;
      const card = pool[i++].cloneNode(true);
      card.classList.add("is-arriving", "is-fresh");
      $$(".item.is-fresh", feed).forEach((c) => c.classList.remove("is-fresh"));
      const flags = $(".item__flags", card);
      if (flags && !$(".badge--new", flags)) flags.insertAdjacentHTML("afterbegin", '<span class="badge badge--new">New</span>');
      feed.prepend(card);
      applyFilters();
      const title = $(".item__title", card).textContent;
      const total = $(".item__total", card).firstChild.textContent.trim();
      toast(`New find: ${title}, ${total}`, { img: $(".item__media img", card).src, action: "Show", onAction: () => $(".item__open", card).click(), ms: 6000 });
      if (soundOn) chirp();
      $$(".navrow__link .count, .tabbar .dot").forEach((c) => { c.textContent = String(Number(c.textContent) + 1); });
      if (document.hidden) document.title = `(${i}) New finds · vinted-sniper`;
      setTimeout(tick, 14000);
    };
    setTimeout(tick, 7000);
  }

  /* ── The logo ring counts down to the next check ──── */
  const ring = $("[data-tick]");
  if (ring && !reduced) {
    let p = 0.62;
    setInterval(() => { p = p >= 1 ? 0 : p + 1 / 60; ring.style.setProperty("--tick", p.toFixed(3)); }, 1000);
  }
  $$("[data-ago]").forEach((t) => {
    let s = Number(t.dataset.ago);
    setInterval(() => { s = s >= 60 ? 2 : s + 1; t.textContent = s < 60 ? `${s} seconds ago` : "1 minute ago"; }, 1000);
  });

  /* ── Searches list: select, bulk bar, filter ──────── */
  const bulk = $("[data-bulkbar]");
  function syncBulk() {
    const boxes = $$("[data-select-row]");
    const n = boxes.filter((b) => b.checked).length;
    boxes.forEach((b) => b.closest(".srow").classList.toggle("is-selected", b.checked));
    if (bulk) { bulk.hidden = n === 0; const c = $("[data-bulk-count]", bulk); if (c) c.textContent = n === 1 ? "1 search selected" : `${n} searches selected`; }
    const all = $("[data-select-all]");
    if (all) { all.checked = n === boxes.length; all.indeterminate = n > 0 && n < boxes.length; }
  }
  $$("[data-select-row]").forEach((b) => b.addEventListener("change", syncBulk));
  const all = $("[data-select-all]");
  if (all) all.addEventListener("change", () => { $$("[data-select-row]").forEach((b) => { b.checked = all.checked; }); syncBulk(); });
  $$("[data-bulk-clear]").forEach((b) => b.addEventListener("click", () => { $$("[data-select-row]").forEach((x) => { x.checked = false; }); syncBulk(); }));
  const sq = $("#search-filter");
  if (sq) sq.addEventListener("input", () => {
    const q = sq.value.toLowerCase();
    $$(".srow").forEach((r) => { r.hidden = !r.textContent.toLowerCase().includes(q); });
  });
  $$("[data-status-filter]").forEach((chip) => chip.addEventListener("click", () => {
    $$("[data-status-filter]").forEach((c) => c.setAttribute("aria-pressed", c === chip));
    const st = chip.dataset.statusFilter;
    $$(".srow").forEach((r) => { r.hidden = st !== "all" && r.dataset.status !== st; });
  }));
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-pause]");
    if (!b) return;
    const row = b.closest(".srow");
    const paused = b.getAttribute("aria-pressed") === "true";
    b.setAttribute("aria-pressed", !paused);
    b.setAttribute("aria-label", paused ? "Pause" : "Resume");
    const u = b.querySelector("use"); if (u) u.setAttribute("href", paused ? "#i-pause" : "#i-play");
    if (row) {
      const st = $(".srow__state .status", row);
      if (st) { st.className = "status status--" + (paused ? "watching" : "paused"); st.textContent = paused ? "Watching" : "Paused"; }
    }
    toast(paused ? "Watching again. First check in a few seconds." : "Paused. No checks and no alerts until you resume.", { ok: paused, icon: paused ? "play" : "pause" });
  });

  /* ── Test send and Telegram pairing (simulated) ───── */
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-test-send]");
    if (!b || b.dataset.busy) return;
    b.dataset.busy = "1";
    const label = b.innerHTML;
    b.innerHTML = '<span class="spinner" style="width:16px;height:16px;border-width:2px"></span>Sending';
    // REAL APP: POST /destinations/{id}/test → {ok, detail}
    setTimeout(() => {
      b.innerHTML = icon("check") + "Sent";
      toast(b.dataset.testSend || "Test sent. Check that it arrived.", { ok: true, icon: "send" });
      setTimeout(() => { b.innerHTML = label; delete b.dataset.busy; }, 2400);
    }, 1200);
  });
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-pair-start]");
    if (!b) return;
    const wrap = b.closest("[data-pair]");
    $$("[data-pair-step]", wrap).forEach((s) => { s.hidden = s.dataset.pairStep !== "wait"; });
    // REAL APP: POST /destinations/telegram/pair → {code}; then poll GET /destinations/telegram/pair/{code}
    setTimeout(() => {
      $$("[data-pair-step]", wrap).forEach((s) => { s.hidden = s.dataset.pairStep !== "done"; });
      toast("Found your chat. Telegram is connected.", { ok: true, icon: "send" });
    }, reduced ? 1500 : 4200);
  });
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-copy]");
    if (!b) return;
    const v = b.dataset.copy;
    if (navigator.clipboard) navigator.clipboard.writeText(v).catch(() => {});
    toast("Copied", { ok: true, icon: "copy" });
  });

  /* ── Add-destination flow: choose kind → details ──── */
  $$("[data-kind-pick]").forEach((r) => r.addEventListener("change", () => {
    const d = r.closest("dialog") || document;
    $$("[data-kind-panel]", d).forEach((p) => { p.hidden = p.dataset.kindPanel !== r.value; });
    const t = $("[data-kind-title]", d);
    if (t) t.textContent = "Connect " + r.closest(".choice").querySelector(".choice__title").textContent;
  }));
  $$("[data-step-go]").forEach((b) => b.addEventListener("click", () => {
    const d = b.closest("dialog");
    $$("[data-flow-step]", d).forEach((s) => { s.hidden = s.dataset.flowStep !== b.dataset.stepGo; });
    const h = $(`[data-flow-step="${b.dataset.stepGo}"] h2`, d); if (h) { h.tabIndex = -1; h.focus(); }
  }));

  /* ── Validate a Discord channel link inline ───────── */
  $$("[data-discord-url]").forEach((inp) => {
    const msg = inp.closest(".field").querySelector("[data-discord-help]");
    const base = msg ? msg.innerHTML : "";
    inp.addEventListener("input", () => {
      const v = inp.value.trim();
      const ok = /^(https?:\/\/)?(ptb\.|canary\.)?discord(app)?\.com\/api\/webhooks\/\d+\/[\w-]+/.test(v);
      if (!v) { inp.removeAttribute("aria-invalid"); msg.className = "help"; msg.innerHTML = base; return; }
      inp.setAttribute("aria-invalid", ok ? "false" : "true");
      msg.className = ok ? "help help--ok" : "help help--error";
      msg.innerHTML = ok ? icon("circle-check-big") + "<span>That's a Discord channel link.</span>"
        : icon("circle-alert") + "<span>That isn't a Discord channel link. It should start with discord.com/api/webhooks/. Step 3 above shows where to copy it.</span>";
    });
  });

  /* ── Onboarding: focus the question, guard double clicks ── */
  const h = $("[data-autofocus]");
  if (h && !/still/.test(location.search)) h.focus({ preventScroll: true });
  const obf = $("#ob-form");
  if (obf) obf.addEventListener("submit", (e) => {
    if (obf.dataset.sent) { e.preventDefault(); return; }
    obf.dataset.sent = "1";
  });

  /* ── Chart tooltips: any [data-tip] inside a .chart ── */
  $$(".chart").forEach((chart) => {
    const tip = document.createElement("div");
    tip.className = "tip"; tip.hidden = true; tip.setAttribute("role", "status");
    chart.appendChild(tip);
    const show = (el) => {
      const r = el.getBoundingClientRect(); const c = chart.getBoundingClientRect();
      tip.innerHTML = el.dataset.tip; tip.hidden = false;
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

  /* Forms that only confirm in the prototype */
  $$("form[data-submit-toast]").forEach((f) => f.addEventListener("submit", (e) => { e.preventDefault(); toast(f.dataset.submitToast, { ok: true }); }));

  /* "/" focuses the finds search */
  document.addEventListener("keydown", (e) => {
    if (e.key !== "/" || e.target.closest("input, textarea, select, [contenteditable]")) return;
    const q = $("#q"); if (q && q.offsetParent) { e.preventDefault(); q.focus(); }
  });
})();
