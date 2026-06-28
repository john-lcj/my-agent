/* ══════════════════════════════════════════════════════════════════
   AUTH — 用户登录态管理
   token 存 localStorage('captainAuthToken')
   所有 /api/* 请求自动带 Authorization: Bearer <token>
   ══════════════════════════════════════════════════════════════════ */
const _AUTH_KEY = 'captainAuthToken';
function getAuthToken()     { try { return localStorage.getItem(_AUTH_KEY) || ''; } catch { return ''; } }
function setAuthToken(t)    { try { t ? localStorage.setItem(_AUTH_KEY, t) : localStorage.removeItem(_AUTH_KEY); } catch {} }
function clearAuthToken()   { setAuthToken(''); }

/* 兼容旧 X-Agent-Token（设备级访问令牌）*/
function getAccessToken() { try { return localStorage.getItem('agentApiToken') || ''; } catch { return ''; } }
function setAccessToken(t) { try { t ? localStorage.setItem('agentApiToken', t) : localStorage.removeItem('agentApiToken'); } catch {} }

/* 所有 /api/* 请求自动带鉴权头 */
(function patchFetchWithToken() {
  const _fetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    try {
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      if (url.indexOf('/api/') !== -1) {
        init = init || {};
        const h = new Headers(init.headers || {});
        const userTok = getAuthToken();
        const devTok  = getAccessToken();
        if (userTok && !h.has('Authorization')) h.set('Authorization', 'Bearer ' + userTok);
        if (devTok  && !h.has('X-Agent-Token'))  h.set('X-Agent-Token', devTok);
        init.headers = h;
      }
    } catch (e) {}
    return _fetch(input, init);
  };
})();

/* ── Auth UI ──────────────────────────────────────────────────────── */
let _authUser = null;

function _authOverlayVisible(v) {
  const el = document.getElementById('auth-overlay');
  if (!el) return;
  el.style.display = v ? 'flex' : 'none';
}

function switchAuthTab(tab) {
  document.getElementById('auth-form-login').style.display    = tab === 'login'    ? '' : 'none';
  document.getElementById('auth-form-register').style.display = tab === 'register' ? '' : 'none';
  document.getElementById('auth-tab-login').classList.toggle('active', tab === 'login');
  document.getElementById('auth-tab-reg').classList.toggle('active',   tab === 'register');
}

async function doLogin() {
  const email = (document.getElementById('auth-login-email')?.value || '').trim();
  const pwd   = document.getElementById('auth-login-pwd')?.value || '';
  const errEl = document.getElementById('auth-login-err');
  errEl.style.display = 'none';
  try {
    const r = await fetch('/api/auth/login', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({email, password: pwd})});
    const d = await r.json();
    if (!d.ok) { errEl.textContent = d.error || '登录失败'; errEl.style.display=''; return; }
    setAuthToken(d.token);
    _authUser = d.user;
    _authOverlayVisible(false);
    _updateUserBadge(d.user);
    _reconnectWs();
    if (typeof loadSessions === 'function') loadSessions();
  } catch(e) { errEl.textContent = '网络错误，请重试'; errEl.style.display=''; }
}

async function doRegister() {
  const email = (document.getElementById('auth-reg-email')?.value || '').trim();
  const pwd   = document.getElementById('auth-reg-pwd')?.value || '';
  const errEl = document.getElementById('auth-reg-err');
  errEl.style.display = 'none';
  try {
    const r = await fetch('/api/auth/register', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({email, password: pwd})});
    const d = await r.json();
    if (!d.ok) { errEl.textContent = d.error || '注册失败'; errEl.style.display=''; return; }
    setAuthToken(d.token);
    _authUser = d.user;
    _authOverlayVisible(false);
    _updateUserBadge(d.user);
    _reconnectWs();
  } catch(e) { errEl.textContent = '网络错误，请重试'; errEl.style.display=''; }
}

function doLogout() {
  clearAuthToken();
  _authUser = null;
  closeUserMenu();
  const badge = document.getElementById('user-badge');
  if (badge) badge.style.display = 'none';
  _authOverlayVisible(true);
}

async function doRedeem() {
  const code = (document.getElementById('redeem-code-input')?.value || '').trim();
  if (!code) return;
  try {
    const r = await fetch('/api/auth/redeem', {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify({code})});
    const d = await r.json();
    if (!d.ok) { if (typeof toast==='function') toast('❌ ' + (d.error||'兑换失败')); return; }
    setAuthToken(d.token);
    _authUser = d.user;
    _updateUserBadge(d.user);
    closeUserMenu();
    if (typeof toast==='function') toast('🎉 已升级到 ' + d.user.plan.toUpperCase() + '！');
  } catch { if (typeof toast==='function') toast('网络错误'); }
}

function openUserMenu() {
  const menu = document.getElementById('user-menu');
  if (!menu) return;
  const info = document.getElementById('user-menu-info');
  if (info && _authUser) {
    info.innerHTML = `<div>${_authUser.email}</div>
      <div style="margin-top:2px">套餐: <b>${(_authUser.plan||'free').toUpperCase()}</b></div>`;
  }
  menu.style.display = menu.style.display === 'none' ? '' : 'none';
}
function closeUserMenu() {
  const menu = document.getElementById('user-menu');
  if (menu) menu.style.display = 'none';
}
document.addEventListener('click', e => {
  if (!e.target.closest('#user-menu') && !e.target.closest('#user-badge')) closeUserMenu();
});

function _updateUserBadge(user) {
  if (!user) return;
  const badge   = document.getElementById('user-badge');
  const planBdg = document.getElementById('user-plan-badge');
  const emailEl = document.getElementById('user-email-short');
  if (badge)   badge.style.display = 'flex';
  if (planBdg) { planBdg.textContent = (user.plan||'free').toUpperCase();
                 planBdg.style.background = user.plan==='pro' ? '#f0c040' : 'var(--accent)'; }
  if (emailEl) emailEl.textContent = (user.email||'').split('@')[0];
  _refreshQuotaBar();
}

async function _refreshQuotaBar() {
  try {
    const d = await (await fetch('/api/auth/me')).json();
    if (!d.ok) return;
    const fill = document.getElementById('user-quota-fill');
    if (fill) fill.style.width = (d.usage?.pct || 0) + '%';
    _authUser = d.user;
  } catch {}
}

/* 启动时检查登录态 */
async function _authInit() {
  const tok = getAuthToken();
  if (!tok) {
    /* 检查服务器是否需要登录（AUTH_SECRET 已设置）*/
    try {
      const r = await fetch('/api/auth/me');
      if (r.status === 401) { _authOverlayVisible(true); return; }
      /* 单机模式：/api/auth/me 200 但没 token → 无需登录 */
    } catch { /* 网络错误，放行继续 */ }
    return;
  }
  try {
    const r = await fetch('/api/auth/me');
    const d = await r.json();
    if (!d.ok) { clearAuthToken(); _authOverlayVisible(true); return; }
    _authUser = d.user;
    _updateUserBadge(d.user);
  } catch {}
}

/* WS 重连（携带新 token）*/
function _reconnectWs() {
  if (typeof reconnectWebSocket === 'function') reconnectWebSocket();
}

document.addEventListener('DOMContentLoaded', () => {
  _authInit();
  setInterval(_refreshQuotaBar, 60000);
});

/* ══ Skill 中文标签(id → 中文描述,用于调用时的友好提示)════════════ */
const SKILL_LABELS = {};
async function loadSkillLabels() {
  try {
    const res = await fetch('/api/skills');
    const data = await res.json();
    (data.skills || []).forEach(s => {
      if (s && s.name) SKILL_LABELS[s.name] = s.description || s.name;
    });
  } catch { /* 离线:用 id 兜底 */ }
}
function skillLabel(skillId) {
  const desc = SKILL_LABELS[skillId];
  if (!desc) return skillId;
  return desc.length > 22 ? desc.slice(0, 20) + '…' : desc;
}

/* ══ 全局状态 ════════════════════════════════════════════════════ */
let ws = null;
let currentView = 'chat';
let msgCount = 0;
let thinkingEl = null;
let streamingMsgEl = null;
let streamingText = '';
let streamRenderTimer = null;
/** 简洁模式:Chat 默认隐藏工具轨迹;开「工具轨迹」后显示 call/result */
let conciseChat = true;
let _activeTraceGroup = null;
const _pendingAttachments = [];

function isToolTraceEnabled() {
  try { return localStorage.getItem('captain-show-tool-trace') === '1'; } catch { return false; }
}
function syncConciseChat() {
  conciseChat = !isToolTraceEnabled();
  const btn = document.getElementById('btn-tool-trace');
  if (btn) btn.classList.toggle('is-on', isToolTraceEnabled());
}
function toggleToolTrace(e) {
  e?.stopPropagation();
  try {
    localStorage.setItem('captain-show-tool-trace', isToolTraceEnabled() ? '0' : '1');
  } catch {}
  syncConciseChat();
}
function resetTraceGroup() { _activeTraceGroup = null; }
function ensureTraceGroup() {
  const area = document.getElementById('chat-messages');
  if (!area) return null;
  if (_activeTraceGroup && _activeTraceGroup.isConnected) return _activeTraceGroup;
  const g = document.createElement('div');
  g.className = 'tool-trace-group';
  area.appendChild(g);
  _activeTraceGroup = g;
  area.scrollTop = area.scrollHeight;
  return g;
}
function parseSearchHits(text) {
  const hits = [];
  const lines = String(text || '').split('\n');
  let cur = null;
  for (const line of lines) {
    const head = line.match(/^(\d+)\.\s+(.+)/);
    if (head) {
      if (cur) hits.push(cur);
      cur = { n: head[1], title: head[2].trim(), url: '', snippet: '' };
      continue;
    }
    if (!cur) continue;
    const t = line.trim();
    if (/^https?:\/\//i.test(t)) { cur.url = t; continue; }
    if (t && !/^\(搜索/.test(t)) {
      cur.snippet = cur.snippet ? (cur.snippet + ' ' + t) : t;
    }
  }
  if (cur) hits.push(cur);
  return hits;
}
function renderSearchSources(hits) {
  const box = document.createElement('div');
  box.className = 'search-sources';
  hits.forEach(h => {
    const a = document.createElement(h.url ? 'a' : 'div');
    a.className = 'search-source';
    if (h.url) { a.href = h.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; }
    a.innerHTML = `<div class="search-source-n">[${escHtml(h.n)}]</div>`
      + `<div class="search-source-t">${escHtml(h.title)}</div>`
      + (h.url ? `<div class="search-source-u">${escHtml(h.url)}</div>` : '')
      + (h.snippet ? `<div class="search-source-s">${escHtml(h.snippet)}</div>` : '');
    box.appendChild(a);
  });
  return box;
}
function appendToolTrace(kind, label, detail, extra) {
  if (!isToolTraceEnabled() || currentView !== 'chat') return;
  const g = ensureTraceGroup();
  if (!g) return;
  const d = document.createElement('details');
  d.className = 'tool-trace-item ' + (kind || 'call');
  d.open = kind === 'call' || kind === 'err';
  const sum = document.createElement('summary');
  sum.textContent = label;
  d.appendChild(sum);
  const body = document.createElement('div');
  body.className = 'tool-trace-body';
  if (extra && extra.searchHits && extra.searchHits.length) {
    body.appendChild(renderSearchSources(extra.searchHits));
    const pre = document.createElement('pre');
    pre.textContent = detail || '';
    if (pre.textContent) body.appendChild(pre);
  } else {
    const pre = document.createElement('pre');
    pre.textContent = detail || '';
    body.appendChild(pre);
  }
  d.appendChild(body);
  g.appendChild(d);
  const area = document.getElementById('chat-messages');
  if (area) area.scrollTop = area.scrollHeight;
}
function buildMsgKey(role, content, id, ts) {
  if (id != null && id !== '') return 'id:' + id;
  return role + ':' + (ts || '') + ':' + String(content || '').length;
}
async function saveFeedback(msgKey, rating) {
  if (!sessionId || !msgKey || ![0, 1, -1].includes(rating)) return;
  try {
    await fetch('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, msg_key: msgKey, rating }),
    });
  } catch {}
}
async function loadFeedbackState(msgKey, upBtn, downBtn) {
  if (!sessionId || !msgKey || !upBtn || !downBtn) return;
  try {
    const d = await (await fetch('/api/feedback?session_id=' + encodeURIComponent(sessionId)
      + '&msg_key=' + encodeURIComponent(msgKey))).json();
    if (d.rating === 1) upBtn.classList.add('is-up');
    if (d.rating === -1) downBtn.classList.add('is-down');
  } catch {}
}
let workMode = 'chat';
let taskRunning = false;
let activeTaskGen = 0;
let taskSessionId = '';
let _sessionInitExpected = '';
let _sessionInitResolve = null;
let lastUserPrompt = '';
let _lastCapCall = null;
let _wsSendQueue = null;
let _wsReconnectTimer = null;
let allSessions = [];
let historySearchQuery = '';
/* 工作台/项目状态:必须在 init(下方 applyModeChrome / refreshWorkbenchMeta)之前声明,
   否则 let 的暂时性死区(TDZ)会让初始化整体抛错。 */
let _coworkWorkspaceDir = '';
let _coworkFolderDir = '';
let _filesDir = '';
let _currentProject = '';
let _projectsCache = [];
let slashCommands = [];
let slashActiveIdx = 0;


function sessionStorageKey(mode) {
  return (mode || workMode) === 'coworker' ? 'agent-session-coworker' : 'agent-session-chat';
}

function genSessionId(mode) {
  const m = mode || workMode;
  const prefix = m === 'coworker' ? 's-cowork-' : 's-chat-';
  return prefix + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

function migrateLegacySession() {
  const legacy = localStorage.getItem('agent-session');
  if (!legacy || localStorage.getItem('agent-session-chat')) return;
  const id = legacy.startsWith('s-chat-') || legacy.startsWith('s-code-')
    ? legacy : (legacy.startsWith('s-') ? 's-chat-' + legacy.slice(2) : 's-chat-' + legacy);
  localStorage.setItem('agent-session-chat', id);
}

function loadSessionIdForMode(mode) {
  migrateLegacySession();
  const key = sessionStorageKey(mode);
  let id = localStorage.getItem(key);
  if (!id) {
    id = genSessionId(mode);
    localStorage.setItem(key, id);
  }
  return id;
}

function persistSessionId() {
  localStorage.setItem(sessionStorageKey(), sessionId);
}

function sessionWorkMode(id) {
  if (!id) return null;
  if (id.startsWith('s-cowork-')) return 'coworker';
  return 'chat';
}

function sessionBelongsToWorkMode(s) {
  if (!s || !s.id || s.id.startsWith('s-code-')) return false;
  if (s.kind === 'roundtable' || s.id.startsWith('rt-')) return false;
  if (workMode === 'coworker') return s.id.startsWith('s-cowork-') || s.kind === 'coworker';
  return !s.id.startsWith('s-cowork-') && s.kind !== 'coworker';
}

function sessionIcon(id, kind) {
  if (id && id.startsWith('s-cowork-')) return '📋 ';
  return '💬 ';
}

let sessionId = 's-chat-pending';

/* ══ WebSocket ═══════════════════════════════════════════════════ */
function setWsConnected(on) {
  const dot = document.getElementById('dot');
  if (dot) dot.classList.toggle('on', !!on);
  const wrap = document.getElementById('chat-status-bar');
  const label = document.getElementById('ctx-connecting-label');
  if (!on && wrap && label) {
    wrap.classList.add('is-connecting');
    label.hidden = false;
    label.textContent = t('connecting');
  }
}

function reconnectWebSocket() {
  if (ws) { try { ws.close(); } catch {} ws = null; }
  connect();
}

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  // 优先用用户 JWT，降级用设备级 token
  const _userTok = getAuthToken();
  const _devTok  = getAccessToken();
  const _tok = _userTok || _devTok;
  const _q = _tok ? `?token=${encodeURIComponent(_tok)}` : '';
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const sock = new WebSocket(`${proto}//${location.host}/ws${_q}`);
  ws = sock;
  setWsConnected(false);
  sock.onopen = () => {
    if (ws !== sock) return;
    setWsConnected(true);
    try { sock.send(JSON.stringify(wsInitPayload())); } catch {}
    if (_wsSendQueue) {
      const q = _wsSendQueue;
      setTimeout(() => {
        if (ws !== sock || sock.readyState !== WebSocket.OPEN) return;
        const inp = document.getElementById('chat-inp');
        if (inp && q) inp.value = q;
        _wsSendQueue = null;
        sendMsg();
      }, 120);
    }
  };
  sock.onclose = () => {
    if (ws !== sock) return;
    setWsConnected(false);
    clearTimeout(_wsReconnectTimer);
    _wsReconnectTimer = setTimeout(connect, 1500);
  };
  sock.onerror = () => { if (ws === sock) setWsConnected(false); };
  sock.onmessage = e => {
    try { handle(JSON.parse(e.data)); } catch (err) { console.error('ws message', err); }
  };
}

function wirePayload(ev) {
  if (ev.payload && typeof ev.payload === 'object' && Object.keys(ev.payload).length > 0) {
    return ev.payload;
  }
  const { type, trace_id, ts, payload, ...rest } = ev;
  return Object.keys(rest).length ? rest : ev;
}

function isBackgroundTaskView() {
  return taskRunning && taskSessionId && sessionId !== taskSessionId;
}

function bindTaskGen(p) {
  const g = p && p.task_gen;
  if (!g) return !isBackgroundTaskView();
  if (!activeTaskGen) activeTaskGen = g;
  return g === activeTaskGen;
}

function handle(ev) {
  const etype = ev.type;
  const isFlatEvent = etype && etype.startsWith('debate_');
  const p = isFlatEvent ? wirePayload(ev) : (ev.payload || {});

  // ── 历史恢复 ──
  if (etype === 'history') {
    if (p.session_id) sessionId = p.session_id;
    renderRestored(p.messages || []);
    if (_sessionInitResolve && p.session_id === _sessionInitExpected) {
      const done = _sessionInitResolve;
      _sessionInitResolve = null;
      done();
    }
    refreshSessions();
    syncChatTopbarTitle();
    return;
  }

  const chatScoped = !isFlatEvent && !['history', 'status_bar'].includes(etype);
  if (chatScoped && isBackgroundTaskView()) return;
  if (chatScoped && p.task_gen && !bindTaskGen(p)) return;

  // ── 聊天事件 ──
  if (etype === 'user_message') return;
  if (etype === 'assistant_token') {
    removeThinking();
    if (!streamingMsgEl) {
      const area = document.getElementById('chat-messages');
      const empty = document.getElementById('chat-empty');
      if (empty) empty.style.display = 'none';
      streamingText = '';
      streamingMsgEl = document.createElement('div');
      streamingMsgEl.className = 'msg msg-agent streaming';
      streamingMsgEl.id = 'streaming-msg';
      streamingMsgEl.innerHTML = '<div class="msg-head"><span class="msg-label msg-label-agent">Captain</span></div><div class="msg-body"></div>';
      area.appendChild(streamingMsgEl);
      if (typeof setTurnImageTarget === 'function') {
        setTurnImageTarget(streamingMsgEl.querySelector('.msg-body'));
      }
    }
    streamingText += p.token || '';
    const body = streamingMsgEl.querySelector('.msg-body');
    setAgentContent(body || streamingMsgEl, streamingText, true);
    streamingMsgEl.parentElement.scrollTop = streamingMsgEl.parentElement.scrollHeight;
    // 流式分句朗读:边出边按句念,首句很快就开口
    if (_ttsReadActive()) {
      if (!_ttsActive) { _ttsReset(); _ttsActive = true; }
      _ttsFeed(streamingText);
    }
  }
    else if (etype === 'assistant_message') {
    removeThinking();
    const text = p.text || '';
    const who = p.expert_role || (p.source && p.source !== 'coordinator' && p.source !== 'system' ? p.source : 'Captain');
    if (p.direct_expert) resetStreamingBubble();
    if (streamingMsgEl && !p.direct_expert) {
      const body = streamingMsgEl.querySelector('.msg-body') || streamingMsgEl;
      const head = streamingMsgEl.querySelector('.msg-label-agent');
      if (head && who !== 'Captain') head.textContent = who;
      setAgentContent(body, text, false);
      if (typeof setTurnImageTarget === 'function') setTurnImageTarget(body);
      streamingMsgEl.classList.remove('streaming');
      attachMsgActions(streamingMsgEl, text);
      streamingMsgEl.removeAttribute('id');
      streamingMsgEl = null;
      streamingText = '';
      // 朗读收尾:把剩余不足一句的也念掉;念完会(对话模式)自动重新开麦
      if (_ttsReadActive()) {
        if (!_ttsActive && !_ttsConsumed) { _ttsReset(); _ttsActive = true; }
        _ttsFlush(text);
      }
    } else {
      chatMsg('agent', text, { name: who });
      if (_ttsReadActive() && text) { _ttsReset(); _ttsActive = true; _ttsFlush(text); }
    }
    if (p.budget_detail) showTaskUsage(p.budget_detail);
    if (p.stopped || (p.source === 'system' && (text === '已停止' || text === 'Stopped'))) {
      setTaskRunning(false);
    }
  }
  else if (etype === 'capability_call') {
    _lastCapCall = { name: p.name || '', args: p.args || {} };
    updateThinkingStatus(p.name || '', p.intent || '');
    const name = p.name || '';
    const args = p.args || {};
    if (isToolTraceEnabled() && currentView === 'chat') {
      if (name === 'coordinator.plan') { /* plan_update */ }
      else if (name === 'coordinator.dispatch') {
        const items = (args.assignments || []).map(a => `${a.agent}: ${(a.sub_task||'').slice(0,80)}`).join('\n');
        appendToolTrace('call', t('evtDispatch'), items || (p.intent || ''));
      } else if (name === 'coordinator.invoke') {
        resetStreamingBubble();
        document.querySelectorAll('.approval-card').forEach(el => el.remove());
        appendToolTrace('call', t('evtExpert'), `${args.agent || '?'} · ${(args.task||'').slice(0,200)}`);
      } else if (name.startsWith('skill.')) {
        appendToolTrace('call', 'Skill', `「${skillLabel(name.slice(6))}」\n` + JSON.stringify(args, null, 2));
      } else {
        const detail = (p.intent ? p.intent + '\n\n' : '') + JSON.stringify(args, null, 2);
        appendToolTrace('call', name, detail);
      }
      return;
    }
    if (conciseChat && currentView === 'chat') return;
    if (name === 'coordinator.plan') return;   // 由 plan_update 事件渲染执行计划图
    if (name === 'coordinator.dispatch') {
      const items = (args.assignments || []).map(a => `${a.agent}: ${(a.sub_task||'').slice(0,80)}`).join('\n');
      chatEvent('call', t('evtDispatch'), items || (p.intent || t('evtAutoDispatch')));
      return;
    }
    if (name === 'coordinator.invoke') {
      resetStreamingBubble();
      document.querySelectorAll('.approval-card').forEach(el => el.remove());
      chatEvent('call', t('evtExpert'), `${args.agent || '?'} · ${(args.task||'').slice(0,120)}`);
      return;
    }
    if (name.startsWith('skill.')) {
      chatEvent('call', 'Skill', `正在调用「${skillLabel(name.slice(6))}」`);
      return;
    }
    chatEvent('call', t('evtCall'), `${name}`);
  }
  else if (etype === 'capability_result') {
    const cap = _lastCapCall;
    const capName = p.name || (cap && cap.name) || '';
    try {
      if (capName === 'fs.write' && p.ok
          && typeof registerWorkbenchArtifact === 'function') {
        registerWorkbenchArtifact((cap && cap.args)?.path, p.output);
      }
      if (capName === 'image.generate' && p.ok
          && typeof appendChatImage === 'function') {
        // 优先从 output(含完整 产物/ 路径)解析;否则才退回用文件名参数,避免丢 产物/ 前缀
        const rel = normalizeArtifactRel('', p.output)
          || normalizeArtifactRel((cap && cap.args)?.name, p.output)
          || normalizeArtifactRel('', p.artifact_path || '');
        if (rel) {
          registerWorkbenchArtifact(rel, p.output);
          appendChatImage(rel);
        }
      }
    } catch {}
    _lastCapCall = null;
    if (isToolTraceEnabled() && currentView === 'chat') {
      const outFull = p.output || p.error || '';
      const hits = (capName === 'web.search' || capName === 'exa.search') && p.ok
        ? parseSearchHits(outFull) : [];
      appendToolTrace(
        p.ok ? 'ok' : 'err',
        `${capName || 'tool'} · ${p.ok ? t('evtResult') : t('evtFail')}`,
        outFull,
        hits.length ? { searchHits: hits } : null,
      );
    } else if (!(conciseChat && currentView === 'chat')) {
      chatEvent(p.ok?'ok':'err', p.ok?t('evtResult'):t('evtFail'), (p.output||p.error||'').slice(0,300));
    }
  }
  else if (etype === 'governance_decision') {
    if (isToolTraceEnabled() && currentView === 'chat') {
      const dec = p.decision || '';
      const cls = dec === 'block' ? 'err' : (dec === 'ask' ? 'warn' : 'ok');
      appendToolTrace(cls, t('evtGov'), `${p.name}: ${dec} · ${t('evtRule')} ${p.rule||'-'} · ${p.reason||''}`);
      return;
    }
    if (conciseChat && currentView === 'chat') return;
    const dec = p.decision || '';
    const cls = dec === 'block' ? 'err' : (dec === 'ask' ? 'warn' : 'ok');
    chatEvent(cls, t('evtGov'), `${p.name}: ${dec} · ${t('evtRule')} ${p.rule||'-'} · ${p.reason||''}`);
  }
  else if (etype === 'approval_request') { approvalCard(p); }
  else if (etype === 'rollback_result') {
    const notes = (p.notes||[]).join('; ') || t('rollbackNone');
    chatMsg('system', p.ok ? t('rollbackOk').replace('{notes}', notes) : t('rollbackFail'));
  }
  else if (etype === 'error' && currentView==='chat') {
    chatEvent('err', t('errLabel'), p.message||'');
    setTaskRunning(false);
  }
  else if (etype === 'plan_update') {
    if (typeof wbHandlePlan === 'function') wbHandlePlan(p);
    if (typeof _snapshotPlan === 'function' && typeof _saveWorkbench === 'function') {
      _saveWorkbench({ plan: _snapshotPlan() });   // 进度快照按会话持久化
    }
  }
  else if (etype === 'status_bar') { updateStatusBar(p); }
  else if (etype === 'task_done') {
    removeThinking();
    resetStreamingBubble();
    const doneGen = p.task_gen || activeTaskGen;
    if (!isBackgroundTaskView() || (doneGen && doneGen === activeTaskGen)) {
      activeTaskGen = 0;
      setTaskRunning(false);
      taskSessionId = '';
    }
    refreshSessions();
  }

  // ── 辩论事件 ──
  else if (etype === 'debate_message') {
    const side = p.side === 'pro' ? t('debatePro') : t('debateCon');
    chatMsg('agent', `[${t('debateTag')}·${side}] ${p.content || ''}`, { name: p.name || side });
  }
  else if (etype === 'debate_summary') { chatMsg('agent', `[${t('debateSummary')}]\n${p.content || ''}`, { name: t('debateHost') }); }
  else if (etype === 'debate_done')   { removeThinking(); }
}

function setStatusBarConnecting() {
  const wrap = document.getElementById('chat-status-bar');
  const label = document.getElementById('ctx-connecting-label');
  const tok = document.getElementById('ctx-tokens');
  const div = document.getElementById('ctx-divider');
  const track = document.getElementById('ctx-track');
  const pctEl = document.getElementById('ctx-pct');
  if (!wrap) return;
  wrap.classList.add('is-connecting');
  if (label) { label.hidden = false; label.textContent = t('connecting'); }
  if (tok) tok.hidden = true;
  if (div) div.hidden = true;
  if (track) track.hidden = true;
  if (pctEl) pctEl.hidden = true;
}

function updateStatusBar(p) {
  const wrap = document.getElementById('chat-status-bar');
  const label = document.getElementById('ctx-connecting-label');
  const tokEl = document.getElementById('ctx-tokens');
  const fill = document.getElementById('ctx-fill');
  const div = document.getElementById('ctx-divider');
  const track = document.getElementById('ctx-track');
  const pctEl = document.getElementById('ctx-pct');
  if (!wrap || !tokEl || !fill || !track || !pctEl) return;

  const tok = p.tokens_label || '';
  const pct = p.pct != null ? Math.max(0, Math.min(100, Number(p.pct))) : null;
  if (!tok || pct == null) {
    setStatusBarConnecting();
    return;
  }

  wrap.classList.remove('is-connecting');
  if (label) label.hidden = true;
  tokEl.hidden = false;
  if (div) div.hidden = false;
  track.hidden = false;
  pctEl.hidden = false;

  tokEl.textContent = tok;
  fill.style.width = `${pct}%`;
  fill.classList.toggle('is-warn', pct >= 80 && pct < 95);
  fill.classList.toggle('is-high', pct >= 95);
  pctEl.textContent = `${Math.round(pct)}%`;
  pctEl.classList.toggle('is-warn', pct >= 80);
  let tip = t('ctxTooltip').replace('{tok}', tok).replace('{pct}', String(Math.round(pct)));
  if (pct >= 80) tip += ' · ' + t('ctxWarn');
  wrap.title = tip;
}

/* ══ 聊天功能 ════════════════════════════════════════════════════ */
function wsInitPayload() {
  const cfg = loadConfig();
  return { type:'init', session_id: sessionId, model: cfg.model || 'deepseek-v4-flash',
           mode: (typeof workMode !== 'undefined' ? workMode : 'chat') };
}

function requestSessionInit() {
  const expected = sessionId;
  _sessionInitExpected = expected;
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    _sessionInitResolve = resolve;
    ws.send(JSON.stringify(wsInitPayload()));
    setTimeout(() => {
      if (_sessionInitResolve === resolve) {
        _sessionInitResolve = null;
        resolve();
      }
    }, 4000);
  });
}

