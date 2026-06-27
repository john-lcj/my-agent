/* ══ Projects / Artifacts / 上传 / 模式  —— 借鉴 Claude 设计的增量功能 ══ */

/* —— 项目空间(声明已提升至顶部状态区,避免 init TDZ)—— */
_currentProject = "";
_projectsCache = [];

function openProjectsView() {
  switchView('projects');
  renderProjectsPage();
  expandSbProjectsMenu();
}

async function ensureProjectsCache() {
  if (_projectsCache.length) return;
  try {
    const r = await fetch('/api/projects');
    const d = await r.json();
    _projectsCache = d.projects || [];
  } catch {}
}

function renderSbProjectMenu() {
  const list = document.getElementById('sb-proj-list');
  if (!list) return;
  const items = [...(_projectsCache || [])].sort((a, b) => {
    const ta = a.updated_at || a.created_at || 0;
    const tb = b.updated_at || b.created_at || 0;
    return tb - ta;
  });
  if (!items.length) {
    list.innerHTML = `<div class="sb-proj-empty">${escHtml(t('projEmpty'))}</div>`;
    return;
  }
  list.innerHTML = items.map(p => {
    const pid = escHtml(p.id);
    const cur = p.id === _currentProject ? ' current' : '';
    return `<button type="button" class="sb-proj-item${cur}" role="menuitem" data-pid="${pid}"
      onclick="selectSbProject(this.dataset.pid)">${escHtml(p.name)}</button>`;
  }).join('');
}

function expandSbProjectsMenu() {
  const nav = document.getElementById('sb-proj-nav');
  const btn = document.getElementById('btn-nav-projects');
  if (!nav) return;
  nav.classList.add('expanded');
  if (btn) btn.setAttribute('aria-expanded', 'true');
  renderSbProjectMenu();
}

function closeSbProjectsMenu() {
  const nav = document.getElementById('sb-proj-nav');
  const btn = document.getElementById('btn-nav-projects');
  if (!nav) return;
  nav.classList.remove('expanded');
  if (btn) btn.setAttribute('aria-expanded', 'false');
}

async function toggleSbProjectsMenu(e) {
  e?.stopPropagation();
  const nav = document.getElementById('sb-proj-nav');
  if (!nav) return;
  const willOpen = !nav.classList.contains('expanded');
  if (willOpen) {
    await ensureProjectsCache();
    expandSbProjectsMenu();
  } else {
    closeSbProjectsMenu();
  }
}

function selectSbProject(pid) {
  closeSbProjectsMenu();
  closeMobileSidebar();
  openProjectArchive(pid);
}

document.addEventListener('click', (e) => {
  const nav = document.getElementById('sb-proj-nav');
  if (!nav || !nav.classList.contains('expanded')) return;
  if (e.target.closest('#sb-proj-nav')) return;
  closeSbProjectsMenu();
});

function formatProjDate(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    const locale = uiLang === 'en' ? 'en-US' : 'zh-CN';
    return d.toLocaleDateString(locale, { month: 'short', day: 'numeric' });
  } catch { return '—'; }
}

async function renderProjectsPage() {
  const grid = document.getElementById('proj-grid');
  const search = document.getElementById('proj-search');
  if (!grid) return;
  grid.innerHTML = `<div style="color:var(--dim);font-size:13px">${escHtml(t('connecting'))}</div>`;
  try {
    const r = await fetch('/api/projects');
    const d = await r.json();
    _projectsCache = d.projects || [];
  } catch {
    grid.innerHTML = `<div style="color:var(--red)">${escHtml(t('usageLoadFailed'))}</div>`;
    return;
  }
  renderSbProjectMenu();
  const q = (search?.value || '').trim().toLowerCase();
  let items = _projectsCache.filter(p => !q || (p.name || '').toLowerCase().includes(q));
  const sort = document.getElementById('proj-sort')?.value || 'updated';
  items.sort((a, b) => {
    if (sort === 'name') return (a.name || '').localeCompare(b.name || '', uiLang === 'en' ? 'en' : 'zh');
    const ta = a.updated_at || a.created_at || '';
    const tb = b.updated_at || b.created_at || '';
    return tb.localeCompare(ta);
  });
  if (!items.length) {
    grid.innerHTML = `<div style="color:var(--dim);grid-column:1/-1;font-size:13px">${escHtml(t('projEmpty'))}</div>`;
    return;
  }
  grid.innerHTML = items.map(p => {
    const pid = escHtml(p.id);
    const updated = formatProjDate(p.updated_at || p.created_at);
    return `<div class="proj-card-wrap">
      <button type="button" class="proj-card" data-pid="${pid}" onclick="selectProjectFromPage(this.dataset.pid)">
        <div class="proj-card-name">${escHtml(p.name)}</div>
        <div class="proj-card-meta">${escHtml(t('projUpdated').replace('{date}', updated))}</div>
      </button>
      <div class="proj-card-actions">
        <button type="button" class="proj-card-act" data-pid="${pid}" title="${escHtml(t('renameChat'))}"
                onclick="event.stopPropagation();renameProjectById(this.dataset.pid)">✎</button>
        <button type="button" class="proj-card-act del" data-pid="${pid}" title="${escHtml(t('deleteChat'))}"
                onclick="event.stopPropagation();deleteProjectById(this.dataset.pid)">×</button>
      </div>
    </div>`;
  }).join('');
}

