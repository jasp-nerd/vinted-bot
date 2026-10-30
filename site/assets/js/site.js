// vinted-bot landing page: the hero demo, tabs, copy buttons and the install tab that
// matches your computer. No dependencies, nothing sent anywhere.
(() => {
  'use strict';

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  // Words for this page's language come from the page itself (see build.py), so the script
  // is the same file in every language. English is the fallback.
  let S = {};
  try { S = JSON.parse(document.getElementById('site-i18n').textContent); } catch { S = {}; }
  const T = {
    copied: S.copied || 'Copied', copyFail: S.copy_fail || 'Select and copy',
    copiedSr: S.copied_sr || 'Copied to the clipboard',
    copyFailSr: S.copy_fail_sr || 'Could not copy. Select the text and copy it yourself.',
    pause: S.pause || 'Pause demo', play: S.play || 'Play demo', match: S.match || 'New match',
    fees: S.fees || 'incl. fees', isNew: S.new || 'New',
    under: (n) => (S.under || '{n}% under typical').replace('{n}', n),
    ages: S.ages || ['just now', '2 min ago', '4 min ago', '6 min ago', '9 min ago', '12 min ago'],
  };
  const ICONS = document.documentElement.dataset.icons || '/assets/icons.svg';

  /* ───────── Language menu: close on outside click or Escape ───────── */
  const langMenu = document.querySelector('[data-lang]');
  if (langMenu) {
    document.addEventListener('click', (e) => { if (langMenu.open && !langMenu.contains(e.target)) langMenu.open = false; });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && langMenu.open) { langMenu.open = false; langMenu.querySelector('summary').focus(); }
    });
  }

  /* ───────── Sticky nav gets a hairline once you scroll ───────── */
  const nav = document.querySelector('[data-nav]');
  if (nav) {
    const onScroll = () => nav.classList.toggle('is-scrolled', window.scrollY > 8);
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  }

  /* ───────── Tabs (WAI-ARIA tabs pattern, automatic activation) ───────── */
  function selectTab(list, tab, focus) {
    const tabs = [...list.querySelectorAll('[role="tab"]')];
    for (const t of tabs) {
      const on = t === tab;
      t.setAttribute('aria-selected', String(on));
      t.tabIndex = on ? 0 : -1;
      const panel = document.getElementById(t.getAttribute('aria-controls'));
      if (panel) panel.hidden = !on;
    }
    if (focus) tab.focus();
  }
  for (const list of document.querySelectorAll('[role="tablist"]')) {
    const tabs = [...list.querySelectorAll('[role="tab"]')];
    list.addEventListener('click', (e) => {
      const tab = e.target.closest('[role="tab"]');
      if (tab) selectTab(list, tab, false);
    });
    list.addEventListener('keydown', (e) => {
      const i = tabs.indexOf(document.activeElement);
      if (i < 0) return;
      let next = null;
      if (e.key === 'ArrowRight') next = tabs[(i + 1) % tabs.length];
      else if (e.key === 'ArrowLeft') next = tabs[(i - 1 + tabs.length) % tabs.length];
      else if (e.key === 'Home') next = tabs[0];
      else if (e.key === 'End') next = tabs[tabs.length - 1];
      if (next) { e.preventDefault(); selectTab(list, next, true); }
    });
  }

  /* ───────── Install tab: open on the visitor's own computer ───────── */
  const osList = document.querySelector('[data-tabs="os"]');
  if (osList) {
    const ua = navigator.userAgent || '';
    const platform = (navigator.userAgentData && navigator.userAgentData.platform) || ua;
    let os = null;
    if (/iPhone|iPad|Android/i.test(ua)) os = null;            // phones: keep Windows, the most common
    else if (/Win/i.test(platform)) os = 'windows';
    else if (/Mac/i.test(platform)) os = 'mac';
    else if (/Linux|X11|CrOS/i.test(platform)) os = 'linux';
    const tab = os && osList.querySelector(`[data-os="${os}"]`);
    if (tab) selectTab(osList, tab, false);
  }

  /* ───────── Copy buttons ───────── */
  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Older browsers, or a page opened from a file: fall back to a hidden textarea.
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.append(ta);
      ta.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch { ok = false; }
      ta.remove();
      return ok;
    }
  }
  const status = document.createElement('p');
  status.className = 'sr-only';
  status.setAttribute('role', 'status');
  document.body.append(status);

  document.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-copy]');
    if (!btn) return;
    const sel = btn.getAttribute('data-copy');
    const source = sel ? document.querySelector(sel) : btn.parentElement.querySelector('pre');
    if (!source) return;
    const ok = await copyText(source.textContent.trim());
    const label = btn.querySelector('span');
    const before = label.textContent;
    btn.classList.toggle('is-done', ok);
    label.textContent = ok ? T.copied : T.copyFail;
    btn.querySelector('use').setAttribute('href', `${ICONS}#${ok ? 'i-check' : 'i-copy'}`);
    status.textContent = ok ? T.copiedSr : T.copyFailSr;
    clearTimeout(btn._t);
    btn._t = setTimeout(() => {
      btn.classList.remove('is-done');
      label.textContent = before;
      btn.querySelector('use').setAttribute('href', `${ICONS}#i-copy`);
    }, 2200);
  });

  /* ───────── Hero demo: listings arrive, a notification drops in ───────── */
  const stage = document.querySelector('[data-stage]');
  if (!stage) return;
  const grid = stage.querySelector('[data-grid]');
  const push = stage.querySelector('[data-push]');
  const ctl = stage.querySelector('[data-stage-ctl]');
  const toggle = stage.querySelector('[data-stage-toggle]');

  // Invented listings, in the order they "arrive". The first six are already on the page.
  const L = S.items || [];
  if (L.length <= 6) return;
  const AGES = T.ages;
  const SHOWN = 6;
  let shown = [0, 1, 2, 3, 4, 5];
  let nextIndex = 6;

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  function card(item) {
    const c = el('div', 'mini');
    const media = el('div', 'mini__media');
    const img = el('img');
    img.src = `/assets/img/demo/${item.img}.webp`;
    img.width = 240; img.height = 360; img.alt = '';
    media.append(img);
    const flags = el('div', 'mini__flags');
    flags.append(el('span', 'badge badge--new', T.isNew));
    if (item.deal) flags.append(el('span', 'badge badge--deal', T.under(item.deal)));
    media.append(flags);
    const body = el('div');
    body.append(el('div', 'mini__title', item.title), el('div', 'mini__meta', item.meta));
    const total = el('div', 'mini__total', `${item.total} `);
    total.append(el('small', null, T.fees));
    const foot = el('div', 'mini__foot');
    const s = el('span');
    const dot = el('i', 'sdot');
    dot.style.setProperty('--sc', `var(--s-${item.s})`);
    s.append(dot, document.createTextNode(item.search));
    foot.append(s, el('time', null, T.ages[0]));
    body.append(total, foot);
    c.append(media, body);
    return c;
  }
  function relabel() {
    grid.querySelectorAll('.mini').forEach((c, i) => {
      const t = c.querySelector('time');
      if (t) t.textContent = AGES[i] || '';
      if (i > 0) {
        c.classList.remove('is-new');
        const b = c.querySelector('.badge--new');
        if (b) b.remove();
      }
    });
  }
  function showPush(item) {
    stage.querySelector('[data-push-title]').textContent = `${T.match} · ${item.search}`;
    stage.querySelector('[data-push-text]').textContent =
      `${item.title} · ${item.total} ${T.fees}` + (item.deal ? ` · ${T.under(item.deal)}` : '');
    stage.querySelector('[data-push-img]').src = `/assets/img/demo/${item.img}.webp`;
    push.classList.remove('is-out');
  }
  function tick() {
    push.classList.add('is-out');
    setTimeout(() => {
      while (shown.includes(nextIndex % L.length)) nextIndex++;
      const idx = nextIndex % L.length;
      nextIndex++;
      const item = L[idx];
      const c = card(item);
      c.classList.add('is-new', 'is-arriving');
      grid.prepend(c);
      shown.unshift(idx);
      while (grid.children.length > SHOWN) grid.lastElementChild.remove();
      shown = shown.slice(0, SHOWN);
      relabel();
      setTimeout(() => showPush(item), 380);
    }, 420);
  }

  // Warm the cache for the photos that arrive later, once the page has settled.
  window.addEventListener('load', () => {
    setTimeout(() => {
      for (const item of L.slice(SHOWN)) { const i = new Image(); i.src = `/assets/img/demo/${item.img}.webp`; }
    }, 1200);
  });

  let timer = null;
  let paused = false;
  let visible = false;
  const PERIOD = 4800;
  const run = () => { if (!timer && !paused && visible && !reduceMotion.matches) timer = setInterval(tick, PERIOD); };
  const stop = () => { clearInterval(timer); timer = null; };

  // Someone who asked for less motion gets the still frame and no button.
  if (!reduceMotion.matches) ctl.hidden = false;
  reduceMotion.addEventListener('change', () => { ctl.hidden = reduceMotion.matches; if (reduceMotion.matches) stop(); else run(); });

  toggle.addEventListener('click', () => {
    paused = !paused;
    toggle.setAttribute('aria-pressed', String(paused));
    toggle.querySelector('span').textContent = paused ? T.play : T.pause;
    toggle.querySelector('use').setAttribute('href', `${ICONS}#${paused ? 'i-play' : 'i-pause'}`);
    if (paused) stop(); else { tick(); run(); }
  });

  // Only animate while the hero is on screen and the tab is visible.
  if ('IntersectionObserver' in window) {
    new IntersectionObserver((entries) => {
      visible = entries[0].isIntersecting;
      if (visible) run(); else stop();
    }, { threshold: 0.25 }).observe(stage);
  } else {
    visible = true;
    run();
  }
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); else run(); });
})();