function onSendClick() {
  if (taskRunning) stopTask();
  else sendMsg();
}

function setTaskRunning(running) {
  taskRunning = running;
  const btn = document.getElementById('btn-send');
  if (!btn) return;
  btn.classList.toggle('is-stop', running);
  btn.textContent = running ? t('btnStop') : '↑';
  btn.setAttribute('aria-label', running ? t('btnStop') : t('btnSend'));
  btn.disabled = false;
}

function stopTask() {
  if (!ws || ws.readyState !== 1) return;
  ws.send(JSON.stringify({ type: 'task_stop' }));
}

function sendMsg() {
  const inp = document.getElementById('chat-inp');
  let text = inp.value.trim();
  const attachRefs = _pendingAttachments.map(a => a.ref).filter(Boolean);
  if (attachRefs.length) text = attachRefs.join('\n') + (text ? '\n' + text : '');
  if (!text) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    _wsSendQueue = text;
    if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) connect();
    return;
  }
  _wsSendQueue = null;
  if (text === '/rollback') {
    chatMsg('user', text);
    ws.send(JSON.stringify({ type:'rollback' }));
    inp.value = ''; return;
  }
  lastUserPrompt = text;
  if (typeof clearChatImagePaths === 'function') clearChatImagePaths();
  resetTraceGroup();
  document.getElementById('ctx-task-usage').hidden = true;
  resetStreamingBubble();
  activeTaskGen = 0;
  document.querySelectorAll('.approval-card').forEach(el => el.remove());
  chatMsg('user', text, { attachments: _pendingAttachments.slice() });
  clearPendingAttachments();
  ws.send(JSON.stringify({ type:'user', text }));
  inp.value = ''; inp.style.height='';
  closeSlashMenu();
  showThinking();
  taskSessionId = sessionId;
  setTaskRunning(true);
  maybeSetTitleFromFirstMessage(text);
  if (typeof _currentProject !== 'undefined' && _currentProject) _assignCurrentSessionToProject();
}

function chatMsg(type, text, opts = {}) {
  const area = document.getElementById('chat-messages');
  const empty = document.getElementById('chat-empty');
  if (empty) empty.style.display = 'none';
  const d = document.createElement('div');
  d.className = `msg msg-${type}`;
  if (opts.msgId != null) d.dataset.msgId = String(opts.msgId);
  const mkey = buildMsgKey(type, text, opts.msgId, opts.msgTs);
  d.dataset.msgKey = mkey;
  if (type === 'agent') {
    const label = escHtml(opts.name || 'Captain');
    d.innerHTML = `<div class="msg-head"><span class="msg-label msg-label-agent">${label}</span></div><div class="msg-body"></div>`;
    const body = d.querySelector('.msg-body');
    setAgentContent(body, text);
    if (typeof setTurnImageTarget === 'function') setTurnImageTarget(body);
    attachMsgActions(d, text, { msgKey: mkey, msgId: opts.msgId });
  } else if (type === 'user') {
    d.innerHTML = '<div class="msg-body user-body"></div>';
    renderUserMessageBody(d.querySelector('.msg-body'), text, opts.attachments);
    attachUserMsgActions(d, text, { msgKey: mkey, msgId: opts.msgId });
  } else {
    d.textContent = text;
  }
  area.appendChild(d);
  area.scrollTop = area.scrollHeight;
  if (type === 'user') msgCount++;
  updateChatLayoutState();
}

function renderUserMessageBody(body, text, attachments) {
  if (!body) return;
  const paths = [];
  (attachments || []).forEach(a => { if (a.path) paths.push(a.path); });
  extractImagePathsFromText(text).forEach(p => paths.push(p));
  const unique = [...new Set(paths)];
  const imgPaths = unique.filter(p => isImageArtifact(p));
  let displayText = String(text || '');
  imgPaths.forEach(p => { displayText = displayText.replace(p, '').trim(); });
  displayText = displayText.replace(/\[已上传[^\]]+\]/g, '').trim();
  body.textContent = displayText || '';
  if (imgPaths.length) {
    const wrap = document.createElement('div');
    wrap.className = 'user-msg-images';
    imgPaths.forEach(p => {
      const img = document.createElement('img');
      img.alt = p.split('/').pop();
      img.onclick = () => openArtifact(p);
      loadInlineImage(img, p);
      wrap.appendChild(img);
    });
    body.appendChild(wrap);
  }
}

function attachUserMsgActions(el, text, meta) {
  if (!el || el.querySelector('.msg-footer')) return;
  const footer = document.createElement('div');
  footer.className = 'msg-footer';
  const mkBtn = (title, svg, onClick) => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'msg-footer-btn'; b.title = title;
    b.setAttribute('aria-label', title); b.innerHTML = svg;
    b.onclick = (e) => { e.stopPropagation(); onClick(b); };
    return b;
  };
  const ICON_EDIT = '<svg viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>';
  footer.appendChild(mkBtn(t('editMsg'), ICON_EDIT, () => startEditUserMessage(el, text, meta)));
  el.appendChild(footer);
}

function startEditUserMessage(el, text, meta) {
  if (!el || el.querySelector('.msg-edit-wrap')) return;
  const body = el.querySelector('.user-body');
  if (!body) return;
  const wrap = document.createElement('div');
  wrap.className = 'msg-edit-wrap';
  const ta = document.createElement('textarea');
  ta.value = text;
  const acts = document.createElement('div');
  acts.className = 'msg-edit-actions';
  const cancel = document.createElement('button');
  cancel.type = 'button'; cancel.className = 'btn-secondary btn-sm'; cancel.textContent = t('cancel');
  const save = document.createElement('button');
  save.type = 'button'; save.className = 'btn-primary btn-sm'; save.textContent = t('save');
  cancel.onclick = () => wrap.remove();
  save.onclick = () => {
    const nt = ta.value.trim();
    if (!nt || !ws || ws.readyState !== 1) return;
    const mid = meta?.msgId || el.dataset.msgId;
    wrap.remove();
    let node = el.nextSibling;
    while (node) { const n = node.nextSibling; node.remove(); node = n; }
    el.remove();
    resetTraceGroup();
    ws.send(JSON.stringify({
      type: 'edit_user', session_id: sessionId, msg_id: mid ? parseInt(mid, 10) : null, text: nt,
    }));
    showThinking();
    setTaskRunning(true);
  };
  acts.appendChild(cancel);
  acts.appendChild(save);
  wrap.appendChild(ta);
  wrap.appendChild(acts);
  el.appendChild(wrap);
  ta.focus();
}

function regenerateFromUserMsg(userMsgId) {
  if (!ws || ws.readyState !== 1) return;
  const area = document.getElementById('chat-messages');
  if (userMsgId != null && area) {
    const uel = area.querySelector(`.msg-user[data-msg-id="${CSS.escape(String(userMsgId))}"]`);
    if (uel) {
      let node = uel.nextSibling;
      while (node) { const n = node.nextSibling; node.remove(); node = n; }
    }
  } else if (area) {
    const users = area.querySelectorAll('.msg-user');
    if (users.length) {
      const uel = users[users.length - 1];
      let node = uel.nextSibling;
      while (node) { const n = node.nextSibling; node.remove(); node = n; }
    }
  }
  resetTraceGroup();
  resetStreamingBubble();
  ws.send(JSON.stringify({
    type: 'regenerate', session_id: sessionId, user_msg_id: userMsgId != null ? userMsgId : null,
  }));
  showThinking();
  setTaskRunning(true);
}

function clearPendingAttachments() {
  _pendingAttachments.length = 0;
  renderComposerAttachments();
}
function renderComposerAttachments() {
  const box = document.getElementById('composer-attachments');
  if (!box) return;
  if (!_pendingAttachments.length) { box.hidden = true; box.innerHTML = ''; return; }
  box.hidden = false;
  box.innerHTML = _pendingAttachments.map((a, i) => {
    const thumb = a.isImage
      ? `<img src="${escAttr(a.previewUrl || '')}" alt="">`
      : `<span>📄</span>`;
    return `<div class="composer-attach-chip">${thumb}<span>${escHtml(a.name)}</span>`
      + `<button type="button" aria-label="remove" onclick="removePendingAttachment(${i})">×</button></div>`;
  }).join('');
}
function removePendingAttachment(idx) {
  const item = _pendingAttachments[idx];
  if (item && item.previewUrl) try { URL.revokeObjectURL(item.previewUrl); } catch {}
  _pendingAttachments.splice(idx, 1);
  renderComposerAttachments();
}

function setAgentContent(el, text, streaming) {
  const normalized = normalizeAgentText(text);
  if (streaming) {
    scheduleStreamRender(el, normalized);
    return;
  }
  if (streamRenderTimer) {
    clearTimeout(streamRenderTimer);
    streamRenderTimer = null;
  }
  el.innerHTML = `<div class="md">${renderMD(normalized)}</div>`;
  attachCodeCopyButtons(el);
  mergeChatImagesInto(el);
}

function scheduleStreamRender(el, text) {
  if (streamRenderTimer) return;
  streamRenderTimer = setTimeout(() => {
    streamRenderTimer = null;
    el.innerHTML = `<div class="md streaming-md">${renderMD(text)}</div>`;
    mergeChatImagesInto(el);
    if (el.parentElement) el.parentElement.scrollTop = el.parentElement.scrollHeight;
  }, 60);
}