async function renameProjectById(pid) {
  const p = _projectsCache.find(x => x.id === pid);
  if (!p) return;
  const name = prompt(t('projRenamePrompt'), p.name || '');
  if (name === null) return;
  const trimmed = name.trim();
  if (!trimmed || trimmed === (p.name || '')) return;
  try {
    const r = await fetch(`/api/projects/${encodeURIComponent(pid)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: trimmed }),
    });
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error(d.error || 'fail');
    p.name = trimmed;
    await loadProjects();
    renderProjectsPage();
    if (_currentProject === pid) {
      const title = document.getElementById('proj-detail-title');
      if (title) title.textContent = trimmed;
    }
  } catch {
    alert(t('projRenameFailed'));
  }
}

async function deleteProjectById(pid) {
  const p = _projectsCache.find(x => x.id === pid);
  if (!p) return;
  if (!confirm(t('projDeleteConfirm').replace('{name}', p.name || ''))) return;
  try {
    const r = await fetch(`/api/projects/${encodeURIComponent(pid)}`, { method: 'DELETE' });
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error('fail');
    _projectsCache = _projectsCache.filter(x => x.id !== pid);
    if (_currentProject === pid) {
      _currentProject = '';
      const sel = document.getElementById('project-select');
      if (sel) sel.value = '';
      onProjectChange('');
      if (currentView === 'project') openProjectsView();
    }
    await loadProjects();
    renderProjectsPage();
  } catch {
    alert(t('projDeleteFailed'));
  }
}

function selectProjectFromPage(pid) {
  openProjectArchive(pid);
}

async function openProjectArchive(pid) {
  if (!pid) return;
  let proj = _projectsCache.find(p => p.id === pid);
  if (!proj) {
    try {
      const r = await fetch('/api/projects');
      const d = await r.json();
      _projectsCache = d.projects || [];
      proj = _projectsCache.find(p => p.id === pid);
    } catch {}
  }
  if (!proj) return;
  const sel = document.getElementById('project-select');
  if (sel) sel.value = pid;
  _currentProject = pid;
  onProjectChange(pid);
  if (proj.workspace && typeof loadFiles === 'function') {
    loadFiles(proj.workspace);
    updateCoworkFolderChip(proj.workspace);
  }
  if (workMode !== 'coworker') setWorkMode('coworker');
  renderProjectDetail(proj);
  switchView('project');
}

function renderProjectDetail(proj) {
  const title = document.getElementById('proj-detail-title');
  const instr = document.getElementById('proj-detail-instr');
  const ctx = document.getElementById('proj-detail-context');
  const list = document.getElementById('proj-detail-sessions');
  if (title) title.textContent = proj.name || '';
  if (instr) {
    const text = (proj.instructions || '').trim();
    instr.textContent = text || t('projDetailNoInstr');
    instr.style.color = text ? 'var(--muted)' : 'var(--dim)';
  }
  if (ctx) {
    const bits = [];
    if (proj.workspace) bits.push(`<div class="proj-panel-ctx">📁 ${escHtml(proj.workspace)}</div>`);
    (proj.knowledge || []).forEach(p => {
      bits.push(`<div class="proj-panel-ctx">📄 ${escHtml(String(p).split('/').pop())}</div>`);
    });
    ctx.innerHTML = bits.length ? bits.join('') : `<div class="proj-panel-body" style="color:var(--dim)">—</div>`;
  }
  if (!list) return;
  const sessions = (allSessions || [])
    .filter(s => s.project_id === proj.id && sessionBelongsToWorkMode(s))
    .sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0));
  if (!sessions.length) {
    list.innerHTML = `<div style="color:var(--dim);font-size:13px;padding:8px 0">${escHtml(t('projDetailEmptySessions'))}</div>`;
    return;
  }
  list.innerHTML = sessions.map(s => {
    const sid = escHtml(s.id);
    const stitle = escHtml(s.title || t('untitledChat'));
    const when = s.updated_at
      ? formatProjDate(new Date(s.updated_at * 1000).toISOString())
      : '—';
    return `<button type="button" class="proj-detail-session" data-sid="${sid}" onclick="openProjectSession(this.dataset.sid)">
      <div class="proj-detail-session-title">${stitle}</div>
      <div class="proj-detail-session-meta">${escHtml(when)}</div>
    </button>`;
  }).join('');
}

function openProjectSession(sid) {
  if (!sid) return;
  switchToSession(sid);
}

async function startProjectTask() {
  const inp = document.getElementById('proj-task-inp');
  const text = (inp?.value || '').trim();
  if (!text) { inp?.focus(); return; }
  if (inp) inp.value = '';
  await newChat();
  switchView('chat');
  const chatInp = document.getElementById('chat-inp');
  if (chatInp) chatInp.value = text;
  sendMsg();
}

function shareCurrentChat() {
  const title = document.getElementById('chat-session-title-text')?.textContent?.trim() || 'Captain';
  const msgs = document.querySelectorAll('#chat-messages .msg');
  let md = `# ${title}\n\n`;
  msgs.forEach(m => {
    const role = m.classList.contains('msg-user') ? 'User' : 'Captain';
    const body = m.querySelector('.md') || m.querySelector('.msg-body') || m;
    md += `## ${role}\n\n${(body.textContent || '').trim()}\n\n`;
  });
  navigator.clipboard.writeText(md).catch(() => {});
}

async function loadProjects() {
  try {
    const r = await fetch('/api/projects'); const d = await r.json();
    _projectsCache = d.projects || [];
    const sel = document.getElementById('project-select');
    if (sel) {
      const keep = sel.value;
      sel.innerHTML = `<option value="">${escHtml(t('projectFilterAll'))}</option>`
        + (_projectsCache || []).map(p => `<option value="${p.id}">📁 ${escHtml(p.name)}</option>`).join('');
      sel.value = keep;
    }
    renderSbProjectMenu();
  } catch {}
}
function onProjectChange(pid) {
  _currentProject = pid || "";
  syncChatTopbarTitle();
  const list = _currentProject
    ? (allSessions || []).filter(s => s.project_id === _currentProject)
    : (allSessions || []);
  renderSessions(list);
}

let _projCreateStep = 'choose';
let _projFolderDir = '';

function closeProjectCreate() {
  document.getElementById('project-create-overlay')?.classList.remove('open');
  _projCreateStep = 'choose';
  _projFolderDir = '';
}

function createProjectPrompt() {
  _projCreateStep = 'choose';
  _projFolderDir = '';
  renderProjectCreateStep();
  document.getElementById('project-create-overlay')?.classList.add('open');
}

function renderProjectCreateStep() {
  const body = document.getElementById('proj-create-body');
  const title = document.getElementById('proj-create-title');
  if (!body) return;
  if (title) title.textContent = t('projCreateTitle');
  if (_projCreateStep === 'choose') {
    body.innerHTML = `
      <p class="proj-create-desc">${escHtml(t('projCreateDesc'))}</p>
      <div class="proj-create-options">
        <button type="button" class="proj-create-opt" onclick="showProjectCreateStep('scratch')">
          <span class="proj-create-opt-ic"><svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg></span>
          <span><div class="proj-create-opt-title">${escHtml(t('projOptScratch'))}</div>
          <div class="proj-create-opt-sub">${escHtml(t('projOptScratchSub'))}</div></span>
        </button>
        <button type="button" class="proj-create-opt" onclick="showProjectCreateStep('import')">
          <span class="proj-create-opt-ic"><svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12"/></svg></span>
          <span><div class="proj-create-opt-title">${escHtml(t('projOptImport'))}</div>
          <div class="proj-create-opt-sub">${escHtml(t('projOptImportSub'))}</div></span>
        </button>
        <button type="button" class="proj-create-opt" onclick="showProjectCreateStep('folder')">
          <span class="proj-create-opt-ic"><svg viewBox="0 0 24 24"><path d="M4 7h16a2 2 0 012 2v10a2 2 0 01-2 2H4a2 2 0 01-2-2V9a2 2 0 012-2z"/><path d="M4 7l2-3h6l2 3"/></svg></span>
          <span><div class="proj-create-opt-title">${escHtml(t('projOptFolder'))}</div>
          <div class="proj-create-opt-sub">${escHtml(t('projOptFolderSub'))}</div></span>
        </button>
      </div>`;
    return;
  }
  if (_projCreateStep === 'scratch') {
    body.innerHTML = `
      <button type="button" class="proj-create-back" onclick="showProjectCreateStep('choose')">‹ ${escHtml(t('projCreateBack'))}</button>
      <div class="proj-create-field">
        <label for="proj-create-name">${escHtml(t('projCreateNameLbl'))}</label>
        <input id="proj-create-name" type="text" placeholder="${escHtml(t('projCreateNamePh'))}" autocomplete="off"/>
      </div>
      <div class="proj-create-field">
        <label for="proj-create-instr">${escHtml(t('projCreateInstrLbl'))}</label>
        <textarea id="proj-create-instr" placeholder="${escHtml(t('projCreateInstrPh'))}"></textarea>
      </div>
      <button type="button" class="btn-proj-submit" onclick="submitProjectFromScratch()">${escHtml(t('projCreateSubmit'))}</button>`;
    setTimeout(() => document.getElementById('proj-create-name')?.focus(), 0);
    return;
  }
  if (_projCreateStep === 'import') {
    body.innerHTML = `
      <button type="button" class="proj-create-back" onclick="showProjectCreateStep('choose')">‹ ${escHtml(t('projCreateBack'))}</button>
      <div class="proj-import-list" id="proj-import-list"><div style="color:var(--dim);font-size:13px">${escHtml(t('connecting'))}</div></div>`;
    renderProjectImportList();
    return;
  }
  if (_projCreateStep === 'folder') {
    body.innerHTML = `
      <button type="button" class="proj-create-back" onclick="showProjectCreateStep('choose')">‹ ${escHtml(t('projCreateBack'))}</button>
      <div class="proj-folder-bar" id="proj-folder-bar"></div>
      <div class="proj-folder-list" id="proj-folder-list"></div>
      <button type="button" class="btn-proj-submit" id="proj-folder-submit" onclick="submitProjectFromFolder()">${escHtml(t('projFolderPick'))}</button>`;
    renderProjectFolderPicker();
  }
}

function showProjectCreateStep(step) {
  _projCreateStep = step;
  if (step === 'folder') _projFolderDir = '';
  renderProjectCreateStep();
}

async function renderProjectImportList() {
  const box = document.getElementById('proj-import-list');
  if (!box) return;
  try {
    const r = await fetch('/api/projects');
    const d = await r.json();
    const items = d.projects || [];
    if (!items.length) {
      box.innerHTML = `<div style="color:var(--dim);font-size:13px;padding:8px 0">${escHtml(t('projImportEmpty'))}</div>`;
      return;
    }
    _projectsCache = items;
    box.innerHTML = items.map(p => {
      const updated = formatProjDate(p.updated_at || p.created_at);
      return `<button type="button" class="proj-import-item" data-pid="${escHtml(p.id)}" onclick="importExistingProject(this.dataset.pid)">
        <div class="proj-import-name">${escHtml(p.name)}</div>
        <div class="proj-import-meta">${escHtml(t('projUpdated').replace('{date}', updated))}</div>
      </button>`;
    }).join('');
  } catch {
    box.innerHTML = `<div style="color:var(--red);font-size:13px">${escHtml(t('usageLoadFailed'))}</div>`;
  }
}

function importExistingProject(pid) {
  const proj = _projectsCache.find(x => x.id === pid);
  const sel = document.getElementById('project-select');
  if (sel) sel.value = pid;
  onProjectChange(pid);
  closeProjectCreate();
  if (workMode !== 'coworker') setWorkMode('coworker');
  switchView('chat');
  renderProjectsPage();
  if (typeof loadFiles === 'function') {
    loadFiles((proj && proj.workspace) || '');
    updateCoworkFolderChip((proj && proj.workspace) || '');
  }
}

async function renderProjectFolderPicker() {
  const bar = document.getElementById('proj-folder-bar');
  const box = document.getElementById('proj-folder-list');
  const btn = document.getElementById('proj-folder-submit');
  if (!box) return;
  if (bar) {
    const label = _projFolderDir || t('projFolderRoot');
    bar.innerHTML = _projFolderDir
      ? `<button type="button" class="proj-create-back" style="margin:0" onclick="projectFolderUp()">‹ ${escHtml(t('projFolderUp'))}</button><span>${escHtml(label)}</span>`
      : `<span>${escHtml(label)}</span>`;
  }
  if (btn) btn.disabled = false;
  box.innerHTML = `<div style="padding:12px;color:var(--dim);font-size:13px">${escHtml(t('connecting'))}</div>`;
  try {
    const r = await fetch('/api/files?dir=' + encodeURIComponent(_projFolderDir || ''));
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
      return `<button type="button" class="proj-folder-row" onclick="projectFolderEnter('${rel}')">📁 ${escHtml(it.name)}</button>`;
    }).join('');
  } catch {
    box.innerHTML = `<div style="padding:12px;color:var(--red);font-size:13px">${escHtml(t('usageLoadFailed'))}</div>`;
  }
}

