/* Ghostlight Studio — desk logic. Vanilla, no build step. */

const $ = (sel) => document.querySelector(sel);
const state = {
  videos: [],
  filter: 'all',
  settings: {},
  dirty: {},
  lastEventId: 0,
  currentFilm: null,
  view: 'desk',
  flash: null,
};

const NETWORK = {
  data: null,
  channels: [],
  templates: [],
  options: { niches: [], styles: [] },
  editing: null,
  loading: null,
};

const RADAR = {
  data: null,
  items: [],
  ideas: [],
  trend: null,
  live: false,
  channelId: '',
  channels: [],
  loading: null,
};

const fmtNum = (n) => (n ?? 0).toLocaleString('en-US');
const fmtMb = (b) => (b ? (b / 1e6).toFixed(1) + ' MB' : '—');
const fmtMoney = (n) => `$${(Number(n) || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const fmtWhen = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 0) return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  if (diff < 90) return 'just now';
  if (diff < 3600) return `${Math.max(1, Math.round(diff / 60))}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} · ${d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`;
};
const fmtAir = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return `${d.toLocaleDateString(undefined, { weekday: 'short' })} ${d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`;
};
const fmtDur = (s) => {
  if (!s) return '—';
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return m ? `${m}m ${sec}s` : `${sec}s`;
};
const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[c]));

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

/* ---------- masthead chips ---------- */

function renderChips(status) {
  const bench = $('#chip-studio');
  if (status.studio.busy) {
    bench.textContent = 'on the bench';
    bench.className = 'chip on';
  } else if (status.studio.queued > 0) {
    bench.textContent = `${status.studio.queued} queued`;
    bench.className = 'chip on';
  } else {
    bench.textContent = 'desk open';
    bench.className = 'chip off';
  }

  const channels = status.youtube.channels || [];
  const total = status.youtube.channel_count ?? channels.length;
  const linked = status.youtube.connected_count ?? channels.filter((c) => c.connected).length;
  const feeds = $('#chip-feeds');
  feeds.textContent = total ? `${total} voice${total === 1 ? '' : 's'}` : 'no network';
  feeds.className = 'chip ' + (total ? 'on' : 'off');

  const sched = $('#chip-schedule');
  if (!status.schedule.enabled) {
    sched.textContent = 'schedule off';
    sched.className = 'chip off';
  } else if (status.schedule.paused) {
    sched.textContent = 'schedule paused';
    sched.className = 'chip warn';
  } else {
    sched.textContent = `auto · ${status.schedule.produced_today}/${status.schedule.max_per_day} today`;
    sched.className = 'chip on';
  }

  const yt = $('#chip-youtube');
  if (linked > 0) {
    const name = status.youtube.channel.name || 'channel';
    yt.textContent = total > 1 ? `YT: ${linked}/${total} linked` : `YT: ${name}`;
    yt.className = 'chip on';
  } else if (status.youtube.authorizing) {
    yt.textContent = 'YT: signing in…';
    yt.className = 'chip warn';
  } else {
    yt.textContent = total > 1 ? `YT: 0/${total} linked` : 'YT: not linked';
    yt.className = 'chip off';
  }

  const quota = $('#chip-quota');
  const q = status.youtube.quota;
  quota.textContent = `${q.uploads_used}/${q.upload_limit} uploads today`;
  quota.className = 'chip ' + (q.uploads_used >= q.upload_limit ? 'warn' : 'off');
}

/* ---------- desk ---------- */

function renderStats(stats) {
  const cells = [
    ['films made', fmtNum(stats.total)],
    ['published', fmtNum(stats.published)],
    ['ready on shelf', fmtNum(stats.ready)],
    ['runtime', `${Math.round(stats.minutes)}m`],
    ['words spoken', fmtNum(stats.words)],
    ['avg novelty', stats.avg_novelty.toFixed(2)],
  ];
  $('#stats').innerHTML = cells.map(([lbl, num]) =>
    `<div class="stat"><div class="num">${esc(num)}</div><div class="lbl">${lbl}</div></div>`
  ).join('');
}

function renderBench(videos) {
  const box = $('#now-making');
  const active = videos.find((v) => ['queued', 'drafting', 'uploading'].includes(v.status));
  if (!active) { box.hidden = true; return; }
  box.hidden = false;
  $('#making-title').textContent = active.title || 'Untitled commission';
  $('#making-stage').textContent =
    `${active.stage || 'queued'} · ${active.progress || 0}%${active.status === 'uploading' ? ' · uploading' : ''}`;
  $('#making-progress').style.width = `${active.progress || 0}%`;
}

function pushLog(event) {
  const log = $('#log');
  const li = document.createElement('li');
  li.className = `level-${event.level}`;
  li.innerHTML = `
    <div class="meta">
      <span>${esc((event.ts || '').slice(11, 19))}</span>
      <span class="badge">${esc(event.kind)}</span>
    </div>
    <div class="msg">${esc(event.message)}</div>`;
  log.appendChild(li);
  while (log.children.length > 120) log.removeChild(log.firstChild);
  log.scrollTop = log.scrollHeight;
}

async function loadLog() {
  const data = await api('/api/events?limit=60');
  data.items.forEach((e) => { state.lastEventId = Math.max(state.lastEventId, e.id); pushLog(e); });
}

function connectStream() {
  const es = new EventSource('/api/stream');
  es.onmessage = (msg) => {
    try {
      const event = JSON.parse(msg.data);
      pushLog(event);
      if (['studio', 'schedule', 'youtube', 'autopilot', 'distribution'].includes(event.kind)) {
        refresh();
      }
    } catch (_) {}
  };
  es.onerror = () => { $('#log-live').innerHTML = '<span class="pulse"></span> reconnecting…'; };
  es.onopen = () => { $('#log-live').innerHTML = '<span class="pulse"></span> live'; };
}

/* ---------- command bar ---------- */

async function runCommand(text) {
  const replyBox = $('#command-reply');
  replyBox.hidden = false;
  replyBox.innerHTML = '<span class="who">The studio</span>…';
  try {
    const out = await api('/api/command', { method: 'POST', body: { text } });
    replyBox.innerHTML = `<span class="who">The studio · ${esc(out.action)}</span>${esc(out.reply)}`;
  } catch (exc) {
    replyBox.innerHTML = `<span class="who">The studio</span>That didn't land — ${esc(exc.message)}`;
  }
  refresh();
}

/* ---------- shelf ---------- */

async function loadVideos() {
  const extra = state.filter === 'archived' ? '&archived=true' : '';
  const statusFilter = ['ready', 'published', 'drafting', 'failed'].includes(state.filter)
    ? `&status=${state.filter}` : '';
  const data = await api(`/api/videos?limit=120${statusFilter}${extra}`);
  state.videos = data.items;
  renderGrid();
  const bench = await api('/api/videos?limit=12');
  renderBench(bench.items);
}

function renderGrid() {
  const grid = $('#grid');
  grid.querySelectorAll('.card').forEach((c) => c.remove());
  const empty = $('#grid-empty');
  empty.hidden = state.videos.length > 0;
  $('#shelf-count').textContent = state.videos.length
    ? `${state.videos.length} film${state.videos.length === 1 ? '' : 's'} on the shelf`
    : '';

  for (const v of state.videos) {
    const card = document.createElement('article');
    card.className = 'card';
    const poster = v.poster_path
      ? `<img loading="lazy" src="/api/videos/${v.id}/file/poster" alt="" />`
      : `<div class="noart">✳</div>`;
    const progress = ['queued', 'drafting', 'uploading'].includes(v.status)
      ? `<div class="card-progress"><i style="width:${v.progress || 0}%"></i></div>` : '';
    const statusLabel = v.archived ? 'archived' : v.status;
    card.innerHTML = `
      <div class="card-poster">
        ${poster}
        <span class="card-status st-${esc(v.status)}">${esc(statusLabel)}</span>
        ${progress}
      </div>
      <div class="card-body">
        <div class="card-title">${esc(v.title || 'Untitled commission')}</div>
        <div class="card-meta">
          <span>${esc(v.format === 'long' ? 'long form' : 'short')}</span>
          <span>${fmtDur(v.duration)}</span>
        </div>
      </div>`;
    card.addEventListener('click', () => openDrawer(v.id));
    grid.appendChild(card);
  }
}

/* ---------- drawer ---------- */