/** 长文预处理:补全 agent 常写但未换行的段落结构 */
function normalizeAgentText(text) {
  if (!text) return '';
  let t = String(text).replace(/\r\n/g, '\n');
  // 中文序号标题前补空行
  t = t.replace(/([^\n])\n(#{1,4} |【|[一二三四五六七八九十]+[、.．]|\d+[、.．])/g, '$1\n\n$2');
  // 连续非空行之间若缺空行且前一行像标题/列表,补空行
  t = t.replace(/^(#{1,4} .+)$/gm, '\n$1\n');
  t = t.replace(/^【(.+)】$/gm, '\n【$1】\n');
  return t.replace(/\n{3,}/g, '\n\n').trim();
}

const CAP_STATUS_LABELS = {
  'fs.read': '正在读取文件…',
  'fs.write': '正在写入文件…',
  'fs.list': '正在浏览目录…',
  'shell.run': '正在执行命令…',
  'web.search': '正在搜索…',
  'web.fetch': '正在获取网页…',
  'memory.recall': '正在回忆…',
  'memory.remember': '正在记住…',
  'agent.delegate': '正在请专家协助…',
};

function updateThinkingStatus(name, intent) {
  if (!thinkingEl) return;
  const span = thinkingEl.querySelector('.thinking-label');
  if (!span) return;
  let label = CAP_STATUS_LABELS[name];
  if (!label && name.startsWith('skill.')) label = `正在调用「${skillLabel(name.slice(6))}」…`;
  if (!label) label = intent ? `${intent.slice(0, 40)}…` : '正在处理…';
  span.textContent = label;
}

function attachCodeCopyButtons(el) {
  if (!el) return;
  const showCopy = true;
  el.querySelectorAll('pre.md-pre').forEach(pre => {
    if (pre.closest('.md-pre-wrap')) return;
    const wrap = document.createElement('div');
    wrap.className = 'md-pre-wrap';
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(pre);
    if (!showCopy) return;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'code-copy';
    btn.textContent = t('copyCode');
    btn.onclick = (e) => {
      e.stopPropagation();
      const code = pre.querySelector('code') || pre;
      navigator.clipboard.writeText(code.textContent || '').catch(() => {});
      btn.textContent = t('copied');
      setTimeout(() => { btn.textContent = t('copyCode'); }, 1500);
    };
    wrap.appendChild(btn);
  });
}

/* ── 语音输出:朗读文本(挑中文好嗓音 + 去 markdown 念得顺)── */
function _pickVoice(lang) {
  try {
    const vs = window.speechSynthesis.getVoices() || [];
    return vs.find(v => v.lang === lang)
        || vs.find(v => v.lang && v.lang.startsWith(lang.split('-')[0])) || null;
  } catch (e) { return null; }
}
let _hqAudio = null;
function _stopSpeak() {
  try { if (window.speechSynthesis) window.speechSynthesis.cancel(); } catch (e) {}
  try { if (_hqAudio) { _hqAudio.pause(); _hqAudio = null; } } catch (e) {}
}
function _speakNative(clean, done) {
  if (!window.speechSynthesis) { done(); return; }
  window.speechSynthesis.cancel();
  const lang = (typeof uiLang !== 'undefined' && uiLang === 'en') ? 'en-US' : 'zh-CN';
  const u = new SpeechSynthesisUtterance(clean.slice(0, 2000));
  u.lang = lang; const v = _pickVoice(lang); if (v) u.voice = v; u.rate = 1.05;
  u.onend = done; u.onerror = done;
  window.speechSynthesis.speak(u);
}
async function _speakHQ(clean, done) {
  try {
    const resp = await fetch('/api/voice/tts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: clean.slice(0, 500) }),
    });
    if (!resp.ok) { _speakNative(clean, done); return; }   // 失败回退原生,不卡循环
    const blob = await resp.blob();
    _stopSpeak();
    _hqAudio = new Audio(URL.createObjectURL(blob));
    _hqAudio.onended = done; _hqAudio.onerror = () => _speakNative(clean, done);
    await _hqAudio.play();
  } catch (e) { _speakNative(clean, done); }
}
function speakText(raw, onEnd) {
  const done = () => { try { onEnd && onEnd(); } catch (e) {} };
  if (!raw) { done(); return; }
  const clean = String(raw)
    .replace(/```[\s\S]*?```/g, ' 代码块 ')
    .replace(/\[(.*?)\]\(.*?\)/g, '$1')
    .replace(/[#*`>_~|]/g, ' ').replace(/\s+/g, ' ').trim();
  if (!clean) { done(); return; }
  if (_hqVoice) _speakHQ(clean, done); else _speakNative(clean, done);
}
window.speakText = speakText;

/* ── 自动朗读回复:开关(持久化)── */
let _autoRead = (() => { try { return localStorage.getItem('autoRead') === '1'; } catch (e) { return false; } })();
function _syncAutoReadBtn() {
  const b = document.getElementById('btn-autoread');
  if (b) b.classList.toggle('ar-on', _autoRead);
}
function toggleAutoRead(e) {
  if (e) e.stopPropagation();
  _autoRead = !_autoRead;
  try { localStorage.setItem('autoRead', _autoRead ? '1' : '0'); } catch (e2) {}
  if (!_autoRead) _ttsReset();
  _syncAutoReadBtn();
}
document.addEventListener('DOMContentLoaded', _syncAutoReadBtn);

/* ── 高音质语音开关:开 → 朗读走小米 MiMo TTS、听写走 MiMo ASR(更自然/更准/支持方言克隆)── */
let _hqVoice = (() => { try { return localStorage.getItem('hqVoice') === '1'; } catch (e) { return false; } })();
function _syncHQBtn() { const b = document.getElementById('btn-hqvoice'); if (b) b.classList.toggle('hq-on', _hqVoice); }
function toggleHQVoice(e) {
  if (e) e.stopPropagation();
  _hqVoice = !_hqVoice;
  try { localStorage.setItem('hqVoice', _hqVoice ? '1' : '0'); } catch (e2) {}
  _ttsReset(); _syncHQBtn();
}
document.addEventListener('DOMContentLoaded', _syncHQBtn);

/* ── 高音质听写:录音 → 转 WAV → /api/voice/asr(小米识别)── */
let _hqRec = null, _hqChunks = [], _hqStream = null;
async function _micHQToggle() {
  const btn = document.getElementById('btn-mic');
  const inp = document.getElementById('chat-inp');
  if (_hqRec && _hqRec.state === 'recording') { _hqRec.stop(); return; }
  try { _hqStream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch (e) { alert('需要麦克风权限。'); return; }
  _hqChunks = [];
  _hqRec = new MediaRecorder(_hqStream);
  _hqRec.ondataavailable = (e) => { if (e.data && e.data.size) _hqChunks.push(e.data); };
  _hqRec.onstart = () => { btn && btn.classList.add('mic-on'); };
  _hqRec.onstop = async () => {
    btn && btn.classList.remove('mic-on');
    try { _hqStream.getTracks().forEach(t => t.stop()); } catch (e) {}
    try {
      const wav = await _blobToWav(new Blob(_hqChunks, { type: (_hqRec && _hqRec.mimeType) || 'audio/webm' }));
      const fd = new FormData(); fd.append('audio', wav, 'rec.wav');
      const d = await (await fetch('/api/voice/asr', { method: 'POST', body: fd })).json();
      if (d.ok && d.text && inp) { inp.value = (inp.value ? inp.value + ' ' : '') + d.text; inp.dispatchEvent(new Event('input')); }
      else if (!d.ok) alert('识别失败:' + (d.error || ''));
    } catch (e) { alert('识别失败:' + e); }
  };
  _hqRec.start();
}
async function _blobToWav(blob) {
  const buf = await blob.arrayBuffer();
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const audio = await ctx.decodeAudioData(buf);
  const ch = audio.getChannelData(0), rate = audio.sampleRate, len = ch.length;
  const out = new DataView(new ArrayBuffer(44 + len * 2));
  const w = (o, s) => { for (let i = 0; i < s.length; i++) out.setUint8(o + i, s.charCodeAt(i)); };
  w(0, 'RIFF'); out.setUint32(4, 36 + len * 2, true); w(8, 'WAVE'); w(12, 'fmt ');
  out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 1, true);
  out.setUint32(24, rate, true); out.setUint32(28, rate * 2, true); out.setUint16(32, 2, true);
  out.setUint16(34, 16, true); w(36, 'data'); out.setUint32(40, len * 2, true);
  let off = 44; for (let i = 0; i < len; i++) { const s = Math.max(-1, Math.min(1, ch[i])); out.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7FFF, true); off += 2; }
  return new Blob([out.buffer], { type: 'audio/wav' });
}

/* ── 语音输入:点麦克风,浏览器原生听写进输入框(zh-CN,实时上屏)── */
let _rec = null, _recOn = false, _micBase = '', _micFinal = '';
function toggleMic(e) {
  if (e) e.stopPropagation();
  if (_hqVoice) { _micHQToggle(); return; }   // 高音质模式 → 走小米 ASR
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const btn = document.getElementById('btn-mic');
  const inp = document.getElementById('chat-inp');
  if (!SR) { alert('当前浏览器不支持语音输入,建议用 Chrome。'); return; }
  if (_recOn) { try { _rec && _rec.stop(); } catch (e2) {} return; }
  _rec = new SR();
  _rec.lang = (typeof uiLang !== 'undefined' && uiLang === 'en') ? 'en-US' : 'zh-CN';
  _rec.interimResults = true; _rec.continuous = true;
  _micBase = inp ? (inp.value ? inp.value + ' ' : '') : ''; _micFinal = '';
  _rec.onstart = () => { _recOn = true; btn && btn.classList.add('mic-on'); };
  _rec.onend = () => { _recOn = false; btn && btn.classList.remove('mic-on'); };
  _rec.onerror = () => { _recOn = false; btn && btn.classList.remove('mic-on'); };
  _rec.onresult = (ev) => {
    let interim = '';
    for (let i = ev.resultIndex; i < ev.results.length; i++) {
      const r = ev.results[i];
      if (r.isFinal) _micFinal += r[0].transcript; else interim += r[0].transcript;
    }
    if (inp) { inp.value = _micBase + _micFinal + interim; inp.dispatchEvent(new Event('input')); }
  };
  try { _rec.start(); } catch (e2) {}
}

/* ── 连续对话模式:免手循环 听→停顿即发→回复→朗读→念完再开麦 ── */
let _convoOn = false, _convoRec = null;
function _syncConvoBtn() {
  const b = document.getElementById('btn-convo');
  if (b) b.classList.toggle('convo-on', _convoOn);
}
function toggleConvo(e) {
  if (e) e.stopPropagation();
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { alert('当前浏览器不支持语音,建议用 Chrome。'); return; }
  _convoOn = !_convoOn;
  _syncConvoBtn();
  if (_convoOn) { _convoListenOnce(); }
  else { try { _convoRec && _convoRec.abort(); } catch (e2) {} _ttsReset(); }
}
function _convoListenOnce() {
  if (!_convoOn) return;
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  try { _convoRec && _convoRec.abort(); } catch (e) {}
  const inp = document.getElementById('chat-inp');
  _convoRec = new SR();
  _convoRec.lang = (typeof uiLang !== 'undefined' && uiLang === 'en') ? 'en-US' : 'zh-CN';
  _convoRec.interimResults = true; _convoRec.continuous = false;  // 停顿即收尾,作为一轮边界
  let finalTxt = '';
  const micBtn = document.getElementById('btn-mic');
  _convoRec.onstart = () => { micBtn && micBtn.classList.add('mic-on'); };
  _convoRec.onresult = (ev) => {
    let interim = '';
    for (let i = ev.resultIndex; i < ev.results.length; i++) {
      const r = ev.results[i];
      if (r.isFinal) finalTxt += r[0].transcript; else interim += r[0].transcript;
    }
    if (inp) { inp.value = finalTxt + interim; inp.dispatchEvent(new Event('input')); }
  };
  _convoRec.onerror = () => { micBtn && micBtn.classList.remove('mic-on'); };
  _convoRec.onend = () => {
    micBtn && micBtn.classList.remove('mic-on');
    if (!_convoOn) return;
    const text = (inp ? inp.value : '').trim();
    if (text && !taskRunning) {
      sendMsg();                       // 这一轮说完了 → 自动发送;回复完成会触发朗读+重新开麦
    } else {
      setTimeout(() => { if (_convoOn) _convoListenOnce(); }, 600);  // 没说话/正忙 → 稍后再听
    }
  };
  try { _convoRec.start(); } catch (e) {}
}
document.addEventListener('DOMContentLoaded', _syncConvoBtn);

/* ── 流式分句朗读:边出文字边按句合成播放,首句 ~2s 就开口,不再憋完整段 ── */
let _ttsActive = false, _ttsConsumed = 0, _ttsQueue = [], _ttsPlaying = false;
function _ttsReadActive() { return _convoOn || _autoRead; }
function _ttsReset() { _ttsActive = false; _ttsConsumed = 0; _ttsQueue = []; _ttsPlaying = false; _stopSpeak(); }
function _ttsClean(s) {
  return String(s).replace(/```[\s\S]*?```/g, ' ').replace(/\[(.*?)\]\(.*?\)/g, '$1')
    .replace(/[#*`>_~|]/g, ' ').replace(/\s+/g, ' ').trim();
}
function _ttsEnqueue(sentence) {
  const clean = _ttsClean(sentence);
  if (clean) { _ttsQueue.push(clean); _ttsPump(); }
}
function _ttsFeed(fullText) {       // 流式中:切出已完成的整句入队
  if (!_ttsActive) return;
  const pending = fullText.slice(_ttsConsumed);
  const re = /[^。！？!?\n]*[。！？!?\n]+/g;
  let m, last = 0;
  while ((m = re.exec(pending)) !== null) { _ttsEnqueue(m[0]); last = re.lastIndex; }
  _ttsConsumed += last;
}
function _ttsFlush(fullText) {       // 收尾:把剩余不足一句的也念掉
  const rest = (fullText || '').slice(_ttsConsumed);
  if (rest.trim()) _ttsEnqueue(rest);
  _ttsConsumed = (fullText || '').length;
  _ttsActive = false;
  if (!_ttsQueue.length && !_ttsPlaying) _ttsDrain();
}
function _speakOne(text) { return new Promise(res => speakText(text, res)); }
async function _ttsPump() {
  if (_ttsPlaying || !_ttsQueue.length) return;
  _ttsPlaying = true;
  await _speakOne(_ttsQueue.shift());
  _ttsPlaying = false;
  if (_ttsQueue.length) _ttsPump();
  else if (!_ttsActive) _ttsDrain();
}
function _ttsDrain() { if (_convoOn) _convoListenOnce(); }  // 念完最后一句 → 对话模式重新开麦

function attachMsgActions(el, text, meta) {
  if (!el || el.querySelector('.msg-footer')) return;
  const footer = document.createElement('div');
  footer.className = 'msg-footer';
  const raw = text || el.textContent || '';
  const msgKey = (meta && meta.msgKey) || el.dataset.msgKey || buildMsgKey('agent', raw);

  const mkBtn = (title, svg, onClick) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'msg-footer-btn';
    b.title = title;
    b.setAttribute('aria-label', title);
    b.innerHTML = svg;
    b.onclick = (e) => { e.stopPropagation(); onClick(b); };
    return b;
  };

  const ICON_COPY = '<svg viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>';
  const ICON_SPEAKER = '<svg viewBox="0 0 24 24"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 010 7.07M19.07 4.93a10 10 0 010 14.14"/></svg>';
  const ICON_RETRY = '<svg viewBox="0 0 24 24"><path d="M1 4v6h6M23 20v-6h-6"/><path d="M20.49 9A9 9 0 005.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 013.51 15"/></svg>';
  const ICON_UP = '<svg viewBox="0 0 24 24"><path d="M7 11v8a1 1 0 001 1h2a1 1 0 001-1v-8M7 11H4a1 1 0 01-1-1V8a1 1 0 011-1h3M7 11l4-6a1 1 0 011-.8h1.5a2 2 0 012 1.7l1.2 5.1H20a1 1 0 011 1v5a1 1 0 01-1 1h-9"/></svg>';
  const ICON_DOWN = '<svg viewBox="0 0 24 24"><path d="M17 13V5a1 1 0 00-1-1h-2a1 1 0 00-1 1v8M17 13h3a1 1 0 001-1V9a1 1 0 00-1-1h-3M17 13l-4 6a1 1 0 01-.9.5H10.5a2 2 0 01-1.8-1.4L7.5 13H4a1 1 0 01-1-1v-5a1 1 0 011-1h13"/></svg>';

  const upBtn = mkBtn(t('thumbUp'), ICON_UP, (btn) => {
    const on = btn.classList.toggle('is-up');
    const sib = footer.querySelector('.is-down');
    if (sib) sib.classList.remove('is-down');
    saveFeedback(msgKey, on ? 1 : 0);
  });
  const downBtn = mkBtn(t('thumbDown'), ICON_DOWN, (btn) => {
    const on = btn.classList.toggle('is-down');
    const sib = footer.querySelector('.is-up');
    if (sib) sib.classList.remove('is-up');
    saveFeedback(msgKey, on ? -1 : 0);
  });
  footer.appendChild(mkBtn(t('copyMsg'), ICON_COPY, (btn) => {
    navigator.clipboard.writeText(raw).catch(() => {});
    btn.classList.add('is-up');
    setTimeout(() => btn.classList.remove('is-up'), 800);
  }));
  footer.appendChild(mkBtn(t('readAloud'), ICON_SPEAKER, () => speakText(raw)));
  footer.appendChild(upBtn);
  footer.appendChild(downBtn);
  footer.appendChild(mkBtn(t('retryMsg'), ICON_RETRY, () => {
    let uid = null;
    let prev = el.previousElementSibling;
    while (prev) {
      if (prev.classList && prev.classList.contains('msg-user') && prev.dataset.msgId) {
        uid = parseInt(prev.dataset.msgId, 10);
        break;
      }
      prev = prev.previousElementSibling;
    }
    regenerateFromUserMsg(uid);
  }));
  loadFeedbackState(msgKey, upBtn, downBtn);

  el.appendChild(footer);
  const spark = document.createElement('div');
  spark.className = 'msg-sparkle';
  spark.setAttribute('aria-hidden', 'true');
  spark.textContent = '✦';
  el.appendChild(spark);
}

function formatRelativeTime(ts) {
  const diff = Math.max(0, Date.now() - (ts || Date.now()));
  const min = Math.floor(diff / 60000);
  if (min < 1) return t('timeJustNow');
  if (min < 60) return t('timeMinutesAgo').replace('{n}', String(min));
  const hr = Math.floor(min / 60);
  if (hr < 24) return t('timeHoursAgo').replace('{n}', String(hr));
  const day = Math.floor(hr / 24);
  return t('timeDaysAgo').replace('{n}', String(day));
}

function dismissUsageBanner() {
  const banner = document.getElementById('usage-banner');
  if (banner) banner.hidden = true;
  try { sessionStorage.setItem('captain-usage-banner-dismissed', String(Date.now())); } catch {}
}

function nextWeeklyResetLabel() {
  const now = new Date();
  const day = now.getDay();
  const daysUntil = (5 - day + 7) % 7 || 7;
  const reset = new Date(now);
  reset.setDate(now.getDate() + daysUntil);
  reset.setHours(18, 0, 0, 0);
  const locale = uiLang === 'en' ? 'en-US' : 'zh-CN';
  const dateStr = reset.toLocaleDateString(locale, { weekday: 'short', month: 'short', day: 'numeric' });
  const timeStr = reset.toLocaleTimeString(locale, { hour: 'numeric', minute: '2-digit' });
  return `${dateStr}, ${timeStr}`;
}

function highlightPaths(text) {
  const safe = escHtml(text);
  return safe.replace(/(?:^|[\s"'(])([a-zA-Z0-9_./-]+\.[a-zA-Z0-9]{1,8})(?=[\s"',)\]]|$)/g,
    (m, p1, off, full) => {
      const pre = full.slice(0, off + m.indexOf(p1));
      if (pre.endsWith('://') || pre.endsWith('href=')) return m;
      return m.replace(p1, `<code class="path-ref">${p1}</code>`);
    });
}

function showTaskUsage(detail) {
  const el = document.getElementById('ctx-task-usage');
  if (!el || !detail) return;
  const tokens = formatTokenCount(detail.tokens || 0);
  const cost = (detail.cost_usd || 0).toFixed(4);
  el.textContent = t('taskUsage').replace('{tokens}', tokens).replace('{cost}', cost);
  el.hidden = false;
}

// 恢复服务端发来的历史消息
let pendingRestoreImages = [];
function renderRestored(messages) {
  const area = document.getElementById('chat-messages');
  area.innerHTML = '';
  if (!messages.length) {
    area.innerHTML = welcomeHtml();
    updateChatLayoutState();
    syncChatTopbarTitle();
    return;
  }
  messages.forEach(m => {
    if (m.role === 'user') {
      pendingRestoreImages = [];
      chatMsg('user', m.content, { msgId: m.id, msgTs: m.ts });
    } else if (m.role === 'assistant' && m.content) {
      chatMsg('agent', m.content, { msgId: m.id, msgTs: m.ts, name: m.name });
      const agents = area.querySelectorAll('.msg-agent .msg-body');
      const body = agents[agents.length - 1];
      if (body) {
        pendingRestoreImages.forEach(rel => attachImageToBody(body, rel));
        mergeChatImagesInto(body);
      }
      pendingRestoreImages = [];
    } else if (m.role === 'tool') {
      const rel = (m.name === 'image.generate' || /已生成图片/.test(m.content || ''))
        ? normalizeArtifactRel('', m.content) : '';
      if (rel && isImageArtifact(rel)) pendingRestoreImages.push(rel);
      else chatEvent('ok', m.name || '工具', (m.content || '').slice(0, 300));
    }
  });
  updateChatLayoutState();
  syncChatTopbarTitle();
}

function chatEvent(cls, label, text) {
  const area = document.getElementById('chat-messages');
  const d = document.createElement('div');
  d.className = 'event-row';
  d.innerHTML = `<span class="pill ${cls}">${escHtml(label)}</span><span>${highlightPaths(text)}</span>`;
  area.appendChild(d);
  area.scrollTop = area.scrollHeight;
}

function approvalCard(p) {
  removeThinking();
  document.querySelectorAll('.approval-card').forEach(el => el.remove());
  const area = document.getElementById('chat-messages');
  const c = document.createElement('div');
  c.className = 'approval-card';
  c.innerHTML = `
    <div class="approval-title">⚠️ 需要你确认</div>
    <div class="approval-detail">能力 <code>${escHtml(p.name)}</code></div>
    <div class="approval-detail">参数 <code>${escHtml(JSON.stringify(p.args))}</code></div>
    ${p.intent ? `<div class="approval-detail" style="margin-top:4px">意图: ${escHtml(p.intent)}</div>` : ''}
    ${p.reason ? `<div class="approval-detail" style="margin-top:4px;color:var(--yellow)">治理: ${escHtml(p.reason)}</div>` : ''}
    <div class="approval-hint">点「允许」后,本问题的后续写文件/执行命令等不再重复弹窗。</div>
    <div class="approval-btns">
      <button class="btn-allow">允许</button>
      <button class="btn-once">仅此次</button>
      <button class="btn-deny">拒绝</button>
    </div>`;
  area.appendChild(c); area.scrollTop = area.scrollHeight;
  const cardGen = p.task_gen || 0;
  const send = (payload) => {
    ws.send(JSON.stringify({type:'approval', task_gen: cardGen, ...payload}));
    c.remove();
  };
  c.querySelector('.btn-allow').onclick = () => send({approved:true, grant_task:true});
  c.querySelector('.btn-once').onclick  = () => send({approved:true, grant_task:false});
  c.querySelector('.btn-deny').onclick  = () => send({approved:false});
}

function showThinking() {
  resetStreamingBubble();
  removeThinking();
  const area = document.getElementById('chat-messages');
  const d = document.createElement('div');
  d.id = 'thinking-indicator';
  d.className = 'event-row';
  d.innerHTML = `<span class="pill">·</span><span class="thinking-label" style="color:var(--dim)">思考中…</span>`;
  area.appendChild(d); area.scrollTop = area.scrollHeight;
  thinkingEl = d;
}
function removeThinking() {
  if (thinkingEl) { thinkingEl.remove(); thinkingEl = null; }
}

function resetStreamingBubble() {
  streamingMsgEl = null;
  streamingText = '';
  if (streamRenderTimer) {
    clearTimeout(streamRenderTimer);
    streamRenderTimer = null;
  }
}

function clearChat() {
  resetStreamingBubble();
  if (typeof clearChatImagePaths === 'function') clearChatImagePaths();
  document.getElementById('chat-messages').innerHTML = welcomeHtml();
  msgCount = 0;
  updateChatLayoutState();
}
async function newChat() {
  if (taskRunning && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'task_stop' }));
  }
  setTaskRunning(false);
  taskSessionId = '';
  activeTaskGen = 0;
  sessionId = genSessionId(workMode);
  persistSessionId();
  resetStreamingBubble();
  clearChat();
  closeMobileSidebar();
  switchView('chat');
  await requestSessionInit();
  refreshSessions();
  syncChatTopbarTitle();
  if (workMode === 'coworker' && typeof resetWorkbenchSession === 'function') resetWorkbenchSession();
}

function switchToSession(id) {
  const s = allSessions.find(x => x.id === id);
  const mode = sessionWorkMode(id);
  const preserveTask = taskRunning;
  closeMobileSidebar();
  switchView('chat');
  if (s && s.title) updateSessionTitle(formatSessionTitle(s));
  if (mode) {
    setWorkMode(mode, { sessionId: id, reloadHistory: true, preserveTask });
  } else {
    sessionId = id;
    persistSessionId();
    resetStreamingBubble();
    clearChat();
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(wsInitPayload()));
    if (!preserveTask) {
      setTaskRunning(false);
      taskSessionId = '';
    }
  }
  refreshSessions();
  syncChatTopbarTitle();
  renderSessions(allSessions);
  if (taskRunning && sessionId === taskSessionId) showThinking();
}

/* ══ 视图切换════════════════════════════════ */
const MAIN_VIEWS = ['chat', 'projects', 'project'];

function switchView(view) {
  currentView = view;
  closeSettings();
  closeCustomize();
  closeMobileSidebar();
  MAIN_VIEWS.forEach(v => {
    const el = document.getElementById('view-' + v);
    if (el) el.classList.toggle('hidden', v !== view);
  });
  const app = document.getElementById('app');
  if (app) {
    app.classList.toggle('view-projects-active', view === 'projects');
    app.classList.toggle('view-project-active', view === 'project');
  }
  document.getElementById('btn-nav-projects')?.classList.toggle('active', view === 'projects' || view === 'project');
  document.getElementById('sb-proj-nav')?.classList.toggle('expanded', view === 'projects' || view === 'project');
  document.querySelectorAll('.sb-foot-btn[data-view]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.view === view);
  });
}

function toggleExpertForm(show) {
  const f = document.getElementById('expert-new-form');
  if (f) f.style.display = (show === undefined ? (f.style.display === 'none' ? 'block' : 'none') : (show ? 'block' : 'none'));
}

async function saveNewExpert() {
  const name = (document.getElementById('exp-name')?.value || '').trim();
  if (!name) { alert(t('expertNameReq')); return; }
  const payload = {
    name,
    description: (document.getElementById('exp-desc')?.value || '').trim(),
    tier: document.getElementById('exp-tier')?.value || 'readonly',
    system_prompt: (document.getElementById('exp-prompt')?.value || '').trim(),
  };
  let r, d;
  try {
    r = await fetch('/api/agents/roster', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    d = await r.json();
  } catch (e) { alert(t('expertSaveFail') + e); return; }
  if (!r.ok || !d.ok) { alert(t('expertSaveFail') + (d && d.error || r.status)); return; }
  toggleExpertForm(false);
  await renderExpertsPage();
  alert(t('expertSaved'));
}

async function deleteExpert(id) {
  if (!confirm(t('expertDelConfirm'))) return;
  try {
    const r = await fetch('/api/agents/roster/' + encodeURIComponent(id), { method: 'DELETE' });
    const d = await r.json();
    if (!r.ok || !d.ok) { alert(t('expertSaveFail') + (d && d.error || r.status)); return; }
  } catch (e) { alert(t('expertSaveFail') + e); return; }
  renderExpertsPage();
}

async function renderExpertsPage() {
  const grid = document.getElementById('experts-page-grid');
  if (!grid) return;
  grid.innerHTML = `<div style="color:var(--dim);font-size:13px">${escHtml(t('loading'))}</div>`;
  try {
    const res = await fetch('/api/agents/roster');
    const data = await res.json();
    const agents = data.agents || [];
    const header = `
      <div class="expert-add-bar" style="grid-column:1/-1;display:flex;justify-content:flex-end;margin-bottom:4px">
        <button class="btn-sm" type="button" onclick="toggleExpertForm()">${escHtml(t('expertAdd'))}</button>
      </div>
      <div id="expert-new-form" style="display:none;grid-column:1/-1;border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:8px;display:none">
        <div class="field"><input id="exp-name" type="text" placeholder="${escHtml(t('expertNamePh'))}" autocomplete="off" style="width:100%"/></div>
        <div class="field" style="margin-top:8px"><input id="exp-desc" type="text" placeholder="${escHtml(t('expertDescPh'))}" autocomplete="off" style="width:100%"/></div>
        <div class="field" style="margin-top:8px">
          <label style="font-size:12px;color:var(--muted)">${escHtml(t('expertTier'))}</label>
          <select id="exp-tier" style="width:100%;margin-top:4px">
            <option value="readonly">${escHtml(t('expertTierRO'))}</option>
            <option value="write">${escHtml(t('expertTierRW'))}</option>
          </select>
        </div>
        <div class="field" style="margin-top:8px"><textarea id="exp-prompt" rows="3" placeholder="${escHtml(t('expertPromptPh'))}" style="width:100%"></textarea></div>
        <div style="margin-top:10px;text-align:right">
          <button class="btn-sm" type="button" onclick="saveNewExpert()">${escHtml(t('expertSaveBtn'))}</button>
        </div>
      </div>`;
    if (!agents.length) {
      grid.innerHTML = header + `<div style="color:var(--dim);grid-column:1/-1">${escHtml(t('expertNoCfg'))}</div>`;
      return;
    }
    grid.innerHTML = header;
    agents.forEach(a => {
      const card = document.createElement('div');
      card.className = 'expert-card';
      const delBtn = a.custom
        ? `<button class="expert-del" type="button" title="delete" onclick="deleteExpert('${escHtml(a.id)}')" style="position:absolute;top:8px;right:8px;border:none;background:none;color:var(--dim);cursor:pointer;font-size:15px">×</button>`
        : '';
      card.style.position = 'relative';
      card.innerHTML = `
        ${delBtn}
        <h3>${escHtml(a.role || a.name || a.id)}</h3>
        <div class="role">${escHtml(a.description || '')}</div>
        <code>/${escHtml(a.name || a.id)} ${escHtml(t('expertCallTaskHint') || '')}</code>`;
      grid.appendChild(card);
    });
  } catch {
    grid.innerHTML = `<div style="color:var(--red)">${escHtml(t('loadFailed') || 'load failed')}</div>`;
  }
}

async function renderSkillsPage() {
  const list = document.getElementById('skills-page-list');
  if (!list) return;
  list.innerHTML = '<div style="color:var(--dim);font-size:13px" data-i18n="loading">加载中…</div>';
  try {
    const res = await fetch('/api/skills');
    const data = await res.json();
    const skills = data.skills || [];
    if (!skills.length) {
      list.innerHTML = '<div style="color:var(--dim)">暂无 skill；可在 skills/ 或 ~/.agents/skills/ 添加</div>';
      return;
    }
    list.innerHTML = '';
    skills.forEach(s => {
      const row = document.createElement('div');
      row.className = 'skill-row';
      const badge = s.origin === 'user'
        ? '<span class="skill-badge user">用户</span>'
        : '<span class="skill-badge builtin">内置</span>';
      const impl = s.has_impl ? '' : ' · 指南型';
      row.innerHTML = `
        <div class="skill-cmd">${escHtml(s.cmd || '')}</div>
        <div style="flex:1">
          <div style="font-weight:500;font-size:13px">${escHtml(s.name || '')}${impl ? `<span style="font-size:11px;color:var(--muted);font-weight:400">${escHtml(impl)}</span>` : ''}</div>
          <div style="font-size:12px;color:var(--muted);margin-top:2px">${escHtml(s.description || '')}</div>
        </div>
        ${badge}`;
      list.appendChild(row);
    });
  } catch {
    list.innerHTML = '<div style="color:var(--red)">加载失败</div>';
  }
}

/* ══ 设置 / 自定义(Claude 式双栏面板)════════════════════════════ */
function openSettings(tab) {
  tab = tab || 'general';
  document.getElementById('settings-overlay').classList.add('open');
  switchSettingsTab(tab);
  loadSettingsUI();
}
function closeSettings() {
  document.getElementById('settings-overlay')?.classList.remove('open');
}
function switchSettingsTab(tab, el) {
  document.querySelectorAll('#settings-overlay .settings-nav-item').forEach(n => {
    n.classList.toggle('active', el ? n === el : n.dataset.tab === tab);
  });
  document.querySelectorAll('#settings-overlay .settings-section').forEach(s => {
    s.classList.toggle('active', s.id === 'settings-' + tab);
  });
  if (tab === 'tasks') refreshTasks();
  if (tab === 'governance') loadGovStats();
  if (tab === 'usage') loadUsageStats();
  if (tab === 'channels' || tab === 'general' || tab === 'keys') loadSettingsUI();
  if (tab === 'goals') renderGoals();
  if (tab === 'monitors') renderMonitors();
}
function openCustomize(tab) {
  tab = tab || 'skills';
  document.getElementById('customize-overlay').classList.add('open');
  switchCustomizeTab(tab);
}
function closeCustomize() {
  document.getElementById('customize-overlay')?.classList.remove('open');
}
function switchCustomizeTab(tab, el) {
  document.querySelectorAll('#customize-overlay .settings-nav-item').forEach(n => {
    n.classList.toggle('active', el ? n === el : n.dataset.tab === tab);
  });
  document.querySelectorAll('#customize-overlay .settings-section').forEach(s => {
    s.classList.toggle('active', s.id === 'customize-' + tab);
  });
  if (tab === 'experts') renderExpertsPage();
  if (tab === 'skills') renderSkillsPage();
  if (tab === 'templates') renderTemplates();
  if (tab === 'schedules') renderSchedules();
  if (tab === 'connectors') renderConnectors();
  if (tab === 'prefs') renderPrefs();
  if (tab === 'writing') renderWritingAssist();
}

/* ── 主动建议:它主动想到的事,你接受(→去做)或忽略 ── */
const _SUG_KIND = { plan:'今日计划', resume:'续做', retro:'复盘', skill:'固化技能', idea:'点子' };
let _sugPending = [];
async function refreshSugBadge() {
  try {
    const d = await (await fetch('/api/suggestions')).json();
    _sugPending = d.suggestions || [];
  } catch { _sugPending = []; }
  const btn = document.getElementById('btn-suggestions');
  const badge = document.getElementById('sug-badge');
  if (btn) btn.style.display = _sugPending.length ? '' : 'none';
  if (badge) badge.textContent = String(_sugPending.length);
}
function openSuggestions() { document.getElementById('suggestions-overlay')?.classList.add('open'); renderSuggestions(); }
function closeSuggestions() { document.getElementById('suggestions-overlay')?.classList.remove('open'); }
async function renderSuggestions() {
  await refreshSugBadge();
  const box = document.getElementById('sug-list'); if (!box) return;
  box.innerHTML = _sugPending.length ? _sugPending.map(s => `
    <div class="expert-card" style="margin-bottom:8px">
      <div style="font-size:11px;color:var(--accent);margin-bottom:4px">${escHtml(_SUG_KIND[s.kind]||s.kind)}</div>
      <div class="role" style="color:var(--txt);white-space:pre-wrap">${escHtml(s.text)}</div>
      <div style="display:flex;gap:8px;margin-top:8px">
        ${s.action ? `<button class="btn-sm primary" onclick="acceptSug('${s.id}')" data-i18n="sugAccept">接受并去做</button>` : `<button class="btn-sm" onclick="acceptSug('${s.id}')" data-i18n="sugGotIt">知道了</button>`}
        <button class="btn-sm" onclick="dismissSug('${s.id}')" data-i18n="sugDismiss">忽略</button>
      </div>
    </div>`).join('') : `<div class="wb-empty" data-i18n="sugEmpty">暂无主动建议</div>`;
  applyI18n();
}
async function acceptSug(id) {
  try {
    const d = await (await fetch(`/api/suggestions/${id}/accept`, {method:'POST'})).json();
    if (d.task_id && typeof toast === 'function') toast('已接受,后台开始处理');
  } catch {}
  renderSuggestions();
}
async function dismissSug(id) {
  try { await fetch(`/api/suggestions/${id}/dismiss`, {method:'POST'}); } catch {}
  renderSuggestions();
}
document.addEventListener('DOMContentLoaded', () => { refreshSugBadge(); setInterval(refreshSugBadge, 90000); });

/* ── 任务 Mission ── 交代目标 → 它自己拆解、顺序执行、卡住时通知 ── */
let _missionTimer = null;
const _MISSION_STATUS = {
  created:   { t: '已创建', c: '#888' },
  planning:  { t: '规划中', c: '#c89b3c' },
  executing: { t: '执行中', c: '#3c8cc8' },
  blocked:   { t: '已卡住', c: '#c85a3c' },
  waiting_user: { t: '等你回应', c: '#c85a3c' },
  completed: { t: '已完成', c: '#3cb371' },
  failed:    { t: '失败', c: '#c84444' },
  cancelled: { t: '已取消', c: '#888' },
};
function _mEsc(s) { const d = document.createElement('div'); d.textContent = (s == null ? '' : String(s)); return d.innerHTML; }

function openMission() {
  document.getElementById('mission-overlay')?.classList.add('open');
  try { applyI18n(); } catch (e) {}
  refreshMissions();
  if (_missionTimer) clearInterval(_missionTimer);
  _missionTimer = setInterval(refreshMissions, 4000);   // 轮询进度
  setTimeout(() => document.getElementById('mission-goal')?.focus(), 60);
}
function closeMission() {
  document.getElementById('mission-overlay')?.classList.remove('open');
  if (_missionTimer) { clearInterval(_missionTimer); _missionTimer = null; }
}
async function createMission() {
  const goal = (document.getElementById('mission-goal')?.value || '').trim();
  if (!goal) return;
  const attn = parseInt(document.getElementById('mission-attn')?.value || '2', 10);
  try {
    const d = await (await fetch('/api/mission', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal, attention_level: attn }) })).json();
    if (d.ok) { const g = document.getElementById('mission-goal'); if (g) g.value = ''; refreshMissions(); }
  } catch (e) {}
}
async function cancelMission(mid) {
  try { await fetch('/api/mission/' + mid + '/cancel', { method: 'POST' }); refreshMissions(); } catch (e) {}
}
async function resumeMission(mid) {
  const info = prompt('补充它需要的资料/决策(留空则直接重试):') ;
  if (info === null) return;   // 取消
  try {
    await fetch('/api/mission/' + mid + '/resume', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ info: (info || '').trim() }) });
    refreshMissions();
  } catch (e) {}
}
async function refreshMissions() {
  const box = document.getElementById('mission-list');
  if (!box) return;
  try {
    const d = await (await fetch('/api/missions')).json();
    const list = d.missions || [];
    if (!list.length) { box.innerHTML = '<div style="color:var(--dim);padding:16px">还没有任务。上面交代一个目标试试。</div>'; return; }
    box.innerHTML = list.map(_missionCard).join('');
  } catch (e) {}
}
function _missionCard(m) {
  const s = _MISSION_STATUS[m.status] || { t: m.status, c: '#888' };
  const tasks = m.tasks || [];
  const done = tasks.filter(t => t.status === 'done').length;
  const prog = tasks.length ? `${done}/${tasks.length}` : '—';
  const terminal = ['completed', 'failed', 'cancelled'].includes(m.status);
  const taskRows = tasks.map(t => {
    const mark = t.status === 'done' ? '✓' : (t.status === 'failed' ? '✗' : (t.status === 'pending' ? '○' : '…'));
    return `<div style="font-size:12px;color:var(--dim);padding:1px 0">${mark} ${_mEsc(t.text)}</div>`;
  }).join('');
  const blocked = (m.status === 'blocked' || m.status === 'waiting_user') && m.blocked_reason
    ? `<div style="font-size:12px;color:#c85a3c;margin-top:4px">⚠ ${_mEsc(m.blocked_reason)}</div>` : '';
  const arts = (m.artifacts || []).length
    ? `<div style="font-size:12px;color:var(--dim);margin-top:4px">产物:${m.artifacts.map(_mEsc).join('、')}</div>` : '';
  return `<div style="border:1px solid var(--border);border-radius:10px;padding:10px 12px;margin-bottom:10px">
    <div style="display:flex;align-items:center;gap:8px">
      <span style="font-size:11px;padding:1px 8px;border-radius:10px;color:#fff;background:${s.c}">${s.t}</span>
      <strong style="flex:1">${_mEsc(m.goal)}</strong>
      <span style="font-size:12px;color:var(--dim)">${prog}</span>
      ${(m.status === 'blocked' || m.status === 'waiting_user') ? `<button class="btn-sm primary" onclick="resumeMission('${m.id}')">补充并恢复</button>` : ''}
      ${terminal ? '' : `<button class="btn-sm" onclick="cancelMission('${m.id}')">取消</button>`}
    </div>
    ${taskRows ? `<div style="margin-top:6px">${taskRows}</div>` : ''}
    ${blocked}${arts}
  </div>`;
}