function projectFolderEnter(rel) {
  _projFolderDir = rel;
  renderProjectFolderPicker();
}

function projectFolderUp() {
  if (!_projFolderDir) return;
  const parts = _projFolderDir.split('/').filter(Boolean);
  parts.pop();
  _projFolderDir = parts.join('/');
  renderProjectFolderPicker();
}

async function submitProjectFromFolder() {
  const name = (_projFolderDir || '').split('/').filter(Boolean).pop() || t('projFolderRoot');
  await createProjectApi({ name, instructions: '', workspace: _projFolderDir || '' });
}

async function submitProjectFromScratch() {
  const nameEl = document.getElementById('proj-create-name');
  const instrEl = document.getElementById('proj-create-instr');
  const name = (nameEl?.value || '').trim();
  if (!name) { nameEl?.focus(); return; }
  const instructions = (instrEl?.value || '').trim();
  await createProjectApi({ name, instructions });
}

async function createProjectApi(payload) {
  let r, d;
  try {
    r = await fetch('/api/projects', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
  } catch (e) { alert(t('projectCreateFailNet') + e); return; }
  if (!r.ok) { alert(t('projectCreateFailHttp') + r.status + (r.status === 401 ? t('projectCreateFailAuth') : '')); return; }
  try { d = await r.json(); } catch (e) { alert(t('projectCreateFailParse') + e); return; }
  if (!d || !d.ok || !d.project) { alert(t('projectCreateFailUnknown') + ((d && d.error) || 'unknown')); return; }
  try {
    await afterProjectCreated(d);
  } catch (e) { console.error('项目 UI 刷新出错(项目已创建):', e); }
}

async function afterProjectCreated(d) {
  await loadProjects();
  const sel = document.getElementById('project-select');
  if (sel) sel.value = d.project.id;
  onProjectChange(d.project.id);
  renderProjectsPage();
  closeProjectCreate();
  if (d.project.workspace && typeof loadFiles === 'function') {
    loadFiles(d.project.workspace);
    updateCoworkFolderChip(d.project.workspace);
  }
  alert(t('projectCreateOk').replace('{name}', d.project.name));
}

const _assignedSessions = new Set();
async function _assignCurrentSessionToProject() {
  const sid = (typeof sessionId !== 'undefined') ? sessionId : '';
  const pid = _currentProject;
  if (!sid || !pid) return;
  const key = sid + '|' + pid;
  if (_assignedSessions.has(key)) return;
  _assignedSessions.add(key);
  // 等服务端在首条消息时建好会话行,再归属
  setTimeout(async () => {
    try {
      await fetch('/api/sessions/' + encodeURIComponent(sid) + '/project', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ project_id: pid }),
      });
      if (typeof refreshSessions === 'function') refreshSessions();
    } catch {}
  }, 1500);
}