async function openDrawer(id) {
  let v;
  try { v = await api(`/api/videos/${id}`); } catch (exc) { return; }
  state.currentFilm = v;
  const drawer = $('#drawer');
  const veil = $('#drawer-veil');

  const script = v.script || {};
  const segments = (script.segments || []).map((s) => `
    <p class="seg">${s.heading ? `<span class="heading">${esc(s.heading)}</span>` : ''}${esc(s.text)}</p>`
  ).join('') || `<p class="seg">${esc(script.narration || v.hook || '')}</p>`;

  const actions = [];
  const gate = v.quality || null;
  const blocked = !!(gate && gate.hard_fail);
  if (v.status === 'ready') {
    if (blocked) actions.push('<button class="btn" data-act="inspect">Run the gate again</button>');
    else if ((v.stage || '') === 'review') actions.push('<button class="btn primary" data-act="approve">Approve &amp; upload</button>');
    else actions.push('<button class="btn primary" data-act="publish">Publish to YouTube</button>');
  }
  if (v.status === 'failed') actions.push('<button class="btn primary" data-act="retry">Try again</button>');
  if (['ready', 'published'].includes(v.status)) actions.push('<button class="btn" data-act="replay">Watch</button>');
  if (['ready', 'published'].includes(v.status)) actions.push('<button class="btn" data-act="share">Share kit</button>');
  if (!v.archived) actions.push('<button class="btn danger" data-act="archive">Archive</button>');
  if (v.archived) actions.push('<button class="btn" data-act="unarchive">Un-archive</button>');
  if (v.youtube_url) actions.push(`<a class="btn" href="${esc(v.youtube_url)}" target="_blank" rel="noopener">Open on YouTube</a>`);

  const metrics = v.metrics || {};
  const upload = v.upload_meta || {};
  const variants = Array.isArray(v.thumb_variants) ? v.thumb_variants : [];
  const variantsBlock = variants.length ? `
    <div class="thumb-variants">
      <span class="kicker">Thumbnail takes</span>
      <div class="thumb-strip">
        ${variants.map((t) => `
          <button type="button" class="thumb-choice ${t.path === v.thumb_path ? 'chosen' : ''}"
            data-thumb="${esc(t.id)}" title="${esc(t.rationale || '')}">
            <img src="/api/videos/${v.id}/file/thumb?variant=${encodeURIComponent(t.id)}" alt="${esc(t.label || t.id)}" />
            <span>${esc(t.label || t.id)}${t.recommended ? ' · studio pick' : ''}</span>
          </button>`).join('')}
      </div>
    </div>` : '';
  const uploadBits = [];
  if (v.youtube_url) uploadBits.push(`<a class="link" href="${esc(v.youtube_url)}" target="_blank" rel="noopener">${esc(v.youtube_url)}</a>`);
  if (upload.privacy) uploadBits.push(`privacy: ${esc(upload.privacy)}`);
  if (upload.contains_synthetic_media) uploadBits.push('AI-disclosed');
  if (upload.auto_captions) uploadBits.push('captions attached');
  if (v.published_at) uploadBits.push(`published ${esc(v.published_at.slice(0, 16).replace('T', ' '))}`);

  drawer.innerHTML = `
    <button class="drawer-close" data-act="close">✕</button>
    <span class="kicker">${v.channel_name ? esc(v.channel_name) + ' · ' : ''}${esc(v.format === 'long' ? 'Long form' : 'Short')} · ${esc(v.niche || 'fresh idea')}</span>
    <h2 class="film-title">${esc(v.title || 'Untitled commission')}</h2>
    <div class="film-meta">
      <span>${fmtDur(v.duration)}</span>
      <span>${fmtNum(v.words)} words</span>
      <span>novelty ${(v.novelty ?? 1).toFixed(2)}</span>
      <span>${fmtMb(v.bytes)}</span>
      <span>${esc(v.status)}</span>
      ${metrics.views ? `<span>${fmtNum(metrics.views)} views</span>` : ''}
      ${metrics.watch_minutes ? `<span>${fmtNum(Math.round(metrics.watch_minutes))} watch min</span>` : ''}
      ${metrics.subs_gained ? `<span>+${fmtNum(metrics.subs_gained)} subs</span>` : ''}
    </div>
    ${v.video_path ? `<video controls preload="metadata" src="/api/videos/${v.id}/file/video"></video>` : ''}
    <div class="thumb-row">
      ${v.thumb_path ? `<img src="/api/videos/${v.id}/file/thumb" alt="thumbnail" />` : ''}
      ${v.poster_path && !v.video_path ? `<img src="/api/videos/${v.id}/file/poster" alt="poster" />` : ''}
    </div>
    ${variantsBlock}
    <div class="film-actions">${actions.join('')}</div>
    ${qualityBlock(v)}
    ${uploadBits.length ? `<p class="secret-note">${uploadBits.join(' · ')}</p>` : ''}
    ${v.error ? `<div class="error-note">${esc(v.error)}</div>` : ''}
    <div class="script-block">
      <span class="kicker">The script</span>
      ${segments}
    </div>
    ${script.hook ? `<div class="script-block"><span class="kicker">The hook</span><p class="seg">${esc(script.hook)}</p></div>` : ''}
    ${script.description ? `<div class="script-block"><span class="kicker">Description sent to YouTube</span><p class="seg">${esc(script.description)}</p></div>` : ''}
  `;
  drawer.hidden = false;
  veil.hidden = false;

  drawer.querySelectorAll('[data-act]').forEach((el) => {
    el.addEventListener('click', (ev) => {
      if (el.tagName === 'A') return;
      ev.stopPropagation();
      drawerAction(el.dataset.act, v.id);
    });
  });

  drawer.querySelectorAll('[data-thumb]').forEach((el) => {
    el.addEventListener('click', async (ev) => {
      ev.stopPropagation();
      try {
        await api(`/api/videos/${v.id}/thumbnail`, { method: 'POST', body: { variant: el.dataset.thumb } });
        closeDrawer();
        openDrawer(v.id);
        refresh();
      } catch (exc) {
        alert(`That didn't work: ${exc.message}`);
      }
    });
  });
}

function closeDrawer() {
  $('#drawer').hidden = true;
  $('#drawer-veil').hidden = true;
  const video = $('#drawer video');
  if (video) video.pause();
}

function qualityBlock(v) {
  const q = v.quality;
  if (!q || !Array.isArray(q.checks) || !q.checks.length) {
    return `<div class="quality-block"><span class="kicker">Quality gate</span>
      <p class="quality-note">Not inspected yet. The gate runs automatically when a film is rendered.</p></div>`;
  }
  const verdict = q.hard_fail ? 'Blocked' : 'Passed';
  const notes = Number(q.warnings) || 0;
  const rows = q.checks.map((c) => `
    <li class="q-${esc(c.status)}">
      <span class="q-dot"></span>
      <span class="q-name">${esc(c.name)}</span>
      <em>${esc(c.detail)}</em>
    </li>`).join('');
  return `<div class="quality-block">
    <span class="kicker">Quality gate</span>
    <p class="quality-verdict ${q.hard_fail ? 'blocked' : 'passed'}">${verdict}${notes ? ` · ${notes} note${notes === 1 ? '' : 's'}` : ''}</p>
    <ul class="quality-list">${rows}</ul>
  </div>`;
}

async function drawerAction(act, id) {
  try {
    if (act === 'close') return closeDrawer();
    if (act === 'share') return showShareKit(id);
    if (act === 'replay') {
      const video = $('#drawer video');
      if (video) { video.scrollIntoView({ behavior: 'smooth' }); video.play(); }
      return;
    }
    if (act === 'publish') {
      await api(`/api/videos/${id}/publish`, { method: 'POST', body: {} });
      runCommandSilently('status');
    }
    if (act === 'approve') {
      await api(`/api/videos/${id}/approve`, { method: 'POST', body: {} });
      runCommandSilently('status');
    }
    if (act === 'inspect') {
      await api(`/api/videos/${id}/quality?refresh=true`);
      closeDrawer();
      openDrawer(id);
      return;
    }
    if (act === 'retry') await api(`/api/videos/${id}/retry`, { method: 'POST' });
    if (act === 'archive') await api(`/api/videos/${id}/archive`, { method: 'POST', body: { archived: true } });
    if (act === 'unarchive') await api(`/api/videos/${id}/archive`, { method: 'POST', body: { archived: false } });
    closeDrawer();
    refresh();
  } catch (exc) {
    alert(`That didn't work: ${exc.message}`);
  }
}