/* ── 分享 / 导出 ── */
function _curSession() { try { return sessionId; } catch (e) { return ''; } }
async function exportConversation() {
  const sid = _curSession();
  if (!sid) { alert('当前没有可导出的对话'); return; }
  window.open(`/api/sessions/${encodeURIComponent(sid)}/export.md`, '_blank');
}
async function shareConversation() {
  const sid = _curSession();
  if (!sid) { alert('当前没有可分享的对话'); return; }
  try {
    const d = await (await fetch(`/api/share/conversation/${encodeURIComponent(sid)}`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })).json();
    if (!d.ok) { alert('分享失败:' + (d.error || '')); return; }
    const link = location.origin + d.url;
    try { await navigator.clipboard.writeText(link); alert('只读分享链接已复制:\n' + link); }
    catch { prompt('只读分享链接(复制):', link); }
  } catch { alert('分享失败(网络)'); }
}
async function shareArtifact(path) {
  try {
    const d = await (await fetch('/api/share/artifact',
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }) })).json();
    if (!d.ok) { alert('发布失败:' + (d.error || '')); return; }
    const link = location.origin + d.url;
    try { await navigator.clipboard.writeText(link); alert('产物已发布,链接已复制:\n' + link); }
    catch { prompt('产物链接(复制):', link); }
  } catch { alert('发布失败(网络)'); }
}
function openShareMenu(e) {
  if (e) e.stopPropagation();
  const pick = prompt('分享/导出当前对话:\n1 = 复制只读分享链接\n2 = 导出 Markdown\n(输入 1 或 2)', '1');
  if (pick === '1') shareConversation();
  else if (pick === '2') exportConversation();
}

/* ── 自定义:提示词模板 ── */
async function renderTemplates() {
  const box = document.getElementById('tpl-list'); if (!box) return;
  try {
    const d = await (await fetch('/api/templates')).json();
    const rows = d.templates || [];
    box.innerHTML = rows.length ? rows.map(t => `
      <div class="expert-card" style="margin-bottom:8px">
        <h3>${escHtml(t.title || '(无标题)')}</h3>
        <div class="role" style="white-space:pre-wrap">${escHtml((t.content||'').slice(0,160))}</div>
        <div style="display:flex;gap:8px;margin-top:6px">
          <button class="btn-sm" onclick='insertTemplate(${JSON.stringify(t.content||"")})' data-i18n="tplInsert">插入对话框</button>
          <button class="btn-sm" onclick="delTemplate('${t.id}')" data-i18n="tplDelete">删除</button>
        </div>
      </div>`).join('') : `<div class="wb-empty" data-i18n="tplEmpty">还没有模板</div>`;
    applyI18n();
  } catch (e) { box.innerHTML = '<div class="wb-empty">加载失败</div>'; }
}
async function saveTemplate() {
  const title = document.getElementById('tpl-title').value.trim();
  const content = document.getElementById('tpl-content').value.trim();
  if (!title && !content) return;
  await fetch('/api/templates', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({title, content})});
  document.getElementById('tpl-title').value=''; document.getElementById('tpl-content').value='';
  renderTemplates();
}
async function delTemplate(id) {
  await fetch('/api/templates/'+id, {method:'DELETE'}); renderTemplates();
}
function insertTemplate(content) {
  const inp = document.getElementById('chat-inp');
  if (inp) { inp.value = (inp.value ? inp.value + '\n' : '') + content; inp.focus(); }
  closeCustomize();
}

/* ── 自定义:定时任务 ── */
async function renderSchedules() {
  const box = document.getElementById('sch-list'); if (!box) return;
  try {
    const d = await (await fetch('/api/tasks')).json();
    const rows = d.tasks || d || [];
    const fmtTs = ts => ts ? new Date(ts * 1000).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) : '—';
    box.innerHTML = (rows.length ? rows.map(t => `
      <div class="expert-card" style="margin-bottom:8px">
        <h3>${escHtml(t.name || t.id)} <span style="font-size:11px;color:${t.enabled===false?'#888':'var(--accent)'}">${t.enabled===false?'已停用':'启用'}</span></h3>
        <div class="role">${escHtml(t.schedule_type || '')} ${escHtml(t.at_hhmm || t.interval_sec ? '每'+t.interval_sec+'秒' : '')} · ${escHtml((t.prompt||'').slice(0,80))}</div>
        <div style="font-size:11px;color:var(--dim);margin-top:4px">上次: ${fmtTs(t.last_run)} · 下次: ${fmtTs(t.next_run)}</div>
        <button class="btn-sm" style="margin-top:6px" onclick="delSchedule('${t.id}')" data-i18n="schDelete">删除</button>
      </div>`).join('') : `<div class="wb-empty" data-i18n="schEmpty">还没有定时任务</div>`);
    applyI18n();
  } catch (e) { box.innerHTML = '<div class="wb-empty">加载失败</div>'; }
}
async function saveSchedule() {
  const name = document.getElementById('sch-name').value.trim();
  const prompt = document.getElementById('sch-prompt').value.trim();
  if (!name || !prompt) return;
  const schType = document.getElementById('sch-type').value;
  const body = {
    name, prompt,
    schedule_type: schType,
    at_hhmm: document.getElementById('sch-time').value,
    task_type: 'scheduled',
    interval_sec: schType === 'interval' ? parseInt(document.getElementById('sch-interval')?.value || '3600', 10) : null,
    deliver: document.getElementById('sch-deliver')?.value || 'chat',
    deliver_to: document.getElementById('sch-deliver-to')?.value || '',
  };
  await fetch('/api/tasks', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  document.getElementById('sch-name').value=''; document.getElementById('sch-prompt').value='';
  renderSchedules();
}
async function delSchedule(id) {
  await fetch('/api/tasks/'+id, {method:'DELETE'}); renderSchedules();
}

/* ── 自定义:连接器 + 凭据 ── */
async function renderConnectors() {
  const sbox = document.getElementById('sec-list');
  const cbox = document.getElementById('conn-list');
  try {
    const sd = await (await fetch('/api/secrets')).json();
    const secs = sd.secrets || [];
    sbox.innerHTML = secs.length ? secs.map(s => `
      <div class="expert-card" style="margin-bottom:8px">
        <h3>${escHtml(s.name)} ${s.has_secret ? '🔑' : ''}</h3>
        <div class="role">${escHtml(s.username||'(无用户名)')} · ${escHtml(s.url||'')}</div>
        <button class="btn-sm" style="margin-top:6px" onclick="delSecret('${escHtml(s.name)}')" data-i18n="connDelCred">删除</button>
      </div>`).join('') : `<div class="wb-empty" data-i18n="connNoCred">还没有凭据</div>`;
  } catch (e) { sbox.innerHTML = '<div class="wb-empty">加载失败</div>'; }
  try {
    const cd = await (await fetch('/api/connectors')).json();
    const cons = cd.connectors || [];
    cbox.innerHTML = cons.length ? cons.map(c => `
      <div class="expert-card" style="margin-bottom:8px">
        <h3>${escHtml(c.label || c.name)}</h3>
        <div class="role">${escHtml(c.base_url)} · 凭据:${escHtml(c.secret_ref||'无')} · ${c.actions.length} 个动作</div>
        <div style="font-size:11px;color:var(--dim);margin-top:4px">${c.actions.map(a=>escHtml(c.name+'.'+a.name)).join('、')}</div>
      </div>`).join('') : `<div class="wb-empty" data-i18n="connNoSvc">connectors/ 目录暂无服务</div>`;
    applyI18n();
  } catch (e) { cbox.innerHTML = '<div class="wb-empty">加载失败</div>'; }
}
async function saveSecret() {
  const name = document.getElementById('sec-name').value.trim();
  if (!name) return;
  await fetch('/api/secrets', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name,
      username: document.getElementById('sec-user').value.trim(),
      secret: document.getElementById('sec-secret').value,
      url: document.getElementById('sec-url').value.trim()})});
  ['sec-name','sec-user','sec-secret','sec-url'].forEach(id=>document.getElementById(id).value='');
  renderConnectors();
}
async function delSecret(name) {
  await fetch('/api/secrets/'+encodeURIComponent(name), {method:'DELETE'}); renderConnectors();
}

/* ── 自定义:偏好与人设 ── */
async function renderPrefs() {
  const box = document.getElementById('pref-list'); if (!box) return;
  try {
    const d = await (await fetch('/api/memory/preferences')).json();
    const rows = d.preferences || d.items || d || [];
    box.innerHTML = rows.length ? rows.map(p => `
      <div class="expert-card" style="margin-bottom:8px">
        <div class="role" style="color:var(--txt)">${escHtml(p.content || p)}</div>
        ${p.id != null ? `<button class="btn-sm" style="margin-top:6px" onclick='delPref(${p.id})' data-i18n="prefDelete">忘掉</button>` : ''}
      </div>`).join('') : `<div class="wb-empty" data-i18n="prefEmpty">Captain 还没记下关于你的偏好</div>`;
    applyI18n();
  } catch (e) { box.innerHTML = '<div class="wb-empty">加载失败</div>'; }
}
async function delPref(id) {
  try { await fetch('/api/memory/preferences/' + id, {method:'DELETE'}); } catch(e){}
  renderPrefs();
}

/* ── 设置:目标 Goals ── */
async function renderGoals() {
  const box = document.getElementById('goal-list'); if (!box) return;
  try {
    const d = await (await fetch('/api/goals')).json();
    const rows = d.goals || d || [];
    box.innerHTML = rows.length ? rows.map(g => `
      <div class="expert-card" style="margin-bottom:8px">
        <div class="role" style="color:var(--txt)">${escHtml(g.text || g.content || g)}</div>
        ${g.id != null ? `<button class="btn-sm" style="margin-top:6px" onclick="deleteGoal('${g.id}')">删除</button>` : ''}
      </div>`).join('') : `<div class="wb-empty">还没有设置目标</div>`;
  } catch { box.innerHTML = '<div class="wb-empty">加载失败</div>'; }
}
async function saveGoal() {
  const txt = (document.getElementById('goal-text')?.value || '').trim();
  if (!txt) return;
  try {
    await fetch('/api/goals', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({text: txt})});
    document.getElementById('goal-text').value = '';
    renderGoals();
  } catch {}
}
async function deleteGoal(id) {
  try { await fetch('/api/goals/' + encodeURIComponent(id), {method:'DELETE'}); } catch {}
  renderGoals();
}

/* ── 设置:监控 Monitors ── */
async function renderMonitors() {
  const box = document.getElementById('monitor-list'); if (!box) return;
  try {
    const d = await (await fetch('/api/monitors')).json();
    const rows = d.monitors || d || [];
    box.innerHTML = rows.length ? rows.map(m => `
      <div class="expert-card" style="margin-bottom:8px">
        <h3>${escHtml(m.name || m.id)}</h3>
        <div class="role">${escHtml(m.source||'')} · ${escHtml(m.monitor_type||m.type||'')} · 每 ${escHtml(String(m.interval_sec||60))} 秒</div>
        <div style="font-size:11px;color:var(--dim);margin-top:2px">触发时: ${escHtml(m.action||'通知')}</div>
        <button class="btn-sm" style="margin-top:6px" onclick="deleteMonitor('${m.id}')">删除</button>
      </div>`).join('') : `<div class="wb-empty">还没有监控任务</div>`;
  } catch { box.innerHTML = '<div class="wb-empty">加载失败</div>'; }
}
async function saveMonitor() {
  const name = (document.getElementById('mon-name')?.value || '').trim();
  const source = (document.getElementById('mon-source')?.value || '').trim();
  if (!name || !source) return;
  const body = {
    name,
    source,
    action: document.getElementById('mon-action')?.value || '',
    monitor_type: document.getElementById('mon-type')?.value || 'keyword',
    interval_sec: parseInt(document.getElementById('mon-interval')?.value || '60', 10),
  };
  try {
    await fetch('/api/monitors', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    ['mon-name','mon-source','mon-action'].forEach(id => { const el = document.getElementById(id); if (el) el.value=''; });
    renderMonitors();
  } catch {}
}
async function deleteMonitor(id) {
  try { await fetch('/api/monitors/' + encodeURIComponent(id), {method:'DELETE'}); } catch {}
  renderMonitors();
}

/* ── 自定义:写作助手 ── */
function renderWritingAssist() {
  // Nothing to load from server; just ensure UI is clean
  const resultBox = document.getElementById('writing-result');
  const saveBtn = document.getElementById('writing-save-btn');
  if (resultBox) resultBox.style.display = 'none';
  if (saveBtn) saveBtn.style.display = 'none';
}
function setWritingInstruction(txt) {
  const el = document.getElementById('writing-instruction');
  if (el) { el.value = txt; el.focus(); }
}
async function runWritingAssist() {
  const text = (document.getElementById('writing-text')?.value || '').trim();
  const instruction = (document.getElementById('writing-instruction')?.value || '').trim();
  if (!text) return;
  const prompt = instruction ? `${instruction}:\n\n${text}` : text;
  const resultBox = document.getElementById('writing-result');
  const outputEl = document.getElementById('writing-output');
  const saveBtn = document.getElementById('writing-save-btn');
  if (outputEl) outputEl.value = '处理中…';
  if (resultBox) resultBox.style.display = '';
  try {
    const d = await (await fetch('/api/writing/assist', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({text, instruction}),
    })).json();
    const result = d.result || d.output || d.text || '';
    if (outputEl) outputEl.value = result;
    if (saveBtn) saveBtn.style.display = result ? '' : 'none';
    // Fallback: if no backend endpoint, send to chat
    if (!result && d.error) {
      if (outputEl) outputEl.value = '（后端不支持独立写作接口，已将任务发送到对话）';
      sendMessage(prompt);
    }
  } catch {
    // No writing API — fallback to chat
    if (outputEl) outputEl.value = '（已将任务发送到对话）';
    sendMessage(prompt);
  }
}
async function saveWritingResult() {
  const output = (document.getElementById('writing-output')?.value || '').trim();
  const title = (document.getElementById('writing-save-title')?.value || '').trim() || '写作结果.md';
  if (!output) return;
  try {
    await fetch('/api/artifacts', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({filename: title, content: output})});
    if (typeof toast === 'function') toast('已保存到产物: ' + title);
  } catch { if (typeof toast === 'function') toast('保存失败'); }
}
function copyWritingOutput() {
  const el = document.getElementById('writing-output');
  if (!el) return;
  try { navigator.clipboard.writeText(el.value); if (typeof toast === 'function') toast('已复制'); } catch {}
}

/* ── 设置:治理 Audit Log ── */
async function loadAuditLog() {
  const box = document.getElementById('audit-log-table'); if (!box) return;
  box.innerHTML = '加载中…';
  try {
    const d = await (await fetch('/api/audit?limit=50')).json();
    const rows = d.logs || d.entries || d || [];
    if (!rows.length) { box.innerHTML = '<div class="wb-empty">暂无审计日志</div>'; return; }
    box.innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead><tr style="color:var(--dim);text-align:left">
        <th style="padding:4px 8px">时间</th><th style="padding:4px 8px">操作</th>
        <th style="padding:4px 8px">裁决</th><th style="padding:4px 8px">风险</th>
      </tr></thead>
      <tbody>${rows.map(r => {
        const ts = r.ts || r.timestamp || r.created_at;
        const time = ts ? new Date(ts*1000).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) : '—';
        const dec = r.decision || r.verdict || '';
        const color = dec==='allow'?'#3cb371':dec==='block'?'#c84444':'#c89b3c';
        return `<tr style="border-top:1px solid var(--border)">
          <td style="padding:4px 8px;color:var(--dim)">${escHtml(time)}</td>
          <td style="padding:4px 8px">${escHtml(r.action||r.tool||r.capability||'')}</td>
          <td style="padding:4px 8px;color:${color}">${escHtml(dec)}</td>
          <td style="padding:4px 8px;color:var(--dim)">${escHtml(r.risk||r.risk_level||'')}</td>
        </tr>`;
      }).join('')}</tbody></table>`;
  } catch { box.innerHTML = '<div class="wb-empty">加载失败</div>'; }
}

function govDecisionLabel(decision, labels) {
  const map = labels?.decisions || {};
  if (currentLang === 'zh') {
    return map[decision] || { allow: '放行', ask: '需确认', block: '拒绝' }[decision] || decision;
  }
  return { allow: 'Allow', ask: 'Confirm', block: 'Block' }[decision] || decision;
}

function govRuleLabel(rule, ruleLabel) {
  if (ruleLabel) return ruleLabel;
  const map = {
    'auto': currentLang === 'zh' ? '自动放行' : 'Auto allow',
    'confirm:fs.write': currentLang === 'zh' ? '写文件' : 'Write file',
    'confirm:gui': currentLang === 'zh' ? '控制电脑' : 'GUI control',
    'confirm:payment': currentLang === 'zh' ? '花钱/支付' : 'Payment',
    'memory:auto': currentLang === 'zh' ? '记住偏好' : 'Remember',
    'task:auto': currentLang === 'zh' ? '本任务已授权' : 'Task authorized',
  };
  if (map[rule]) return map[rule];
  if (rule.startsWith('confirm:shell:')) return currentLang === 'zh' ? '删改命令' : 'Shell modify/delete';
  if (rule.startsWith('confirm:')) return currentLang === 'zh' ? '需确认操作' : 'Confirm required';
  if (rule.startsWith('forbidden_path:')) return currentLang === 'zh' ? '敏感路径' : 'Forbidden path';
  return rule;
}

async function loadGovStats() {
  const el = document.getElementById('gov-stats-table');
  const sumEl = document.getElementById('gov-stats-summary');
  try {
    const res = await fetch('/api/governance/stats?days=7');
    const data = await res.json();
    const rows = data.rows || [];
    const summary = data.summary || {};
    const labels = data.labels || {};

    if (!rows.length && !data.total) {
      sumEl.style.display = 'none';
      el.textContent = t('govNoData');
      return;
    }

    const hitPct = Math.round((summary.hit_rate || 0) * 100);
    const reusePct = Math.round((summary.reuse_rate || 0) * 100);
    sumEl.style.display = 'block';
    // 概览数字(pills)+ 裁决分布(放行/需确认/拒绝)三色条
    sumEl.innerHTML = `
      <div class="stat-pills">
        <div class="stat-pill"><b>${data.total || 0}</b><span>${t('govTotal')}</span></div>
        <div class="stat-pill"><b>${hitPct}%</b><span>${t('govHitRate')}</span></div>
        <div class="stat-pill"><b>${summary.block || 0}</b><span>${t('govBlock')}</span></div>
        <div class="stat-pill"><b>${reusePct}%</b><span>${t('govReuse')}</span></div>
      </div>
      <div style="font-size:12px;color:var(--dim);margin:6px 0 2px">${t('govDist')}</div>` +
      miniBars([
        { label: t('govAllow'), value: summary.allow || 0, color: '#4caf79' },
        { label: t('govAsk'), value: summary.ask || 0, color: '#f5c842' },
        { label: t('govBlock'), value: summary.block || 0, color: '#e85555' },
      ]);

    // 命中规则 Top(按总次数)横条
    const ruleBars = rows.map(row => {
      const counts = row.counts || {};
      const total = Object.values(counts).reduce((a, b) => a + b, 0);
      return { label: govRuleLabel(row.rule, row.rule_label), value: total, display: String(total) };
    });
    el.innerHTML = `<div style="font-size:12px;color:var(--dim);margin:12px 0 2px">${t('govTopRules')}</div>`
      + miniBars(ruleBars, 'var(--accent)');
  } catch {
    sumEl.style.display = 'none';
    el.textContent = t('govLoadFailed');
  }
}

function loadConfig() {
  try { return JSON.parse(localStorage.getItem('agent-config') || '{}'); }
  catch { return {}; }
}

async function fetchConfiguredModels(selected) {
  const cur = selected || 'deepseek-v4-flash';
  try {
    const res = await fetch(`/api/models?current=${encodeURIComponent(cur)}`);
    const data = await res.json();
    return (data.models || []).filter(m => m.configured !== false);
  } catch {
    return [];
  }
}

async function fetchAllModels(current) {
  const cur = current || 'deepseek-v4-flash';
  try {
    const res = await fetch(`/api/models?all=true&current=${encodeURIComponent(cur)}`);
    const data = await res.json();
    return data.models || [];
  } catch {
    return [];
  }
}

async function initComposerModel() {
  const cfg = loadConfig();
  let modelId = cfg.model || '';
  try {
    const res = await fetch('/api/config');
    const srv = await res.json();
    if (srv.model) modelId = srv.model;
  } catch { /* 离线 */ }
  const models = await fetchAllModels(modelId || 'deepseek-v4-flash');
  const configured = models.filter(m => m.configured);
  let picked = modelId || 'deepseek-v4-flash';
  if (!configured.some(m => m.id === picked)) {
    picked = configured.length ? configured[0].id : (models[0]?.id || picked);
  }
  updateModelPill(picked, models);
  if (picked !== cfg.model) {
    cfg.model = picked;
    localStorage.setItem('agent-config', JSON.stringify(cfg));
    try {
      await fetch('/api/config', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: picked }),
      });
    } catch { /* 离线 */ }
  }
  return picked;
}

function updateModelPill(modelId, models) {
  const pill = document.getElementById('model-pill-label');
  if (!pill) return;
  const m = (models || []).find(x => x.id === modelId);
  const label = m?.label || modelId || t('lblModel');
  pill.textContent = label.length > 18 ? label.slice(0, 16) + '…' : label;
}

async function loadModelOptions(selected) {
  const sel = document.getElementById('cfg-model');
  const hint = document.getElementById('model-hint-empty');
  sel.innerHTML = '';
  const cur = selected || 'deepseek-v4-flash';
  const models = await fetchConfiguredModels(cur);
  if (!models.length) {
    if (hint) {
      hint.style.display = 'block';
      hint.textContent = t('noModelsConfigured');
    }
    sel.disabled = true;
    updateModelPill(cur, []);
    return [];
  }
  if (hint) hint.style.display = 'none';
  sel.disabled = false;
  sel.innerHTML = '';                 // 再清一次:防并发竞态把选项追加成重复
  const _seen = new Set();
  models.forEach(m => {
    if (_seen.has(m.id)) return; _seen.add(m.id);
    const opt = document.createElement('option');
    opt.value = m.id;
    opt.textContent = m.label || m.id;
    sel.appendChild(opt);
  });
  const picked = models.some(m => m.id === cur) ? cur : models[0].id;
  sel.value = picked;
  updateModelPill(picked, models);
  return models;
}

function closeModelPicker() {
  document.getElementById('model-picker')?.classList.remove('open');
}

async function toggleModelPicker(e) {
  e?.stopPropagation();
  const picker = document.getElementById('model-picker');
  if (!picker) return;
  const open = picker.classList.toggle('open');
  if (open) await renderModelPicker();
  else closeModelPicker();
}

async function renderModelPicker() {
  const picker = document.getElementById('model-picker');
  if (!picker) return;
  const cfg = loadConfig();
  let cur = cfg.model || 'deepseek-v4-flash';
  try {
    const res = await fetch('/api/config');
    const srv = await res.json();
    if (srv.model) cur = srv.model;
  } catch { /* 离线 */ }
  const models = await fetchConfiguredModels(cur);
  picker.innerHTML = '';
  if (!models.length) {
    picker.innerHTML = `<div class="model-picker-empty">${escHtml(t('noModelsConfigured'))}</div>`;
    return;
  }
  const _seenP = new Set();
  models.forEach(m => {
    if (_seenP.has(m.id)) return; _seenP.add(m.id);
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'model-picker-item' + (m.id === cur ? ' active' : '');
    btn.textContent = m.label || m.id;
    btn.onclick = (ev) => { ev.stopPropagation(); selectModel(m.id); };
    picker.appendChild(btn);
  });
}

async function selectModel(modelId) {
  const cfg = loadConfig();
  cfg.model = modelId;
  localStorage.setItem('agent-config', JSON.stringify(cfg));
  try {
    await fetch('/api/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: modelId }),
    });
    if (ws && ws.readyState === 1) ws.send(JSON.stringify(wsInitPayload()));
  } catch { /* 离线 */ }
  const models = await fetchConfiguredModels(modelId);
  updateModelPill(modelId, models);
  const sel = document.getElementById('cfg-model');
  if (sel && !sel.disabled) sel.value = modelId;
  closeModelPicker();
}

const MODEL_KEY_FIELDS = { deepseek: 'key-deepseek', openai: 'key-openai', claude: 'key-claude' };

function saveAccessToken() {
  const el = document.getElementById('cfg-access-token');
  const result = document.getElementById('access-token-result');
  const v = (el?.value || '').trim();
  setAccessToken(v);
  if (el) { el.value = ''; el.placeholder = v ? '已设置(留空清除)' : '未设置'; }
  if (result) result.textContent = v ? '已保存。重连后生效(刷新页面或重开会话)。' : '已清除访问令牌。';
}

function loadAccessTokenField() {
  const el = document.getElementById('cfg-access-token');
  if (el) { el.value = ''; el.placeholder = getAccessToken() ? '已设置(留空清除)' : '未设置'; }
}

let _customProviders = [];   // 本地新加、尚未保存的自定义端点 id

// 渲染模型接入列表:每行一个接口,含状态徽标 + key/base_url/model 输入 + 测试/保存
async function loadModelKeys() {
  const box = document.getElementById('model-providers');
  if (!box) return;
  let keys = {};
  try { keys = (await (await fetch('/api/keys')).json()).keys || {}; } catch { return; }
  // 把本地新加的自定义端点也并进来(还没保存,后端列表里没有)
  for (const id of _customProviders) if (!keys[id]) keys[id] = { label: id, kind:'chat', builtin:false, configured:false, verified:false, key:'', base_url:'', model:'' };
  const order = Object.keys(keys).sort((a,b)=> (keys[b].builtin?1:0)-(keys[a].builtin?1:0));
  box.innerHTML = order.map(prov => {
    const k = keys[prov];
    const badge = k.verified ? '<span style="color:#3a9">✓ 已验证</span>'
               : k.configured ? '<span style="color:var(--accent)">● 已配置</span>'
               : '<span style="color:var(--dim)">○ 未配置</span>';
    const isCustom = !k.builtin;
    const showUrlModel = isCustom || k.kind === 'vision' || k.kind === 'image';
    return `<div class="expert-card" style="margin-bottom:8px" data-prov="${escHtml(prov)}">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <h3 style="margin:0">${escHtml(k.label||prov)} <span style="font-size:11px;color:var(--dim)">${escHtml(k.kind)}</span></h3>
        <span style="font-size:12px">${badge}</span>
      </div>
      <input class="field-input mk-key" type="password" style="margin-top:6px" placeholder="${k.configured?'已配置(留空不改动)':'API Key'}" autocomplete="off"/>
      ${showUrlModel ? `<input class="field-input mk-url" style="margin-top:6px" placeholder="base_url(如 https://api.moonshot.cn/v1)" value="${escHtml(k.base_url||'')}"/>
      <input class="field-input mk-model" style="margin-top:6px" placeholder="模型名(如 moonshot-v1-8k)" value="${escHtml(k.model||'')}"/>` : ''}
      <div style="display:flex;gap:8px;margin-top:6px">
        <button class="btn-sm primary" onclick="saveProvider('${escHtml(prov)}')" data-i18n="mkSave">保存</button>
        <button class="btn-sm" onclick="testProvider('${escHtml(prov)}')" data-i18n="mkTest">测试连接</button>
        ${isCustom ? `<button class="btn-sm" onclick="deleteProvider('${escHtml(prov)}')" data-i18n="mkDelete">删除</button>`:''}
        <span class="mk-status" style="font-size:12px;color:var(--dim);align-self:center"></span>
      </div>
    </div>`;
  }).join('');
  applyI18n();
}

function _provEls(prov) {
  const card = document.querySelector(`#model-providers [data-prov="${CSS.escape(prov)}"]`);
  if (!card) return {};
  return { card, key: card.querySelector('.mk-key'), url: card.querySelector('.mk-url'),
           model: card.querySelector('.mk-model'), status: card.querySelector('.mk-status') };
}