/* —— 文件上传 / 附件菜单 —— */
function closeAttachMenu() {
  const m = document.getElementById('attach-menu');
  if (m) m.hidden = true;
}

function triggerAttach(e) {
  e?.stopPropagation();
  if (workMode === 'coworker') {
    const m = document.getElementById('attach-menu');
    if (!m) { triggerUpload(); return; }
    closeModelPicker();
    m.hidden = !m.hidden;
    return;
  }
  triggerUpload();
}

function attachPickFile() { closeAttachMenu(); triggerUpload(); }
function attachPickWorkspaceFolder() { closeAttachMenu(); openCoworkFolderPicker(); }
function attachPickLocalFolder() { closeAttachMenu(); triggerFolderUpload(); }

function triggerUpload() { const i = document.getElementById('file-inp'); if (i) i.click(); }
function onFilePicked(input) {
  const file = input.files && input.files[0];
  if (!file) return;
  if (file.size > 20 * 1024 * 1024) { alert(t('uploadTooLarge')); input.value = ''; return; }
  const reader = new FileReader();
  reader.onload = async () => {
    const b64 = String(reader.result).split(',')[1] || '';
    try {
      const r = await fetch('/api/upload', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ name: file.name, content_b64: b64 }),
      });
      const d = await r.json();
      if (d.ok) {
        const path = d.path || '';
        const ref = t('uploadedRef').replace('{path}', path);
        const isImage = /\.(png|jpe?g|webp|gif|svg)$/i.test(file.name || path);
        const previewUrl = isImage ? URL.createObjectURL(file) : '';
        _pendingAttachments.push({ path, name: file.name, ref, isImage, previewUrl });
        renderComposerAttachments();
        const inp = document.getElementById('chat-inp');
        if (inp && !isImage) inp.value = ref + inp.value;
        inp?.focus();
      } else { alert(t('uploadFail') + (d.error || '')); }
    } catch (e) { alert(t('uploadFail') + e); }
    input.value = '';
  };
  reader.readAsDataURL(file);
}