async function runCommandSilently(text) {
  try { await api('/api/command', { method: 'POST', body: { text } }); } catch (_) {}
  refresh();
}

async function showShareKit(id) {
  const kit = await api(`/api/videos/${id}/share`);
  const drawer = $('#drawer');
  const old = drawer.querySelector('.share-kit');
  if (old) old.remove();
  const box = document.createElement('div');
  box.className = 'share-kit';
  box.innerHTML = `
    <div class="caption">${esc(kit.caption)}</div>
    <div class="kit-actions">
      <button class="btn small primary" id="kit-copy">Copy caption</button>
      ${kit.srt ? '<button class="btn small" id="kit-srt">Download .srt</button>' : ''}
      ${kit.url ? `<a class="btn small" href="${esc(kit.url)}" target="_blank" rel="noopener">Open on YouTube</a>` : ''}
    </div>`;
  drawer.appendChild(box);
  box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  $('#kit-copy').addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(kit.caption);
      $('#kit-copy').textContent = 'Copied';
    } catch (_) {
      window.prompt('Copy the caption:', kit.caption);
    }
  });
  const srtBtn = $('#kit-srt');
  if (srtBtn) srtBtn.addEventListener('click', () => {
    const blob = new Blob([kit.srt], { type: 'text/plain;charset=utf-8' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `${(kit.title || 'film').replace(/[^a-z0-9]+/gi, '-').toLowerCase()}.srt`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 2000);
  });
}

/* ---------- settings & panels ---------- */

const SETTING_FIELDS = [
  {
    group: 'The writer',
    rows: [
      ['creator.tone', 'Voice & tone', 'text'],
      ['creator.audience', 'Who it is for', 'text'],
      ['script.words_per_minute', 'Words per minute', 'number'],
      ['script.short_seconds', 'Short length (s)', 'text'],
    ],
  },
  {
    group: 'The picture',
    rows: [
      ['visuals.style', 'Art style (or auto)', 'text'],
      ['music.enabled', 'Score the films', 'check'],
      ['music.gain', 'Music level', 'number'],
    ],
  },
  {
    group: 'The render',
    rows: [
      ['render.fps', 'Frames per second', 'number'],
      ['render.crf', 'Quality (crf, lower = finer)', 'number'],
      ['render.keep_work_files', 'Keep work files', 'check'],
    ],
  },
  {
    group: 'YouTube',
    rows: [
      ['youtube.enabled', 'Uploads enabled', 'check'],
      ['youtube.auto_upload', 'Auto-upload when ready', 'check'],
      ['youtube.auto_start_schedule', 'Go live after Google sign-in', 'check'],
      ['youtube.privacy', 'Privacy (private/unlisted/public)', 'text'],
      ['youtube.disclose_ai', 'Disclose AI content', 'check'],
      ['youtube.auto_captions', 'Attach word-timed captions', 'check'],
      ['youtube.auto_comment', 'Post the first comment', 'check'],
      ['youtube.daily_upload_limit', 'Uploads per channel per day', 'number'],
    ],
  },
  {
    group: 'The network',
    rows: [
      ['autopilot.enabled', 'Autopilot', 'check'],
      ['autopilot.target_channels', 'Channels to open', 'number'],
      ['autopilot.backlog', 'Films kept warm', 'number'],
      ['autopilot.explore', 'Exploration share (0–0.5)', 'number'],
      ['autopilot.learn_minutes', 'Learn every (minutes)', 'number'],
      ['autopilot.max_films_per_day', 'Network cap per day', 'number'],
      ['autopilot.adapt_schedule', 'Move airtimes to what works', 'check'],
    ],
  },
  {
    group: 'Distribution',
    rows: [
      ['distribution.enabled', 'Share every upload', 'check'],
      ['distribution.webhook_url', 'Discord / webhook URL', 'text'],
      ['distribution.rss', 'Publish RSS feed', 'check'],
    ],
  },
  {
    group: 'The schedule',
    rows: [
      ['schedule.enabled', 'Run on its own', 'check'],
      ['schedule.mode', 'Mode (rhythm/continuous)', 'text'],
      ['schedule.times', 'Times (comma list)', 'text'],
      ['schedule.max_per_day', 'Max films per day', 'number'],
      ['schedule.min_gap_minutes', 'Min gap (minutes)', 'number'],
    ],
  },
  {
    group: 'Novelty',
    rows: [
      ['novelty.max_similarity', 'Max similarity to earlier films', 'number'],
      ['novelty.attempts', 'Rewrite attempts', 'number'],
    ],
  },
];

function getByPath(obj, path) {
  return path.split('.').reduce((acc, key) => (acc == null ? acc : acc[key]), obj);
}

function renderSettings(snapshot) {
  state.settings = snapshot;
  state.dirty = {};
  const body = $('#settings-body');
  const html = SETTING_FIELDS.map((g) => `
    <div class="setting-group">
      <h3>${esc(g.group)}</h3>
      ${g.rows.map(([path, label, type]) => {
        const value = getByPath(snapshot, path);
        if (type === 'check') {
          return `<div class="setting-row"><label for="set-${esc(path)}">${esc(label)}</label>
            <input type="checkbox" id="set-${esc(path)}" data-path="${esc(path)}" ${value ? 'checked' : ''} /></div>`;
        }
        const shown = Array.isArray(value) ? value.join(', ') : (value ?? '');
        return `<div class="setting-row"><label for="set-${esc(path)}">${esc(label)}</label>
          <input type="${type}" id="set-${esc(path)}" data-path="${esc(path)}" value="${esc(shown)}" /></div>`;
      }).join('')}
    </div>`).join('');
  body.innerHTML = html + `
    <div class="save-bar">
      <button class="btn primary" id="save-settings">Save the knobs</button>
      <span class="save-note" id="save-note"></span>
    </div>`;

  body.querySelectorAll('[data-path]').forEach((input) => {
    input.addEventListener('change', () => {
      const path = input.dataset.path;
      const original = getByPath(state.settings, path);
      let value = input.type === 'checkbox' ? input.checked : input.value;
      if (input.type === 'number') value = Number(value);
      if (typeof original === 'object' && original !== null) {
        value = String(value).split(',').map((s) => s.trim()).filter(Boolean);
      }
      state.dirty[path] = value;
    });
  });

  $('#save-settings').addEventListener('click', async () => {
    if (!Object.keys(state.dirty).length) return;
    try {
      await api('/api/settings', { method: 'PATCH', body: state.dirty });
      $('#save-note').textContent = 'Saved. The studio felt that.';
      setTimeout(() => { $('#save-note').textContent = ''; }, 2600);
      state.dirty = {};
      refresh();
    } catch (exc) {
      $('#save-note').textContent = `Couldn't save: ${exc.message}`;
    }
  });
}

function switchView(view) {
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('is-active', t.dataset.view === view));
  document.querySelectorAll('.view').forEach((v) => v.classList.toggle('is-active', v.id === `view-${view}`));
  state.view = view;
  if (view === 'network') loadNetwork().catch(() => {});
  if (view === 'radar') loadRadar().catch(() => {});
}