async function saveProvider(prov) {
  const e = _provEls(prov); if (!e.card) return;
  const body = { provider: prov, key: (e.key?.value||'').trim() };
  if (e.url) body.base_url = (e.url.value||'').trim();
  if (e.model) body.model = (e.model.value||'').trim();
  e.status.textContent = '保存中…';
  try {
    const d = await (await fetch('/api/keys', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})).json();
    if (d.ok) { e.status.textContent = '已保存'; _customProviders = _customProviders.filter(x=>x!==prov); await loadModelKeys();
      try { await renderModelPicker(); } catch {} }
    else e.status.textContent = '保存失败';
  } catch { e.status.textContent = '保存失败(网络)'; }
}

async function testProvider(prov) {
  const e = _provEls(prov); if (!e.card) return;
  const body = { provider: prov };
  if (e.key && e.key.value.trim()) body.key = e.key.value.trim();
  if (e.url) body.base_url = (e.url.value||'').trim();
  if (e.model) body.model = (e.model.value||'').trim();
  e.status.textContent = '测试中…';
  try {
    const d = await (await fetch('/api/models/test', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})).json();
    if (d.ok) { e.status.innerHTML = `<span style="color:#3a9">✓ 连通 ${d.latency_ms||''}ms</span>`; await loadModelKeys(); }
    else e.status.innerHTML = `<span style="color:#d66">✗ ${escHtml(d.error||'失败')}</span>`;
  } catch { e.status.textContent = '测试失败(网络)'; }
}

async function deleteProvider(prov) {
  _customProviders = _customProviders.filter(x=>x!==prov);
  try { await fetch('/api/keys/'+encodeURIComponent(prov), {method:'DELETE'}); } catch {}
  await loadModelKeys();
}

function addCustomProvider() {
  const name = (prompt('给这个自定义端点起个 id(英文,如 kimi):')||'').trim().toLowerCase().replace(/[^a-z0-9_]/g,'');
  if (!name) return;
  if (!_customProviders.includes(name)) _customProviders.push(name);
  loadModelKeys();
}

async function loadUsageStats() {
  const tokEl = document.getElementById('usage-total-tokens');
  const costEl = document.getElementById('usage-total-cost');
  const tasksEl = document.getElementById('usage-total-tasks');
  const table = document.getElementById('usage-daily-table');
  try {
    const res = await fetch('/api/usage?days=30');
    const data = await res.json();
    tokEl.textContent = formatTokenCount(data.total_tokens || 0);
    costEl.textContent = '$' + (data.total_cost_usd || 0).toFixed(4);
    tasksEl.textContent = String(data.tasks || 0);
    const rows = data.by_day || [];
    if (!rows.length) {
      table.textContent = t('usageNoData');
      return;
    }
    // 每日 tokens 横条图(近 30 天),并在条上标注费用/任务数。
    const bars = rows.map(r => ({
      label: escHtml(r.date),
      value: r.tokens || 0,
      display: `${formatTokenCount(r.tokens)} · $${(r.cost_usd || 0).toFixed(4)}`,
    }));
    table.innerHTML = miniBars(bars, 'var(--accent)');
  } catch {
    table.textContent = t('usageLoadFailed');
  }
}

/* 迷你横条图:items=[{label,value,display?}],按最大值归一化宽度。零依赖、主题色。 */
function miniBars(items, color) {
  color = color || 'var(--accent)';
  const max = Math.max(1, ...items.map(i => Number(i.value) || 0));
  return '<div class="mini-bars">' + items.map(i => {
    const pct = Math.max(2, Math.round((Number(i.value) || 0) / max * 100));
    const val = i.display != null ? i.display : (Number(i.value) || 0);
    return `<div class="mini-bar-row">
      <span class="mini-bar-label" title="${escHtml(String(i.label))}">${escHtml(String(i.label))}</span>
      <span class="mini-bar-track"><span class="mini-bar-fill" style="width:${pct}%;background:${i.color || color}"></span></span>
      <span class="mini-bar-val">${escHtml(String(val))}</span>
    </div>`;
  }).join('') + '</div>';
}

function formatTokenCount(n) {
  n = Math.max(0, parseInt(n, 10) || 0);
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(/\.0$/, '') + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, '') + 'K';
  return String(n);
}

async function loadSettingsUI() {
  const cfg = loadConfig();
  try {
    const res = await fetch('/api/config');
    const srv = await res.json();
    if (srv.model) cfg.model = srv.model;
    else if (srv.provider) cfg.model = srv.provider;
    if (srv.max_cost_usd != null) cfg.maxCost = srv.max_cost_usd;
    if (srv.governance_mode) cfg.governanceMode = srv.governance_mode;
  } catch { /* 离线 */ }
  await loadModelOptions(cfg.model || 'deepseek-v4-flash');
  await loadModelKeys();
  loadAccessTokenField();
  document.getElementById('cfg-governance-mode').value = cfg.governanceMode || 'balanced';
  document.getElementById('cfg-max-cost').value = cfg.maxCost ?? '';
  // 0 / 空 = 无限制(显示为空,placeholder 提示)
  document.getElementById('cfg-max-steps').value =
    (cfg.maxSteps === 0 || cfg.maxSteps === '0' || cfg.maxSteps === '' || cfg.maxSteps == null) ? '' : cfg.maxSteps;
  // 频道配置从服务端加载
  try {
    const res = await fetch('/api/channels');
    const data = await res.json();
    const c = data.config || {};
    const en = data.enabled || {};
    if (c.email) {
      document.getElementById('email-imap').value = c.email.imap || '';
      document.getElementById('email-smtp').value = c.email.smtp || '';
      document.getElementById('email-user').value = c.email.user || '';
      const ip = document.getElementById('email-imap-port'); if (ip) ip.value = c.email.imap_port || '';
      const sp = document.getElementById('email-smtp-port'); if (sp) sp.value = c.email.smtp_port || '';
      const al = document.getElementById('email-allowed'); if (al) al.value = c.email.allowed || '';
      if (c.email.password) document.getElementById('email-pass').placeholder = '已配置(留空不改动)';
    }
    setChannelStatus('email', en.email);
  } catch { /* 离线 */ }
}

function emailChannelValues() {
  const v = {
    imap: document.getElementById('email-imap').value,
    smtp: document.getElementById('email-smtp').value,
    user: document.getElementById('email-user').value,
    password: document.getElementById('email-pass').value,
  };
  const ip = document.getElementById('email-imap-port'); if (ip && ip.value) v.imap_port = ip.value;
  const sp = document.getElementById('email-smtp-port'); if (sp && sp.value) v.smtp_port = sp.value;
  const al = document.getElementById('email-allowed'); if (al) v.allowed = al.value;
  return v;
}

function setChannelStatus(name, enabled) {
  const el = document.getElementById(`${name}-status`);
  if (!el) return;
  el.textContent = enabled ? '已启用' : '未启用';
  el.classList.toggle('ok', !!enabled);
}

async function saveSettings() {
  const cfg = {
    model: document.getElementById('cfg-model').value,
    maxCost: document.getElementById('cfg-max-cost').value,
    maxSteps: document.getElementById('cfg-max-steps').value,
  };
  localStorage.setItem('agent-config', JSON.stringify(cfg));
  try {
    await fetch('/api/config', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({
        model: cfg.model,
        max_cost_usd: cfg.maxCost === '' ? null : cfg.maxCost,
        governance_mode: document.getElementById('cfg-governance-mode').value,
        max_steps: (cfg.maxSteps === '' || cfg.maxSteps == null) ? 0 : Number(cfg.maxSteps),
      }),
    });
    if (ws && ws.readyState === 1) ws.send(JSON.stringify(wsInitPayload()));
  } catch { /* ignore */ }
  // 保存邮件渠道配置到服务端
  await saveChannel('email', emailChannelValues());
  closeSettings();
}

async function saveChannel(channel, values) {
  try {
    await fetch('/api/channels', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ channel, values }),
    });
  } catch { /* ignore */ }
}

async function testEmail() {
  const el = document.getElementById('email-test-result');
  el.textContent = '测试中…';
  // 先保存当前填写的配置再测
  await saveChannel('email', emailChannelValues());
  try {
    const res = await fetch('/api/channels/email/test', { method: 'POST' });
    const r = await res.json();
    if (r.ok) el.innerHTML = '<span style="color:var(--green)">✓ IMAP + SMTP 连接成功</span>';
    else el.innerHTML = `<span style="color:var(--red)">✗ ${escHtml(r.error||'失败')}</span>`;
  } catch (e) {
    el.innerHTML = `<span style="color:var(--red)">✗ ${escHtml(String(e))}</span>`;
  }
}


async function restartChannel(name) {
  // 先落盘当前表单,再热启用
  if (name === 'email') await saveChannel('email', emailChannelValues());
  try {
    const res = await fetch(`/api/channels/${name}/restart`, { method: 'POST' });
    const r = await res.json();
    setChannelStatus(name, r.ok);
    if (!r.ok) alert(`${name} 启用失败,请检查配置`);
  } catch (e) { alert('请求失败:' + e); }
}

/* ── 定时任务 ── */
function openTaskForm() {
  document.getElementById('task-form').style.display = 'block';
}
function closeTaskForm() {
  document.getElementById('task-form').style.display = 'none';
}
function toggleTaskSchedule() {
  const t = document.getElementById('task-sched-type').value;
  document.getElementById('task-every-wrap').style.display = t === 'every' ? '' : 'none';
  document.getElementById('task-daily-wrap').style.display = t === 'daily' ? '' : 'none';
}

async function refreshTasks() {
  const list = document.getElementById('task-list');
  try {
    const res = await fetch('/api/tasks');
    const data = await res.json();
    const tasks = data.tasks || [];
    if (!tasks.length) {
      list.innerHTML = '<div style="font-size:12px;color:var(--dim);padding:8px">暂无定时任务</div>';
      return;
    }
    list.innerHTML = '';
    tasks.forEach(t => {
      const row = document.createElement('div');
      row.className = 'task-row' + (t.enabled ? '' : ' disabled');
      const sched = t.schedule_type === 'daily'
        ? `每天 ${t.at_hhmm}` : `每 ${t.interval_sec}s`;
      const last = t.last_run ? new Date(t.last_run*1000).toLocaleString('zh-CN') : '从未';
      const next = t.next_run ? new Date(t.next_run*1000).toLocaleString('zh-CN') : '-';
      row.innerHTML = `
        <div class="task-info">
          <div class="task-name">${escHtml(t.name)}</div>
          <div class="task-meta">${sched} · ${t.enabled?'启用':'暂停'} · 上次:${last} · 下次:${next}</div>
          <div class="task-meta" style="margin-top:2px">${escHtml(t.prompt.slice(0,80))}</div>
          ${t.last_result ? `<div class="task-result">${escHtml(t.last_result.slice(0,120))}</div>` : ''}
        </div>
        <div class="task-actions">
          <button class="btn-sm" onclick="runTaskNow('${t.id}')" title="立即运行">▶</button>
          <button class="btn-sm" onclick="toggleTask('${t.id}',${!t.enabled})">${t.enabled?'⏸':'▶'}</button>
          <button class="btn-sm" onclick="deleteTask('${t.id}')" style="color:var(--red)">✕</button>
        </div>`;
      list.appendChild(row);
    });
  } catch {
    list.innerHTML = '<div style="color:var(--red);font-size:12px">加载失败</div>';
  }
}

function toggleTaskType() {
  const t = document.getElementById('task-type').value;
  document.getElementById('task-prompt-wrap').style.display = t === 'memory_forget' ? 'none' : '';
}

function fillMemoryForgetTask() {
  document.getElementById('task-type').value = 'memory_forget';
  document.getElementById('task-name').value = '每周记忆清理';
  toggleTaskType();
  openTaskForm();
}

async function createTask() {
  const taskType = document.getElementById('task-type').value;
  const body = {
    name: document.getElementById('task-name').value.trim() || '未命名',
    prompt: document.getElementById('task-prompt').value.trim(),
    task_type: taskType,
    schedule_type: document.getElementById('task-sched-type').value,
    interval_sec: parseInt(document.getElementById('task-interval').value) || 3600,
    at_hhmm: document.getElementById('task-at').value || '09:00',
    deliver: document.getElementById('task-deliver').value,
    deliver_to: document.getElementById('task-deliver-to').value,
  };
  if (taskType === 'memory_forget') body.prompt = body.prompt || '维护:清理低价值长期记忆';
  else if (!body.prompt) { document.getElementById('task-prompt').focus(); return; }
  await fetch('/api/tasks', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
  closeTaskForm();
  refreshTasks();
}

async function runTaskNow(id) {
  const res = await fetch(`/api/tasks/${id}/run`, { method:'POST' });
  const r = await res.json();
  if (r.ok) refreshTasks();
  else alert(r.error || '运行失败');
}

async function toggleTask(id, enabled) {
  await fetch(`/api/tasks/${id}`, { method:'PATCH', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ enabled }) });
  refreshTasks();
}

async function deleteTask(id) {
  if (!confirm('确定删除此定时任务?')) return;
  await fetch(`/api/tasks/${id}`, { method:'DELETE' });
  refreshTasks();
}

/* ══ 历史记录(服务端持久化会话)════════════════════════════════ */
function getPinnedSessions() {
  try { return JSON.parse(localStorage.getItem('captain-pinned') || '[]'); }
  catch { return []; }
}

function togglePinSession(id) {
  const pins = getPinnedSessions();
  const idx = pins.indexOf(id);
  if (idx >= 0) pins.splice(idx, 1);
  else pins.push(id);
  localStorage.setItem('captain-pinned', JSON.stringify(pins));
  renderSessions(allSessions);
}

async function onHistorySearch(q) {
  historySearchQuery = (q || '').trim().toLowerCase();
  if (!historySearchQuery) {
    renderSessions(allSessions);
    return;
  }
  try {
    const d = await (await fetch('/api/sessions/search?q=' + encodeURIComponent(historySearchQuery))).json();
    renderSessions(d.sessions || d || []);
  } catch {
    renderSessions(allSessions.filter(s => {
      const title = (s.title || s.id || '').toLowerCase();
      return title.includes(historySearchQuery);
    }));
  }
}

function sessionDayGroup(ts) {
  const d = new Date((ts || 0) * 1000);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const that = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diff = (today - that) / 86400000;
  if (diff < 1) return 'today';
  if (diff < 2) return 'yesterday';
  return 'older';
}

function appendHistoryItem(list, s, pinned) {
  const wrap = document.createElement('div');
  wrap.className = 'history-item-wrap';
  wrap.tabIndex = 0;
  const d = document.createElement('div');
  const isCurrent = s.id === sessionId && currentView === 'chat';
  d.className = 'history-item' + (isCurrent ? ' current' : '');
    const prefix = sessionIcon(s.id, s.kind);
    const baseTitle = s.title || t('untitledChat');
    d.textContent = prefix + projectPrefix(s) + baseTitle;
    d.title = (s.title || s.id) + ' · ' + t('renameHint');
    let clickTimer = null;
    d.onclick = (e) => {
      if (e.target.closest('.history-rename-input')) return;
      clearTimeout(clickTimer);
      clickTimer = setTimeout(() => switchToSession(s.id), 220);
    };
    d.ondblclick = (e) => {
      e.stopPropagation();
      clearTimeout(clickTimer);
      startRenameSession(s, d);
    };
  const actions = document.createElement('div');
  actions.className = 'history-actions';
  const renameBtn = document.createElement('button');
  renameBtn.type = 'button';
  renameBtn.className = 'history-rename-btn';
  renameBtn.setAttribute('aria-label', t('renameChat'));
  renameBtn.textContent = '✎';
  renameBtn.onmousedown = (e) => { e.preventDefault(); e.stopPropagation(); };
  renameBtn.onclick = (e) => { e.stopPropagation(); startRenameSession(s, d); };
  const pinBtn = document.createElement('button');
  pinBtn.type = 'button';
  pinBtn.className = 'history-pin-btn' + (pinned ? ' pinned' : '');
  pinBtn.setAttribute('aria-label', t('pinChat'));
  pinBtn.textContent = pinned ? '📌' : '○';
  pinBtn.onmousedown = (e) => { e.preventDefault(); e.stopPropagation(); };
  pinBtn.onclick = (e) => { e.stopPropagation(); togglePinSession(s.id); };
  const del = document.createElement('button');
  del.type = 'button';
  del.className = 'history-del';
  del.setAttribute('aria-label', t('deleteChat'));
  del.textContent = '×';
  del.onmousedown = (e) => { e.preventDefault(); e.stopPropagation(); };
  del.onclick = (e) => { e.stopPropagation(); deleteSessionById(s.id); };
  actions.appendChild(renameBtn);
  actions.appendChild(pinBtn);
  actions.appendChild(del);
  wrap.appendChild(d);
  wrap.appendChild(actions);
  list.appendChild(wrap);
}

function removePinnedSession(id) {
  const pins = getPinnedSessions().filter(x => x !== id);
  localStorage.setItem('captain-pinned', JSON.stringify(pins));
}

function waitForTaskDone(ms) {
  return new Promise(resolve => {
    if (!taskRunning) { resolve(); return; }
    const start = Date.now();
    const timer = setInterval(() => {
      if (!taskRunning || Date.now() - start >= ms) {
        clearInterval(timer);
        resolve();
      }
    }, 80);
  });
}

async function refreshSessions() {
  try {
    const res = await fetch('/api/sessions');
    const data = await res.json();
    allSessions = data.sessions || [];
    renderSessions(allSessions);
    syncChatTopbarTitle();
    if (currentView === 'project' && _currentProject) {
      const p = _projectsCache.find(x => x.id === _currentProject);
      if (p) renderProjectDetail(p);
    }
  } catch { /* 离线则忽略 */ }
}

function renderSessions(sessions) {
  const list = document.getElementById('history-list');
  const searchEl = document.getElementById('history-search');
  sessions = (sessions || []).filter(sessionBelongsToWorkMode);
  if (searchEl && !searchEl.placeholder) searchEl.placeholder = t('historySearch');
  list.innerHTML = '';
  if (!sessions.length) {
    list.innerHTML = `<div style="font-size:11px;color:var(--dim);padding:4px 6px">${t('noHistory')}</div>`;
    return;
  }
  const pins = getPinnedSessions();
  let items = [...sessions].sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));
  if (historySearchQuery) {
    items = items.filter(s => ((s.title || '') + s.id).toLowerCase().includes(historySearchQuery));
    if (!items.length) {
      list.innerHTML = `<div style="font-size:11px;color:var(--dim);padding:4px 6px">${t('noSearchResults')}</div>`;
      return;
    }
    items.forEach(s => appendHistoryItem(list, s, pins.includes(s.id)));
    return;
  }
  const pinned = items.filter(s => pins.includes(s.id));
  const rest = items.filter(s => !pins.includes(s.id));
  const groups = { today: [], yesterday: [], older: [] };
  rest.forEach(s => groups[sessionDayGroup(s.updated_at)].push(s));
  if (pinned.length) {
    const lbl = document.createElement('div');
    lbl.className = 'history-group-label';
    lbl.textContent = t('grpPinned');
    list.appendChild(lbl);
    pinned.forEach(s => appendHistoryItem(list, s, true));
  }
  [['today', 'grpToday'], ['yesterday', 'grpYesterday'], ['older', 'grpOlder']].forEach(([key, labelKey]) => {
    if (!groups[key].length) return;
    const lbl = document.createElement('div');
    lbl.className = 'history-group-label';
    lbl.textContent = t(labelKey);
    list.appendChild(lbl);
    groups[key].forEach(s => appendHistoryItem(list, s, false));
  });
}

async function renameSessionApi(id, title) {
  const url = `/api/sessions/${encodeURIComponent(id)}`;
  const body = JSON.stringify({ title });
  const headers = { 'Content-Type': 'application/json' };
  let res = await fetch(url, { method: 'PATCH', headers, body });
  if (res.status === 405) {
    res = await fetch(`${url}/rename`, { method: 'POST', headers, body });
  }
  return res;
}

