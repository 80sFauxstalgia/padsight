// Padsight control panel. Talks only to the local app (same origin) through /api/*, with the per-install key
// that the app passes in the URL fragment. Plain DOM code, no third-party scripts.
'use strict';
(() => {
  // ---------------------------------------------------------------- key, mode
  const hash = new URLSearchParams(location.hash.slice(1));
  const KEY = hash.get('k') || sessionStorage.getItem('padsight.k') || '';
  if (hash.get('k')) sessionStorage.setItem('padsight.k', hash.get('k'));
  const DOCK = hash.get('dock') === '1';
  if (DOCK) document.documentElement.classList.add('dock');

  // ---------------------------------------------------------------- helpers
  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const store = {
    get(k, d) { try { const v = localStorage.getItem('padsight.' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem('padsight.' + k, JSON.stringify(v)); } catch { } },
  };

  async function api(path, body) {
    const opt = { headers: { 'X-Panel-Key': KEY }, cache: 'no-store' };
    if (body !== undefined) {
      opt.method = 'POST';
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    const r = await fetch('/api/' + path, opt);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(j.error || r.statusText); e.status = r.status; throw e; }
    return j;
  }

  let toastTimer;
  function toast(msg) {
    const t = $('#toast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), 2200);
  }

  async function copy(text, what) {
    try { await navigator.clipboard.writeText(text); }
    catch {
      const ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); } catch { }
      ta.remove();
    }
    toast((what || 'Copied') + ' copied to the clipboard');
  }

  // ---------------------------------------------------------------- names
  const CONNECTION = {
    CONNECTION_DONGLE_SC: 'wireless receiver', CONNECTION_WIRE_USB: 'USB cable', CONNECTION_BT: 'Bluetooth',
    CONNECTION_DONGLE_DS4: 'wireless adapter',
  };
  function connectionLabel(c) {
    if (c.connection === 'CONNECTION_DONGLE_SC' && (c.kinds || []).includes('DEVICE_SC2026')) return 'wireless puck';
    return CONNECTION[c.connection] || 'connected';
  }
  const GAUGE_LABEL = { stick_left: 'L STICK', stick_right: 'R STICK', touch_left: 'L PAD', touch_right: 'R PAD', touch_center: 'PAD', triggers: 'TRIGGERS' };
  const gaugeLabel = k => GAUGE_LABEL[k] || k.replace(/_/g, ' ').toUpperCase();
  const QUAD_FACE = { n: 'Y', e: 'B', s: 'A', w: 'X' };
  const QUAD_DPAD = { n: 'D-PAD UP', e: 'D-PAD RIGHT', s: 'D-PAD DOWN', w: 'D-PAD LEFT' };
  function chipLabel(p, sc2026) {
    let m;
    if ((m = /^quad_right:([nesw])$/.exec(p))) return QUAD_FACE[m[1]];
    if ((m = /^quad_left:([nesw])$/.exec(p))) return QUAD_DPAD[m[1]];
    if ((m = /^bumpers:([lr])$/.exec(p))) return m[1].toUpperCase() + 'B';
    if ((m = /^grip:([lr])$/.exec(p))) return sc2026 ? m[1].toUpperCase() + '4' : m[1].toUpperCase() + ' GRIP';
    if ((m = /^grip2:([lr])$/.exec(p))) return m[1].toUpperCase() + '5';
    if ((m = /^grip_sense:([lr])$/.exec(p))) return 'GRIP SENSE ' + m[1].toUpperCase();
    if ((m = /^stick_touch:([lr])$/.exec(p))) return m[1].toUpperCase() + ' STICK TOUCH';
    if ((m = /^(touch_left|touch_right|touch_center):click$/.exec(p))) return gaugeLabel(m[1]) + ' CLICK';
    if ((m = /^(\w+)=(\w+)$/.exec(p))) return (m[1] === 'dpad' ? 'D-PAD ' : m[1].toUpperCase() + ' ') + m[2].toUpperCase();
    const named = { home: 'STEAM', menu: 'MENU', select: 'VIEW', start: 'MENU', qam: 'QAM', back: 'BACK' };
    if (named[p]) return named[p];
    return p.replace(/[_:]/g, ' ').toUpperCase();
  }

  // ---------------------------------------------------------------- state
  let state = null;
  let themes = null;
  let route = store.get('route', 'home');
  let setupStep = 0;            // 1..3 while the first-run setup is open
  let lastSig = {};
  const opts = Object.assign({ theme: '', idle: 0, opacity: 100, fps: 0, align: '', crop: false, cx: 0, cy: 0, cw: 0, ch: 0 }, store.get('obs', {}));

  const main = $('#main');
  const origin = location.origin;
  const overlayBase = origin + '/';
  const dockUrl = () => `${origin}/panel/#k=${encodeURIComponent(KEY)}&dock=1`;

  // Which controllers to show: hide Steam's virtual Xbox pads when a real controller with its own driver is present.
  function visibleControllers() {
    const all = (state?.controllers || []).filter(c => c.present);
    const dedicated = all.filter(c => !c.xinput);
    return dedicated.length ? dedicated : all;
  }
  function hiddenVirtualPads() {
    const all = (state?.controllers || []).filter(c => c.present);
    return all.some(c => !c.xinput) ? all.filter(c => c.xinput).length : 0;
  }
  // A receiver with no controller awake on it: entries exist but none is present.
  function sleepingReceivers() {
    const out = [];
    const byKind = {};
    for (const c of state?.controllers || []) {
      if (c.xinput) continue;
      const k = c.kindLabel;
      (byKind[k] = byKind[k] || []).push(c);
    }
    for (const [k, list] of Object.entries(byKind)) if (!list.some(c => c.present)) out.push({ kindLabel: k, list });
    return out;
  }
  // Primary kind only: the 2026 controller also lists DEVICE_SC so older themes can bind to it.
  const myKinds = () => new Set(visibleControllers().map(c => (c.kinds || [])[0]).filter(Boolean));

  // ---------------------------------------------------------------- navigation
  function go(r, step) {
    route = r;
    setupStep = r === 'setup' ? (step || 1) : 0;
    if (r !== 'setup') store.set('route', r);
    lastSig = {};
    render();
    main.scrollTop = 0;
    main.focus({ preventScroll: true });
  }

  function render() {
    for (const b of $$('[data-nav]')) b.setAttribute('aria-current', b.dataset.nav === route ? 'page' : 'false');
    const page = route === 'setup' ? setupPage() : (PAGES[route] || PAGES.home)();
    main.innerHTML = `<div class="page">${page}</div>`;
    lastSig = {}; // the DOM was rebuilt, so every dynamic part must be redrawn
    if (route === 'themes' || (route === 'setup' && setupStep === 2)) renderThemeGrid();
    if (route === 'obs' || (route === 'setup' && setupStep === 3)) updateObsOutputs(true);
    update();
  }

  // ---------------------------------------------------------------- pages
  const PAGES = {
    home: () => `
      <div class="head"><div><p class="eyebrow">Live</p><h1>Home</h1></div></div>
      <section class="strip" aria-label="System status">
        <div class="pill"><span class="dot" id="dOverlay"></span><div><div class="k">OVERLAY</div><div class="v" id="vOverlay">…</div></div></div>
        <div class="pill"><span class="dot" id="dCtrl"></span><div><div class="k">CONTROLLER</div><div class="v" id="vCtrl">…</div></div></div>
        <div class="pill"><span class="dot" id="dFollow"></span><div><div class="k">FOLLOW MODE</div><div class="v" id="vFollow">…</div></div></div>
      </section>
      <div class="grid cols-2">
        <section class="grid" aria-label="Controllers" style="align-content:start">
          <h2 class="label">Controllers</h2>
          <div class="grid" id="ctrls"></div>
        </section>
        <section class="grid" aria-label="Overlay" style="align-content:start">
          <h2 class="label">Overlay · what OBS sees</h2>
          <div class="stage tall"><iframe title="Overlay preview" src="/?preview=1"></iframe><span class="tag badge" id="stageBadge">TRANSPARENT</span></div>
          <div class="card"><div class="row spread"><div><h3 id="themeName">No theme yet</h3><p class="small" id="themeMeta">Pick a look in Themes.</p></div>
            <button class="btn" type="button" data-act="nav" data-to="themes">Change theme</button></div></div>
          <div class="row">
            <button class="btn primary big" type="button" data-act="copy-obs">${ICON_COPY} Copy OBS URL</button>
            <button class="btn big" type="button" data-act="nav" data-to="obs">Set it up in OBS</button>
          </div>
          <p class="small mono" id="urlNote"></p>
        </section>
      </div>`,

    themes: () => themesPage(false),
    obs: () => obsPage(false),

    help: () => `
      <div class="head"><div><p class="eyebrow">Every state says what to do next</p><h1>Help &amp; status</h1></div>
        <div class="row"><button class="btn" type="button" data-act="setup">Run setup again</button>
        <button class="btn" type="button" data-act="diag">Copy diagnostics for a bug report</button></div></div>
      <h2 class="label">Controller</h2><div class="grid auto-fill" id="helpCtrl"></div>
      <h2 class="label">Overlay and OBS</h2><div class="grid auto-fill" id="helpOverlay"></div>
      <h2 class="label">Questions</h2>
      <div class="grid auto-fill">
        <div class="card"><h3>Does this change how games see my controller?</h3><p class="sub">Padsight only reads input. It doesn’t remap or block buttons, and Steam can keep running.</p></div>
        <div class="card"><h3>Why is there no green screen?</h3><p class="sub">OBS Browser Sources support real transparency, so the overlay sits on your scene as it is. No chroma key needed.</p></div>
        <div class="card"><h3>Does anything leave this PC?</h3><p class="sub">No. The server listens on 127.0.0.1 only, and the panel's controls need a key that only this app knows.</p></div>
      </div>
      <section class="diag" id="diag" aria-label="Diagnostics"></section>`,

    settings: () => {
      const s = state?.settings || {};
      const accents = [['#3ad6ff', 'Cyan'], ['#ff71ce', 'Pink'], ['#05ffa1', 'Mint'], ['#b967ff', 'Lavender'], ['#fffb96', 'Yellow'], ['#01cdfe', 'Blue']];
      const cur = (s.accent || '#3ad6ff').toLowerCase();
      const fpsList = [30, 48, 60, 90, 120];
      return `
      <div class="head"><div><p class="eyebrow">Preferences</p><h1>Settings</h1></div></div>
      <div class="grid cols-2">
        <section class="card" aria-label="Controllers">
          <h2 class="label">Controllers</h2>
          <div>
            ${toggle('followMode', s.followMode, 'Follow the controller in use', 'Switch the overlay to whichever controller you pick up. The current one has to be idle for 2 seconds first.')}
            ${toggle('rememberThemePerController', s.rememberThemePerController, 'Remember a theme per controller', 'Each kind of controller keeps its own look.')}
            ${toggle('autoSelect', s.autoSelect, 'Pick the only controller automatically', 'When exactly one controller is connected, show it without asking.')}
          </div>
        </section>
        <section class="card" aria-label="App">
          <h2 class="label">App</h2>
          <div>
            ${toggle('openPanelOnStart', s.openPanelOnStart, 'Open this panel when Padsight starts', 'Otherwise it starts in the tray. Click the tray icon to open the panel.')}
            ${toggle('previewWindow', s.previewWindow, 'Desktop preview window', 'The classic borderless window that draws the controller on your desktop. OBS doesn’t need it.')}
          </div>
        </section>
        <section class="card" aria-label="Overlay">
          <h2 class="label">Overlay</h2>
          <label class="field">Default frame rate
            <select data-set="overlayFps">${fpsList.map(f => `<option value="${f}" ${f === s.overlayFps ? 'selected' : ''}>${f} fps</option>`).join('')}</select></label>
          <p class="small">Each OBS source can still pick its own rate on the OBS page. The server is on port ${esc(s.overlayPort)}${state?.instance ? ` + ${state.instance} for this instance` : ''}, local only.</p>
          <div class="row"><button class="btn" type="button" data-act="open" data-what="advanced-settings">Port and background colour…</button></div>
        </section>
        <section class="card" aria-label="Look">
          <h2 class="label">Accent colour</h2>
          <div class="swatches">${accents.map(([c, n]) => `<button type="button" class="swatch" style="background:${c}" title="${n}" aria-label="${n}" aria-pressed="${c === cur}" data-act="accent" data-color="${c}"></button>`).join('')}</div>
          <p class="small">Only changes this panel. Pink, mint, lavender and yellow match the Vaporwave Pixel themes.</p>
          <div class="row"><button class="btn" type="button" data-act="open" data-what="about">About and licenses</button></div>
        </section>
      </div>`;
    },
  };

  const ICON_COPY = '<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><rect x="5" y="5" width="8" height="9" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M3 11V3.5A1.5 1.5 0 0 1 4.5 2H10" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>';

  function toggle(key, on, title, text) {
    return `<label class="toggle"><input type="checkbox" data-set="${key}" ${on ? 'checked' : ''}><span><b>${esc(title)}</b><br>${esc(text)}</span></label>`;
  }

  function stepHeader(n, title, lead) {
    return `<div class="steps" aria-hidden="true">${[1, 2, 3].map(i => `<span class="${i <= n ? 'done' : ''}"></span>`).join('')}</div>
      <div class="head"><div><p class="eyebrow">Step ${n} of 3</p><h1>${title}</h1></div></div>${lead ? `<p class="sub" style="max-width:720px">${lead}</p>` : ''}`;
  }

  function setupPage() {
    if (setupStep === 1) return `
      ${stepHeader(1, 'Pick up a controller and press any button.', 'Padsight finds Steam Controllers on its own. Steam can keep running; Padsight only reads input and doesn’t remap anything.')}
      <div class="grid cols-2">
        <section class="grid" style="align-content:start" aria-label="Controllers"><div class="grid" id="ctrls"></div>
          <p class="small">Using something else? DualShock, DualSense and Xbox-style pads work too. <button class="link" type="button" data-act="nav" data-to="help">Not seeing your controller?</button></p></section>
        <section class="grid" style="align-content:start" aria-label="Live preview"><div class="stage tall"><iframe title="Overlay preview" src="/?preview=1"></iframe><span class="tag ok badge">LIVE INPUT</span></div>
          <p class="small">This is exactly what OBS will show. Try the trackpads, the back buttons, and resting your thumbs on the sticks.</p></section>
      </div>
      <div class="footer-actions"><button class="btn" type="button" data-act="finish-setup">Skip setup</button>
        <button class="btn primary big" type="button" data-act="step" data-step="2">Next: choose a look</button></div>`;
    if (setupStep === 2) return themesPage(true) + `
      <div class="footer-actions"><button class="btn" type="button" data-act="step" data-step="1">Back</button>
        <button class="btn primary big" type="button" data-act="step" data-step="3">Next: add it to OBS</button></div>`;
    return obsPage(true) + `
      <div class="footer-actions"><button class="btn" type="button" data-act="step" data-step="2">Back</button>
        <button class="btn primary big" type="button" data-act="finish-setup">Finish</button></div>`;
  }

  // ---------------------------------------------------------------- themes
  let themeFilter = store.get('themeFilter', 'mine');
  let themeSearch = '';

  function themesPage(inSetup) {
    return `${inSetup ? stepHeader(2, 'Choose a look') : '<div class="head"><div><p class="eyebrow">Gallery</p><h1>Themes</h1></div></div>'}
      <div class="row spread">
        <div class="filters" role="group" aria-label="Filter by controller" id="filters"></div>
        <label class="field" style="min-width:240px"><span class="small">Search</span><input type="search" id="themeSearch" placeholder="Name, controller or author" value="${esc(themeSearch)}"></label>
      </div>
      <div class="themes" id="themeGrid"><div class="empty">Loading themes…</div></div>
      <div class="card"><h3>Make your own</h3>
        <p class="sub">A theme is a folder of PNGs plus one JSON file. Copy one in the themes folder, change it, and it shows up here with a live preview.</p>
        <div class="row"><button class="btn" type="button" data-act="open" data-what="themes-folder">Open themes folder</button>
        <button class="btn" type="button" data-act="open" data-what="theme-docs">Theme guide</button>
        <button class="btn" type="button" data-act="reload-themes">Reload list</button></div></div>
      <p class="small">Picking a theme while a controller is on the overlay remembers it for that kind of controller.</p>`;
  }

  async function loadThemes(force) {
    if (themes && !force) return themes;
    themes = (await api('themes')).themes || [];
    return themes;
  }

  function themeTitle(t) { return t ? `${t.theme} · ${t.variant}` : ''; }

  async function renderThemeGrid() {
    const grid = $('#themeGrid');
    if (!grid) return;
    try { await loadThemes(); } catch (e) { grid.innerHTML = `<div class="empty">Couldn't load themes: ${esc(e.message)}</div>`; return; }
    if (!$('#themeGrid')) return;
    const kinds = myKinds();
    const families = [...new Set(themes.map(t => t.family))].sort();
    if (!(themeFilter === 'mine' || themeFilter === 'all' || families.includes(themeFilter.slice(2)))) themeFilter = 'mine';
    const chips = [['mine', 'For my controllers'], ['all', `All ${themes.length}`]];
    const other = themeFilter.startsWith('f:') ? themeFilter : '';
    $('#filters').innerHTML = chips.map(([k, n]) => `<button type="button" aria-pressed="${k === themeFilter}" data-act="filter" data-f="${esc(k)}">${esc(n)}</button>`).join('') +
      `<select class="chip-select" aria-label="Controller type" data-act-change="family"><option value="">Controller type…</option>${families.map(f => `<option value="f:${esc(f)}" ${'f:' + f === other ? 'selected' : ''}>${esc(f)}</option>`).join('')}</select>`;
    const q = themeSearch.trim().toLowerCase();
    let list = themes.filter(t => themeFilter === 'all' ? true : themeFilter === 'mine' ? kinds.has(t.kind) : t.family === themeFilter.slice(2));
    if (themeFilter === 'mine' && !list.length) list = themes;
    if (q) list = list.filter(t => `${t.family} ${t.theme} ${t.variant} ${t.author || ''}`.toLowerCase().includes(q));
    const cur = state?.theme?.key;
    grid.innerHTML = list.length ? list.map(t => `
      <article class="card theme ${t.key === cur ? 'current' : ''}" data-key="${esc(t.key)}">
        <div class="stage thumb"><img loading="lazy" alt="${esc(themeTitle(t))} preview" src="/preview?theme=${encodeURIComponent(t.key)}"><span class="tag ok" ${t.key === cur ? '' : 'hidden'}>IN USE</span></div>
        <div class="body">
          <h3>${esc(t.theme)}</h3>
          <p class="small">${esc(t.family)} · ${esc(t.variant)}${t.width ? ` · ${t.width}×${t.height}` : ''}${t.author ? ` · by ${esc(t.author)}` : ''}</p>
          <div class="actions"><button class="btn small ${t.key === cur ? '' : 'primary'}" type="button" data-act="use-theme" data-key="${esc(t.key)}">${t.key === cur ? 'In use' : 'Use'}</button>
          <button class="btn small" type="button" data-act="copy-pinned" data-key="${esc(t.key)}" aria-label="Copy an OBS URL pinned to ${esc(themeTitle(t))}">Copy URL</button></div>
        </div>
      </article>`).join('') : `<div class="empty">No themes match. ${themeFilter !== 'all' ? '<button class="link" type="button" data-act="filter" data-f="all">Show all themes</button>' : ''}</div>`;
  }

  function markCurrentTheme() {
    const cur = state?.theme?.key;
    for (const card of $$('#themeGrid .theme')) {
      const on = card.dataset.key === cur;
      card.classList.toggle('current', on);
      $('.tag', card).hidden = !on;
      const b = $('[data-act="use-theme"]', card);
      b.textContent = on ? 'In use' : 'Use';
      b.classList.toggle('primary', !on);
    }
  }

  // ---------------------------------------------------------------- OBS
  function obsPage(inSetup) {
    const themeOptions = (themes || []).map(t => `<option value="${esc(t.key)}" ${t.key === opts.theme ? 'selected' : ''}>${esc(t.family)} · ${esc(themeTitle(t))}</option>`).join('');
    const sel = (key, list) => `<select data-opt="${key}">${list.map(([v, n]) => `<option value="${v}" ${String(opts[key]) === String(v) ? 'selected' : ''}>${n}</option>`).join('')}</select>`;
    return `${inSetup ? stepHeader(3, 'Add it to OBS') : '<div class="head"><div><p class="eyebrow">Streaming</p><h1>OBS</h1></div></div>'}
      <div class="grid cols-2">
        <section class="card hud" aria-label="Add by hand">
          <h2 class="label">Add it to OBS</h2>
          <ol class="steps-list">
            <li>In OBS, under <b>Sources</b>, click <b>+</b> › <b>Browser</b> › <b>Create new</b>.</li>
            <li>Paste the URL and size below. Leave Custom CSS as it is.</li>
            <li>Tick <b>Shutdown source when not visible</b>, click OK, then move and scale it.</li>
          </ol>
          <div class="copy"><code id="obsUrl"></code><button class="btn" type="button" data-act="copy-built">Copy</button></div>
          <div class="row"><span class="tag" id="obsW"></span><span class="tag" id="obsH"></span><span class="small" id="obsSizeNote"></span></div>
          <p class="small">The URL only works on this PC. Each OBS source can use different options.</p>
        </section>
        <section class="grid" style="align-content:start" aria-label="Preview">
          <div class="stage tall" id="obsStage"><iframe title="Preview with these options" id="obsFrame"></iframe><span class="tag badge">PREVIEW</span></div>
        </section>
      </div>
      <section class="card" aria-label="Overlay options">
        <div class="row spread"><h2 class="label">Overlay options</h2><span class="small">Saved into the URL, so each OBS source can differ.</span></div>
        <div class="form">
          <label class="field">Theme<select data-opt="theme"><option value="">Follow the app (per controller)</option>${themeOptions}</select></label>
          <label class="field">Fade out when idle${sel('idle', [[0, 'Never'], [3, 'After 3 seconds'], [5, 'After 5 seconds'], [8, 'After 8 seconds'], [15, 'After 15 seconds'], [30, 'After 30 seconds']])}</label>
          <label class="field">Opacity <span class="mono" id="opVal">${opts.opacity}%</span><input type="range" min="20" max="100" step="5" value="${opts.opacity}" data-opt="opacity"></label>
          <label class="field">Frame rate${sel('fps', [[0, 'App default'], [30, '30 fps'], [60, '60 fps'], [90, '90 fps'], [120, '120 fps']])}</label>
          <label class="field">Anchor inside the source${sel('align', [['', 'Centre'], ['bottom', 'Bottom'], ['top', 'Top'], ['left', 'Left'], ['right', 'Right']])}</label>
          <label class="field">Show${sel('crop', [[false, 'Whole controller'], [true, 'Only part of it (crop)']])}</label>
        </div>
        <div class="form" id="cropFields" ${opts.crop ? '' : 'hidden'}>
          ${['cx', 'cy', 'cw', 'ch'].map((k, i) => `<label class="field">${['Left', 'Top', 'Width', 'Height'][i]} (theme pixels)<input type="number" min="0" step="1" value="${opts[k]}" data-opt="${k}"></label>`).join('')}
        </div>
      </section>
      <section class="card" aria-label="OBS dock">
        <h2 class="label">Control it from inside OBS</h2>
        <p class="sub">This panel also works as an OBS dock. In OBS, open <b>Docks › Custom Browser Docks</b>, name it Padsight and paste the dock URL. Then you can switch themes or controllers mid-stream without leaving OBS.</p>
        <div class="copy"><code>${esc(origin)}/panel/#k=••••••&amp;dock=1</code><button class="btn" type="button" data-act="copy-dock">Copy dock URL</button></div>
        <p class="small">The dock URL contains this PC's panel key. Paste it only into OBS, and don't show it on stream.</p>
      </section>`;
  }

  function currentThemeInfo() {
    const key = opts.theme || state?.theme?.key;
    return (themes || []).find(t => t.key === key) || state?.theme || null;
  }

  function builtUrl(forPreview) {
    const p = new URLSearchParams();
    if (opts.theme) p.set('theme', opts.theme);
    if (+opts.fps) p.set('fps', String(opts.fps));
    if (+opts.idle && !forPreview) p.set('idle', String(opts.idle));
    if (+opts.opacity < 100) p.set('opacity', String(opts.opacity / 100));
    if (opts.align) p.set('align', opts.align);
    if (opts.crop && opts.cw > 0 && opts.ch > 0) p.set('crop', [opts.cx, opts.cy, opts.cw, opts.ch].map(n => Math.round(+n || 0)).join(','));
    if (forPreview) p.set('preview', '1');
    const qs = p.toString().replace(/%2F/g, '/').replace(/%2C/g, ',');
    return overlayBase + (qs ? '?' + qs : '');
  }

  let frameTimer;
  function updateObsOutputs(reloadFrame) {
    const urlEl = $('#obsUrl');
    if (!urlEl) return;
    urlEl.textContent = builtUrl(false);
    const t = currentThemeInfo();
    const w = opts.crop && opts.cw > 0 ? Math.round(opts.cw) : t?.width;
    const h = opts.crop && opts.ch > 0 ? Math.round(opts.ch) : t?.height;
    $('#obsW').textContent = 'WIDTH ' + (w || '?');
    $('#obsH').textContent = 'HEIGHT ' + (h || '?');
    $('#obsSizeNote').textContent = opts.theme ? '' : 'Size of the theme in use now.';
    if (reloadFrame) {
      clearTimeout(frameTimer);
      frameTimer = setTimeout(() => { const f = $('#obsFrame'); if (f) f.src = builtUrl(true); }, 250);
    }
  }

  function setOpt(key, raw) {
    let v = raw;
    if (key === 'crop') v = raw === 'true' || raw === true;
    else if (['idle', 'opacity', 'fps', 'cx', 'cy', 'cw', 'ch'].includes(key)) v = Math.max(0, +raw || 0);
    opts[key] = v;
    if (key === 'crop' && v && !(opts.cw > 0)) {
      const t = currentThemeInfo();
      Object.assign(opts, { cx: 0, cy: 0, cw: t?.width || 0, ch: t?.height || 0 });
      for (const k of ['cx', 'cy', 'cw', 'ch']) { const i = $(`[data-opt="${k}"]`); if (i) i.value = opts[k]; }
    }
    store.set('obs', opts);
    if (key === 'opacity') $('#opVal').textContent = v + '%';
    if (key === 'crop') $('#cropFields').hidden = !v;
    updateObsOutputs(true);
  }

  // ---------------------------------------------------------------- controller cards
  function cardStatus(c) {
    if (c.selected) return ['ok', 'ON OVERLAY'];
    if (c.inUse) return ['info', 'IN USE'];
    return ['', 'STANDBY'];
  }

  function gaugeKeys(c) {
    const l = c.live || {};
    const order = k => ({ stick_left: 0, stick_right: 1, touch_left: 2, touch_right: 3 }[k] ?? 9);
    return {
      sticks: Object.keys(l.sticks || {}).sort((a, b) => order(a) - order(b)),
      pads: Object.keys(l.pads || {}).sort((a, b) => order(a) - order(b)),
      triggers: Object.keys(l.triggers || {}),
    };
  }

  function controllerCard(c, compact) {
    const [tone, label] = cardStatus(c);
    const g = gaugeKeys(c);
    const live = c.live ? `
      <div class="live" data-live="${esc(c.id)}">
        ${g.sticks.map(k => `<div class="gauge"><div class="well round" data-g="s:${esc(k)}"><i></i></div><span>${gaugeLabel(k)}</span></div>`).join('')}
        ${g.pads.map(k => `<div class="gauge"><div class="well square" data-g="p:${esc(k)}"><i></i></div><span>${gaugeLabel(k)}</span></div>`).join('')}
        ${g.triggers.map(k => `<div class="gauge"><div class="bars" data-g="t:${esc(k)}"><div class="bar"><i></i></div><div class="bar"><i></i></div></div><span>${gaugeLabel(k)}</span></div>`).join('')}
      </div>
      <div class="chips" data-chips="${esc(c.id)}"></div>` :
      `<p class="small">Not being read. ${c.selected ? '' : 'Press something on it, or put it on the overlay.'}</p>`;
    const actions = compact ? '' : `<div class="row">
        ${c.selected ? '' : `<button class="btn small" type="button" data-act="use-ctrl" data-id="${esc(c.id)}">Put this one on the overlay</button>`}
        <button class="btn small" type="button" data-act="identify" data-id="${esc(c.id)}" title="Makes the controller buzz or flash so you can tell which one it is">Find it</button></div>`;
    return `<article class="card ${c.selected ? 'hud on' : ''}" data-id="${esc(c.id)}">
      <div class="ctrl-head"><div><h3>${esc(c.kindLabel)}</h3><p class="small">${esc(connectionLabel(c))}${c.name && c.name !== c.kindLabel ? ' · ' + esc(c.name) : ''}</p></div>
        <span class="tag ${tone}">${label}</span></div>
      ${live}${actions}</article>`;
  }

  function renderControllers(compact) {
    const box = $('#ctrls');
    if (!box) return;
    const vis = visibleControllers();
    const sleeping = sleepingReceivers();
    const hidden = hiddenVirtualPads();
    const sig = JSON.stringify([vis.map(c => [c.id, c.selected, c.inUse, !!c.live, gaugeKeys(c)]), sleeping.map(s => s.kindLabel), hidden, compact]);
    if (sig !== lastSig.ctrls) {
      lastSig.ctrls = sig;
      let html = vis.map(c => controllerCard(c, compact)).join('');
      html += sleeping.map(s => `<article class="card warn"><div class="ctrl-head"><div><h3>${esc(s.kindLabel)}</h3>
        <p class="small">The receiver is plugged in, but the controller is asleep. Press its Steam button to wake it.</p></div><span class="tag warn">WAITING</span></div></article>`).join('');
      if (!vis.length && !sleeping.length) html += `<div class="card err"><div class="ctrl-head"><div><h3>No controller found yet</h3>
        <p class="sub">Plug in the receiver or puck (directly, not through an unpowered hub) and turn the controller on. It shows up within a second.</p></div><span class="tag err">NOT FOUND</span></div>
        <div class="row"><button class="btn small" type="button" data-act="open" data-what="rescan">Scan again</button></div></div>`;
      if (hidden) html += `<p class="small">${hidden} Xbox-style pad${hidden > 1 ? 's are' : ' is'} hidden: Steam creates them to mirror your real controller, so the overlay always shows the real one.</p>`;
      box.innerHTML = html;
    }
    for (const c of vis) if (c.live) updateLive(c);
  }

  function updateLive(c) {
    const root = $(`[data-live="${CSS.escape(c.id)}"]`);
    if (!root) return;
    const l = c.live;
    for (const [k, s] of Object.entries(l.sticks || {})) {
      const w = $(`[data-g="s:${CSS.escape(k)}"]`, root); if (!w) continue;
      w.firstElementChild.style.transform = `translate(${(s.x * 25).toFixed(1)}px, ${(s.y * 25).toFixed(1)}px)`;
      w.classList.toggle('idle', Math.abs(s.x) < 0.05 && Math.abs(s.y) < 0.05 && !s.click);
      w.classList.toggle('pressed', !!s.click);
    }
    for (const [k, p] of Object.entries(l.pads || {})) {
      const w = $(`[data-g="p:${CSS.escape(k)}"]`, root); if (!w) continue;
      const scale = p.touch ? 1 + (p.p || 0) * 0.8 : 1;
      w.firstElementChild.style.transform = `translate(${(p.x * 25).toFixed(1)}px, ${(p.y * 25).toFixed(1)}px) scale(${scale.toFixed(2)})`;
      w.classList.toggle('idle', !p.touch);
      w.classList.toggle('pressed', !!p.click);
    }
    for (const [k, t] of Object.entries(l.triggers || {})) {
      const w = $(`[data-g="t:${CSS.escape(k)}"]`, root); if (!w) continue;
      const [bl, br] = w.children;
      bl.firstElementChild.style.height = (t.l * 100).toFixed(0) + '%';
      br.firstElementChild.style.height = (t.r * 100).toFixed(0) + '%';
      bl.classList.toggle('full', !!t.l2); br.classList.toggle('full', !!t.r2);
    }
    const chips = $(`[data-chips="${CSS.escape(c.id)}"]`);
    if (chips) {
      const sc2026 = (c.kinds || []).includes('DEVICE_SC2026');
      const html = (l.pressed || []).length ? l.pressed.map(p => `<span class="chip">${esc(chipLabel(p, sc2026))}</span>`).join('') : '<span class="none">Press something…</span>';
      if (chips._html !== html) { chips.innerHTML = html; chips._html = html; }
    }
  }

  // ---------------------------------------------------------------- live updates
  function update() {
    if (!state) return;
    document.documentElement.style.setProperty('--accent', state.settings.accent || '#3ad6ff');
    $('#navFoot').innerHTML = `v${esc(state.version)}${state.instance ? ` · instance ${state.instance + 1}` : ''}<br>Based on VSCView by Nielk1 (MIT)<br>© 2026 Talaria Software LLC`;

    if (route === 'home') updateHome();
    if (route === 'setup' && setupStep === 1) renderControllers(true);
    if (route === 'help') updateHelp();
    if (route === 'themes' || (route === 'setup' && setupStep === 2)) {
      const sig = state.theme?.key + '|' + [...myKinds()].join(',');
      if (lastSig.themes !== undefined && sig.split('|')[1] !== lastSig.themes.split('|')[1] && themeFilter === 'mine') renderThemeGrid();
      else if (sig !== lastSig.themes) markCurrentTheme();
      lastSig.themes = sig;
    }
    if (route === 'obs' || (route === 'setup' && setupStep === 3)) {
      const sig = state.theme?.key;
      if (sig !== lastSig.obs) { lastSig.obs = sig; updateObsOutputs(false); }
    }
  }

  function setPill(id, tone, text) {
    const d = $('#d' + id), v = $('#v' + id);
    if (!d) return;
    d.className = 'dot ' + tone;
    if (v.textContent !== text) v.textContent = text;
  }

  function updateHome() {
    const s = state;
    if (!s.server.running) setPill('Overlay', 'err', 'Server off');
    else if (s.overlay.sources > 0) setPill('Overlay', 'ok', `On air · ${s.overlay.sources} OBS source${s.overlay.sources > 1 ? 's' : ''}`);
    else setPill('Overlay', 'info', 'Ready · no OBS source yet');
    const vis = visibleControllers();
    const sel = vis.find(c => c.selected);
    if (sel) setPill('Ctrl', sel.inUse ? 'ok' : 'info', `${sel.kindLabel}${sel.inUse ? ' · in use' : ''}`);
    else if (vis.length) setPill('Ctrl', 'warn', `${vis.length} connected · none on the overlay`);
    else setPill('Ctrl', 'err', 'None connected');
    setPill('Follow', s.settings.followMode ? 'ok' : '', s.settings.followMode ? 'On · follows the one in use' : 'Off');

    const t = s.theme;
    const name = t ? (t.theme ? themeTitle(t) : t.key) : 'No theme yet';
    if ($('#themeName').textContent !== name) {
      $('#themeName').textContent = name;
      const remembered = s.settings.rememberThemePerController && visibleControllers().some(c => c.selected);
      $('#themeMeta').textContent = t ? `${t.family || ''}${t.width ? ` · ${t.width}×${t.height}` : ''}${remembered ? ' · remembered for this controller' : ''}` : 'Pick a look in Themes.';
      $('#stageBadge').textContent = t?.width ? `TRANSPARENT · ${t.width}×${t.height}` : 'TRANSPARENT';
    }
    const note = `${s.server.url}  ·  local only, never leaves this PC`;
    if ($('#urlNote').textContent !== note) $('#urlNote').textContent = note;
    renderControllers(false);
  }

  function helpCard(tone, tag, title, body, act) {
    return `<article class="card ${tone === 'ok' ? 'on' : tone}"><div class="row"><span class="tag ${tone === 'info' ? '' : tone}">${tag}</span><h3>${esc(title)}</h3></div>
      <p class="sub">${body}</p>${act ? `<div class="row">${act}</div>` : ''}</article>`;
  }

  function updateHelp() {
    const s = state;
    const vis = visibleControllers();
    const ctrl = [];
    for (const c of vis) {
      if (c.selected) ctrl.push(helpCard('ok', 'ON OVERLAY', `${c.kindLabel}: connected and on the overlay`, 'Padsight is reading it, and the overlay follows its inputs.'));
      else ctrl.push(helpCard('info', 'STANDBY', `${c.kindLabel}: connected, not on the overlay`, s.settings.followMode ? 'Follow mode switches to it as soon as you press something on it.' : 'Turn on follow mode in Settings, or put it on the overlay by hand.',
        `<button class="btn small" type="button" data-act="use-ctrl" data-id="${esc(c.id)}">Use this one now</button>`));
    }
    for (const r of sleepingReceivers()) ctrl.push(helpCard('warn', 'ASLEEP', `${r.kindLabel}: receiver found, controller asleep`, 'The wireless receiver is plugged in, but the controller is off. Press its Steam button.'));
    if (!vis.length) ctrl.push(helpCard('err', 'NOT FOUND', 'No controller detected', 'Check the receiver or puck is plugged in directly (not through an unpowered hub), then turn the controller on. Detection takes about a second.',
      '<button class="btn small" type="button" data-act="open" data-what="rescan">Run a controller check</button>'));
    if (s.sdl && !/ready/i.test(s.sdl)) ctrl.push(helpCard('warn', 'SDL', '2026 controller support is not running', esc(s.sdl)));

    const ov = [];
    if (!s.server.running) {
      const busy = /in use|only one usage|address already/i.test(s.server.error || '');
      ov.push(helpCard('err', busy ? 'PORT BUSY' : 'SERVER OFF', busy ? `Port ${s.server.port} is already in use` : 'The overlay server is off',
        busy ? 'Another program is using it. Pick a free port; then update the URL in OBS.' : esc(s.server.error || 'Turn it on in Settings.'),
        '<button class="btn small" type="button" data-act="open" data-what="advanced-settings">Choose another port</button>'));
    } else if (s.overlay.sources > 0) {
      ov.push(helpCard('ok', 'ON AIR', 'OBS is showing the overlay', `${s.overlay.sources} Browser Source${s.overlay.sources > 1 ? 's are' : ' is'} connected and receiving frames.`));
    } else {
      ov.push(helpCard('info', 'NO SOURCE', 'Nothing is connected yet', 'The overlay is ready, but OBS hasn’t opened it. Add a Browser Source with the URL from the OBS page.',
        '<button class="btn small" type="button" data-act="nav" data-to="obs">Open OBS setup</button>'));
    }
    if (!s.theme) ov.push(helpCard('warn', 'NO THEME', 'No theme chosen', 'OBS shows nothing until a theme is picked.', '<button class="btn small" type="button" data-act="nav" data-to="themes">Choose a theme</button>'));

    const sig = JSON.stringify([ctrl, ov]);
    if (sig !== lastSig.help) {
      lastSig.help = sig;
      $('#helpCtrl').innerHTML = ctrl.join('');
      $('#helpOverlay').innerHTML = ov.join('');
    }
    const ch = s.overlay.channels || [];
    const render = ch.length ? Math.max(...ch.map(c => c.renderMs)) : 0;
    const png = ch.length ? Math.max(...ch.map(c => c.pngMs)) : 0;
    const diag = [
      `SDL ${s.sdl || 'not started'}`,
      `Server 127.0.0.1:${s.server.port} · ${s.server.running ? 'local only' : 'off'}`,
      `Render ${render.toFixed(1)} ms · PNG ${png.toFixed(1)} ms`,
      `Padsight ${s.version} · based on VSCView by Nielk1`,
    ].map(t => `<span>${esc(t)}</span>`).join('');
    if ($('#diag').innerHTML !== diag) $('#diag').innerHTML = diag;
  }

  // ---------------------------------------------------------------- actions
  const ACTIONS = {
    nav: b => go(b.dataset.to),
    setup: () => go('setup', 1),
    step: b => go('setup', +b.dataset.step),
    'finish-setup': async () => { try { state = await api('settings', { setupDone: true }); } catch { } go('home'); },
    'copy-obs': () => copy(state?.server?.url || overlayBase, 'OBS URL'),
    'copy-built': () => copy(builtUrl(false), 'OBS URL'),
    'copy-dock': () => copy(dockUrl(), 'Dock URL'),
    'copy-pinned': b => copy(`${overlayBase}?theme=${b.dataset.key}`, 'Pinned URL'),
    'use-theme': async b => {
      try { state = await api('theme', { theme: b.dataset.key }); markCurrentTheme(); toast('Theme applied'); }
      catch (e) { toast(e.message); }
    },
    'use-ctrl': async b => { try { state = await api('controller', { id: b.dataset.id }); lastSig = {}; update(); } catch (e) { toast(e.message); } },
    identify: async b => { try { await api('identify', { id: b.dataset.id }); toast('Sent: watch or listen for the controller'); } catch (e) { toast(e.message); } },
    open: async b => { try { await api('open', { what: b.dataset.what }); if (b.dataset.what === 'rescan') toast('Scanning for controllers…'); } catch (e) { toast(e.message); } },
    accent: async b => { try { state = await api('settings', { accent: b.dataset.color }); render(); } catch (e) { toast(e.message); } },
    filter: b => { themeFilter = b.dataset.f; store.set('themeFilter', themeFilter); renderThemeGrid(); },
    'reload-themes': async () => { themes = null; await renderThemeGrid(); toast('Theme list reloaded'); },
    diag: () => {
      const d = Object.assign({}, state, { userAgent: navigator.userAgent, time: new Date().toISOString() });
      copy(JSON.stringify(d, null, 2), 'Diagnostics');
    },
  };

  document.addEventListener('click', e => {
    const nav = e.target.closest('[data-nav]');
    if (nav) { go(nav.dataset.nav); return; }
    const b = e.target.closest('[data-act]');
    if (b && ACTIONS[b.dataset.act] && !b.disabled) {
      e.preventDefault();
      const r = ACTIONS[b.dataset.act](b, e);
      // Calls that wait on the app (switching controller, loading a theme) show as busy until they finish.
      if (r && typeof r.then === 'function' && b.tagName === 'BUTTON') {
        b.disabled = true;
        r.finally(() => { b.disabled = false; });
      }
    }
  });

  main.addEventListener('change', async e => {
    const el = e.target;
    if (el.dataset.set) {
      const v = el.type === 'checkbox' ? el.checked : +el.value;
      try { state = await api('settings', { [el.dataset.set]: v }); toast('Saved'); }
      catch (err) { toast(err.message); }
    } else if (el.dataset.opt) setOpt(el.dataset.opt, el.value);
    else if (el.dataset.actChange === 'family') { themeFilter = el.value || 'mine'; store.set('themeFilter', themeFilter); renderThemeGrid(); }
  });
  main.addEventListener('input', e => {
    const el = e.target;
    if (el.id === 'themeSearch') { themeSearch = el.value; renderThemeGrid(); }
    else if (el.dataset.opt && (el.type === 'range' || el.type === 'number')) setOpt(el.dataset.opt, el.value);
  });

  // ---------------------------------------------------------------- polling
  let failures = 0;
  const fastPage = () => route === 'home' || (route === 'setup' && setupStep === 1);
  async function tick() {
    try {
      state = await api('state');
      failures = 0;
      $('#offline').hidden = true;
      if (!tick.started) {
        tick.started = true;
        if (!state.settings.setupDone && !DOCK) { setupStep = 1; route = 'setup'; }
        if (!themes) loadThemes().then(() => { if (route === 'obs' || route === 'setup') render(); }).catch(() => { });
        render();
      } else update();
    } catch (e) {
      if (!e.status) console.error(e);
      failures++;
      if (e.status === 401) {
        $('#offlineText').textContent = 'This page has no valid panel key. Open the panel from Padsight itself, or copy the dock URL again from its OBS page.';
        $('#offline').hidden = false;
      } else if (failures > 3) $('#offline').hidden = false;
    }
    setTimeout(tick, document.hidden ? 1000 : fastPage() ? 100 : 400);
  }
  if (!KEY) {
    $('#offlineText').textContent = 'This page has no panel key. Open the panel from Padsight itself (its window or tray icon).';
    $('#offline').hidden = false;
  } else tick();
})();