function renderYoutubePanel(status) {
  const yt = status.youtube;
  const channels = yt.channels || [];
  const q = yt.quota;
  const pct = Math.min(100, Math.round((q.units_used / Math.max(1, q.units_limit)) * 100));
  const linked = yt.connected_count ?? channels.filter((c) => c.connected).length;
  let inner = '';

  if (channels.length) {
    inner += `<div class="channel-mini-list">${channels.map((c) => `
      <div class="state-line"><span class="state-dot ${c.connected ? 'on' : c.configured ? 'amber' : ''}"></span>
        <strong>${esc(c.name)}</strong>
        <span class="mini-note">${c.connected ? 'signed in' : c.configured ? 'key ready — connect on the Network page' : 'no Google key'}</span>
      </div>`).join('')}</div>`;
  }

  if (linked > 0) {
    inner += `
      <div class="quota-bar">
        <div class="quota-legend"><span>API quota (Pacific day)</span><span>${fmtNum(q.units_used)} / ${fmtNum(q.units_limit)} units</span></div>
        <div class="progress-rail"><div class="progress-fill" style="width:${pct}%"></div></div>
        <div class="quota-legend"><span>${q.uploads_used} / ${q.upload_limit} uploads today</span><span>~${q.upload_cost} units per upload</span></div>
      </div>`;
  } else if (yt.authorizing) {
    inner += `<div class="state-line"><span class="state-dot amber"></span>Signing in — finish in the Google tab…</div>`;
  } else {
    inner += `
      <div class="state-line"><span class="state-dot"></span>${channels.length > 1 ? 'No voice is linked yet.' : 'No channel linked yet.'}</div>
      <p class="secret-note">Each voice gets its own Google sign-in on <strong>The Network</strong> page.
      Drop an OAuth <code>client_secret.json</code> there (Google Cloud Console → OAuth client → “Desktop app”),
      then press Connect. The studio uploads at most <strong>${fmtNum(q.upload_limit)} films a day per channel</strong>,
      always announcing itself as AI-made.</p>`;
  }

  inner += `
    <div class="film-actions">
      <button class="btn primary" id="yt-manage">Open the network</button>
    </div>`;
  $('#youtube-body').innerHTML = inner;

  $('#yt-manage').addEventListener('click', () => switchView('network'));
}

function renderSchedulePanel(status) {
  const s = status.schedule;
  const body = $('#schedule-body');
  const times = (s.times || []).map((t) => `<span class="time-pill">${esc(t)}</span>`).join('');
  const feeds = (s.channels || []).map((c) => `
    <div class="feed-line">
      <span class="state-dot ${c.linked ? 'on' : ''}"></span>
      <span class="feed-name">${esc(c.name)}</span>
      <span class="feed-times">${(c.times || []).map(esc).join(' · ') || 'no airtimes'}</span>
      <span class="feed-count">${c.produced_today}/${c.max_per_day}</span>
    </div>`).join('');
  body.innerHTML = `
    <div class="state-line">
      <span class="state-dot ${s.paused ? 'warn' : s.enabled ? 'on' : ''}"></span>
      ${s.enabled ? (s.paused ? 'Paused — nothing starts on its own' : 'Running on its own') : 'Switched off'}
    </div>
    ${s.channels && s.channels.length
      ? `<div class="feed-list">${feeds}</div>`
      : `<div class="schedule-times">${times || '<span class="secret-note">no times set</span>'}</div>`}
    <p class="secret-note">${esc(s.mode)} mode · formats ${esc((s.formats || []).join(' → ') || 'short')} ·
      ${s.produced_today}/${s.max_per_day} made today overall · ${s.failure_streak} failures in a row</p>
    <div class="film-actions">
      ${s.paused || !s.enabled
        ? '<button class="btn primary" id="sched-resume">Resume</button>'
        : '<button class="btn" id="sched-pause">Pause</button>'}
    </div>`;

  const pauseBtn = $('#sched-pause');
  if (pauseBtn) pauseBtn.addEventListener('click', async () => {
    await api('/api/schedule/pause', { method: 'POST' }); refresh();
  });
  const resumeBtn = $('#sched-resume');
  if (resumeBtn) resumeBtn.addEventListener('click', async () => {
    await api('/api/schedule/resume', { method: 'POST' }); refresh();
  });
}

/* ---------- the network ---------- */

let flashTimer = null;

function networkFlash(message, level = 'ok') {
  const box = $('#network-flash');
  if (!box) return;
  box.hidden = false;
  box.className = `network-flash ${level === 'warn' ? 'warn' : ''}`;
  box.textContent = message;
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => { box.hidden = true; }, 8000);
}

function nicheLabel(key) {
  const found = NETWORK.options.niches.find((n) => n.id === key);
  return found ? found.label : String(key || '').replace(/_/g, ' ');
}

function channelName(id) {
  const found = NETWORK.channels.find((c) => c.id === id);
  return found ? found.name : id || '';
}

async function loadNetwork() {
  if (NETWORK.loading) return NETWORK.loading;
  NETWORK.loading = (async () => {
    const [growth, channels] = await Promise.all([api('/api/growth'), api('/api/channels')]);
    NETWORK.data = growth;
    NETWORK.channels = growth.channels || [];
    NETWORK.templates = channels.templates || [];
    NETWORK.options = channels.options || { niches: [], styles: [] };
    renderNetwork(growth);
  })();
  try {
    return await NETWORK.loading;
  } finally {
    NETWORK.loading = null;
  }
}

function renderNetwork(data) {
  const channels = data.channels || [];
  const totals = data.summary.totals;
  const subs = channels.reduce((sum, c) => sum + (Number(c.subscribers) || 0), 0);
  const linked = channels.filter((c) => c.connected).length;

  $('#network-totals').innerHTML = [
    ['voices', fmtNum(channels.length)],
    ['published', fmtNum(totals.published)],
    ['views', fmtNum(totals.views)],
    ['watch hours', fmtNum(Math.round(totals.watch_minutes / 60))],
    ['subscribers', fmtNum(subs)],
    ['earned', fmtMoney(totals.revenue)],
  ].map(([label, num], index) =>
    `<div class="total ${index === 5 ? 'accent' : ''}"><div class="num">${esc(num)}</div><div class="lbl">${label}</div></div>`
  ).join('');

  const schedule = data.autopilot || {};
  const lede = linked === 0
    ? 'The films are already being written, scored and painted. Nothing publishes until a channel is signed in — press Connect with Google on one of the voices below, and the schedule takes over from there.'
    : linked < channels.length
      ? `${linked} of ${channels.length} voices are signed in. Each one publishes on its own airtimes, keeps a warm film on the shelf, and reads its own analytics before choosing what comes next.`
      : 'Every voice is signed in. The network is running on its own airtimes, one film at a time, and learning from what the audience actually watches.';
  $('#network-lede').textContent = lede;

  const auto = data.autopilot || {};
  const last = auto.last_learn ? `last lesson ${fmtWhen(auto.last_learn)}` : 'no lesson read yet';
  $('#autopilot-strip').innerHTML = `
    <span class="state-dot ${auto.enabled ? 'on' : ''}"></span>
    <div class="autopilot-copy">
      <strong>Autopilot ${auto.enabled ? 'engaged' : 'stood down'}</strong>
      <span>Re-reads analytics every ${auto.learn_minutes || 180} minutes · ${last} · keeps ${auto.backlog ?? 1} film warm · adapts airtimes ${auto.adapt_schedule ? 'on' : 'off'}</span>
    </div>
    <button class="btn small" data-auto="think">Think now</button>
    <button class="btn small ${auto.enabled ? '' : 'primary'}" data-auto="toggle">${auto.enabled ? 'Stand down' : 'Engage'}</button>`;

  $('#channel-grid').innerHTML = channels.map((c) => channelCard(c)).join('') ||
    '<div class="empty"><div class="empty-mark">✳</div><p>No voices yet. Add one below.</p></div>';

  renderJournal(data.journal || []);
  renderTemplates();

  if (state.flash) {
    networkFlash(state.flash.message, state.flash.level);
    state.flash = null;
  }
}