function startRenameSession(s, el) {
  if (el.querySelector('.history-rename-input')) return;
  const prev = s.title || '';
  const inp = document.createElement('input');
  inp.className = 'history-rename-input';
  inp.value = prev;
  inp.onclick = (e) => e.stopPropagation();
  inp.onmousedown = (e) => e.stopPropagation();
  el.textContent = '';
  el.appendChild(inp);
  let done = false;
  const finish = async () => {
    if (done) return;
    done = true;
    const title = inp.value.trim();
    try {
      const res = await renameSessionApi(s.id, title);
      if (!res.ok) throw new Error('rename failed');
      s.title = title;
      if (s.id === sessionId) updateSessionTitle(title || t('untitledChat'));
      refreshSessions();
    } catch {
      el.textContent = prev || t('untitledChat');
      alert(t('renameFailed'));
    }
  };
  setTimeout(() => { inp.focus(); inp.select(); }, 0);
  setTimeout(() => { inp.onblur = finish; }, 150);
  inp.onkeydown = (e) => {
    e.stopPropagation();
    if (e.key === 'Enter') { e.preventDefault(); inp.blur(); }
    if (e.key === 'Escape') { e.preventDefault(); inp.value = prev; inp.blur(); }
  };
}

async function deleteSessionById(id) {
  if (!confirm(t('deleteSessionConfirm'))) return;
  if (id === sessionId && taskRunning) {
    stopTask();
    await waitForTaskDone(4000);
  }
  let res;
  try {
    res = await fetch(`/api/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' });
  } catch {
    alert(t('deleteFailed'));
    return;
  }
  if (!res.ok) {
    alert(t('deleteFailed'));
    return;
  }
  removePinnedSession(id);
  allSessions = allSessions.filter(s => s.id !== id);
  if (id === sessionId) {
    sessionId = genSessionId(workMode);
    persistSessionId();
    clearChat();
    if (ws && ws.readyState === 1) ws.send(JSON.stringify(wsInitPayload()));
  }
  renderSessions(allSessions);
  refreshSessions();
}

/* ══ 工具函数 ════════════════════════════════════════════════════ */
function closeIfBg(e, id) {
  if (e.target === document.getElementById(id)) {
    if (id === 'cowork-folder-overlay') closeCoworkFolderPicker();
    else if (id === 'project-create-overlay') closeProjectCreate();
    else document.getElementById(id).classList.remove('open');
  }
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
                  .replace(/"/g,'&quot;');
}
function escAttr(s) {
  return escHtml(s).replace(/'/g, '&#39;');
}

function hexToRgba(hex, a) {
  const r = parseInt(hex.slice(1,3),16)||136;
  const g = parseInt(hex.slice(3,5),16)||136;
  const b = parseInt(hex.slice(5,7),16)||136;
  return `rgba(${r},${g},${b},${a})`;
}


function inlineMD(s) {
  let t = escHtml(s);
  t = t.replace(/`([^`]+)`/g, '<code class="md-inline">$1</code>');
  t = t.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  t = t.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
  t = t.replace(/\[([^\]]+)\]\(([^)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return t;
}

function renderMD(text) {
  if (!text) return '';
  const lines = String(text).replace(/\r\n/g, '\n').split('\n');
  const out = [];
  let i = 0;
  const paraBuf = [];

  function flushParagraph() {
    if (!paraBuf.length) return;
    out.push(`<p>${inlineMD(paraBuf.join(' '))}</p>`);
    paraBuf.length = 0;
  }

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith('```')) {
      flushParagraph();
      const codeLines = [];
      i++;
      while (i < lines.length && !lines[i].startsWith('```')) {
        codeLines.push(lines[i]);
        i++;
      }
      if (i < lines.length) i++;
      out.push(`<pre class="md-pre"><code>${escHtml(codeLines.join('\n'))}</code></pre>`);
      continue;
    }

    const hm = line.match(/^(#{1,4}) (.+)$/);
    if (hm) {
      flushParagraph();
      const level = hm[1].length;
      out.push(`<h${level}>${inlineMD(hm[2])}</h${level}>`);
      i++;
      continue;
    }

    const cnH = line.match(/^【(.+)】$/);
    if (cnH) {
      flushParagraph();
      out.push(`<h3 class="md-cn-h">${inlineMD(cnH[1])}</h3>`);
      i++;
      continue;
    }

    if (/^\|.+\|$/.test(line.trim())) {
      flushParagraph();
      const tableLines = [];
      while (i < lines.length && /^\|.+\|$/.test(lines[i].trim())) {
        tableLines.push(lines[i].trim());
        i++;
      }
      if (tableLines.length >= 1) {
        const parseRow = row => row.slice(1, -1).split('|').map(c => c.trim());
        const isSep = tableLines.length > 1 && /^\|[\s:|-]+\|$/.test(tableLines[1]);
        const headerRow = tableLines[0];
        const bodyRows = isSep ? tableLines.slice(2) : tableLines.slice(1);
        let html = '<table class="md-table"><thead><tr>';
        parseRow(headerRow).forEach(h => { html += `<th>${inlineMD(h)}</th>`; });
        html += '</tr></thead><tbody>';
        bodyRows.forEach(row => {
          html += '<tr>';
          parseRow(row).forEach(c => { html += `<td>${inlineMD(c)}</td>`; });
          html += '</tr>';
        });
        html += '</tbody></table>';
        out.push(html);
      }
      continue;
    }

    if (line.startsWith('> ')) {
      flushParagraph();
      const bq = [];
      while (i < lines.length && lines[i].startsWith('> ')) {
        bq.push(lines[i].slice(2));
        i++;
      }
      out.push(`<blockquote>${inlineMD(bq.join(' '))}</blockquote>`);
      continue;
    }

    if (/^-{3,}$/.test(line.trim())) {
      flushParagraph();
      out.push('<hr class="md-hr"/>');
      i++;
      continue;
    }

    if (/^[-*] /.test(line)) {
      flushParagraph();
      const items = [];
      while (i < lines.length && /^[-*] /.test(lines[i])) {
        items.push(`<li>${inlineMD(lines[i].slice(2))}</li>`);
        i++;
      }
      out.push(`<ul>${items.join('')}</ul>`);
      continue;
    }

    if (/^\d+\. /.test(line)) {
      flushParagraph();
      const items = [];
      while (i < lines.length && /^\d+\. /.test(lines[i])) {
        items.push(`<li>${inlineMD(lines[i].replace(/^\d+\. /, ''))}</li>`);
        i++;
      }
      out.push(`<ol>${items.join('')}</ol>`);
      continue;
    }

    if (line.trim() === '') {
      flushParagraph();
      i++;
      continue;
    }

    paraBuf.push(line);
    i++;
  }
  flushParagraph();
  return out.join('');
}

/* ══ 侧栏折叠 + 工作模式 ════════════════════════════════════════ */
function isMobileLayout() {
  return window.matchMedia('(max-width: 680px)').matches;
}

function updateWorkbenchToggle() {
  const btn = document.getElementById('btn-workbench');
  const app = document.getElementById('app');
  if (!btn || !app) return;
  const open = app.classList.contains('wb-open');
  btn.textContent = open ? '›' : '‹';
}

function updateSidebarToggle() {
  const btn = document.getElementById('btn-sb-toggle');
  const app = document.getElementById('app');
  if (!btn || !app) return;
  const collapsed = app.classList.contains('sb-collapsed');
  const mobileOpen = app.classList.contains('sb-mobile-open');
  if (isMobileLayout()) {
    btn.textContent = mobileOpen ? '×' : '☰';
    btn.title = mobileOpen ? '关闭侧栏' : '打开侧栏';
  } else {
    btn.textContent = collapsed ? '›' : '‹';
    btn.title = collapsed ? '展开侧栏' : '折叠侧栏';
  }
}

function closeMobileSidebar() {
  document.getElementById('app')?.classList.remove('sb-mobile-open');
  updateSidebarToggle();
}

/* 移动端:在抽屉里点了对话/新建/导航项后,自动收起抽屉,露出对话 */
document.addEventListener('DOMContentLoaded', () => {
  const sb = document.getElementById('sidebar');
  if (!sb) return;
  sb.addEventListener('click', (e) => {
    const app = document.getElementById('app');
    if (!app || !app.classList.contains('sb-mobile-open')) return;
    if (e.target.closest('.history-item, #btn-new-chat, #btn-suggestions, .sb-proj-item, [data-session-id]')) {
      setTimeout(closeMobileSidebar, 140);
    }
  });
});

function toggleSidebar() {
  const app = document.getElementById('app');
  if (isMobileLayout()) {
    app.classList.toggle('sb-mobile-open');
  } else {
    const collapsed = app.classList.toggle('sb-collapsed');
    localStorage.setItem('captain-sb-collapsed', collapsed ? '1' : '0');
  }
  updateSidebarToggle();
}

function fillComposer(text) {
  const inp = document.getElementById('chat-inp');
  if (!inp) return;
  inp.value = text;
  inp.focus();
  inp.dispatchEvent(new Event('input'));
}

function fillSlashChip(cmd) {
  fillComposer(cmd + ' ');
}

function getWelcomeScenarios() {
  return [
    { title: t('scWrite'), desc: t('scWriteD'), prompt: t('scWriteP') },
    { title: t('scResearch'), desc: t('scResearchD'), prompt: t('scResearchP') },
    { title: t('scPlan'), desc: t('scPlanD'), prompt: t('scPlanP') },
  ];
}

function onWelcomeScenario(item) {
  fillComposer(item.prompt || '');
}

function getTimeGreeting() {
  const h = new Date().getHours();
  const name = 'captain';
  if (uiLang === 'en') {
    if (h < 5) return `Night, ${name}`;
    if (h < 12) return `Morning, ${name}`;
    if (h < 17) return `Afternoon, ${name}`;
    return `Evening, ${name}`;
  }
  if (h < 5) return `夜深了，${name}`;
  if (h < 12) return `早上好，${name}`;
  if (h < 17) return `下午好，${name}`;
  return `晚上好，${name}`;
}

function refreshWelcomeGreeting() {
  const el = document.querySelector('#chat-empty .welcome-title');
  if (el) el.textContent = getTimeGreeting();
}

function welcomeHtml() {
  if (workMode === 'coworker') {
    const sub = t('welcome_coworker');
    return `<div class="welcome" id="chat-empty">
      <div class="welcome-title">Captain</div>
      <div class="welcome-sub">${sub}</div>
    </div>`;
  }
  const sub = t('welcome_chat');
  return `<div class="welcome" id="chat-empty">
    <div class="welcome-greet"><span class="welcome-greet-ic">☀</span>
      <div class="welcome-title">${escHtml(getTimeGreeting())}</div></div>
    <div class="welcome-sub">${sub}</div>
    <div class="welcome-chips"></div>
    <div class="welcome-scenarios"></div>
  </div>`;
}

function renderQuickActions() {
  const box = document.getElementById('chat-quick-actions');
  if (!box) return;
  const items = [
    { label: t('qaWrite'), prompt: t('qaWriteP'), icon: '✎' },
    { label: t('qaLearn'), prompt: t('qaLearnP'), icon: '📖' },
    { label: t('qaCode'), prompt: t('qaCodeP'), icon: '</>' },
    { label: t('qaLife'), prompt: t('qaLifeP'), icon: '☕' },
    { label: t('qaChoice'), prompt: t('qaChoiceP'), icon: '✦' },
  ];
  box.innerHTML = items.map((it, i) =>
    `<button type="button" class="chat-qa-btn" onclick="welcomeScenarioClick(${i})" data-qa-idx="${i}">
      <span>${escHtml(it.icon)}</span><span>${escHtml(it.label)}</span>
    </button>`
  ).join('');
  box._qaItems = items;
}

function welcomeScenarioClick(idx) {
  const box = document.getElementById('chat-quick-actions');
  const items = (box && box._qaItems) || getWelcomeScenarios();
  const item = items[idx];
  if (item) onWelcomeScenario(item);
}

async function refreshUsageBanner() {
  const banner = document.getElementById('usage-banner');
  const label = document.getElementById('usage-banner-label');
  const fill = document.getElementById('usage-banner-fill');
  const link = document.getElementById('usage-banner-link');
  if (!banner || !label || workMode === 'coworker') return;
  try {
    const dismissed = parseInt(sessionStorage.getItem('captain-usage-banner-dismissed') || '0', 10);
    if (dismissed && Date.now() - dismissed < 3600000) { banner.hidden = true; return; }
  } catch {}
  try {
    const res = await fetch('/api/usage?days=7');
    const data = await res.json();
    const tokens = data.total_tokens || 0;
    const pct = Math.min(100, Math.round((tokens / 200000) * 100)) || 0;
    const amount = formatTokenCount(tokens) + (lang === 'zh' ? '' : ' tokens');
    label.textContent = t('usageBannerTotal').replace('{amount}', amount);
    if (fill) fill.style.width = Math.max(pct, tokens > 0 ? 4 : 0) + '%';
    if (link) link.textContent = t('usageBannerCta');
    banner.classList.remove('usage-warn');
    banner.hidden = false;
  } catch {
    banner.hidden = true;
  }
}

function updateChatLayoutState() {
  const view = document.getElementById('view-chat');
  const area = document.getElementById('chat-messages');
  if (!view || !area) return;
  const hasMsgs = !!area.querySelector('.msg');
  view.classList.toggle('has-messages', hasMsgs);
}

function applyModeChrome() {
  const app = document.getElementById('app');
  if (!app) return;
  app.classList.remove('work-mode-chat', 'work-mode-coworker');
  app.classList.add('work-mode-' + workMode);
  const newBtn = document.getElementById('btn-new-chat');
  const newBtnTxt = document.getElementById('btn-new-chat-txt');
  if (newBtn) newBtn.classList.toggle('sb-new-primary', workMode === 'chat');
  if (newBtnTxt) {
    newBtnTxt.textContent = workMode === 'coworker' ? t('navNewTask') : t('navNewChat');
  }
  document.getElementById('lang-zh')?.classList.toggle('active', uiLang === 'zh');
  document.getElementById('lang-en')?.classList.toggle('active', uiLang === 'en');
  renderQuickActions();
  refreshUsageBanner();
  updateChatLayoutState();
  updateWorkbenchToggle();
  updateCoworkFolderChip(_coworkWorkspaceDir || '');
  if (typeof refreshWorkbenchMeta === 'function') refreshWorkbenchMeta();
}

const I18N = {
  zh: {
    taskNew: '+ 新建任务',
    skillCallHint: '/skill 名',
    expertCallHint: '/专家名',
    taskTypeAgent: 'Agent 执行 prompt',
    emailImapHost: 'IMAP 服务器',
    emailImapPort: 'IMAP 端口',
    modelMock: 'Mock(测试)',
    emailAuthHint: 'QQ/163 邮箱请使用授权码(非登录密码)。保存后点「测试连接」验证,再点「启用渠道」。',
    emailSmtpHost: 'SMTP 服务器',
    emailSmtpPort: 'SMTP 端口',
    custTabSkills: 'Skill 插件',
    custTabTemplates: '提示词模板', custTabSchedules: '定时任务', custTabConnectors: '连接器', custTabPrefs: '偏好与人设',
    tplDesc: '把常用话术、固定任务存成模板,一键插入对话框。',
    tplTitlePh: '模板标题，如「周报」', tplContentPh: '模板内容…', tplSave: '保存模板',
    tplInsert: '插入对话框', tplDelete: '删除', tplEmpty: '还没有模板',
    schDesc: '让 Captain 定时自动执行任务(如每天早上出简报)。',
    schNamePh: '任务名', schPromptPh: '要做什么(给 Captain 的指令)…',
    schDaily: '每天', schOnce: '一次', schSave: '新建任务', schDelete: '删除', schEmpty: '还没有定时任务',
    connDesc: '外部服务接口(connectors/*.json)+ 凭据(密码加密保存,绝不明文展示)。',
    connCredTitle: '添加/更新凭据', connNamePh: '凭据名(如 github)', connUserPh: '用户名(可选)',
    connSecretPh: '密码 / API Token(加密保存)', connUrlPh: '登录页/说明(可选)',
    connSaveCred: '保存凭据', connDelCred: '删除', connNoCred: '还没有凭据',
    connServices: '已接入的服务', connNoSvc: 'connectors/ 目录暂无服务',
    prefDesc: 'Captain 记住的关于你的偏好(称呼、语气、长期目标等),会长期影响它的回应。',
    prefDelete: '忘掉', prefEmpty: 'Captain 还没记下关于你的偏好',
    deliverNone: '不投递',
    artifactPreview: '产物预览',
    taskNameLbl: '任务名称',
    taskTypeLbl: '任务类型',
    taskUseForgetTpl: '使用「记忆清理」模板',
    btnSaveEnable: '保存并启用',
    btnCreate: '创建',
    tasksDescFull: '到点自动执行 prompt(无人值守,默认只读)',
    loading: '加载中…',
    btnCancel: '取消',
    emailEnable: '启用渠道',
    modelKeyHint: '填入对应平台的 API Key 即可启用该模型,保存后自动出现在上方「默认模型」中。已配置的留空表示不改动。Key 仅保存在本机服务端(logs/model_keys.json),不会回显明文。',
    custTabExperts: '执行专家',
    taskPromptLbl: '执行指令(prompt)',
    taskDeliverTo: '投递邮箱(留空=发给自己)',
    emailPass: '授权码',
    taskAtHHMM: '时间(HH:MM)',
    statusDisconnected: '未连接',
    navSuggestions: '主动建议', sugAccept: '接受并去做', sugGotIt: '知道了', sugDismiss: '忽略', sugEmpty: '暂无主动建议',
    shareTitle: '分享/导出当前对话', artifactPublish: '发布并复制链接',
    navWriting: '写作', writingTitle: '标题', writingSaveBtn: '保存到产物', writingExportBtn: '导出',
    navMission: '任务', missionTitle: '任务 · Mission', missionTagline: '交代目标,它自己拆解、顺序执行、卡住时通知你',
    missionRefresh: '刷新', missionClose: '关闭', missionCreate: '交给它', missionGoalPh: '交代一个目标,例如:写一份德国市场分析,保存成 Word',
    missionAttn0: '自己决定', missionAttn1: '轻通知', missionAttn2: '邮件告知', missionAttn3: '必须确认',
    writingClose: '关闭', writingApply: '应用',
    writingPh: '开始写…（选中一段文字,用下方按钮让 Captain 润色/改写;不选则作用于全文）',
    writingInstPh: '或输入自定义指令…',
    micTitle: '语音输入(点一下开始说话)', autoReadTitle: '自动朗读回复',
    convoTitle: '连续对话模式(免手:说完自动发,回复念给你听,再自动开麦)',
    hqVoiceTitle: '高音质语音(用小米 MiMo:朗读更自然、识别更准、支持方言/克隆;关则用浏览器原生)',
    modelKeyTitle: '模型接入',
    mkAddCustom: '+ 自定义 OpenAI 兼容端点', mkSave: '保存', mkTest: '测试连接', mkDelete: '删除',
    schedDaily: '每天固定时间',
    schedEvery: '每隔 N 秒',
    emailTest: '测试连接',
    wbBindFolderHint: '点「+」绑定目录，浏览工作区文件',
    emailAllowSenders: '白名单发件人(留空=只听自己)',
    expertSysPrompt: '系统提示词',
    taskDeliverLbl: '结果投递',
    expertCaps: '能力',
    expertRoleDesc: '角色描述',
    expertRoleDuty: '角色职责',
    taskTypeForget: '记忆清理(维护)',
    tokenTitle: '访问令牌(远程访问用)',
    schedTypeLbl: '调度方式',
    emailUser: '账号',
    channelEmail: '邮件',
    btnConfigure: '配置',
    taskIntervalSec: '间隔(秒)',
    settingsGeneralSub: '默认模型、治理档位与会话成本上限',
    newChat: '+ 新对话',
    newCode: '+ 新 Code 会话',
    modeChatHint: '日常问答、写作、调研',
    modeCodeHint: '读代码、改 bug、跑命令(完整工具链)',
    footCustomize: '自定义',
    footSettings: '设置',
    connecting: '连接中…',
    wsNotConnected: '未连接到 Captain，请稍候或刷新页面',
    ctxLabel: '上下文',
    noHistory: '暂无历史',
    untitledChat: '(未命名对话)',
    deleteChat: '删除对话',
    deleteSessionConfirm: '确定删除这条对话？此操作不可恢复。',
    deleteFailed: '删除失败，请稍后重试',
    renameFailed: '重命名失败，请重启服务后重试',
    noModelsConfigured: '暂无已配置的模型。请在 .env 中配置 API Key 后刷新。',
    placeholder_chat: '问我点什么,或输入 / 调用技能',
    placeholder_code: '描述代码任务或粘贴报错…',
    placeholder_coworker: '交办一件事:做网页 / 出报告 / 批量处理文件 / 登录网站取数…我来动手,右侧看进度和产物',
    renameChat: '重命名',
    pinChat: '置顶',
    historySearch: '搜索对话…',
    noSearchResults: '无匹配对话',
    grpPinned: '置顶',
    grpToday: '今天',
    grpYesterday: '昨天',
    grpOlder: '更早',
    btnSend: '发送',
    btnStop: '停',
    copyCode: '复制',
    copied: '已复制',
    copyMsg: '复制',
    readAloud: '朗读',
    retryMsg: '重试',
    taskUsage: '本次 ≈ {tokens} tokens · ${cost}',
    ctxTooltip: '上下文 {tok}（{pct}%）— 当前会话 token 估算',
    ctxWarn: '接近上限，建议新对话或 /rollback',
    errLabel: '错误',
    evtDispatch: '派发',
    evtAutoDispatch: '自动派发专家',
    evtExpert: '专家',
    evtCall: '调用',
    evtResult: '结果',
    evtFail: '失败',
    evtGov: '治理',
    evtRule: '规则',
    rollbackNone: '(无可回滚变更)',
    rollbackOk: '已回滚: {notes}',
    rollbackFail: '回滚失败',
    debatePro: '正方',
    debateCon: '反方',
    debateTag: '辩论',
    debateSummary: '辩论总结',
    debateHost: '主持人',
    navGroupCommon: '常用',
    navGroupAdvanced: '高级',
    navChannels: '连接器',
    navTasks: '定时任务',
    navGovernance: '治理',
    navAbout: '关于',
    settingsNavTitle: '设置',
    btnSettingsRefresh: '刷新状态',
    btnSettingsSave: '保存',
    shortcutsTitle: '键盘快捷键',
    shortcutsLink: '键盘快捷键',
    scWrite: '写方案',
    scWriteD: '整理目标与执行计划',
    scWriteP: '帮我拆解这个目标并给出执行步骤：',
    scResearch: '整理资料',
    scResearchD: '汇总、提炼要点',
    scResearchP: '帮我调研并总结以下主题：',
    scPlan: '任务规划',
    scPlanD: '拆解待办与优先级',
    scPlanP: '帮我规划这件事的步骤和优先级：',
    scCodeFix: '修 bug',
    scCodeFixD: '定位并修复报错',
    scCodeFixP: '帮我分析并修复这个报错：',
    scCodeRead: '读仓库',
    scCodeReadD: '理解模块与依赖',
    scCodeReadP: '帮我阅读这个仓库的结构和关键模块：',
    scCodeTest: '写测试',
    scCodeTestD: '补测试或跑 harness',
    scCodeTestP: '为这个功能补测试并说明如何验证：',
    welcome_chat: '听懂目标，自己拆解执行，只给你结果',
    welcome_code: '写代码、改 bug、读仓库。Captain 会调用工具并展示过程',
    welcome_coworker: '把活儿交给我:调研、做网页、写报告、跑脚本、登录网站取数——我拆成待办一步步做完,右侧看进度和产物',
    navUsage: '用量',
    settingsUsage: '用量',
    settingsUsageDesc: '近 30 天 tokens 消耗与费用估算',
    usageLblTokens: '总 Tokens',
    usageLblCost: '总费用 (USD)',
    usageLblTasks: '任务次数',
    usageDailyTitle: '按日明细',
    usageNoData: '暂无用量数据',
    usageLoadFailed: '加载失败',
    usageTasksUnit: '次',
    renameHint: '双击可重命名',
    settingsGeneral: '通用',
    settingsGeneralDesc: '语言、默认模型、治理档位与会话成本上限',
    lblLang: '语言',
    lblModel: '默认模型',
    lblGov: '治理档位',
    govConservative: '保守(写操作多确认)',
    govBalanced: '平衡',
    govAggressive: '激进(写操作自动放行)',
    lblMaxCost: '金额上限(USD,留空不限)',
    lblMaxSteps: '最大步数',
    settingsChannelsDesc: '手机直连(Tailscale)+ 邮件',
    settingsTasks: '定时任务',
    settingsTasksDesc: '到点自动执行，无人值守时默认只读',
    settingsGovernance: '治理',
    settingsGovernanceDesc: '近 7 天裁决分布',
    settingsAbout: '关于',
    settingsAboutDesc: 'Captain Agent 平台',
    aboutTagline: '听懂目标 · 自己拆解执行 · 治理可审计',
    aboutFeatures: '单 Agent 自治 + 主动反思 + 多模态/语音 + 加密保险库 + 浏览器/连接器 + 手机直连/邮件',
    govStatsHint: '近 7 天治理裁决统计(来自 trace)',
    govHitRate: '免确认命中率',
    govHitRateHint: 'Agent 调用工具时,无需弹窗、直接放行的比例。只读操作自动放行、本任务/路径已授权复用都算命中。',
    govAllow: '放行',
    govAsk: '需确认',
    govBlock: '拒绝',
    govReuse: '授权复用',
    govTotal: '总裁决',
    govDist: '裁决分布',
    govTopRules: '命中规则 Top(近 7 天)',
    govNoData: '暂无治理事件',
    govLoadFailed: '加载失败',
    skNewChat: '新对话',
    skSettings: '打开设置',
    skFocus: '聚焦输入框',
    skClose: '关闭弹层',
    skHelp: '快捷键帮助',
    navNewTask: '新建任务',
    navNewChat: '+ 新对话',
    navProjects: '工作区',
    navArtifacts: '产物',
    expertAdd: '+ 新增专家',
    expertNamePh: '专家名称(如:行情分析)',
    expertDescPh: '一句话描述这个专家擅长什么',
    expertTier: '权限',
    expertTierRO: '只读(查资料/读文件,不改动)',
    expertTierRW: '可写(可改文件 / 跑命令)',
    expertPromptPh: '系统提示词(可选,留空用默认)',
    expertSaveBtn: '新增并保存',
    expertDelConfirm: '删除这个自定义专家?',
    expertSaved: '专家已保存',
    expertNameReq: '请先填专家名称',
    expertSaveFail: '保存失败:',
    expertNoCfg: '暂无专家配置',
    artifactsTitle: '历史产物',
    artifactsSearchPh: '按文件名搜索产物…',
    artifactsEmpty: '暂无产物',
    artifactsRefresh: '刷新',
    expertCallTaskHint: '任务描述',
    loadFailed: '加载失败',
    navScheduled: '定时',
    navDispatch: '派发',
    navBeta: 'Beta',
    navCustomize: '自定义',
    sbRecents: '最近',
    sbUserPlan: 'Pro',
    projectFilterAll: '全部对话',
    modeChat: 'Chat',
    modeCowork: 'Cowork',
    modeCode: 'Code',
    modeChatHint: '日常问答、写作、调研',
    modeCoworkHint: '交办任务、自动拆解执行',
    modeCodeHint: '读代码、改 bug、跑命令',
    toggleSidebar: '折叠侧栏',
    toggleWorkbench: '切换工作台',
    chatSessionTitle: '当前会话/工作区',
    composerAttach: '上传文件',
    composerAddFolder: '选择工作区文件夹',
    composerAddCtx: '添加工作区上下文',
    coworkFolderTitle: '添加文件夹',
    coworkFolderDesc: '选择工作区内的文件夹，或从本地上传整个文件夹。',
    coworkFolderUse: '使用此文件夹',
    coworkFolderUpload: '本地上传文件夹',
    folderCtxRef: '[工作目录: {path}] ',
    folderUploadedRef: '[已上传文件夹: {path}] ',
    folderUploadDone: '已上传 {ok} 个文件',
    folderUploadPartial: '已上传 {ok} 个，跳过 {skip} 个',
    wbProgress: '执行进度',
    wbProgressHint: 'Captain 拆解任务后，步骤与完成状态在此更新',
    wbPlanEmpty: '交办任务后，执行步骤会出现在这里',
    wbTasks: '任务',
    wbFiles: '工作目录',
    wbFilesHint: '点「+」绑定目录，浏览工作区文件',
    wbFilesEmptyDir: '此目录为空',
    wbArtifacts: '产物',
    wbArtifactsHint: 'Captain 写入或生成的文件，点即可预览',
    wbFilesDefault: '工作区根目录',
    wbFilesUp: '上一级',
    wbNoArtifacts: '暂无产物',
    wbProgressIdle: '等待任务',
    wbProgressRunning: '执行中…',
    wbProgressDone: '已完成',
    progressCount: '{done} / {total}',
    progressCountZero: '0 / 0',
    projectCtxPrefix: '[工作区: {name}] ',
    projectCreateName: '新建工作区名称(比如:梯子搭建 / 周报):',
    projectCreateInstr: '工作区专属指令(可选,每条对话都会带上;留空跳过):',
    projectCreateFailNet: '创建失败(网络/请求):',
    projectCreateFailHttp: '创建失败:HTTP ',
    projectCreateFailAuth: '(需在设置里填访问令牌)',
    projectCreateFailParse: '创建失败(返回解析):',
    projectCreateFailUnknown: '创建失败:',
    projectCreateOk: '已创建工作区「{name}」并切换过去。\n在此工作区下点「新建任务」开始聊,首条消息后会自动归到该工作区;开场也会带上工作区专属指令。',
    uploadTooLarge: '文件超过 20MB',
    uploadFail: '上传失败:',
    uploadedRef: '[已上传文件: {path}] ',
    greetChat: '又见面了，captain',
    greetCode: '接下来做什么，captain？',
    codeWhatsNew: '新功能',
    codeTabOverview: '概览',
    codeTabModels: '模型',
    codeStatSessions: '会话',
    codeStatMessages: '消息',
    codeStatTokens: '总 tokens',
    codeStatTasks: '任务',
    codeEmptySessions: '你开始的 Code 会话会显示在这里',
    codeLocal: '本地',
    codeSelectFolder: '选择文件夹…',
    codeDashFoot: '近 30 天共 {tokens} tokens，{tasks} 次任务',
    navRoutines: '例行任务',
    usageBannerTotal: '本周用量 {amount}',
    usageBannerCta: '查看用量',
    usageGetMore: '获取更多额度',
    usageWarningApproaching: '即将达到本周用量上限',
    usageResets: '重置于 {when}',
    usageUpgrade: '升级',
    thumbUp: '有帮助',
    thumbDown: '没帮助',
    editMsg: '编辑',
    cancel: '取消',
    save: '保存并发送',
    toolTraceTitle: '显示工具轨迹(调用/输出)',
    timeJustNow: '刚刚',
    timeMinutesAgo: '{n} 分钟前',
    timeHoursAgo: '{n} 小时前',
    timeDaysAgo: '{n} 天前',
    qaWrite: '写作',
    qaLearn: '学习',
    qaCode: '代码',
    qaLife: '生活',
    qaChoice: 'Captain 推荐',
    qaWriteP: '帮我写一份清晰的方案：',
    qaLearnP: '帮我学习并总结这个主题：',
    qaCodeP: '帮我读代码并解释这段逻辑：',
    qaLifeP: '帮我规划一下这件事：',
    qaChoiceP: '根据我的工作区，推荐一个值得做的任务',
    chatDisclaimer: 'Captain 可能会犯错，请核实重要信息。',
    shareChat: '导出对话',
    projSortName: '名称',
    projSortTime: '时间',
    projViewAll: '全部工作区',
    projNew: '新建工作区',
    projRenamePrompt: '工作区名称',
    projRenameFailed: '重命名失败',
    projDeleteConfirm: '确定删除工作区「{name}」？',
    projDeleteFailed: '删除失败',
    projSearchPh: '搜索工作区…',
    projEmpty: '暂无工作区',
    projUpdated: '更新于 {date}',
    projCreateTitle: '创建新工作区',
    projCreateDesc: '为长期任务准备专属空间,指令与文件会持续积累。',
    projOptScratch: '从零开始',
    projOptScratchSub: '新建工作区并填写名称与专属指令',
    projOptImport: '从 Chat 导入',
    projOptImportSub: '把 Chat 里已有的工作区带到 Cowork 继续',
    projOptFolder: '使用已有文件夹',
    projOptFolderSub: '指定工作区内一个你已在用的目录',
    projCreateBack: '返回',
    projCreateNameLbl: '工作区名称',
    projCreateNamePh: '例如：外贸软件 / 周报',
    projCreateInstrLbl: '工作区专属指令（可选）',
    projCreateInstrPh: '每条对话都会自动带上…',
    projCreateSubmit: '创建工作区',
    projImportEmpty: '还没有可导入的工作区,请先从零创建',
    projFolderPick: '选择此文件夹',
    projFolderUp: '上一级',
    projFolderRoot: '工作区根目录',
    projDetailBack: '‹ 工作区',
    projDetailPrompt: '在这个工作区里想做什么？',
    projDetailStart: '开始',
    projDetailRecents: '最近',
    projDetailInstr: '专属指令',
    projDetailContext: '上下文',
    projDetailEmptySessions: '还没有对话记录，在上面输入任务开始',
    projDetailNoInstr: '（未设置专属指令）',
  },
  en: {
    taskNew: '+ New task',
    skillCallHint: '/skill name',
    expertCallHint: '/expert-name',
    taskTypeAgent: 'Agent runs prompt',
    emailImapHost: 'IMAP server',
    emailImapPort: 'IMAP port',
    modelMock: 'Mock (test)',
    emailAuthHint: 'For QQ/163 mailboxes use an app authorization code (not your login password). After saving, click \'Test connection\' to verify, then \'Enable channel\'.',
    emailSmtpHost: 'SMTP server',
    emailSmtpPort: 'SMTP port',
    custTabSkills: 'Skill plugins',
    custTabTemplates: 'Templates', custTabSchedules: 'Schedules', custTabConnectors: 'Connectors', custTabPrefs: 'Preferences',
    tplDesc: 'Save common phrasings and recurring tasks as templates; insert into the input with one click.',
    tplTitlePh: 'Template title, e.g. "Weekly report"', tplContentPh: 'Template content…', tplSave: 'Save template',
    tplInsert: 'Insert', tplDelete: 'Delete', tplEmpty: 'No templates yet',
    schDesc: 'Let Captain run tasks automatically on a schedule (e.g. a morning briefing).',
    schNamePh: 'Task name', schPromptPh: 'What to do (instruction for Captain)…',
    schDaily: 'Daily', schOnce: 'Once', schSave: 'Create task', schDelete: 'Delete', schEmpty: 'No scheduled tasks yet',
    connDesc: 'External service APIs (connectors/*.json) + credentials (passwords stored encrypted, never shown).',
    connCredTitle: 'Add / update credential', connNamePh: 'Credential name (e.g. github)', connUserPh: 'Username (optional)',
    connSecretPh: 'Password / API token (encrypted)', connUrlPh: 'Login page / note (optional)',
    connSaveCred: 'Save credential', connDelCred: 'Delete', connNoCred: 'No credentials yet',
    connServices: 'Connected services', connNoSvc: 'No services in connectors/',
    prefDesc: 'Preferences Captain remembers about you (name, tone, long-term goals) that shape its responses.',
    prefDelete: 'Forget', prefEmpty: 'Captain hasn\'t noted any preferences yet',
    deliverNone: 'No delivery',
    artifactPreview: 'Artifact preview',
    taskNameLbl: 'Task name',
    taskTypeLbl: 'Task type',
    taskUseForgetTpl: 'Use \'memory cleanup\' template',
    btnSaveEnable: 'Save & enable',
    btnCreate: 'Create',
    tasksDescFull: 'Runs the prompt on schedule (unattended, read-only by default)',
    loading: 'Loading…',
    btnCancel: 'Cancel',
    emailEnable: 'Enable channel',
    modelKeyHint: 'Enter the API key for each platform to enable that model. After saving it appears under \'Default model\' above. Leave a configured key blank to keep it unchanged. Keys are stored only on the local server (logs/model_keys.json) and never echoed back in plaintext.',
    custTabExperts: 'Execution experts',
    taskPromptLbl: 'Instruction (prompt)',
    taskDeliverTo: 'Delivery email (blank = send to yourself)',
    emailPass: 'Authorization code',
    taskAtHHMM: 'Time (HH:MM)',
    statusDisconnected: 'Not connected',
    navSuggestions: 'Suggestions', sugAccept: 'Accept & do it', sugGotIt: 'Got it', sugDismiss: 'Dismiss', sugEmpty: 'No suggestions yet',
    shareTitle: 'Share / export this conversation', artifactPublish: 'Publish & copy link',
    navWriting: 'Write', writingTitle: 'Title', writingSaveBtn: 'Save to outputs', writingExportBtn: 'Export',
    navMission: 'Missions', missionTitle: 'Missions', missionTagline: 'Give it a goal — it plans, executes in order, and pings you when blocked',
    missionRefresh: 'Refresh', missionClose: 'Close', missionCreate: 'Hand it over', missionGoalPh: 'Give a goal, e.g. write a Germany market analysis and save as Word',
    missionAttn0: 'Decide itself', missionAttn1: 'Notify', missionAttn2: 'Email me', missionAttn3: 'Must confirm',
    writingClose: 'Close', writingApply: 'Apply',
    writingPh: 'Start writing… (select text and use the buttons to have Captain polish/rewrite; no selection = whole doc)',
    writingInstPh: 'or type a custom instruction…',
    micTitle: 'Voice input (click to start talking)', autoReadTitle: 'Auto read replies aloud',
    convoTitle: 'Conversation mode (hands-free: speak, it sends, reads the reply, then listens again)',
    hqVoiceTitle: 'HD voice (Xiaomi MiMo: more natural TTS, more accurate ASR, dialects/cloning; off = browser native)',
    modelKeyTitle: 'Models',
    mkAddCustom: '+ Custom OpenAI-compatible endpoint', mkSave: 'Save', mkTest: 'Test', mkDelete: 'Delete',
    schedDaily: 'Daily at fixed time',
    schedEvery: 'Every N seconds',
    emailTest: 'Test connection',
    wbBindFolderHint: 'Use + to bind a directory and browse workspace files',
    emailAllowSenders: 'Allowed senders (blank = only yourself)',
    expertSysPrompt: 'System prompt',
    taskDeliverLbl: 'Result delivery',
    expertCaps: 'Capabilities',
    expertRoleDesc: 'Role description',
    expertRoleDuty: 'Role duties',
    taskTypeForget: 'Memory cleanup (maintenance)',
    tokenTitle: 'Access token (for remote access)',
    schedTypeLbl: 'Schedule type',
    emailUser: 'Account',
    channelEmail: 'Email',
    btnConfigure: 'Configure',
    taskIntervalSec: 'Interval (sec)',
    settingsGeneralSub: 'Default model, governance level and per-session cost cap',
    newChat: '+ New chat',
    newCode: '+ New code session',
    modeChatHint: 'Q&A, writing, research',
    modeCodeHint: 'Read code, fix bugs, run tools (full trace)',
    footCustomize: 'Customize',
    footSettings: 'Settings',
    connecting: 'Connecting…',
    wsNotConnected: 'Not connected to Captain — wait or refresh',
    ctxLabel: 'Context',
    noHistory: 'No history',
    untitledChat: '(Untitled)',
    deleteChat: 'Delete chat',
    deleteSessionConfirm: 'Delete this chat? This cannot be undone.',
    deleteFailed: 'Delete failed. Please try again.',
    renameFailed: 'Rename failed. Try restarting the server.',
    noModelsConfigured: 'No configured models. Add API keys in .env and refresh.',
    placeholder_chat: 'Type / for skills',
    placeholder_code: 'Describe a coding task or paste an error…',
    placeholder_coworker: 'Hand me a task: build a page / write a report / batch-process files / log in & fetch data — progress on the right',
    renameChat: 'Rename',
    pinChat: 'Pin',
    historySearch: 'Search chats…',
    noSearchResults: 'No matching chats',
    grpPinned: 'Pinned',
    grpToday: 'Today',
    grpYesterday: 'Yesterday',
    grpOlder: 'Older',
    btnSend: 'Send',
    btnStop: 'Stop',
    copyCode: 'Copy',
    copied: 'Copied',
    copyMsg: 'Copy',
    readAloud: 'Read aloud',
    retryMsg: 'Retry',
    taskUsage: 'This run ≈ {tokens} tokens · ${cost}',
    ctxTooltip: 'Context {tok} ({pct}%) — estimated session tokens',
    ctxWarn: 'Near limit — start a new chat or /rollback',
    errLabel: 'Error',
    evtDispatch: 'Dispatch',
    evtAutoDispatch: 'Auto-dispatch experts',
    evtExpert: 'Expert',
    evtCall: 'Call',
    evtResult: 'Result',
    evtFail: 'Failed',
    evtGov: 'Governance',
    evtRule: 'rule',
    rollbackNone: '(nothing to roll back)',
    rollbackOk: 'Rolled back: {notes}',
    rollbackFail: 'Rollback failed',
    debatePro: 'Pro',
    debateCon: 'Con',
    debateTag: 'Debate',
    debateSummary: 'Debate summary',
    debateHost: 'Moderator',
    navGroupCommon: 'General',
    navGroupAdvanced: 'Advanced',
    navChannels: 'Connectors',
    navTasks: 'Scheduled tasks',
    navGovernance: 'Governance',
    navAbout: 'About',
    settingsNavTitle: 'Settings',
    btnSettingsRefresh: 'Refresh',
    btnSettingsSave: 'Save',
    shortcutsTitle: 'Keyboard shortcuts',
    shortcutsLink: 'Keyboard shortcuts',
    scWrite: 'Draft plan',
    scWriteD: 'Goals and execution steps',
    scWriteP: 'Break down this goal into actionable steps:',
    scResearch: 'Research',
    scResearchD: 'Summarize and extract key points',
    scResearchP: 'Research and summarize this topic:',
    scPlan: 'Task planning',
    scPlanD: 'Break down todos and priorities',
    scPlanP: 'Plan the steps and priorities for:',
    scCodeFix: 'Fix bug',
    scCodeFixD: 'Diagnose and fix errors',
    scCodeFixP: 'Analyze and fix this error:',
    scCodeRead: 'Explore repo',
    scCodeReadD: 'Understand modules and deps',
    scCodeReadP: 'Explain this repo structure and key modules:',
    scCodeTest: 'Write tests',
    scCodeTestD: 'Add tests or run harness',
    scCodeTestP: 'Add tests for this feature and how to verify:',
    welcome_chat: 'Understand goals, execute autonomously, report results only',
    welcome_code: 'Write code, fix bugs, explore the repo. Tools and steps stay visible',
    welcome_coworker: 'Delegate a task — research, build pages, write reports, run scripts, log in & fetch data; I break it into a checklist and work through it. Progress on the right',
    navUsage: 'Usage',
    settingsUsage: 'Usage',
    settingsUsageDesc: 'Token consumption and estimated cost (last 30 days)',
    usageLblTokens: 'Total tokens',
    usageLblCost: 'Total cost (USD)',
    usageLblTasks: 'Tasks',
    usageDailyTitle: 'Daily breakdown',
    usageNoData: 'No usage data yet',
    usageLoadFailed: 'Failed to load',
    usageTasksUnit: 'tasks',
    renameHint: 'double-click to rename',
    settingsGeneral: 'General',
    settingsGeneralDesc: 'Language, default model, governance, and budget',
    lblLang: 'Language',
    lblModel: 'Default model',
    lblGov: 'Governance',
    govConservative: 'Conservative (more write confirmations)',
    govBalanced: 'Balanced',
    govAggressive: 'Aggressive (auto-approve writes)',
    lblMaxCost: 'Cost cap (USD, empty = unlimited)',
    lblMaxSteps: 'Max steps',
    settingsChannelsDesc: 'Phone direct (Tailscale) + Email',
    settingsTasks: 'Scheduled tasks',
    settingsTasksDesc: 'Run prompts on schedule (unattended, read-only by default)',
    settingsGovernance: 'Governance',
    settingsGovernanceDesc: 'Decision distribution (last 7 days)',
    settingsAbout: 'About',
    settingsAboutDesc: 'Captain Agent platform',
    aboutTagline: 'Understand goals · execute autonomously · auditable governance',
    aboutFeatures: 'Autonomous agent + proactive reflection + multimodal/voice + encrypted vault + browser/connectors + phone/email',
    govStatsHint: 'Governance stats from trace (last 7 days)',
    govHitRate: 'Auto-allow rate',
    govHitRateHint: 'Share of tool calls allowed without a confirmation prompt (read-only, task/path grants, etc.).',
    govAllow: 'Allowed',
    govAsk: 'Confirm',
    govBlock: 'Blocked',
    govReuse: 'Grant reuse',
    govTotal: 'Decisions',
    govDist: 'Decision mix',
    govTopRules: 'Top rules (7d)',
    govNoData: 'No governance events',
    govLoadFailed: 'Failed to load',
    skNewChat: 'New chat',
    skSettings: 'Open settings',
    skFocus: 'Focus composer',
    skClose: 'Close overlay',
    skHelp: 'Shortcuts help',
    navNewTask: 'New task',
    navNewChat: '+ New chat',
    navProjects: 'Workspaces',
    navArtifacts: 'Artifacts',
    expertAdd: '+ New expert',
    expertNamePh: 'Expert name (e.g. Market analysis)',
    expertDescPh: 'One line: what this expert is good at',
    expertTier: 'Permission',
    expertTierRO: 'Read-only (research / read, no writes)',
    expertTierRW: 'Read-write (edit files / run commands)',
    expertPromptPh: 'System prompt (optional, blank = default)',
    expertSaveBtn: 'Add & save',
    expertDelConfirm: 'Delete this custom expert?',
    expertSaved: 'Expert saved',
    expertNameReq: 'Please enter an expert name',
    expertSaveFail: 'Save failed: ',
    expertNoCfg: 'No experts configured yet',
    artifactsTitle: 'Artifacts',
    artifactsSearchPh: 'Search artifacts by filename…',
    artifactsEmpty: 'No artifacts yet',
    artifactsRefresh: 'Refresh',
    expertCallTaskHint: 'task description',
    loadFailed: 'Load failed',
    navScheduled: 'Scheduled',
    navDispatch: 'Dispatch',
    navBeta: 'Beta',
    navCustomize: 'Customize',
    sbRecents: 'Recents',
    sbUserPlan: 'Pro',
    projectFilterAll: 'All chats',
    modeChat: 'Chat',
    modeCowork: 'Cowork',
    modeCode: 'Code',
    modeChatHint: 'Q&A, writing, research',
    modeCoworkHint: 'Delegate tasks; auto plan & execute',
    modeCodeHint: 'Read code, fix bugs, run commands',
    toggleSidebar: 'Toggle sidebar',
    toggleWorkbench: 'Toggle workbench',
    chatSessionTitle: 'Current session / workspace',
    composerAttach: 'Attach file',
    composerAddFolder: 'Pick workspace folder',
    composerAddCtx: 'Add workspace context',
    coworkFolderTitle: 'Add folder',
    coworkFolderDesc: 'Pick a folder in the workspace, or upload a folder from your computer.',
    coworkFolderUse: 'Use this folder',
    coworkFolderUpload: 'Upload folder',
    folderCtxRef: '[Workspace: {path}] ',
    folderUploadedRef: '[Uploaded folder: {path}] ',
    folderUploadDone: 'Uploaded {ok} files',
    folderUploadPartial: 'Uploaded {ok}, skipped {skip}',
    wbProgress: 'Progress',
    wbProgressHint: 'Task steps and status update here as Captain works',
    wbPlanEmpty: 'Steps appear here after you delegate a task',
    wbTasks: 'Tasks',
    wbFiles: 'Workspace',
    wbFilesHint: 'Use + to bind a directory and browse files',
    wbFilesEmptyDir: 'Empty folder',
    wbArtifacts: 'Outputs',
    wbArtifactsHint: 'Files Captain writes or generates — click to preview',
    wbFilesDefault: 'Workspace root',
    wbFilesUp: 'Up',
    wbNoArtifacts: 'No outputs yet',
    wbProgressIdle: 'Waiting',
    wbProgressRunning: 'Running…',
    wbProgressDone: 'Done',
    progressCount: '{done} of {total}',
    progressCountZero: '0 of 0',
    projectCtxPrefix: '[Workspace: {name}] ',
    projectCreateName: 'New workspace name (e.g. weekly report):',
    projectCreateInstr: 'Workspace instructions (optional; applied to each chat):',
    projectCreateFailNet: 'Create failed (network):',
    projectCreateFailHttp: 'Create failed: HTTP ',
    projectCreateFailAuth: '(set access token in Settings)',
    projectCreateFailParse: 'Create failed (parse error):',
    projectCreateFailUnknown: 'Create failed:',
    projectCreateOk: 'Created workspace "{name}".\nStart a new task under this workspace; the first message will attach it.',
    uploadTooLarge: 'File exceeds 20MB',
    uploadFail: 'Upload failed:',
    uploadedRef: '[Uploaded: {path}] ',
    greetChat: 'Back at it, captain',
    greetCode: "What's up next, captain?",
    codeWhatsNew: "What's new",
    codeTabOverview: 'Overview',
    codeTabModels: 'Models',
    codeStatSessions: 'Sessions',
    codeStatMessages: 'Messages',
    codeStatTokens: 'Total tokens',
    codeStatTasks: 'Tasks',
    codeEmptySessions: 'Sessions you start will show up here',
    codeLocal: 'Local',
    codeSelectFolder: 'Select folder…',
    codeDashFoot: '{tokens} tokens and {tasks} tasks in the last 30 days',
    navRoutines: 'Routines',
    usageBannerTotal: 'Weekly usage {amount}',
    usageBannerCta: 'View usage',
    usageGetMore: 'Get more usage',
    usageWarningApproaching: 'Approaching weekly usage limit',
    usageResets: 'Resets {when}',
    usageUpgrade: 'Upgrade',
    thumbUp: 'Good response',
    thumbDown: 'Bad response',
    editMsg: 'Edit',
    cancel: 'Cancel',
    save: 'Save & send',
    toolTraceTitle: 'Show tool trace (calls/output)',
    timeJustNow: 'Just now',
    timeMinutesAgo: '{n} minutes ago',
    timeHoursAgo: '{n} hours ago',
    timeDaysAgo: '{n} days ago',
    qaWrite: 'Write',
    qaLearn: 'Learn',
    qaCode: 'Code',
    qaLife: 'Life stuff',
    qaChoice: "Captain's pick",
    qaWriteP: 'Help me draft a clear plan for:',
    qaLearnP: 'Help me learn and summarize:',
    qaCodeP: 'Help me read and explain this code:',
    qaLifeP: 'Help me plan this out:',
    qaChoiceP: 'Suggest a worthwhile task based on my workspace',
    chatDisclaimer: 'Captain is AI and can make mistakes. Please double-check responses.',
    shareChat: 'Export chat',
    projSortName: 'Name',
    projSortTime: 'Time',
    projViewAll: 'All workspaces',
    projNew: 'New workspace',
    projRenamePrompt: 'Workspace name',
    projRenameFailed: 'Rename failed',
    projDeleteConfirm: 'Delete workspace "{name}"?',
    projDeleteFailed: 'Delete failed',
    projSearchPh: 'Search workspaces…',
    projEmpty: 'No workspaces yet',
    projUpdated: 'Updated {date}',
    projCreateTitle: 'Create a new workspace',
    projCreateDesc: 'A dedicated place for ongoing work, where context builds over time.',
    projOptScratch: 'Start from scratch',
    projOptScratchSub: 'Set up a new workspace with instructions',
    projOptImport: 'Import a workspace',
    projOptImportSub: 'Bring a workspace you made in Chat over to Cowork',
    projOptFolder: 'Use an existing folder',
    projOptFolderSub: 'Point Captain at a folder you already work from',
    projCreateBack: 'Back',
    projCreateNameLbl: 'Workspace name',
    projCreateNamePh: 'e.g. weekly report',
    projCreateInstrLbl: 'Workspace instructions (optional)',
    projCreateInstrPh: 'Applied to every chat in this workspace…',
    projCreateSubmit: 'Create workspace',
    projImportEmpty: 'No workspaces yet — start from scratch first',
    projFolderPick: 'Use this folder',
    projFolderUp: 'Up',
    projFolderRoot: 'Workspace root',
    projDetailBack: '‹ Workspaces',
    projDetailPrompt: 'What would you like to work on in this workspace?',
    projDetailStart: 'Start',
    projDetailRecents: 'Recents',
    projDetailInstr: 'Instructions',
    projDetailContext: 'Context',
    projDetailEmptySessions: 'No chats yet — describe a task above to begin',
    projDetailNoInstr: '(No instructions yet)',
  },
};
let uiLang = 'zh';

function t(key) {
  return (I18N[uiLang] && I18N[uiLang][key]) || I18N.zh[key] || key;
}

function setLanguage(lang) {
  uiLang = lang === 'en' ? 'en' : 'zh';
  localStorage.setItem('captain-lang', uiLang);
  document.documentElement.lang = uiLang === 'en' ? 'en' : 'zh-CN';
  const sel = document.getElementById('cfg-lang');
  if (sel) sel.value = uiLang;
  applyI18n();
  setWorkMode(workMode);
  if (document.getElementById('chat-status-bar')?.classList.contains('is-connecting')) {
    setStatusBarConnecting();
  }
}

function applyI18n() {
  const map = {
    'btn-new-chat': 'newChat',
    'foot-customize': 'footCustomize',
    'foot-settings': 'footSettings',
    'nav-usage': 'navUsage',
    'nav-general': 'settingsGeneral',
    'nav-channels': 'navChannels',
    'nav-tasks': 'navTasks',
    'nav-governance': 'navGovernance',
    'nav-about': 'navAbout',
    'nav-group-common': 'navGroupCommon',
    'nav-group-advanced': 'navGroupAdvanced',
    'settings-nav-title': 'settingsNavTitle',
    'settings-general-title': 'settingsGeneral',
    'settings-usage-title': 'settingsUsage',
    'settings-usage-desc': 'settingsUsageDesc',
    'settings-channels-title': 'navChannels',
    'settings-channels-desc': 'settingsChannelsDesc',
    'settings-tasks-title': 'settingsTasks',
    'settings-tasks-desc': 'settingsTasksDesc',
    'settings-governance-title': 'settingsGovernance',
    'settings-governance-desc': 'settingsGovernanceDesc',
    'settings-about-title': 'settingsAbout',
    'settings-about-desc': 'settingsAboutDesc',
    'about-tagline': 'aboutTagline',
    'about-features': 'aboutFeatures',
    'gov-stats-hint': 'govStatsHint',
    'usage-lbl-tokens': 'usageLblTokens',
    'usage-lbl-cost': 'usageLblCost',
    'usage-lbl-tasks': 'usageLblTasks',
    'usage-daily-title': 'usageDailyTitle',
    'settings-general-desc': 'settingsGeneralDesc',
    'lbl-lang': 'lblLang',
    'lbl-model': 'lblModel',
    'btn-settings-refresh': 'btnSettingsRefresh',
    'btn-settings-save': 'btnSettingsSave',
    'btn-open-shortcuts': 'shortcutsLink',
    'shortcuts-title': 'shortcutsTitle',
  };
  Object.entries(map).forEach(([id, key]) => {
    const el = document.getElementById(id);
    if (!el || !key) return;
    el.textContent = t(key);
  });
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (key) el.textContent = t(key);
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    const key = el.getAttribute('data-i18n-title');
    if (key) el.setAttribute('title', t(key));
  });
  document.querySelectorAll('[data-i18n-opt]').forEach(el => {
    const key = el.getAttribute('data-i18n-opt');
    if (key) el.textContent = t(key);
  });
  document.getElementById('lang-zh')?.classList.toggle('active', uiLang === 'zh');
  document.getElementById('lang-en')?.classList.toggle('active', uiLang === 'en');
  const searchEl = document.getElementById('history-search');
  if (searchEl) searchEl.placeholder = t('historySearch');
  const projSearch = document.getElementById('proj-search');
  if (projSearch) projSearch.placeholder = t('projSearchPh');
  const projTask = document.getElementById('proj-task-inp');
  if (projTask) projTask.placeholder = t('projDetailPrompt');
  const gov = document.getElementById('cfg-governance-mode');
  if (gov && gov.options.length >= 3) {
    gov.options[0].textContent = t('govConservative');
    gov.options[1].textContent = t('govBalanced');
    gov.options[2].textContent = t('govAggressive');
  }
  const lblGov = document.getElementById('lbl-gov');
  if (lblGov) lblGov.textContent = t('lblGov');
  const lblCost = document.getElementById('lbl-max-cost');
  if (lblCost) lblCost.textContent = t('lblMaxCost');
  const lblSteps = document.getElementById('lbl-max-steps');
  if (lblSteps) lblSteps.textContent = t('lblMaxSteps');
  const inp = document.getElementById('chat-inp');
  if (inp) inp.placeholder = t(`placeholder_${workMode}`);
  const sendBtn = document.getElementById('btn-send');
  if (sendBtn && !taskRunning) sendBtn.setAttribute('aria-label', t('btnSend'));
  const sessionTitle = document.getElementById('chat-session-title-text');
  if (sessionTitle) syncChatTopbarTitle();
  _wbUpdateProgressFraction();
  const area = document.getElementById('chat-messages');
  if (area && !area.querySelector('.msg')) area.innerHTML = welcomeHtml();
  renderSessions(allSessions);
  renderShortcutsList();
  renderQuickActions();
}

function isTypingTarget(el) {
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
}

function modKey(e) {
  return navigator.platform.includes('Mac') ? e.metaKey : e.ctrlKey;
}

function openShortcuts() {
  document.getElementById('shortcuts-overlay')?.classList.add('open');
  renderShortcutsList();
}

function closeShortcuts() {
  document.getElementById('shortcuts-overlay')?.classList.remove('open');
}

function renderShortcutsList() {
  const el = document.getElementById('shortcuts-list');
  if (!el) return;
  const mod = navigator.platform.includes('Mac') ? '⌘' : 'Ctrl';
  const rows = [
    [`${mod}+N`, t('skNewChat')],
    [`${mod}+,`, t('skSettings')],
    [`${mod}+/`, t('skFocus')],
    ['Esc', t('skClose')],
    ['?', t('skHelp')],
  ];
  el.innerHTML = rows.map(([k, desc]) =>
    `<div><kbd>${escHtml(k)}</kbd>${escHtml(desc)}</div>`
  ).join('');
}

function closeAllOverlays() {
  closeSettings();
  closeCustomize();
  closeProjectCreate();
  closeCoworkFolderPicker();
  closeModelPicker();
  closeAttachMenu();
  closeShortcuts();
}

function initSidebarState() {
  const app = document.getElementById('app');
  if (!isMobileLayout() && localStorage.getItem('captain-sb-collapsed') === '1') {
    app.classList.add('sb-collapsed');
  }
  updateSidebarToggle();
}

function setWorkMode(mode, opts = {}) {
  const prev = workMode;
  workMode = ['chat', 'coworker'].includes(mode) ? mode : 'chat';
  localStorage.setItem('captain-work-mode', workMode);
  syncConciseChat();
  try {
    const app = document.getElementById('app');
    if (app) app.classList.toggle('wb-open', workMode === 'coworker');
    // 只有真正绑定了文件夹才显示工作目录内容;没选则留空(不自动列工作区根)
    if (workMode === 'coworker' && (_filesDir || _coworkWorkspaceDir)) {
      loadFiles(_filesDir || _coworkWorkspaceDir);
    }
    updateWorkbenchToggle();
  } catch {}

  document.querySelectorAll('.mode-tab').forEach(tab => {
    const on = tab.dataset.mode === workMode;
    tab.classList.toggle('active', on);
    tab.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  const view = document.getElementById('view-chat');
  if (view) {
    view.classList.toggle('mode-coworker', workMode === 'coworker');
    view.classList.toggle('mode-chat', workMode === 'chat');
  }

  applyModeChrome();

  if (currentView === 'projects' || currentView === 'project') switchView('chat');

  const inp = document.getElementById('chat-inp');
  if (inp) inp.placeholder = t(`placeholder_${workMode}`);

  const modeChanged = prev !== workMode;
  if (opts.sessionId) {
    sessionId = opts.sessionId;
    persistSessionId();
  } else if (modeChanged) {
    sessionId = loadSessionIdForMode(workMode);
  }

  const reloadHistory = opts.reloadHistory || modeChanged || !!opts.sessionId;
  if (reloadHistory) {
    resetStreamingBubble();
    if (!opts.preserveTask) {
      setTaskRunning(false);
      taskSessionId = '';
    }
    clearChat();
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(wsInitPayload()));
    syncChatTopbarTitle();
    if (typeof restoreWorkbench === 'function') restoreWorkbench();   // 恢复该会话的工作目录+产物
  } else {
    const sub = document.querySelector('#chat-empty .welcome-sub');
    if (sub) sub.textContent = t(`welcome_${workMode}`);
    const area = document.getElementById('chat-messages');
    if (area && !area.querySelector('.msg')) area.innerHTML = welcomeHtml();
  }
}

function initWorkMode() {
  migrateLegacySession();
  const saved = localStorage.getItem('captain-work-mode');
  workMode = ['chat', 'coworker'].includes(saved) ? saved : 'chat';
  if (saved === 'code') localStorage.setItem('captain-work-mode', 'chat');
  sessionId = loadSessionIdForMode(workMode);
  setWorkMode(workMode, { reloadHistory: false });
  if (typeof restoreWorkbench === 'function') restoreWorkbench();   // 初次加载也恢复工作台
}

function initLanguage() {
  setLanguage(localStorage.getItem('captain-lang') || 'zh');
}

async function loadSlashCommands() {
  try {
    const res = await fetch('/api/commands');
    const data = await res.json();
    slashCommands = data.commands || [];
  } catch {
    slashCommands = [
      {cmd:'/model', label:'切换大模型', hint:'/model deepseek-v4-flash', group:'系统'},
      {cmd:'/experts', label:'列出执行专家', hint:'/experts', group:'系统'},
      {cmd:'/skills', label:'列出 Skill', hint:'/skills', group:'系统'},
      {cmd:'/rollback', label:'撤销文件改动', hint:'/rollback', group:'系统'},
    ];
  }
}

function filterSlashCommands(query) {
  const q = (query || '').trim().toLowerCase();
  if (!q.startsWith('/')) return [];
  return slashCommands.filter(c => (c.cmd || '').toLowerCase().startsWith(q));
}

function renderSlashMenu(matches) {
  const menu = document.getElementById('slash-menu');
  if (!matches.length) {
    menu.classList.remove('open');
    menu.innerHTML = '';
    slashActiveIdx = 0;
    return;
  }
  slashActiveIdx = Math.min(slashActiveIdx, matches.length - 1);
  let lastGroup = '';
  let html = '';
  matches.forEach((c, i) => {
    if (c.group && c.group !== lastGroup) {
      html += `<div class="slash-group">${escHtml(c.group)}</div>`;
      lastGroup = c.group;
    }
    const active = i === slashActiveIdx ? ' active' : '';
    html += `<div class="slash-item${active}" data-idx="${i}" role="option">
      <span class="slash-cmd">${escHtml(c.cmd)}</span>
      <div class="slash-meta">
        <div class="slash-label">${escHtml(c.label || '')}</div>
        ${c.hint ? `<div class="slash-hint">${escHtml(c.hint)}</div>` : ''}
      </div>
    </div>`;
  });
  menu.innerHTML = html;
  menu.classList.add('open');
  menu.querySelectorAll('.slash-item').forEach(el => {
    el.onclick = () => applySlashCommand(matches[Number(el.dataset.idx)]);
  });
  const activeEl = menu.querySelector('.slash-item.active');
  if (activeEl) activeEl.scrollIntoView({ block: 'nearest' });
}

function applySlashCommand(item) {
  if (!item) return;
  const inp = document.getElementById('chat-inp');
  const cmd = item.cmd || '';
  const hasArg = cmd.includes(' ');
  inp.value = hasArg ? cmd : (cmd + ' ');
  inp.focus();
  closeSlashMenu();
  inp.dispatchEvent(new Event('input'));
  const len = inp.value.length;
  inp.setSelectionRange(len, len);
}

const INSTANT_SLASH = new Set(['/skills', '/skill', '/experts', '/rollback']);

function slashSendsImmediately(text) {
  const t = text.trim().toLowerCase();
  if (INSTANT_SLASH.has(t)) return true;
  return t === '/model' || t === '/models';
}

function slashInputHasArgs(text) {
  const t = text.trim();
  const m = t.match(/^\/\S+\s+(.+)/s);
  return !!(m && m[1].trim());
}

function closeSlashMenu() {
  document.getElementById('slash-menu').classList.remove('open');
  slashActiveIdx = 0;
}

function slashMenuOpen() {
  return document.getElementById('slash-menu').classList.contains('open');
}

function updateSlashMenuFromInput() {
  const inp = document.getElementById('chat-inp');
  const val = inp.value;
  if (!val.startsWith('/')) {
    closeSlashMenu();
    return;
  }
  const matches = filterSlashCommands(val);
  renderSlashMenu(matches);
}

const chatInpEl = document.getElementById('chat-inp');
chatInpEl.addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 160) + 'px';
  slashActiveIdx = 0;
  updateSlashMenuFromInput();
});
chatInpEl.addEventListener('keydown', e => {
  const matches = filterSlashCommands(chatInpEl.value);
  if (slashMenuOpen() && matches.length) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      slashActiveIdx = (slashActiveIdx + 1) % matches.length;
      renderSlashMenu(matches);
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      slashActiveIdx = (slashActiveIdx - 1 + matches.length) % matches.length;
      renderSlashMenu(matches);
      return;
    }
    if (e.key === 'Tab') {
      e.preventDefault();
      applySlashCommand(matches[slashActiveIdx]);
      return;
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      const cur = chatInpEl.value.trim();
      if (slashInputHasArgs(cur) || slashSendsImmediately(cur)) {
        closeSlashMenu();
        sendMsg();
        return;
      }
      applySlashCommand(matches[slashActiveIdx]);
      return;
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      closeSlashMenu();
      return;
    }
  }
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMsg(); }
});