/* —— 聊天内联图片(每轮回复各自显示,不串台) —— */
const _IMAGE_EXT_RE = /\.(png|jpe?g|webp|gif|svg)$/i;
const _IMAGE_PATH_RE = /(?:已生成图片|saved to)[:：]\s*([^\s\n]+\.(?:png|jpe?g|webp|gif|svg))|产物\/[^\s\n，。；、！？）)\]]+\.(?:png|jpe?g|webp|gif|svg)|!\[[^\]]*\]\(([^)]+\.(?:png|jpe?g|webp|gif|svg))\)/gi;
const _turnImagePaths = new Set();
let _turnImageTarget = null;
function clearChatImagePaths() {
  _turnImagePaths.clear();
  _turnImageTarget = null;
}
function setTurnImageTarget(el) { _turnImageTarget = el || null; }
function trackTurnImage(path) {
  const key = String(path || '').replace(/\\/g, '/').trim();
  if (key && isImageArtifact(key)) _turnImagePaths.add(key);
}
function isImageArtifact(path) { return _IMAGE_EXT_RE.test(String(path || '')); }
function artifactRawUrl(path) {
  return '/api/artifact/raw?path=' + encodeURIComponent(path);
}
function previewUrl(path) {
  // /preview/<工作区相对路径>:每段单独编码,保留 / 以便相对资源解析
  const clean = String(path || '').replace(/\\/g, '/').replace(/^\.?\//, '');
  return '/preview/' + clean.split('/').map(encodeURIComponent).join('/');
}
async function loadInlineImage(imgEl, path) {
  if (!imgEl || !path) return;
  try {
    const r = await fetch(artifactRawUrl(path));
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const blob = await r.blob();
    imgEl.src = URL.createObjectURL(blob);
  } catch {
    imgEl.alt = '图片加载失败';
    imgEl.style.opacity = '0.5';
  }
}
function extractImagePathsFromText(text) {
  const paths = new Set();
  const s = String(text || '');
  let m; _IMAGE_PATH_RE.lastIndex = 0;
  while ((m = _IMAGE_PATH_RE.exec(s))) {
    const raw = m[1] || m[2] || m[0];
    if (!raw) continue;
    const r = normalizeArtifactRel('', raw);
    if (r && isImageArtifact(r)) paths.add(r);
  }
  return [...paths];
}
function _makeChatImageWrap(key) {
  const wrap = document.createElement('div');
  wrap.className = 'chat-image-wrap';
  wrap.dataset.chatImage = key;
  const img = document.createElement('img');
  img.className = 'chat-inline-image';
  img.alt = key.split('/').pop();
  img.loading = 'lazy';
  img.onclick = () => openArtifact(key);
  wrap.appendChild(img);
  loadInlineImage(img, key);
  return wrap;
}
function attachImageToBody(body, rel) {
  if (!body || !rel || !isImageArtifact(rel)) return;
  const key = rel.replace(/\\/g, '/');
  if (body.querySelector(`[data-chat-image="${CSS.escape(key)}"]`)) return;
  body.appendChild(_makeChatImageWrap(key));
}
function mergeChatImagesInto(el) {
  if (!el) return;
  const paths = new Set(extractImagePathsFromText(el.textContent || ''));
  if (el === _turnImageTarget) {
    _turnImagePaths.forEach(p => paths.add(p));
  }
  paths.forEach(key => attachImageToBody(el, key));
}
function appendChatImage(rel) {
  if (!rel || !isImageArtifact(rel)) return;
  const key = rel.replace(/\\/g, '/');
  trackTurnImage(key);
  const area = document.getElementById('chat-messages');
  if (!area) return;
  const empty = document.getElementById('chat-empty');
  if (empty) empty.style.display = 'none';
  let target = _turnImageTarget;
  if (!target && streamingMsgEl) target = streamingMsgEl.querySelector('.msg-body');
  if (!target) {
    const agents = area.querySelectorAll('.msg-agent .msg-body');
    if (agents.length) target = agents[agents.length - 1];
  }
  if (target) {
    setTurnImageTarget(target);
    attachImageToBody(target, key);
  } else {
    const d = document.createElement('div');
    d.className = 'msg msg-agent';
    d.innerHTML = '<div class="msg-head"><span class="msg-label msg-label-agent">Captain</span></div><div class="msg-body"></div>';
    const body = d.querySelector('.msg-body');
    setTurnImageTarget(body);
    attachImageToBody(body, key);
    area.appendChild(d);
  }
  area.scrollTop = area.scrollHeight;
}
function embedChatImages(root) {
  const bodies = [];
  if (root && root.classList && root.classList.contains('msg-body') && !root.classList.contains('user-body')) {
    bodies.push(root);
  } else if (root && root.querySelectorAll) {
    root.querySelectorAll('.msg-body:not(.user-body)').forEach(b => bodies.push(b));
  }
  bodies.forEach(body => {
    const paths = new Set(extractImagePathsFromText(body.textContent || ''));
    paths.forEach(key => attachImageToBody(body, key));
  });
}

/* —— 产物内联预览 —— */
async function openArtifact(path) {
  window._curArtifactPath = path;
  const ov = document.getElementById('artifact-overlay');
  const body = document.getElementById('artifact-body');
  const title = document.getElementById('artifact-title');
  if (!ov || !body || !title) return;
  ov.classList.add('open');
  body.style.cssText = '';
  body.innerHTML = '<div style="padding:20px;color:var(--muted)" data-i18n="loading">加载中…</div>';
  title.textContent = path.split('/').pop() || '产物预览';
  if (isImageArtifact(path)) {
    body.innerHTML = '';
    body.style.cssText = 'display:flex;align-items:center;justify-content:center;padding:12px;min-height:200px;background:var(--surface2)';
    const img = document.createElement('img');
    img.style.cssText = 'max-width:100%;max-height:min(80vh,720px);object-fit:contain;display:block';
    loadInlineImage(img, path);
    body.appendChild(img);
    return;
  }
  try {
    const r = await fetch('/api/artifact?path=' + encodeURIComponent(path));
    const d = await r.json();
    if (!d.ok) { body.innerHTML = `<div style="padding:20px;color:var(--red)">${escHtml(d.error||'读取失败')}</div>`; return; }
    title.textContent = d.name || '产物预览';
    if (d.kind === 'image') {
      body.innerHTML = '';
      body.style.cssText = 'display:flex;align-items:center;justify-content:center;padding:12px;min-height:200px;background:var(--surface2)';
      const img = document.createElement('img');
      img.style.cssText = 'max-width:100%;max-height:min(80vh,720px);object-fit:contain;display:block';
      loadInlineImage(img, path);
      body.appendChild(img);
    } else if (d.kind === 'html') {
      // 真实预览:用 /preview 服务文件,相对资源(css/图片)能解析、能在新标签打开
      const url = previewUrl(path);
      body.innerHTML = '';
      body.style.cssText = 'display:flex;flex-direction:column;height:100%';
      const bar = document.createElement('div');
      bar.style.cssText = 'padding:6px 10px;border-bottom:1px solid var(--border);display:flex;gap:8px;align-items:center';
      bar.innerHTML = '<span style="font-size:12px;color:var(--dim);flex:1">网页预览</span>';
      const open = document.createElement('a');
      open.href = url; open.target = '_blank'; open.rel = 'noopener';
      open.className = 'btn-sm'; open.textContent = '↗ 在新标签打开';
      bar.appendChild(open);
      const ifr = document.createElement('iframe');
      ifr.setAttribute('sandbox', 'allow-scripts allow-same-origin');
      ifr.style.cssText = 'width:100%;flex:1;border:0;background:#fff';
      ifr.src = url;
      body.appendChild(bar); body.appendChild(ifr);
    } else if (d.kind === 'markdown') {
      body.innerHTML = '<div class="md" style="padding:18px">' + renderMD(d.content) + '</div>';
    } else {
      body.innerHTML = '<pre style="padding:18px;white-space:pre-wrap;word-break:break-word;margin:0">'
        + escHtml(d.content) + '</pre>';
    }
  } catch (e) {
    body.innerHTML = `<div style="padding:20px;color:var(--red)">${escHtml(String(e))}</div>`;
  }
}
function closeArtifact() { document.getElementById('artifact-overlay')?.classList.remove('open'); }

/* ── 历史产物浏览器:检索之前输出的产物 ── */
function artifactIcon(ext) {
  const m = { md:'📝', html:'🌐', htm:'🌐', pdf:'📕', docx:'📄', xlsx:'📊', pptx:'📑',
    csv:'📊', txt:'📄', png:'🖼️', jpg:'🖼️', jpeg:'🖼️', gif:'🖼️', svg:'🖼️',
    py:'🐍', js:'📜', json:'🔧', ipynb:'📓', zip:'🗜️' };
  return m[ext] || '📄';
}
function openArtifactsBrowser() {
  const ov = document.getElementById('artifacts-browser-overlay');
  if (!ov) return;
  ov.classList.add('open');
  const s = document.getElementById('artifacts-search');
  if (s) { s.placeholder = t('artifactsSearchPh'); s.value = ''; }
  loadArtifactsList('');
}
function closeArtifactsBrowser() {
  document.getElementById('artifacts-browser-overlay')?.classList.remove('open');
}
async function revealArtifactsFolder() {
  // 一键在系统文件管理器里打开产物文件夹
  try {
    const r = await fetch('/api/artifacts/reveal', { method: 'POST' });
    const d = await r.json();
    if (!d.ok) alert('打开失败:' + (d.error || '') + (d.dir ? '\n路径:' + d.dir : ''));
  } catch (e) { alert('打开失败:' + e); }
}
async function loadArtifactsList(q) {
  const box = document.getElementById('artifacts-list');
  if (!box) return;
  box.innerHTML = `<div style="color:var(--dim);font-size:13px">${escHtml(t('loading'))}</div>`;
  try {
    const r = await fetch('/api/artifacts?q=' + encodeURIComponent(q || ''));
    const d = await r.json();
    const items = d.items || [];
    if (!items.length) { box.innerHTML = `<div style="color:var(--dim);font-size:13px">${escHtml(t('artifactsEmpty'))}</div>`; return; }
    box.innerHTML = items.map(it => {
      const dt = new Date((it.mtime || 0) * 1000).toLocaleString();
      const kb = it.size >= 1024 ? Math.round(it.size / 1024) + ' KB' : (it.size || 0) + ' B';
      const rel = String(it.rel);
      return `<div class="wb-file" role="button" tabindex="0" data-artifact-path="${escAttr(rel)}" style="display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:8px;cursor:pointer;border:1px solid transparent">
        <span>${artifactIcon(it.ext)}</span>
        <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(it.rel)}</span>
        <span style="color:var(--dim);font-size:11px;flex:0 0 auto">${escHtml(dt)} · ${kb}</span>
      </div>`;
    }).join('');
  } catch {
    box.innerHTML = `<div style="color:var(--red);font-size:13px">${escHtml(t('loadFailed'))}</div>`;
  }
}

/* 把助理消息里的产物路径变成可点预览链接 */
const _ARTIFACT_RE = /((?:产物\/)?[^\s"'<>]+\.(?:html?|md|xlsx?|docx?|pptx?|pdf|csv|json|png|jpe?g|webp|gif|svg))/g;
function _linkifyArtifacts(root) {
  if (!root || !root.querySelectorAll) return;
  root.querySelectorAll('.msg-body:not(.user-body)').forEach(el => {
    if (el.dataset.linkified) return;
    el.dataset.linkified = '1';
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const targets = [];
    let n; while ((n = walker.nextNode())) { if (_ARTIFACT_RE.test(n.nodeValue)) targets.push(n); }
    targets.forEach(node => {
      const frag = document.createDocumentFragment();
      let last = 0; const s = node.nodeValue; _ARTIFACT_RE.lastIndex = 0; let m;
      while ((m = _ARTIFACT_RE.exec(s))) {
        if (m.index > last) frag.appendChild(document.createTextNode(s.slice(last, m.index)));
        const a = document.createElement('a');
        a.textContent = m[1]; a.className = 'artifact-link'; a.dataset.path = m[1];
        a.style.cssText = 'color:var(--accent);cursor:pointer;text-decoration:underline';
        frag.appendChild(a); last = m.index + m[1].length;
        _addArtifact(m[1]);
      }
      if (last < s.length) frag.appendChild(document.createTextNode(s.slice(last)));
      node.parentNode.replaceChild(frag, node);
    });
  });
}
(function () {
  const area = document.getElementById('chat-messages');
  if (!area) return;
  area.addEventListener('click', e => {
    const a = e.target.closest && e.target.closest('.artifact-link');
    if (a) { e.preventDefault(); openArtifact(a.dataset.path); }
  });
  new MutationObserver(muts => {
    muts.forEach(mu => mu.addedNodes && mu.addedNodes.forEach(node => _linkifyArtifacts(node.parentNode || area)));
    _linkifyArtifacts(area);
  }).observe(area, { childList: true, subtree: true });
})();

/* —— 右侧工作台:进度 + 产物文件 —— */
const _artifacts = new Set();

function normalizeArtifactRel(path, output) {
  let p = String(path || '').trim();
  if (!p && output) {
    const out = String(output);
    const m = out.match(/(?:已生成图片|saved to)[:：]\s*(.+?)\s*$/i)
      || out.match(/到\s+(.+?)\s*$/);
    if (m) p = m[1].trim();
  }
  if (!p) return '';
  p = p.replace(/\\/g, '/');
  const prod = p.indexOf('产物/');
  if (prod >= 0) p = p.slice(prod);
  p = p.replace(/[，。；、！？）)\]]+$/g, '');
  const idx = p.indexOf('/uploads/');
  if (idx >= 0) return p.slice(idx + 1);
  if (p.startsWith('/')) return p;
  return p.replace(/^\.\//, '');
}

function registerWorkbenchArtifact(path, output) {
  const rel = normalizeArtifactRel(path, output);
  if (!rel) return;
  _addArtifact(rel);
  const parent = rel.includes('/') ? rel.split('/').slice(0, -1).join('/') : '';
  if (parent && typeof loadFiles === 'function') {
    if (!_filesDir || _filesDir === parent || parent.startsWith(_filesDir + '/')) loadFiles(_filesDir || parent);
  }
}

function resetWorkbenchSession() {
  _artifacts.clear();
  renderWorkbench();
  const plan = document.getElementById('wb-plan');
  if (plan) plan.innerHTML = '';
  _wbUpdateProgressFraction();
}

function refreshWorkbenchMeta() {
  const meta = document.getElementById('wb-workspace-meta');
  if (!meta) return;
  const dir = _coworkWorkspaceDir || _filesDir || '';
  let text = '';
  if (_currentProject) {
    const p = _projectsCache.find(x => x.id === _currentProject);
    if (p && p.name) text = `📁 ${p.name}`;
  }
  if (dir) text = text ? `${text} · ${dir}` : dir;
  meta.textContent = text || t('wbFilesHint');
}

function _addArtifact(path) {
  if (_artifacts.has(path)) return;
  _artifacts.add(path);
  renderWorkbench();
  _saveWorkbench({ artifacts: [path] });   // 按会话累积持久化
}

/* —— 工作台状态按会话持久化 ——
   主存储:localStorage(按 sessionId 隔离,刷新必活、无异步/鉴权坑);服务端只做最佳努力同步。 */
function _wbKey(sid) { return 'wb:' + (sid || sessionId || ''); }
function _wbLoad(sid) {
  try { return JSON.parse(localStorage.getItem(_wbKey(sid)) || '{}') || {}; }
  catch (e) { return {}; }
}
function _wbStore(sid, rec) {
  try { localStorage.setItem(_wbKey(sid), JSON.stringify(rec)); } catch (e) {}
}
async function _saveWorkbench(patch) {
  if (!sessionId) return;
  patch = patch || {};
  const rec = _wbLoad(sessionId);
  if ('workspace_dir' in patch) rec.workspace_dir = patch.workspace_dir || '';
  if (Array.isArray(patch.artifacts)) {
    rec.artifacts = rec.artifacts || [];
    patch.artifacts.forEach(a => { if (a && !rec.artifacts.includes(a)) rec.artifacts.push(a); });
  }
  if (Array.isArray(patch.plan)) rec.plan = patch.plan;
  _wbStore(sessionId, rec);                              // 本地立即持久化(刷新可恢复)
  try {                                                  // 服务端最佳努力同步(跨设备),失败不影响本地
    if (!sessionId.endsWith('-pending')) {
      fetch('/api/sessions/' + encodeURIComponent(sessionId) + '/workbench', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch) });
    }
  } catch (e) {}
}
function _snapshotPlan() {
  return Array.from(document.querySelectorAll('#wb-plan .wbn')).map(r => ({
    id: r.dataset.wbnode || '',
    text: (r.querySelector('.tx') ? r.querySelector('.tx').textContent : '') || '',
    done: r.classList.contains('done'),
  }));
}
function _restorePlan(nodes) {
  const box = document.getElementById('wb-plan');
  if (!box || !nodes || !nodes.length) return;
  box.innerHTML = nodes.map(n =>
    `<div class="wbn${n.done ? ' done' : ''}" data-wbnode="${escHtml(n.id)}">` +
    `<span class="st ${n.done ? 'ok' : ''}">${n.done ? '✓' : '○'}</span>` +
    `<span class="tx">${escHtml(n.text)}</span></div>`).join('');
  if (typeof refreshWbPlanEmpty === 'function') refreshWbPlanEmpty();
  if (typeof _wbUpdateProgressFraction === 'function') _wbUpdateProgressFraction();
}
async function restoreWorkbench() {
  if (!sessionId) return;
  const sid = sessionId;
  let rec = _wbLoad(sid);                                 // 先读本地(主存储)
  const empty = !rec.workspace_dir && !(rec.artifacts && rec.artifacts.length) && !(rec.plan && rec.plan.length);
  if (empty && !sid.endsWith('-pending')) {              // 本地没有 → 回服务端拿(换浏览器/设备)
    try {
      const d = await (await fetch('/api/sessions/' + encodeURIComponent(sid) + '/workbench')).json();
      if (sessionId !== sid) return;                      // 期间又切走了,放弃,避免串台
      rec = { workspace_dir: d.workspace_dir || '', artifacts: d.artifacts || [], plan: d.plan || [] };
      if (!empty || rec.workspace_dir || rec.artifacts.length || rec.plan.length) _wbStore(sid, rec);
    } catch (e) {}
  }
  if (sessionId !== sid) return;
  // —— 无论有没有内容,都把右侧面板重置成"这个会话"的状态,杜绝 A/B 串台 ——
  _artifacts.clear();
  (rec.artifacts || []).forEach(p => _artifacts.add(p));
  renderWorkbench();
  const planBox = document.getElementById('wb-plan');
  if (rec.plan && rec.plan.length) { _restorePlan(rec.plan); }
  else if (planBox) { planBox.innerHTML = ''; if (typeof refreshWbPlanEmpty === 'function') refreshWbPlanEmpty(); }
  if (rec.workspace_dir) {
    _coworkWorkspaceDir = rec.workspace_dir;
    if (typeof updateCoworkFolderChip === 'function') updateCoworkFolderChip(rec.workspace_dir);
    if (typeof loadFiles === 'function') loadFiles(rec.workspace_dir);
    const app = document.getElementById('app'); if (app) app.classList.add('wb-open');
  } else {
    _coworkWorkspaceDir = '';
    _filesDir = '';
    const fb = document.getElementById('wb-files');
    if (fb) fb.innerHTML = '<div class="wb-empty">' + escHtml(t('wbFilesHint')) + '</div>';
    if (typeof refreshWorkbenchMeta === 'function') refreshWorkbenchMeta();
  }
}
function renderWorkbench() {
  const box = document.getElementById('wb-artifacts');
  if (!box) return;
  const items = Array.from(_artifacts);
  box.innerHTML = items.length
    ? items.map(p => {
        const name = p.split('/').pop();
        const sub = p.includes('/') ? `<span style="font-size:10px;color:var(--dim);display:block">${escHtml(p)}</span>` : '';
        const icon = isImageArtifact(p) ? '🖼️' : '📄';
        return `<div class="wb-file" role="button" tabindex="0" data-artifact-path="${escAttr(p)}"><span>${icon}</span><span>${escHtml(name)}${sub}</span></div>`;
      }).join('')
    : `<div class="wb-empty">${escHtml(t('wbNoArtifacts'))}</div>`;
}
function toggleWorkbench() {
  const app = document.getElementById('app');
  if (app) {
    app.classList.toggle('wb-open');
    if (app.classList.contains('wb-open')) loadFiles(_filesDir);
    updateWorkbenchToggle();
  }
}