function channelCard(c) {
  const stats = c.stats || {};
  const quota = c.quota || {};
  const yt = c.youtube_channel || {};
  const playbook = c.playbook || {};
  const top = (c.top_films || []).slice(0, 3);
  const uploads = Number(quota.uploads_used) || 0;
  const uploadLimit = Number(quota.upload_limit) || 1;
  const uploadPct = Math.min(100, Math.round((uploads / Math.max(1, uploadLimit)) * 100));
  const units = Number(quota.units_used) || 0;
  const stateText = c.connected
    ? `signed in${yt.name ? ' as ' + yt.name : ''}`
    : c.configured ? 'Google key ready · not signed in' : 'no Google key yet';
  const dot = c.connected ? 'on' : c.configured ? 'amber' : '';
  const privacy = (c.privacy || 'private').toLowerCase();
  const privacyPill = `<span class="pill privacy ${esc(privacy)}">${esc(privacy)}</span>`;
  const approval = (c.approval || 'auto').toLowerCase();
  const approvalPill = `<span class="pill approval ${esc(approval)}">${approval === 'review' ? 'review shelf' : 'auto-publish'}</span>`;
  const airtimes = (c.times || []).map((t) => `<span class="pill air">${esc(t)}</span>`).join('');
  const niches = (c.niches || []).map((n) => `<span class="pill">${esc(nicheLabel(n))}</span>`).join('');
  const styles = (c.styles || []).map((s) => `<span class="pill">${esc(s)}</span>`).join('');
  const films = top.length
    ? `<div class="channel-films">${top.map((f) => `
        <div class="channel-film" data-video="${esc(f.id)}">
          <span>${esc(f.title || 'Untitled')}</span>
          <span class="views">${fmtNum(f.views)} views</span>
        </div>`).join('')}</div>`
    : '';
  const insight = playbook.insight ? `<p class="channel-insight">${esc(playbook.insight)}</p>` : '';

  return `
    <article class="channel-card" data-channel="${esc(c.id)}">
      <div class="channel-head">
        <div class="channel-mark">${esc((c.name || '?').trim().charAt(0))}</div>
        <div class="channel-id">
          <div class="channel-name">${esc(c.name)}</div>
          <div class="channel-tagline">${esc(c.tagline || 'an editorial identity')}</div>
        </div>
      </div>
      <div class="channel-state"><span class="state-dot ${dot}"></span>${esc(stateText)}</div>
      <div class="channel-pills">${privacyPill}${approvalPill}${airtimes}${niches}${styles}</div>
      <div class="channel-stats">
        <div><div class="num">${fmtNum(stats.published)}</div><div class="lbl">published</div></div>
        <div><div class="num">${fmtNum(stats.views)}</div><div class="lbl">views</div></div>
        <div><div class="num">${fmtNum(c.subscribers)}</div><div class="lbl">subscribers</div></div>
      </div>
      <div class="channel-quota">
        <div class="progress-rail"><div class="progress-fill" style="width:${uploadPct}%"></div></div>
        <div class="quota-legend"><span>${uploads}/${uploadLimit} uploads today</span><span>${fmtNum(units)} units used</span></div>
      </div>
      ${films}
      ${insight}
      <div class="channel-actions">
        ${c.connected
          ? '<button class="btn small" data-nc="disconnect" data-id="' + esc(c.id) + '">Disconnect</button>'
          : '<button class="btn small primary" data-nc="connect" data-id="' + esc(c.id) + '">Connect with Google</button>'}
        ${c.connected ? '' : '<button class="btn small" data-nc="secret" data-id="' + esc(c.id) + '">Google key</button>'}
        <button class="btn small ghost" data-nc="make" data-id="${esc(c.id)}">Make one now</button>
        <button class="btn small" data-nc="toggle" data-id="${esc(c.id)}">${c.enabled ? 'Pause' : 'Resume'}</button>
        <button class="btn small" data-nc="edit" data-id="${esc(c.id)}">Edit</button>
        ${NETWORK.channels.length > 1 ? '<button class="btn small danger" data-nc="delete" data-id="' + esc(c.id) + '">Remove</button>' : ''}
      </div>
    </article>`;
}

function renderJournal(entries) {
  const box = $('#journal');
  if (!box) return;
  if (!entries.length) {
    box.innerHTML = '<li class="j-empty">Nothing in the journal yet. The machine writes its first entry when it makes a choice.</li>';
    return;
  }
  box.innerHTML = entries.map((e) => `
    <li>
      <div class="j-meta">
        <span>${esc(fmtWhen(e.ts))}</span>
        <span class="j-kind ${esc(e.kind)}">${esc(e.kind)}</span>
        <span>${esc(channelName(e.channel_id))}</span>
      </div>
      <div class="j-headline">${esc(e.headline)}</div>
      ${e.body ? `<div class="j-body">${esc(e.body)}</div>` : ''}
    </li>`).join('');
}

function renderTemplates() {
  const row = $('#template-row');
  if (!row) return;
  const existing = new Set(NETWORK.channels.map((c) => c.id));
  const cards = NETWORK.templates.map((t) => {
    const taken = existing.has(t.id);
    return `
      <div class="template-card">
        <div class="name">${esc(t.name)}</div>
        <div class="tagline">${esc(t.tagline || '')}</div>
        <div class="niches">${(t.niches || []).map((n) => esc(nicheLabel(n))).join(' · ')}</div>
        <button class="btn small ${taken ? '' : 'ghost'}" data-tpl="${esc(t.id)}" ${taken ? 'disabled' : ''}>
          ${taken ? 'Already on the network' : 'Add this voice'}
        </button>
      </div>`;
  }).join('');
  row.innerHTML = cards + `
    <div class="template-card">
      <div class="name">A blank slate</div>
      <div class="tagline">Your own obsessions, from scratch.</div>
      <div class="niches">choose niches · styles · airtimes</div>
      <button class="btn small ghost" data-tpl="new">Build a voice</button>
    </div>`;
}

async function channelAction(act, id) {
  const channel = NETWORK.channels.find((c) => c.id === id);
  if (!channel && act !== 'new') return;
  try {
    if (act === 'connect') {
      networkFlash(`Opening Google sign-in for ${channel.name}…`);
      const out = await api(`/api/channels/${encodeURIComponent(id)}/connect`, { method: 'POST' });
      if (out.url) window.location.href = out.url;
      return;
    }
    if (act === 'secret') {
      pendingSecretChannel = id;
      networkFlash(`Choose the Google OAuth client file for ${channel.name}.`);
      $('#secret-file').click();
      return;
    }
    if (act === 'disconnect') {
      if (!confirm(`Unlink ${channel.name} from YouTube? Its films stay on the shelf.`)) return;
      await api(`/api/channels/${encodeURIComponent(id)}/disconnect`, { method: 'POST' });
      networkFlash(`${channel.name} unlinked.`);
    } else if (act === 'make') {
      const out = await api(`/api/channels/${encodeURIComponent(id)}/generate`, { method: 'POST', body: {} });
      const plan = out.plan || {};
      networkFlash(`${channel.name} started a ${plan.format || 'short'} — ${plan.rationale || 'on the bench now'}.`);
    } else if (act === 'toggle') {
      const path = channel.enabled ? 'pause' : 'resume';
      await api(`/api/channels/${encodeURIComponent(id)}/${path}`, { method: 'POST' });
      networkFlash(`${channel.name} ${path === 'pause' ? 'paused' : 'back on its airtimes'}.`);
    } else if (act === 'edit') {
      openChannelModal(channel, null);
      return;
    } else if (act === 'delete') {
      if (!confirm(`Remove ${channel.name} from the network? Its films stay on the shelf, unassigned.`)) return;
      await api(`/api/channels/${encodeURIComponent(id)}`, { method: 'DELETE' });
      networkFlash(`${channel.name} left the network.`);
    }
    await loadNetwork();
  } catch (exc) {
    networkFlash(exc.message, 'warn');
    if (act === 'connect' && /OAuth client|client_secret/i.test(exc.message)) {
      pendingSecretChannel = id;
      $('#secret-file').click();
    }
  }
}

/* ---------- channel editor ---------- */

let pendingSecretChannel = null;