document.addEventListener('click', (e) => {
  const wrap = document.getElementById('model-picker-wrap');
  if (wrap && !wrap.contains(e.target)) closeModelPicker();
  const attachWrap = document.getElementById('attach-menu-wrap');
  if (attachWrap && !attachWrap.contains(e.target)) closeAttachMenu();
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { closeAllOverlays(); return; }
  if (e.key === '?' && !isTypingTarget(document.activeElement)) {
    e.preventDefault();
    openShortcuts();
    return;
  }
  if (!modKey(e)) return;
  const k = e.key.toLowerCase();
  if (k === 'n') { e.preventDefault(); newChat(); return; }
  if (e.key === ',') { e.preventDefault(); openSettings('general'); return; }
  if (k === '/' || k === 'k') { e.preventDefault(); document.getElementById('chat-inp')?.focus(); }
});

/* ══ 初始化 ══════════════════════════════════════════════════════ */
switchView('chat');
initLanguage();
initSidebarState();
initWorkMode();
applyModeChrome();
setStatusBarConnecting();
syncConciseChat();
window.addEventListener('resize', () => {
  const app = document.getElementById('app');
  if (!isMobileLayout()) app.classList.remove('sb-mobile-open');
  updateSidebarToggle();
});
refreshSessions();
initComposerModel().then((picked) => {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(wsInitPayload()));
  return picked;
});
connect();
(function initWorkbenchClicks() {
  document.getElementById('wb-artifacts')?.addEventListener('click', (e) => {
    const row = e.target.closest('[data-artifact-path]');
    if (row?.dataset.artifactPath) openArtifact(row.dataset.artifactPath);
  });
  document.getElementById('wb-files')?.addEventListener('click', (e) => {
    const row = e.target.closest('[data-file-rel]');
    if (!row?.dataset.fileRel) return;
    if (row.dataset.fileType === 'dir') loadFiles(row.dataset.fileRel);
    else openArtifact(row.dataset.fileRel);
  });
  document.getElementById('artifacts-list')?.addEventListener('click', (e) => {
    const row = e.target.closest('[data-artifact-path]');
    if (!row?.dataset.artifactPath) return;
    closeArtifactsBrowser();
    openArtifact(row.dataset.artifactPath);
  });
})();
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && (!ws || ws.readyState === WebSocket.CLOSED)) connect();
});
loadSlashCommands();
loadSkillLabels();
loadSettingsUI();