/* —— 右侧项目文件树(借鉴 Cowork 的 "my agent" 文件浏览;声明已提升至顶部状态区)—— */
_filesDir = "";
const _FILE_ICON = {dir:'📁', md:'📝', py:'🐍', js:'📜', html:'🌐', json:'🔧', csv:'📊',
  xlsx:'📊', docx:'📄', pptx:'📑', pdf:'📕', txt:'📄', sh:'⚙️', yaml:'🔧', yml:'🔧'};
async function loadFiles(dir) {
  _filesDir = dir || "";
  const box = document.getElementById('wb-files');
  const up = document.getElementById('wb-files-up');
  if (!box) return;
  refreshWorkbenchMeta();
  try {
    const r = await fetch('/api/files?dir=' + encodeURIComponent(_filesDir));
    const d = await r.json();
    if (!d.ok) { box.innerHTML = `<div class="wb-empty">${escHtml(d.error||'读取失败')}</div>`; return; }
    if (up) up.style.display = _filesDir ? 'inline' : 'none';
    const items = d.items || [];
    if (!items.length) {
      box.innerHTML = `<div class="wb-empty">${escHtml(_filesDir ? t('wbFilesEmptyDir') : t('wbFilesHint'))}</div>`;
      return;
    }
    box.innerHTML = items.map(it => {
      const ic = it.type === 'dir' ? _FILE_ICON.dir : (_FILE_ICON[it.ext] || '📄');
      return `<div class="wb-row" role="button" tabindex="0" data-file-rel="${escAttr(it.rel)}" data-file-type="${escAttr(it.type)}"><span class="ic">${ic}</span><span>${escHtml(it.name)}</span></div>`;
    }).join('');
  } catch (e) { box.innerHTML = `<div class="wb-empty">${escHtml(String(e))}</div>`; }
}
function filesUp() {
  const parts = _filesDir.split('/').filter(Boolean);
  parts.pop();
  loadFiles(parts.join('/'));
}