function openChannelModal(channel, template) {
  const base = channel || template || {
    name: '', tagline: '', niches: [], styles: ['aurora'], formats: ['short'],
    times: ['12:00'], max_per_day: 1, tone: '', audience: '', cta: '',
  };
  NETWORK.editing = { id: channel ? channel.id : null, template };
  const niches = (NETWORK.options.niches || []).map((n) => `
    <label class="check"><input type="checkbox" name="cf-niche" value="${esc(n.id)}"
      ${(base.niches || []).includes(n.id) ? 'checked' : ''} />${esc(n.label)}</label>`).join('');
  const styles = (NETWORK.options.styles || []).map((s) => `
    <label class="check"><input type="checkbox" name="cf-style" value="${esc(s.id)}"
      ${(base.styles || []).includes(s.id) ? 'checked' : ''} />${esc(s.label)}</label>`).join('');
  const formats = ['short', 'long'].map((f) => `
    <label class="check"><input type="checkbox" name="cf-format" value="${f}"
      ${(base.formats || ['short']).includes(f) ? 'checked' : ''} />${f === 'short' ? 'Shorts' : 'Long form'}</label>`).join('');
  const privacy = (base.privacy || 'private').toLowerCase();
  const privacyOptions = [
    ['private', 'Private — review before anyone sees'],
    ['unlisted', 'Unlisted — link only'],
    ['public', 'Public — straight to the world'],
  ].map(([value, label]) => `
    <option value="${value}" ${privacy === value ? 'selected' : ''}>${label}</option>`).join('');
  const approval = (base.approval || 'auto').toLowerCase();
  const approvalOptions = [
    ['auto', 'Auto-publish — the studio uploads on its own'],
    ['review', 'Review shelf — a human approves each film'],
  ].map(([value, label]) => `
    <option value="${value}" ${approval === value ? 'selected' : ''}>${label}</option>`).join('');

  const modal = $('#channel-modal');
  modal.innerHTML = `
    <h2>${channel ? 'Edit ' + esc(channel.name) : 'A new voice'}</h2>
    <p class="modal-note">${channel ? 'This changes how the machine writes, paints and schedules this voice.' : "Give the machine a distinct obsession. It will never borrow another channel's niche or register."}</p>
    <div class="field-grid">
      <div class="field"><label for="cf-name">Name</label>
        <input id="cf-name" type="text" value="${esc(base.name || '')}" placeholder="The Quiet Machine" /></div>
      <div class="field"><label for="cf-tagline">Tagline</label>
        <input id="cf-tagline" type="text" value="${esc(base.tagline || '')}" placeholder="small machines, large questions" /></div>
      <div class="field wide"><label>Niches</label><div class="check-row">${niches}</div></div>
      <div class="field wide"><label>Art direction</label><div class="check-row">${styles}</div></div>
      <div class="field wide"><label>Formats</label><div class="check-row">${formats}</div></div>
      <div class="field"><label for="cf-times">Airtimes (HH:MM, comma list)</label>
        <input id="cf-times" type="text" value="${esc((base.times || []).join(', '))}" placeholder="09:30, 19:30" /></div>
      <div class="field"><label for="cf-max">Films per day</label>
        <input id="cf-max" type="number" min="1" max="8" value="${esc(base.max_per_day || 1)}" /></div>
      <div class="field"><label for="cf-privacy">Visibility on upload</label>
        <select id="cf-privacy">${privacyOptions}</select></div>
      <div class="field"><label for="cf-approval">Who signs off</label>
        <select id="cf-approval">${approvalOptions}</select></div>
      <div class="field wide"><label for="cf-tone">Voice &amp; tone</label>
        <textarea id="cf-tone" rows="2" placeholder="cinematic, intimate, curious">${esc(base.tone || '')}</textarea></div>
      <div class="field wide"><label for="cf-audience">Who it is for</label>
        <textarea id="cf-audience" rows="2" placeholder="curious night owls">${esc(base.audience || '')}</textarea></div>
      <div class="field wide"><label for="cf-cta">Closing call to action</label>
        <input id="cf-cta" type="text" value="${esc(base.cta || '')}" placeholder="Subscribe for one strange idea at a time." /></div>
    </div>
    <div class="modal-actions">
      <button class="btn" data-cm="cancel">Cancel</button>
      <button class="btn primary" data-cm="save">${channel ? 'Save the channel' : 'Add to the network'}</button>
    </div>`;
  modal.hidden = false;
  $('#channel-veil').hidden = false;

  modal.querySelectorAll('[data-cm]').forEach((el) => {
    el.addEventListener('click', () => {
      if (el.dataset.cm === 'cancel') closeChannelModal();
      else saveChannelModal();
    });
  });
}

function closeChannelModal() {
  NETWORK.editing = null;
  $('#channel-modal').hidden = true;
  $('#channel-veil').hidden = true;
}

function pickedCheckboxes(name) {
  return [...document.querySelectorAll(`input[name="${name}"]:checked`)].map((i) => i.value);
}

async function saveChannelModal() {
  const editing = NETWORK.editing;
  if (!editing) return;
  const body = {
    name: $('#cf-name').value.trim(),
    tagline: $('#cf-tagline').value.trim(),
    niches: pickedCheckboxes('cf-niche'),
    styles: pickedCheckboxes('cf-style'),
    formats: pickedCheckboxes('cf-format'),
    times: $('#cf-times').value.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean),
    max_per_day: Number($('#cf-max').value || 1),
    privacy: $('#cf-privacy').value,
    approval: $('#cf-approval').value,
    tone: $('#cf-tone').value.trim(),
    audience: $('#cf-audience').value.trim(),
    cta: $('#cf-cta').value.trim(),
  };
  if (!body.name) { networkFlash('A voice needs a name.', 'warn'); return; }
  if (!body.niches.length) { networkFlash('Choose at least one niche.', 'warn'); return; }
  if (!body.styles.length) { networkFlash('Choose at least one art direction.', 'warn'); return; }
  if (!body.times.length) { networkFlash('Give it an airtime, e.g. 12:30.', 'warn'); return; }
  if (!editing.id && editing.template) {
    const t = editing.template;
    body.kicker = t.kicker || body.name.toUpperCase();
    body.persona = t.persona || {};
    body.palette = t.palette || '';
    if (!body.tagline) body.tagline = t.tagline || '';
    if (!body.tone) body.tone = t.tone || '';
    if (!body.audience) body.audience = t.audience || '';
    if (!body.cta) body.cta = t.cta || '';
  }
  try {
    if (editing.id) {
      await api(`/api/channels/${encodeURIComponent(editing.id)}`, { method: 'PATCH', body });
    } else {
      await api('/api/channels', { method: 'POST', body });
    }
    closeChannelModal();
    networkFlash(`${body.name} is on the network.`);
    await loadNetwork();
  } catch (exc) {
    networkFlash(exc.message, 'warn');
  }
}

/* ---------- the radar ---------- */

let radarFlashTimer = null;

function radarFlash(message, level = 'ok') {
  const box = $('#radar-flash');
  if (!box) return;
  box.hidden = false;
  box.className = `network-flash ${level === 'warn' ? 'warn' : ''}`;
  box.textContent = message;
  clearTimeout(radarFlashTimer);
  radarFlashTimer = setTimeout(() => { box.hidden = true; }, 8000);
}

function radarChannelId() {
  return $('#radar-channel').value || RADAR.channelId || '';
}

function radarFormat() {
  return $('#radar-format').value || 'short';
}