/* FRONTEND_CONTRACT 别名 */
function connectWS() { connect(); }
function sendMessage() { sendMsg(); }

function focusArtifacts() {
  // 「产物」按钮:打开历史产物浏览器,检索之前输出的所有产物
  if (typeof openArtifactsBrowser === 'function') { openArtifactsBrowser(); return; }
  const app = document.getElementById('app');
  if (app) app.classList.add('wb-open');
  const wb = document.getElementById('workbench');
  if (wb) loadFiles(_filesDir || '');
  document.getElementById('wb-artifacts-sec')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function addProjectContext() {
  if (workMode === 'coworker') {
    openCoworkFolderPicker();
    return;
  }
  const sel = document.getElementById('project-select');
  if (sel && sel.value) {
    const name = sel.options[sel.selectedIndex]?.text?.replace(/^📁\s*/, '') || '';
    const inp = document.getElementById('chat-inp');
    if (inp && name) inp.value = t('projectCtxPrefix').replace('{name}', name) + inp.value;
    inp?.focus();
    return;
  }
  createProjectPrompt();
}

/* 声明已提升至顶部状态区(避免 init TDZ);此处仅保留初值重置 */
_coworkWorkspaceDir = '';
_coworkFolderDir = '';

function updateCoworkFolderChip(dir) {
  _coworkWorkspaceDir = dir || '';
}

function openCoworkFolderPicker() {
  _coworkFolderDir = _coworkWorkspaceDir || _filesDir || '';
  closeModelPicker();
  const el = document.getElementById('cowork-folder-overlay');
  if (el) el.classList.add('open');
  renderCoworkFolderPicker();
}

function closeCoworkFolderPicker() {
  document.getElementById('cowork-folder-overlay')?.classList.remove('open');
}

async function renderCoworkFolderPicker() {
  const bar = document.getElementById('cowork-folder-bar');
  const box = document.getElementById('cowork-folder-list');
  if (!box) return;
  if (bar) {
    const label = _coworkFolderDir || t('projFolderRoot');
    bar.innerHTML = _coworkFolderDir
      ? `<button type="button" class="proj-create-back" style="margin:0" onclick="coworkFolderUp()">‹ ${escHtml(t('projFolderUp'))}</button><span>${escHtml(label)}</span>`
      : `<span>${escHtml(label)}</span>`;
  }
  box.innerHTML = `<div style="padding:12px;color:var(--dim);font-size:13px">${escHtml(t('connecting'))}</div>`;
  try {
    const r = await fetch('/api/files?dir=' + encodeURIComponent(_coworkFolderDir || ''));
    const d = await r.json();
    if (!d.ok) {
      box.innerHTML = `<div style="padding:12px;color:var(--red);font-size:13px">${escHtml(d.error || t('usageLoadFailed'))}</div>`;
      return;
    }
    const dirs = (d.items || []).filter(it => it.type === 'dir');
    if (!dirs.length) {
      box.innerHTML = `<div style="padding:12px;color:var(--dim);font-size:13px">—</div>`;
      return;
    }
    box.innerHTML = dirs.map(it => {
      const rel = escHtml(it.rel);
      return `<button type="button" class="proj-folder-row" onclick="coworkFolderEnter('${rel}')">📁 ${escHtml(it.name)}</button>`;
    }).join('');
  } catch {
    box.innerHTML = `<div style="padding:12px;color:var(--red);font-size:13px">${escHtml(t('usageLoadFailed'))}</div>`;
  }
}

function coworkFolderEnter(rel) {
  _coworkFolderDir = rel;
  renderCoworkFolderPicker();
}

function coworkFolderUp() {
  if (!_coworkFolderDir) return;
  const parts = _coworkFolderDir.split('/').filter(Boolean);
  parts.pop();
  _coworkFolderDir = parts.join('/');
  renderCoworkFolderPicker();
}

async function confirmCoworkFolder() {
  const dir = _coworkFolderDir || '';
  closeCoworkFolderPicker();
  const app = document.getElementById('app');
  if (app) app.classList.add('wb-open');
  loadFiles(dir);
  updateCoworkFolderChip(dir);
  refreshWorkbenchMeta();
  if (typeof _saveWorkbench === 'function') _saveWorkbench({ workspace_dir: dir });   // 按会话固定
  if (_currentProject) {
    try {
      const r = await fetch(`/api/projects/${encodeURIComponent(_currentProject)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace: dir }),
      });
      const d = await r.json();
      if (r.ok && d.ok && d.project) {
        const p = _projectsCache.find(x => x.id === _currentProject);
        if (p) p.workspace = dir;
      }
    } catch {}
  }
  const inp = document.getElementById('chat-inp');
  if (inp) {
    const label = dir || t('projFolderRoot');
    inp.value = t('folderCtxRef').replace('{path}', label) + inp.value;
    inp.focus();
  }
}

function triggerFolderUpload() {
  document.getElementById('folder-inp')?.click();
}

function readFileAsB64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1] || '');
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function onFolderPicked(input) {
  const files = Array.from(input.files || []);
  input.value = '';
  if (!files.length) return;
  closeCoworkFolderPicker();
  const root = (files[0].webkitRelativePath || files[0].name || '').split('/')[0] || 'folder';
  let ok = 0;
  let skip = 0;
  for (const file of files) {
    if (file.size > 20 * 1024 * 1024) { skip++; continue; }
    const rel = file.webkitRelativePath || file.name;
    try {
      const b64 = await readFileAsB64(file);
      const r = await fetch('/api/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: file.name, rel_path: 'uploads/' + rel, content_b64: b64 }),
      });
      const d = await r.json();
      if (d.ok) ok++; else skip++;
    } catch { skip++; }
  }
  const uploadDir = 'uploads/' + root;
  const app = document.getElementById('app');
  if (app) app.classList.add('wb-open');
  loadFiles(uploadDir);
  updateCoworkFolderChip(uploadDir);
  if (typeof _saveWorkbench === 'function') _saveWorkbench({ workspace_dir: uploadDir });   // 按会话固定
  // 不再往输入框注入「[已上传文件夹: ...]」——文件夹已在工作台显示,无需污染每条对话的输入框
  if (skip > 0) alert(t('folderUploadPartial').replace('{ok}', String(ok)).replace('{skip}', String(skip)));
  else if (ok > 0) alert(t('folderUploadDone').replace('{ok}', String(ok)));
}

function updateSessionTitle(text) {
  const el = document.getElementById('chat-session-title-text');
  if (el && text) el.textContent = text;
}

function currentSessionRecord() {
  return (allSessions || []).find(x => x.id === sessionId) || null;
}

function deriveTitleFromDom() {
  const el = document.querySelector('#chat-messages .msg-user .user-body, #chat-messages .msg-user');
  if (!el) return '';
  return (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40);
}

function projectPrefix(s) {
  // 归属工作区(项目)的对话:返回「项目名」前缀,避免和普通对话混在一起。
  if (!s || !s.project_id) return '';
  const proj = (_projectsCache || []).find(x => x.id === s.project_id);
  return (proj && proj.name) ? `「${proj.name}」` : '';
}

function formatSessionTitle(s) {
  const raw = (s && s.title ? String(s.title) : '').trim();
  const clean = raw ? raw.replace(/^[💬⌨️🤝]\s*/, '') : '';
  return clean ? projectPrefix(s) + clean : clean;
}

function syncChatTopbarTitle() {
  const el = document.getElementById('chat-session-title-text');
  if (!el) return;
  let title = formatSessionTitle(currentSessionRecord());
  if (!title) title = deriveTitleFromDom();
  if (!title) title = t('untitledChat');
  el.textContent = title;
}

function maybeSetTitleFromFirstMessage(text) {
  if (formatSessionTitle(currentSessionRecord())) return;
  const trimmed = (text || '').trim().replace(/\n/g, ' ').slice(0, 40);
  if (trimmed) updateSessionTitle(trimmed);
}

function syncSessionTitleFromHistory() {
  syncChatTopbarTitle();
}

function _wbUpdateProgressFraction() {
  const nodes = document.querySelectorAll('#wb-plan .wbn');
  const total = nodes.length;
  const done = document.querySelectorAll('#wb-plan .wbn.done').length;
  const countEl = document.getElementById('wb-progress-count');
  const bar = document.getElementById('wb-progress-bar');
  if (countEl) countEl.textContent = total
    ? t('progressCount').replace('{done}', String(done)).replace('{total}', String(total))
    : t('progressCountZero');
  if (bar) bar.style.width = total ? `${Math.round((done / total) * 100)}%` : '0%';
  refreshWbPlanEmpty();
  if (typeof _wbProgress === 'function' && !taskRunning) _wbProgress(false);
}

function refreshWbPlanEmpty() {
  const empty = document.getElementById('wb-plan-empty');
  const plan = document.getElementById('wb-plan');
  if (!empty) return;
  const has = plan && plan.querySelector('.wbn');
  empty.style.display = has ? 'none' : 'block';
}