/* —— 右侧三段(进度/工作目录/产物)折叠:点标题切换,状态记进 localStorage —— */
function wbToggleSec(el){
  const sec = el.closest && el.closest('.wb-sec');
  if(!sec) return;
  const on = sec.classList.toggle('wb-collapsed');
  const key = [...sec.classList].find(c => c.endsWith('-sec'));
  if(key){ try{ localStorage.setItem('wbCollapsed:'+key, on ? '1':'0'); }catch(e){} }
}
function wbRestoreCollapsed(){
  document.querySelectorAll('#workbench .wb-sec').forEach(sec => {
    const key = [...sec.classList].find(c => c.endsWith('-sec'));
    if(!key) return;
    try{ if(localStorage.getItem('wbCollapsed:'+key)==='1') sec.classList.add('wb-collapsed'); }catch(e){}
  });
}
document.addEventListener('DOMContentLoaded', wbRestoreCollapsed);

/* —— Progress 打勾清单(把 DAG 执行计划画进工作台)—— */
const _WB_ST = {
  pending: {ic:'○', cls:''}, running: {ic:'◔', cls:'run'},
  done: {ic:'✔', cls:'ok'}, ok: {ic:'✔', cls:'ok'}, success: {ic:'✔', cls:'ok'},
  failed: {ic:'✘', cls:'bad'}, blocked: {ic:'⊘', cls:'bad'}, revising: {ic:'↻', cls:'run'},
};
function wbHandlePlan(p) {
  if (p.type === 'plan') {
    const app = document.getElementById('app');
    if (app && !app.classList.contains('wb-open')) {
      app.classList.add('wb-open');
      loadFiles(_filesDir);
    }
    const box = document.getElementById('wb-plan');
    if (!box) return;
    box.innerHTML = (p.nodes || []).map(n =>
      `<div class="wbn" data-wbnode="${escHtml(n.id)}"><span class="st">○</span>` +
      `<span class="tx">${escHtml((n.sub_task || '').slice(0, 60))}</span></div>`
    ).join('');
    refreshWbPlanEmpty();
    _wbUpdateProgressFraction();
  } else if (p.type === 'node') {
    const row = document.querySelector(`#wb-plan .wbn[data-wbnode="${(window.CSS&&CSS.escape)?CSS.escape(p.id||''):p.id}"]`);
    if (!row) return;
    const st = _WB_ST[p.status] || _WB_ST.pending;
    const stEl = row.querySelector('.st');
    if (stEl) { stEl.textContent = st.ic; stEl.className = 'st ' + st.cls; }
    row.classList.toggle('done', st.cls === 'ok');
    _wbUpdateProgressFraction();
  }
}
function _wbProgress(running) {
  const p = document.getElementById('wb-progress');
  const txt = document.getElementById('wb-progress-text');
  if (!p || !txt) return;
  p.classList.toggle('running', !!running);
  if (running) {
    txt.textContent = t('wbProgressRunning');
    return;
  }
  const total = document.querySelectorAll('#wb-plan .wbn').length;
  const done = document.querySelectorAll('#wb-plan .wbn.done').length;
  txt.textContent = total && done >= total ? t('wbProgressDone') : t('wbProgressIdle');
}
/* 包裹 setTaskRunning,让进度同步到工作台(非侵入式) */
if (typeof setTaskRunning === 'function') {
  const _origSetTaskRunning = setTaskRunning;
  setTaskRunning = function (running) { _origSetTaskRunning(running); _wbProgress(running); };
}

loadProjects();
if (typeof refreshWbPlanEmpty === 'function') refreshWbPlanEmpty();
if (typeof refreshWorkbenchMeta === 'function') refreshWorkbenchMeta();