async function ensureRadarChannels() {
  if (RADAR.channels.length) return;
  const data = await api('/api/channels');
  RADAR.channels = data.items || [];
  const select = $('#radar-channel');
  select.innerHTML = RADAR.channels.map((c) =>
    `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('');
  if (!select.value && RADAR.channels.length) select.value = RADAR.channels[0].id;
  RADAR.channelId = select.value;
  const format = $('#radar-format');
  const channel = RADAR.channels.find((c) => c.id === RADAR.channelId);
  if (channel && (channel.formats || []).includes('long') && !(channel.formats || []).includes('short')) {
    format.value = 'long';
  }
}

async function loadRadar() {
  if (RADAR.loading) return RADAR.loading;
  RADAR.loading = (async () => {
    await ensureRadarChannels();
    const channelId = radarChannelId();
    const url = `/api/trends?channel_id=${encodeURIComponent(channelId)}&live=${RADAR.live ? 1 : 0}&limit=18`;
    const [data] = await Promise.all([
      api(url),
      loadCalendar().catch(() => {}),
      loadBrain().catch(() => {}),
    ]);
    RADAR.data = data;
    RADAR.items = data.items || [];
    renderRadar(data);
    if (RADAR.ideas.length) renderIdeas();
    else drawIdeas(null, { quiet: true });
  })();
  try {
    return await RADAR.loading;
  } finally {
    RADAR.loading = null;
  }
}

function renderRadar(data) {
  const channel = RADAR.channels.find((c) => c.id === radarChannelId());
  const live = data.live
    ? `${data.live_count} live signal${data.live_count === 1 ? '' : 's'} from Google Trends`
    : 'curated shelf — press “Pull live signals” for today’s searches';
  $('#radar-lede').textContent = channel
    ? `Opportunities scored for ${channel.name}: interest, momentum, competition and fit. The machine reads this the way an editor reads a room.`
    : 'Opportunities scored on interest, momentum, competition and fit.';

  $('#radar-meta').innerHTML = `
    <span class="radar-stat"><strong>${esc(data.as_of)}</strong> as of</span>
    <span class="radar-stat"><strong>${esc(data.catalog_count || 0)}</strong> on the shelf</span>
    <span class="radar-stat"><strong>${esc(data.live_count || 0)}</strong> live</span>
    <span class="radar-stat"><strong>${esc(data.top_niche_label || '—')}</strong> leading</span>
    <span class="radar-note">${esc(live)}</span>`;

  const grid = $('#trend-grid');
  if (!RADAR.items.length) {
    grid.innerHTML = '<div class="empty"><div class="empty-mark">✳</div><p>The radar is quiet. Refresh it, or pull live signals.</p></div>';
    return;
  }
  grid.innerHTML = RADAR.items.map((t, index) => trendCard(t, index)).join('');
}

function trendCard(t, index) {
  const score = Math.round(Number(t.opportunity) || 0);
  const grade = String(t.grade || 'steady');
  const direction = String(t.direction || 'flat');
  const tags = (t.tags || []).slice(0, 3).map((tag) => `<span class="pill">${esc(tag)}</span>`).join('');
  const source = t.live ? '<span class="pill live">live search</span>' : `<span class="pill">${esc(t.window || 'evergreen')}</span>`;
  const niche = t.niche_label ? `<span class="trend-niche">${esc(t.niche_label)}</span>` : '<span class="trend-niche">live signal</span>';
  return `
    <article class="trend-card grade-${esc(grade)}" data-trend-index="${index}">
      <div class="trend-top">
        <div class="trend-score"><span class="num">${score}</span><span class="lbl">opportunity</span></div>
        <div class="trend-badges">
          ${niche}
          <span class="trend-grade">${esc(grade)}</span>
          <span class="trend-dir ${esc(direction)}">${direction === 'up' ? '▲' : direction === 'down' ? '▼' : '■'} ${esc(direction)}</span>
        </div>
      </div>
      <h3 class="trend-topic">${esc(t.topic)}</h3>
      <p class="trend-angle">${esc(t.angle || '')}</p>
      ${t.why ? `<p class="trend-why">${esc(t.why)}</p>` : ''}
      <div class="trend-pills">${source}${tags}</div>
      <div class="trend-metrics">
        <span>interest <i>${Math.round(t.interest || 0)}</i></span>
        <span>momentum <i>${Math.round(t.momentum || 0)}</i></span>
        <span>competition <i>${Math.round(t.competition || 0)}</i></span>
        <span>fit <i>${Math.round((t.fit || 0) * 100)}</i></span>
      </div>
      <div class="trend-actions">
        <button class="btn small primary" data-trend-act="commission" data-index="${index}">Commission this</button>
        <button class="btn small" data-trend-act="ideas" data-index="${index}">Draw ideas from it</button>
      </div>
    </article>`;
}

function trendGuidance(t) {
  const bits = [`Current signal: ${t.topic}.`];
  if (t.angle) bits.push(`Angle: ${t.angle}.`);
  if (t.why) bits.push(`Why it is surfacing: ${t.why}`);
  bits.push('Use the signal as raw material, not a headline. Keep the film standalone, factual and original; a viewer should never feel they have seen this exact video before.');
  return bits.join(' ');
}

async function commissionTrend(index) {
  const t = RADAR.items[index];
  if (!t) return;
  try {
    const channelId = radarChannelId();
    await api('/api/ideas/queue', {
      method: 'POST',
      body: {
        channel_id: channelId,
        title: t.topic,
        subject: t.topic,
        niche: t.niche || '',
        format: radarFormat(),
        guidance: trendGuidance(t),
      },
    });
    radarFlash(`Commissioned “${t.topic}”. The writer is on it — novelty and the quality gate still decide whether it ships.`);
    setTimeout(() => loadRadar().catch(() => {}), 2500);
  } catch (exc) {
    radarFlash(exc.message, 'warn');
  }
}

async function drawIdeas(trend, opts = {}) {
  try {
    RADAR.trend = trend || null;
    $('#idea-seed').innerHTML = trend
      ? `seeded from “${esc(trend.topic)}” <button class="link" id="idea-clear">clear</button>`
      : '';
    if (!opts.quiet) $('#idea-grid').innerHTML = '<div class="idea-loading">The Muse is sketching four directions…</div>';
    const out = await api('/api/ideas', {
      method: 'POST',
      body: {
        channel_id: radarChannelId(),
        format: radarFormat(),
        count: 4,
        niche: trend && trend.niche ? trend.niche : undefined,
        trend: trend
          ? { topic: trend.topic, angle: trend.angle, why: trend.why, opportunity: trend.opportunity }
          : undefined,
      },
    });
    RADAR.ideas = out.items || [];
    renderIdeas();
  } catch (exc) {
    $('#idea-grid').innerHTML = `<div class="idea-loading">The Muse could not draw: ${esc(exc.message)}</div>`;
  }
}

function renderIdeas() {
  const grid = $('#idea-grid');
  if (!RADAR.ideas.length) {
    grid.innerHTML = '<div class="idea-loading">Press “Draw four ideas” and the Muse will pitch the next films.</div>';
    return;
  }
  grid.innerHTML = RADAR.ideas.map((idea, index) => `
    <article class="idea-card">
      <div class="idea-meta">
        <span class="pill">${esc(idea.niche_label || idea.niche)}</span>
        <span class="pill">${esc(idea.style)}</span>
        ${idea.trend ? '<span class="pill live">from the radar</span>' : ''}
      </div>
      <h3 class="idea-title">${esc(idea.title)}</h3>
      <p class="idea-hook">${esc(idea.hook || '')}</p>
      <p class="idea-angle">${esc(idea.angle || '')}${idea.question ? ` · ${esc(idea.question)}` : ''}</p>
      <div class="idea-actions">
        <button class="btn small primary" data-idea-act="queue" data-index="${index}">Make this film</button>
        <button class="btn small" data-idea-act="tweak" data-index="${index}">Another angle</button>
      </div>
    </article>`).join('');
}

async function queueIdea(index) {
  const idea = RADAR.ideas[index];
  if (!idea) return;
  try {
    await api('/api/ideas/queue', {
      method: 'POST',
      body: {
        channel_id: idea.channel_id || radarChannelId(),
        title: idea.title,
        subject: idea.subject,
        niche: idea.niche,
        style: idea.style,
        palette: idea.palette,
        format: idea.format,
        guidance: idea.guidance,
      },
    });
    radarFlash(`“${idea.title}” is on the bench. The writer has the brief.`);
    setTimeout(() => loadRadar().catch(() => {}), 2500);
  } catch (exc) {
    radarFlash(exc.message, 'warn');
  }
}

async function loadCalendar() {
  const box = $('#calendar');
  if (!box) return;
  const data = await api(`/api/calendar?days=7&channel_id=${encodeURIComponent(radarChannelId())}`);
  const days = data.days || [];
  if (!days.length) {
    box.innerHTML = '<div class="idea-loading">No airtimes yet. Give a voice an airtime on The Network page.</div>';
    return;
  }
  box.innerHTML = days.map((day) => `
    <div class="cal-day ${day.is_today ? 'is-today' : ''}">
      <div class="cal-head"><span>${esc(day.weekday)}</span><strong>${esc(day.label)}</strong></div>
      <div class="cal-slot-list">
        ${(day.slots || []).length
          ? day.slots.map((slot) => `
              <div class="cal-slot ${esc(slot.state)}">
                <span class="cal-time">${esc(slot.time)}</span>
                <span class="cal-title">${esc(slot.title || slot.note)}</span>
              </div>`).join('')
          : '<div class="cal-slot empty">no airtime</div>'}
      </div>
    </div>`).join('');
}

async function loadBrain() {
  const box = $('#brain');
  if (!box) return;
  const data = await api(`/api/brain?channel_id=${encodeURIComponent(radarChannelId())}`);
  const channels = data.channels || [];
  if (!channels.length) {
    box.innerHTML = '<div class="idea-loading">The brain has no voices to read yet.</div>';
    return;
  }
  box.innerHTML = channels.map((c) => `
    <div class="brain-card">
      <div class="brain-head"><strong>${esc(c.name)}</strong><span>${esc(c.samples)} published film${c.samples === 1 ? '' : 's'} read</span></div>
      <p class="brain-insight">${esc(c.insight || 'No lesson yet — the first cycle is exploration.')}</p>
      <div class="brain-cells">
        <div><span class="lbl">best niche</span><strong>${esc(c.best_niche_label || '—')}</strong></div>
        <div><span class="lbl">best register</span><strong>${esc(c.best_style || '—')}</strong></div>
        <div><span class="lbl">best hour</span><strong>${esc(c.best_hour || '—')}</strong></div>
        <div><span class="lbl">next film</span><strong>${esc(c.next_film || '—')}</strong></div>
      </div>
    </div>`).join('');
}

/* ---------- oauth client upload ---------- */

async function installClientSecret(file) {
  if (!file) return;
  try {
    const text = await file.text();
    JSON.parse(text);
    await fetch(`/api/youtube/client-secret?channel_id=${encodeURIComponent(pendingSecretChannel || '')}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: text,
    }).then(async (res) => {
      if (!res.ok) {
        let detail = res.statusText;
        try { detail = (await res.json()).detail || detail; } catch (_) {}
        throw new Error(detail);
      }
      return res.json();
    });
    networkFlash('Google key installed. Press Connect with Google on that voice.');
    await loadNetwork();
  } catch (exc) {
    networkFlash(`That key did not take: ${exc.message}`, 'warn');
  }
  pendingSecretChannel = null;
  $('#secret-file').value = '';
}



let refreshTimer = null;
let refreshBusy = false;
let refreshQueued = false;

async function refresh() {
  if (refreshBusy) { refreshQueued = true; return; }
  refreshBusy = true;
  try {
    const status = await api('/api/status');
    renderChips(status);
    renderStats(status.stats);
    renderYoutubePanel(status);
    renderSchedulePanel(status);
    if (!Object.keys(state.dirty).length) {
      renderSettings(await api('/api/settings'));
    }
    await loadVideos();
    if (state.view === 'network') loadNetwork().catch(() => {});
    if (state.view === 'radar') loadRadar().catch(() => {});
  } catch (_) {
    /* desk is restarting; the stream will bring it back */
  }
  refreshBusy = false;
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(refresh, 30000);
  if (refreshQueued) {
    refreshQueued = false;
    setTimeout(refresh, 1500);
  }
}

/* ---------- wire up ---------- */

document.querySelectorAll('.tab').forEach((tab) => {
  tab.addEventListener('click', () => switchView(tab.dataset.view));
});

document.querySelectorAll('.filter').forEach((f) => {
  f.addEventListener('click', () => {
    document.querySelectorAll('.filter').forEach((x) => x.classList.remove('is-active'));
    f.classList.add('is-active');
    state.filter = f.dataset.filter;
    loadVideos();
  });
});

document.querySelectorAll('.hint').forEach((h) => {
  h.addEventListener('click', () => {
    $('#command-input').value = h.dataset.cmd;
    runCommand(h.dataset.cmd);
  });
});

$('#command-form').addEventListener('submit', (ev) => {
  ev.preventDefault();
  const input = $('#command-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  runCommand(text);
});

$('#channel-grid').addEventListener('click', (ev) => {
  const btn = ev.target.closest('[data-nc]');
  if (btn) {
    ev.stopPropagation();
    channelAction(btn.dataset.nc, btn.dataset.id);
    return;
  }
  const film = ev.target.closest('[data-video]');
  if (film) openDrawer(film.dataset.video);
});

$('#autopilot-strip').addEventListener('click', async (ev) => {
  const btn = ev.target.closest('[data-auto]');
  if (!btn) return;
  try {
    if (btn.dataset.auto === 'think') {
      await api('/api/autopilot/think', { method: 'POST', body: {} });
      networkFlash('The studio is reading the analytics and choosing the next films.');
      setTimeout(() => loadNetwork().catch(() => {}), 4000);
    } else {
      const currently = Boolean(NETWORK.data && NETWORK.data.autopilot && NETWORK.data.autopilot.enabled);
      await api('/api/autopilot/toggle', { method: 'POST', body: { enabled: !currently } });
      networkFlash(`Autopilot ${currently ? 'stood down' : 'engaged'}.`);
      await loadNetwork();
    }
  } catch (exc) {
    networkFlash(exc.message, 'warn');
  }
});

$('#template-row').addEventListener('click', (ev) => {
  const btn = ev.target.closest('[data-tpl]');
  if (!btn || btn.disabled) return;
  if (btn.dataset.tpl === 'new') { openChannelModal(null, null); return; }
  const template = NETWORK.templates.find((t) => t.id === btn.dataset.tpl);
  if (template) openChannelModal(null, template);
});

$('#journal-refresh').addEventListener('click', async () => {
  try {
    await api('/api/autopilot/think', { method: 'POST', body: {} });
    networkFlash('The studio is reading the analytics and choosing the next films.');
    setTimeout(() => loadNetwork().catch(() => {}), 4000);
  } catch (exc) {
    networkFlash(exc.message, 'warn');
  }
});

$('#channel-veil').addEventListener('click', closeChannelModal);
$('#secret-file').addEventListener('change', (ev) => installClientSecret(ev.target.files[0]));

/* ---------- radar wiring ---------- */

$('#radar-channel') && $('#radar-channel').addEventListener('change', () => {
  RADAR.channelId = $('#radar-channel').value;
  RADAR.ideas = [];
  RADAR.trend = null;
  loadRadar().catch(() => {});
});

$('#radar-refresh') && $('#radar-refresh').addEventListener('click', () => {
  loadRadar().catch((exc) => radarFlash(exc.message, 'warn'));
});

$('#radar-live') && $('#radar-live').addEventListener('click', async () => {
  RADAR.live = !RADAR.live;
  $('#radar-live').textContent = RADAR.live ? 'Live signals on' : 'Pull live signals';
  await loadRadar().catch((exc) => radarFlash(exc.message, 'warn'));
});

$('#idea-generate') && $('#idea-generate').addEventListener('click', () => drawIdeas(RADAR.trend));

$('#idea-seed') && $('#idea-seed').addEventListener('click', (ev) => {
  if (ev.target.closest('#idea-clear')) {
    RADAR.trend = null;
    $('#idea-seed').innerHTML = '';
    drawIdeas(null);
  }
});

$('#trend-grid') && $('#trend-grid').addEventListener('click', (ev) => {
  const btn = ev.target.closest('[data-trend-act]');
  if (!btn) return;
  const index = Number(btn.dataset.index);
  if (btn.dataset.trendAct === 'commission') commissionTrend(index);
  else {
    const trend = RADAR.items[index];
    if (trend) {
      drawIdeas(trend);
      $('#idea-grid').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }
});

$('#idea-grid') && $('#idea-grid').addEventListener('click', (ev) => {
  const btn = ev.target.closest('[data-idea-act]');
  if (!btn) return;
  const index = Number(btn.dataset.index);
  if (btn.dataset.ideaAct === 'queue') queueIdea(index);
  else drawIdeas(RADAR.trend);
});

$('#brain-think') && $('#brain-think').addEventListener('click', async () => {
  try {
    await api('/api/autopilot/think', { method: 'POST', body: {} });
    radarFlash('The brain is reading the analytics and writing the next lesson.');
    setTimeout(() => { loadBrain().catch(() => {}); loadRadar().catch(() => {}); }, 4000);
  } catch (exc) {
    radarFlash(exc.message, 'warn');
  }
});

$('#drawer-veil').addEventListener('click', closeDrawer);
document.addEventListener('keydown', (ev) => {
  if (ev.key !== 'Escape') return;
  closeDrawer();
  if (!$('#channel-modal').hidden) closeChannelModal();
});

/* land on the right view after a Google redirect */
const bootParams = new URLSearchParams(location.search);
const youtubeResult = bootParams.get('youtube');
if (youtubeResult) {
  state.flash = youtubeResult === 'connected'
    ? {
        level: 'ok',
        message: `Google sign-in complete${bootParams.get('channel') ? ' for ' + bootParams.get('channel') : ''}. The schedule is live — the first film goes up at the next airtime.`,
      }
    : {
        level: 'warn',
        message: `Sign-in did not finish (${bootParams.get('reason') || 'unknown'}). Press Connect with Google on the voice you want to link.`,
      };
  history.replaceState({}, '', location.pathname);
  switchView('network');
} else if (location.hash === '#network') {
  switchView('network');
}

loadLog().then(() => {
  connectStream();
  refresh();
  if (state.view === 'network') loadNetwork().catch(() => {});
});

/* The shell can live offline; the studio itself always talks to the server. */
if ('serviceWorker' in navigator && (location.protocol === 'https:' || ['localhost', '127.0.0.1'].includes(location.hostname))) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}
