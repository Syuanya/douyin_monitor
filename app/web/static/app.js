const state = {
  token: localStorage.getItem('douyin_monitor_web_token') || '',
  accounts: [],
  visibleAccounts: [],
  selectedAccounts: new Set(),
  inboxItems: [],
  visibleInbox: [],
  selectedItems: new Set(),
  settings: {},
  taskTimer: null,
  eventSource: null,
  liveLogSource: null,
  mediaPreviewFiles: [],
  mediaPreviewIndex: 0,
  storagePreviewFiles: [],
  storagePreviewIndex: 0,
  storageViewMode: 'grid',
  storageCurrentPath: '',
  parsedResults: {},
  currentLogName: "",
  lastEventAt: null,
};
const $ = (id) => document.getElementById(id);

function toast(msg) {
  const el = $('toast');
  el.textContent = msg;
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 3800);
}

function headers(extra = {}) {
  const h = { ...extra };
  if (state.token) h['Authorization'] = `Bearer ${state.token}`;
  return h;
}

async function api(path, options = {}) {
  const opts = { ...options, headers: headers(options.headers || {}) };
  if (opts.body && !(opts.body instanceof FormData) && !opts.headers['Content-Type']) opts.headers['Content-Type'] = 'application/json';
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return await res.json();
}

function authedUrl(path){ const sep = path.includes('?') ? '&' : '?'; return `${path}${sep}x_auth_token=${encodeURIComponent(state.token || '')}`; }
function connectEvents(){
  if(state.eventSource){ state.eventSource.close(); state.eventSource=null; }
  if(!state.token || !window.EventSource) return;
  const es = new EventSource(authedUrl('/api/events?interval=2'));
  es.onmessage = (msg) => {
    try {
      const ev = JSON.parse(msg.data || '{}');
      state.lastEventAt = ev.time || Math.floor(Date.now()/1000);
      const q = ev.download_queue || {};
      const dash = ev.dashboard || {};
      $('subTitle').textContent = `实时连接正常 ｜ 账号 ${dash.accounts ?? '-'} ｜ 任务 ${dash.running_tasks ?? '-'} ｜ 下载速度 ${formatBytes(q.total_speed_bps || 0)}/s`;
      if(currentTab()==='queue') renderQueueRealtime(q);
    } catch (_) {}
  };
  es.onerror = () => { $('subTitle').textContent = '实时连接断开，页面将继续使用手动刷新。'; };
  state.eventSource = es;
}


function escapeHtml(s) { return String(s ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function truncate(s, n = 120) { s = String(s ?? ''); return s.length > n ? `${s.slice(0, n)}…` : s; }
function fmtTime(v) { if (!v) return '-'; if (typeof v === 'number') return new Date(v * 1000).toLocaleString(); return String(v); }
function itemKey(accountId, itemId) { return `${accountId}::${itemId}`; }
function parseKey(key) { const [account_id, ...rest] = String(key).split('::'); return { account_id, item_id: rest.join('::') }; }
function stat(label, value) { return `<div class="stat"><div class="value">${escapeHtml(value ?? 0)}</div><div class="label">${escapeHtml(label)}</div></div>`; }
function badge(text, cls = '') { return `<span class="badge ${cls}">${escapeHtml(text)}</span>`; }

const titles = { dashboard: '主页', accounts: '内容监控', inbox: '新作品箱', import: '批量导入', parse: '视频解析', tasks: '任务中心', history: '下载历史', diagnostics: '诊断', cookies: 'Cookie 管理', queue: '下载队列', batchjobs: '批量任务', media: '作品库', storage: '存储', logs: '运行日志', risk: '问题中心', notifications: '通知管理', updates: '更新管理', access: '访问控制', backups: '备份恢复', settings: '设置' };
const primaryTab = { inbox: 'accounts', import: 'accounts', media: 'accounts', queue: 'tasks', batchjobs: 'tasks', logs: 'tasks', cookies: 'settings', notifications: 'settings', updates: 'settings', access: 'settings', backups: 'settings' };
function currentTab() { return document.querySelector('.tab.active')?.id || 'dashboard'; }
function showTab(name) {
  const activeNav = primaryTab[name] || name;
  document.querySelectorAll('.nav').forEach(n => n.classList.toggle('active', n.dataset.tab === activeNav));
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.id === name));
  $('pageTitle').textContent = titles[activeNav] || titles[name] || name;
  if (name === 'dashboard') loadStatus();
  if (name === 'accounts') loadAccounts();
  if (name === 'inbox') loadInbox();
  if (name === 'tasks') loadTasks();
  if (name === 'history') loadHistory();
  if (name === 'settings') loadSettings();
  if (name === 'diagnostics') loadDiagnostics();
  if (name === 'cookies') loadCookies();
  if (name === 'queue') loadQueue();
  if (name === 'batchjobs') loadBatchJobs();
  if (name === 'media') loadMediaLibrary();
  if (name === 'storage') loadStorage();
  if (name === 'logs') loadLogs();
  if (name === 'risk') loadRisk();
  if (name === 'notifications') loadNotifications();
  if (name === 'updates') loadUpdates();
  if (name === 'access') loadAccess();
  if (name === 'backups') loadBackups();
}


async function loadStatus() {
  try {
    const data = await api('/api/status');
    const d = data.dashboard || {};
    $('statGrid').innerHTML = [
      stat('账号', d.accounts), stat('监控中', d.running_accounts), stat('新作品', d.new_works), stat('作品', d.works),
      stat('运行任务', d.running_tasks), stat('失败任务', d.failed_tasks), stat('今日下载', d.today_downloads), stat('解析并发', d.parse_concurrency)
    ].join('');
    const obs = data.observability || {};
    $('cookieHealthBox').innerHTML = renderKv(obs.cookie_health || {});
    $('rateLimiterBox').innerHTML = renderKv(obs.rate_limiter || {});
    $('observabilityBox').textContent = JSON.stringify({ batch_jobs: obs.batch_jobs, segmented_download: obs.segmented_download }, null, 2);
  } catch (e) { toast(`加载状态失败：${e.message}`); }
}

function renderKv(obj) {
  const entries = Object.entries(obj || {}).slice(0, 16);
  if (!entries.length) return '<p class="hint">暂无数据</p>';
  return entries.map(([k, v]) => `<div><span>${escapeHtml(k)}</span><strong>${escapeHtml(typeof v === 'object' ? JSON.stringify(v) : v)}</strong></div>`).join('');
}

async function loadAccounts() {
  try {
    const data = await api('/api/accounts');
    state.accounts = data.accounts || [];
    applyAccountFilters();
  } catch (e) { toast(`加载账号失败：${e.message}`); }
}

function accountMatches(a) {
  const q = $('accountSearch').value.trim().toLowerCase();
  const f = $('accountStatusFilter').value;
  if (q) {
    const text = [a.display_name, a.douyin_nickname, a.group_name, a.homepage_url, a.status, a.last_error].join(' ').toLowerCase();
    if (!text.includes(q)) return false;
  }
  if (f === 'monitoring' && !a.monitor_enabled) return false;
  if (f === 'stopped' && a.monitor_enabled) return false;
  if (f === 'new' && Number(a.new_unhandled_count || 0) <= 0) return false;
  if (f === 'error' && !a.last_error && !String(a.status || '').includes('异常')) return false;
  return true;
}

function applyAccountFilters() {
  state.visibleAccounts = state.accounts.filter(accountMatches);
  $('accountList').innerHTML = state.visibleAccounts.map(renderAccount).join('') || '<div class="panel">暂无匹配账号。</div>';
  updateAccountSelectionSummary();
}

function renderAccount(a) {
  const name = a.display_name || a.douyin_nickname || '抖音用户';
  const checked = state.selectedAccounts.has(a.account_id) ? 'checked' : '';
  const statusBadge = a.monitor_enabled ? badge('监控中') : badge('未监控', 'warn');
  const newBadge = Number(a.new_unhandled_count || 0) > 0 ? badge(`新作品 ${a.new_unhandled_count}`, 'ok') : '';
  return `<div class="card account-card">
    <div class="card-title">
      <label class="check strong"><input type="checkbox" class="accountSelect" data-id="${escapeHtml(a.account_id)}" ${checked}/> ${escapeHtml(name)}</label>
      <div>${statusBadge}${newBadge}</div>
    </div>
    <p class="hint">${escapeHtml(a.homepage_url || '')}</p>
    <p>分组：${escapeHtml(a.group_name || '-')} ｜ 状态：${escapeHtml(a.status || '-')} ｜ 最近检测：${escapeHtml(a.last_check_time || '-')} ｜ 作品：${a.item_count || 0}</p>
    ${a.last_error ? `<p class="hint danger">错误：${escapeHtml(a.last_error)}</p>` : ''}
    <div class="card-actions">
      <button onclick="checkAccount('${a.account_id}')">检测一次</button>
      <button onclick="syncAccount('${a.account_id}')">同步作品</button>
      <button onclick="toggleMonitor('${a.account_id}', ${!a.monitor_enabled})">${a.monitor_enabled ? '停止监控' : '启动监控'}</button>
      <button onclick="showItems('${a.account_id}')">查看作品</button><button onclick="showAccountInsights('${a.account_id}')">账号详情</button>
      <button class="danger" onclick="deleteAccount('${a.account_id}')">删除</button>
    </div>
    <div id="items-${a.account_id}" class="itemBox" style="display:none"></div>
  </div>`;
}

function updateAccountSelectionSummary() {
  $('accountSelectionSummary').textContent = `已选 ${state.selectedAccounts.size} / 当前 ${state.visibleAccounts.length}`;
  document.querySelectorAll('.accountSelect').forEach(el => { el.checked = state.selectedAccounts.has(el.dataset.id); });
}

document.addEventListener('change', (e) => {
  if (e.target.classList.contains('accountSelect')) {
    e.target.checked ? state.selectedAccounts.add(e.target.dataset.id) : state.selectedAccounts.delete(e.target.dataset.id);
    updateAccountSelectionSummary();
  }
  if (e.target.classList.contains('inboxSelect')) {
    e.target.checked ? state.selectedItems.add(e.target.dataset.key) : state.selectedItems.delete(e.target.dataset.key);
    updateInboxSelectionSummary();
  }
});

async function addAccount() {
  const homepage_url = $('accountUrl').value.trim();
  if (!homepage_url) return toast('请输入主页链接');
  try {
    await api('/api/accounts', { method: 'POST', body: JSON.stringify({ homepage_url, display_name: $('accountName').value.trim() }) });
    $('accountUrl').value = ''; $('accountName').value = '';
    toast('已添加账号'); await loadAccounts();
  } catch (e) { toast(`添加失败：${e.message}`); }
}
async function checkAccount(id) { await runSimple(`/api/accounts/${id}/check`, '检测完成'); await loadAccounts(); }
async function syncAccount(id) { await runSimple(`/api/accounts/${id}/sync`, '同步完成'); await loadAccounts(); }
async function toggleMonitor(id, enabled) { await api('/api/accounts/bulk/monitor?enabled=' + enabled, { method: 'POST', body: JSON.stringify({ account_ids: [id] }) }); await loadAccounts(); }
async function deleteAccount(id) { if (!confirm('确认删除该账号？')) return; await api(`/api/accounts/${id}`, { method: 'DELETE' }); state.selectedAccounts.delete(id); await loadAccounts(); }
async function runSimple(path, ok) { try { const r = await api(path, { method: 'POST' }); toast(r.reason || r.summary || ok); } catch(e) { toast(e.message); } }

async function bulkMonitor(enabled) {
  const ids = [...state.selectedAccounts]; if (!ids.length) return toast('请先选择账号');
  await api('/api/accounts/bulk/monitor?enabled=' + enabled, { method: 'POST', body: JSON.stringify({ account_ids: ids }) });
  await loadAccounts();
}
async function bulkDeleteAccounts() {
  const ids = [...state.selectedAccounts]; if (!ids.length) return toast('请先选择账号');
  if (!confirm(`确认删除 ${ids.length} 个账号？`)) return;
  await api('/api/accounts/bulk/delete', { method: 'POST', body: JSON.stringify({ account_ids: ids }) });
  state.selectedAccounts.clear(); await loadAccounts();
}
async function bulkCheckAccounts() {
  const ids = [...state.selectedAccounts]; if (!ids.length) return toast('请先选择账号');
  const data = await api('/api/monitor/check-selected', { method: 'POST', body: JSON.stringify({ account_ids: ids }) });
  toast(`检测任务已提交：${data.job?.job_id || ''}`); showTab('tasks');
}
async function bulkSyncAccounts() {
  const ids = [...state.selectedAccounts]; if (!ids.length) return toast('请先选择账号');
  if (!confirm(`同步 ${ids.length} 个账号作品明细？账号多时可能触发风控。`)) return;
  const data = await api('/api/monitor/sync-all', { method: 'POST', body: JSON.stringify({ account_ids: ids }) });
  toast(`同步任务已提交：${data.job?.job_id || ''}`); showTab('tasks');
}

async function showItems(id) {
  const box = $(`items-${id}`);
  if (box.style.display !== 'none') { box.style.display = 'none'; return; }
  const data = await api(`/api/accounts/${id}/items`);
  const items = data.items || [];
  box.innerHTML = items.length ? `<div class="miniList">${items.slice(0, 80).map(item => renderItemMini(id, item)).join('')}</div>` : '<p class="hint">暂无作品。</p>';
  box.style.display = 'block';
}

async function showAccountInsights(id) {
  const box = $(`items-${id}`);
  const data = await api(`/api/accounts/${id}/insights`);
  const ins = data.insights || {};
  const suggestions = (ins.suggestions || []).map(x => `<li>${escapeHtml(x)}</li>`).join('');
  const failures = (ins.failures || []).slice(0,20).map(r => `<div class="miniItem"><div><strong>${escapeHtml(r.title || r.task_id)}</strong><p class="hint danger">${escapeHtml(r.detail || '')}</p></div></div>`).join('');
  const timeline = (ins.timeline || []).slice(0,50).map(x => `<div class="miniItem"><div><strong>${escapeHtml(x.title || x.type)}</strong><p class="hint">${escapeHtml(x.type || '')} ｜ ${escapeHtml(x.status || '')} ｜ ${fmtTime(x.time)}</p><p>${escapeHtml(truncate(x.detail || '', 160))}</p></div></div>`).join('');
  box.innerHTML = `<div class="panel"><h3>账号详情</h3><div class="grid small">${stat('作品', (data.items||[]).length)}${stat('新作品', ins.status_counts?.new || 0)}${stat('失败任务', (ins.failures||[]).length)}${stat('监控', data.monitor_enabled ? '开启' : '关闭')}</div><p>分组：${escapeHtml(data.group_name || '-')} ｜ 策略：${escapeHtml(data.auto_download_policy || '-')} ｜ 间隔：${escapeHtml(data.monitor_interval_minutes || '-')} 分钟</p><p class="hint">${escapeHtml(data.homepage_url || '')}</p><h4>建议</h4><ul>${suggestions || '<li>暂无建议</li>'}</ul><h4>检测 / 作品时间线</h4>${timeline || '<p class="hint">暂无时间线。</p>'}<h4>最近失败</h4>${failures || '<p class="hint">暂无失败记录。</p>'}<h4>原始详情</h4><pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre></div>`;
  box.style.display = 'block';
}

function renderItemMini(accountId, item) {
  const title = item.title || item.description || item.item_id;
  return `<div class="miniItem"><div><strong>${escapeHtml(truncate(title, 80))}</strong><p class="hint">${escapeHtml(item.status || '-')} ｜ ${escapeHtml(item.item_id || '')}</p></div><button onclick="downloadOne('${accountId}', '${item.item_id}')">下载</button></div>`;
}
async function downloadOne(accountId, itemId) { await api(`/api/accounts/${accountId}/items/${itemId}/download`, { method:'POST' }); toast('下载任务已提交'); }

async function loadInbox() {
  try {
    const q = encodeURIComponent($('inboxSearch').value.trim());
    const data = await api(`/api/inbox/new-items?q=${q}`);
    state.inboxItems = data.items || [];
    state.visibleInbox = state.inboxItems;
    $('inboxList').innerHTML = state.visibleInbox.map(renderInboxItem).join('') || '<div class="panel">当前没有未处理新作品。</div>';
    updateInboxSelectionSummary();
  } catch(e) { toast(`加载新作品失败：${e.message}`); }
}
function renderInboxItem(item) {
  const key = itemKey(item.account_id, item.item_id);
  const checked = state.selectedItems.has(key) ? 'checked' : '';
  const title = item.title || item.description || item.item_id;
  const status = item.status === 'count_only' ? '数量变化' : '新作品';
  return `<div class="card">
    <div class="card-title"><label class="check strong"><input type="checkbox" class="inboxSelect" data-key="${escapeHtml(key)}" ${checked}/> ${escapeHtml(truncate(title, 96))}</label>${badge(status, item.status === 'count_only' ? 'warn' : 'ok')}</div>
    <p>账号：${escapeHtml(item.account_name || '-')} ｜ 作品ID：${escapeHtml(item.item_id || '')}</p>
    <p class="hint">${escapeHtml(item.share_url || item.account_homepage_url || '')}</p>
    <div class="card-actions">
      <button onclick="downloadItems([{account_id:'${item.account_id}', item_id:'${item.item_id}'}])">下载</button>
      <button onclick="markSeen([{account_id:'${item.account_id}', item_id:'${item.item_id}'}])">标记已处理</button>
    </div>
  </div>`;
}
function updateInboxSelectionSummary() { $('inboxSelectionSummary').textContent = `已选 ${state.selectedItems.size} / 当前 ${state.visibleInbox.length}`; }
async function markSeen(items) { await api('/api/items/mark-seen', { method:'POST', body: JSON.stringify({ items }) }); toast('已标记处理'); items.forEach(i=>state.selectedItems.delete(itemKey(i.account_id,i.item_id))); await loadInbox(); await loadAccounts(); }
async function downloadItems(items) { const data = await api('/api/items/download', { method:'POST', body: JSON.stringify({ items }) }); toast(`下载任务已提交：${data.job?.job_id || ''}`); showTab('tasks'); }

async function startJob(path, title) {
  try { const data = await api(path, { method: 'POST', body: JSON.stringify({}) }); toast(`${title}已提交：${data.job?.job_id || ''}`); showTab('tasks'); }
  catch (e) { toast(`${title}失败：${e.message}`); }
}

async function previewImport() {
  try {
    const file = $('importFile').files[0]; let data;
    if (file) { const form = new FormData(); form.append('file', file); data = await api(`/api/import/file/preview?default_group=${encodeURIComponent($('importGroup').value)}`, { method: 'POST', body: form }); }
    else data = await api('/api/import/preview', { method: 'POST', body: JSON.stringify(importPayload()) });
    renderImportPreview(data);
  } catch (e) { $('importPreview').innerHTML = `<div class="danger">预览失败：${escapeHtml(e.message)}</div>`; }
}
async function commitImport() {
  if (!confirm('确认导入预览中的有效账号？大批量导入建议不要立即启动监控。')) return;
  try {
    const file = $('importFile').files[0]; let data;
    if (file) { const form = new FormData(); form.append('file', file); const qs = new URLSearchParams({ default_group: $('importGroup').value, auto_download_policy: $('importPolicy').value, notify_enabled: $('notifyEnabled').checked, start_monitor: $('startMonitor').checked }); data = await api(`/api/import/file/commit?${qs}`, { method: 'POST', body: form }); }
    else data = await api('/api/import/commit', { method: 'POST', body: JSON.stringify(importPayload()) });
    renderImportPreview(data); await loadAccounts(); toast(data.summary || '导入完成');
  } catch (e) { $('importPreview').innerHTML = `<div class="danger">导入失败：${escapeHtml(e.message)}</div>`; }
}
function importPayload() { return { text: $('importText').value, default_group: $('importGroup').value, auto_download_policy: $('importPolicy').value, notify_enabled: $('notifyEnabled').checked, start_monitor: $('startMonitor').checked }; }
function renderImportPreview(data) {
  const c = data.counts || data.preview_counts || {};
  $('importSummary').innerHTML = [stat('有效', c.valid ?? data.added ?? 0), stat('新增', c.add ?? data.added ?? 0), stat('更新', c.update ?? data.updated ?? 0), stat('重复', c.duplicate ?? data.duplicate ?? 0), stat('无效', c.invalid ?? data.invalid ?? 0)].join('');
  const rows = data.rows || [];
  const failures = data.failures || data.errors || [];
  if (rows.length) {
    $('importPreview').innerHTML = `<table><thead><tr><th>行</th><th>状态</th><th>链接</th><th>备注</th><th>分组</th><th>原因</th></tr></thead><tbody>${rows.slice(0,300).map(r=>`<tr><td>${r.line_no}</td><td>${escapeHtml(r.status)}</td><td>${escapeHtml(truncate(r.normalized_url || r.raw_url,90))}</td><td>${escapeHtml(r.name||'')}</td><td>${escapeHtml(r.group||'')}</td><td>${escapeHtml(r.reason||'')}</td></tr>`).join('')}</tbody></table>`;
  } else {
    $('importPreview').innerHTML = `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>${failures.length ? `<pre>${escapeHtml(JSON.stringify(failures, null, 2))}</pre>` : ''}`;
  }
}

async function parseText() {
  state.parsedResults = {};
  $('parseResult').innerHTML = ''; $('parseProgress').textContent = '解析中...';
  let ok = 0, fail = 0, progress = 0, downloads = 0;
  try {
    const res = await fetch('/api/parse/stream', { method:'POST', headers: headers({'Content-Type':'application/json'}), body: JSON.stringify({ text:$('parseText').value, concurrency:Number($('parseConcurrency').value||3), download:$('parseDownload').checked }) });
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    const reader = res.body.getReader(); const decoder = new TextDecoder(); let buf = '';
    while (true) {
      const { value, done } = await reader.read(); if (done) break;
      buf += decoder.decode(value, {stream:true});
      const parts = buf.split('\n\n'); buf = parts.pop() || '';
      for (const part of parts) {
        const line = part.split('\n').find(l => l.startsWith('data: ')); if (!line) continue;
        const ev = JSON.parse(line.slice(6));
        if (ev.event === 'done') { $('parseProgress').textContent = `完成：成功 ${ok}，失败 ${fail}，下载事件 ${downloads}`; continue; }
        if (ev.event === 'success') ok += 1; else if (ev.event === 'failure') fail += 1; else if (ev.event === 'download') downloads += 1; else progress += 1;
        appendParseEvent(ev); $('parseProgress').textContent = `进行中：成功 ${ok}，失败 ${fail}`;
      }
    }
  } catch(e) { $('parseProgress').textContent = `解析失败：${e.message}`; }
}
function appendParseEvent(ev) {
  if (ev.event === 'progress') return;
  if (ev.event === 'success') return appendParseSuccess(ev);
  if (ev.event === 'download') return appendParseDownloadEvent(ev);
  if (ev.event === 'failure') return appendParseFailure(ev);
  $('parseResult').insertAdjacentHTML('beforeend', `<div class="card"><div class="card-title"><strong>${escapeHtml(ev.event || '事件')}</strong></div></div>`);
}
function parseResultKey(ev) {
  return `parsed_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}
function appendParseSuccess(ev) {
  const key = parseResultKey(ev);
  state.parsedResults[key] = ev;
  const title = ev.description || ev.title || ev.item_id || '解析成功';
  const type = (ev.media_type === 'image' || (ev.image_urls || []).length) ? '图集' : '视频';
  const countText = type === '图集' ? ` ｜ 图片 ${(ev.image_urls || []).length || (ev.watermark_image_urls || []).length || 0} 张` : '';
  const author = ev.author_nickname || ev.author_id || '-';
  const directUrl = ev.no_watermark_url || ev.watermark_url || (ev.image_urls || [])[0] || '';
  $('parseResult').insertAdjacentHTML('beforeend', `<div class="card parse-card" id="card-${key}">
    <div class="card-title"><strong>${escapeHtml(truncate(title, 80))}</strong>${badge(type, 'ok')}</div>
    <p>作者：${escapeHtml(author)} ｜ 作品ID：${escapeHtml(ev.item_id || '-')}${countText}</p>
    <p class="hint">来源：${escapeHtml(truncate(ev.source_url || '', 130))}</p>
    <div class="card-actions">
      <button class="primary parseDownloadBtn" data-key="${key}">下载</button>
      ${directUrl ? `<button class="parseCopyBtn" data-url="${escapeHtml(directUrl)}">复制直链</button>` : ''}
      ${ev.source_url ? `<a class="buttonLike" href="${escapeHtml(ev.source_url)}" target="_blank" rel="noreferrer">打开来源</a>` : ''}
    </div>
    <div id="parse-status-${key}" class="hint"></div>
    <details><summary>查看解析明细</summary><pre>${escapeHtml(JSON.stringify(compactParsedResult(ev), null, 2))}</pre></details>
  </div>`);
}
function compactParsedResult(ev) {
  return {
    media_type: ev.media_type,
    item_id: ev.item_id,
    description: ev.description,
    author_nickname: ev.author_nickname,
    no_watermark_url: ev.no_watermark_url,
    watermark_url: ev.watermark_url,
    image_count: (ev.image_urls || []).length,
    source_url: ev.source_url,
  };
}
function appendParseFailure(ev) {
  $('parseResult').insertAdjacentHTML('beforeend', `<div class="card parse-card"><div class="card-title"><strong>解析失败</strong>${badge(ev.category || '失败', 'danger')}</div><p>${escapeHtml(ev.reason || '未知错误')}</p>${ev.next_step ? `<p class="hint">建议：${escapeHtml(ev.next_step)}</p>` : ''}<p class="hint">${escapeHtml(ev.source_url || '')}</p></div>`);
}
function appendParseDownloadEvent(ev) {
  const ok = ev.success || ev.status === 'completed';
  $('parseResult').insertAdjacentHTML('beforeend', `<div class="card parse-card"><div class="card-title"><strong>${escapeHtml(ev.item_id || ev.source_url || '下载任务')}</strong>${badge(ok ? '下载完成' : (ev.status || '下载'), ok ? 'ok' : 'warn')}</div><p>${escapeHtml(ev.reason || '')}</p>${ev.path ? `<p class="hint">保存：${escapeHtml(ev.path)}</p>` : ''}</div>`);
}
async function downloadParsedResult(key) {
  const item = state.parsedResults[key];
  if (!item) return toast('解析结果已失效，请重新解析');
  const status = $(`parse-status-${key}`);
  if (status) status.textContent = '正在提交下载...';
  try {
    const data = await api('/api/parse/download', { method:'POST', body: JSON.stringify({ item }) });
    const r = data.result || data;
    if (status) status.textContent = r.success === false ? `下载失败：${r.reason || '未知错误'}` : `下载完成：${r.path || r.reason || '已保存'}`;
    toast(r.success === false ? `下载失败：${r.reason || ''}` : '下载完成');
  } catch(e) {
    if (status) status.textContent = `下载失败：${e.message}`;
    toast(`下载失败：${e.message}`);
  }
}

async function loadTasks() {
  try {
    const data = await api('/api/tasks'); const records = data.records || []; const jobs = data.web_jobs || [];
    $('taskList').innerHTML = [
      ...jobs.map(j => `<div class="card"><div class="card-title"><strong>${escapeHtml(j.title)}</strong>${badge(j.status, j.status==='failed'?'danger':j.status==='completed'?'ok':'')}</div><p>创建：${fmtTime(j.created_at)} ｜ 更新：${fmtTime(j.updated_at)}</p><div class="card-actions">${j.status==='running'?`<button onclick="cancelJob('${j.job_id}')" class="danger">取消</button>`:''}</div><pre>${escapeHtml(JSON.stringify(j.result || j.error || {}, null, 2))}</pre></div>`),
      ...records.map(t => `<div class="card"><div class="card-title"><strong>${escapeHtml(t.title)}</strong>${badge(t.status, t.status==='failed'?'danger':t.status==='completed'?'ok':'')}</div><p>${escapeHtml(t.detail || '')}</p><p>进度：${t.completed || 0}/${t.total || 0} 成功 ${t.success_count || 0} 失败 ${t.failed_count || 0}</p><div class="card-actions"><button onclick="cancelTaskRecord('${t.task_id}')">取消记录</button>${t.retry_action?`<button onclick="retryTaskRecord('${t.task_id}')">重试</button>`:''}</div></div>`)
    ].join('') || '<div class="panel">暂无任务。</div>';
  } catch (e) { toast(`加载任务失败：${e.message}`); }
}
async function cancelJob(id) { await api(`/api/jobs/${id}/cancel`, { method:'POST' }); toast('已发送取消请求'); await loadTasks(); }
async function cancelTaskRecord(id){ const r=await api(`/api/tasks/${id}/cancel`,{method:'POST'}); toast(r.reason||'已取消'); await loadTasks(); await loadQueue(); }
async function retryTaskRecord(id){ const r=await api(`/api/tasks/${id}/retry`,{method:'POST'}); toast(r.reason||'已提交重试'); await loadTasks(); }

async function loadHistory() {
  try {
    const data = await api(`/api/download-history?status=${encodeURIComponent($('historyStatus').value)}&limit=120`);
    const c = data.counts || {}; $('historyStats').innerHTML = [stat('总数', c.total), stat('完成', c.completed), stat('失败', c.failed), stat('可恢复', c.recoverable)].join('');
    $('historyList').innerHTML = (data.records || []).map(r => `<div class="card"><div class="card-title"><strong>${escapeHtml(truncate(r.label || r.title || r.download_id, 90))}</strong>${badge(r.status, r.status==='failed'?'danger':r.status==='completed'?'ok':'')}</div><p>进度：${r.bytes_downloaded || 0}/${r.total_bytes || 0}</p><p class="hint">${escapeHtml(r.save_path || r.url || '')}</p>${r.error?`<p class="hint danger">${escapeHtml(r.error)}</p>`:''}</div>`).join('') || '<div class="panel">暂无下载历史。</div>';
  } catch(e) { toast(`加载下载历史失败：${e.message}`); }
}


async function exportDiagnostics(){ const res=await fetch('/api/diagnostics/export',{method:'POST', headers:headers()}); if(!res.ok) return toast('导出失败'); const blob=await res.blob(); const url=URL.createObjectURL(blob); const a=document.createElement('a'); a.href=url; a.download='douyin_monitor_diagnostics.zip'; a.click(); URL.revokeObjectURL(url); }

async function loadDiagnostics() {
  try {
    const params = new URLSearchParams({ include_network: $('diagNetwork')?.checked || false, include_douyin: $('diagDouyin')?.checked || false });
    const data = await api(`/api/diagnostics?${params}`);
    const c = data.counts || {};
    $('diagnosticStats').innerHTML = [stat('总项', data.total), stat('正常', c['正常'] || 0), stat('可用', c['可用'] || 0), stat('异常', c['异常'] || 0), stat('需配置', c['需配置'] || 0)].join('');
    $('diagnosticList').innerHTML = (data.results || []).map(r => `<div class="card"><div class="card-title"><strong>${escapeHtml(r.name)}</strong>${badge(r.status, r.status==='异常'?'danger':r.status==='正常'?'ok':'warn')}</div><p>${escapeHtml(r.detail || '')}</p>${r.next_step ? `<p class="hint">建议：${escapeHtml(r.next_step)}</p>` : ''}</div>`).join('') || '<div class="panel">暂无诊断结果。</div>';
  } catch (e) { toast(`诊断失败：${e.message}`); }
}

async function loadCookies() {
  try {
    const data = await api('/api/cookies?platform=douyin');
    const s = data.summary || {};
    $('cookieSummary').innerHTML = [stat('Cookie', data.total), stat('正常', s.healthy || 0), stat('降级', s.degraded || 0), stat('冷却', s.cooldown || 0), stat('禁用', (data.rows||[]).filter(r=>r.disabled).length)].join('');
    $('cookieList').innerHTML = (data.rows || []).map(r => `<div class="card"><div class="card-title"><label class="check strong"><input class="cookieSelect" data-hash="${r.hash}" type="checkbox"/> #${r.index} ${escapeHtml(r.masked)}</label>${badge(r.disabled?'已禁用':`score ${Number(r.score || 0).toFixed(2)}`, r.disabled?'danger':Number(r.score||0)<0.5?'warn':'ok')}</div><p>成功 ${r.success_count || 0} ｜ 失败 ${r.failure_count || 0} ｜ 空响应 ${r.empty_response_count || 0}</p><p class="hint">hash=${escapeHtml(r.hash)} ｜ 冷却到：${fmtTime(Number(r.cooldown_until || 0))} ｜ ${escapeHtml(r.last_reason || '')}</p><div class="card-actions"><button onclick="testCookie('${r.hash}')">结构测试</button><button onclick="cookieDisable('${r.hash}', ${!r.disabled})">${r.disabled?'启用':'禁用'}</button><button class="danger" onclick="deleteCookieByHash('${r.hash}')">删除</button></div></div>`).join('') || '<div class="panel">未配置 Cookie。</div>';
  } catch(e) { toast(`加载 Cookie 失败：${e.message}`); }
}
async function saveCookies() {
  const text = $('cookieText').value;
  if (!text.trim() && !confirm('Cookie 内容为空，确认保存为空？')) return;
  const data = await api('/api/cookies', { method:'PATCH', body: JSON.stringify({ platform:'douyin', cookie_text:text }) });
  toast(data.summary || '已保存 Cookie'); $('cookieText').value=''; await loadCookies();
}
async function clearCookieHealth() { if(!confirm('确认清理 Cookie 健康记录？')) return; const r=await api('/api/cookies/clear-health?platform=douyin', {method:'POST'}); toast(`已清理 ${r.cleared || 0} 条`); await loadCookies(); }
async function cookieDisable(hash, disabled) { await api(disabled?'/api/cookies/disable':'/api/cookies/enable', {method:'POST', body:JSON.stringify({platform:'douyin', cookie_hash:hash})}); toast(disabled?'Cookie 已禁用':'Cookie 已启用'); await loadCookies(); }
async function deleteCookieByHash(hash) { if(!confirm('确认删除这条 Cookie？')) return; const r=await api('/api/cookies/delete', {method:'POST', body:JSON.stringify({platform:'douyin', cookie_hash:hash})}); toast(r.summary || r.reason || '已处理'); await loadCookies(); }
async function testCookie(hash) { const r=await api('/api/cookies/test', {method:'POST', body:JSON.stringify({platform:'douyin', cookie_hash:hash})}); alert(`Cookie 结构测试\n分数：${r.score}\n标记：${(r.found_markers||[]).join(', ') || '-'}\n说明：${r.reason || ''}`); }

function selectedCookieHashes(){ return [...document.querySelectorAll('.cookieSelect:checked')].map(el=>el.dataset.hash); }
function selectAllCookies(){ document.querySelectorAll('.cookieSelect').forEach(el=>el.checked=true); }
async function bulkCookie(disabled){ const hashes=selectedCookieHashes(); if(!hashes.length) return toast('请先选择 Cookie'); await api(disabled?'/api/cookies/bulk-disable':'/api/cookies/bulk-enable',{method:'POST', body:JSON.stringify({platform:'douyin', cookie_hashes:hashes})}); toast(disabled?'已批量禁用':'已批量启用'); await loadCookies(); }

function renderQueueRealtime(data){
  const s = data.summary || {}; const snap=data.snapshot||{};
  $('queueSummary').innerHTML = [stat('状态', s.status_text || '-'), stat('运行', (data.running||[]).length), stat('等待', (data.queued||[]).length), stat('总速度', formatBytes(data.total_speed_bps||0) + '/s'), stat('暂停', s.paused ? '是' : '否')].join('');
  const rows = [...(data.running||[]), ...(data.queued||[])];
  if($('queueTaskList')) $('queueTaskList').innerHTML = rows.map(t=>`<div class="card"><div class="card-title"><strong>${escapeHtml(t.title||t.label||t.task_id||'下载任务')}</strong>${badge(t.status||'-', String(t.status||'').includes('失败')?'danger':String(t.status||'').includes('完成')?'ok':'warn')}</div><p>${escapeHtml(t.detail||'')}</p><p>进度：${t.completed||0}/${t.total||0} ｜ 速度：${formatBytes(t.speed_bps||0)}/s ｜ ETA：${t.eta_seconds?Math.round(t.eta_seconds)+'s':'-'}</p><div class="card-actions"><button onclick="cancelTaskRecord('${t.task_id||''}')">取消记录</button>${t.retry_action?`<button onclick="retryTaskRecord('${t.task_id}')">重试</button>`:''}</div></div>`).join('') || '<div class="panel">当前没有运行或等待中的下载任务。</div>';
  if($('queueSnapshot')) $('queueSnapshot').textContent = JSON.stringify(snap, null, 2);
}
async function loadQueue() {
  try { const data = await api('/api/download-queue'); renderQueueRealtime(data); }
  catch(e) { toast(`加载队列失败：${e.message}`); }
}

async function queueAction(action) { const r=await api(`/api/download-queue/${action}`, {method:'POST'}); toast(r.reason || '已执行'); await loadQueue(); }

async function loadBatchJobs() {
  try {
    const data = await api('/api/batch-jobs'); const c = data.counts || {};
    $('batchJobStats').innerHTML = [stat('总数', data.total || 0), stat('运行', c.running || 0), stat('暂停', c.paused || 0), stat('失败', c.failed || 0), stat('完成', c.completed || 0)].join('');
    $('batchJobList').innerHTML = (data.jobs || []).map(j => `<div class="card"><div class="card-title"><strong>${escapeHtml(j.title || j.batch_key || j.job_id)}</strong>${badge(j.status, j.status==='failed'?'danger':j.status==='completed'?'ok':j.status==='paused'?'warn':'')}</div><p>完成：${(j.completed_ids||[]).length}/${j.total || 0} ｜ 失败：${(j.failed_ids||[]).length} ｜ 剩余：${(j.remaining_ids||[]).length}</p><div class="card-actions"><button onclick="batchJobAction('${j.job_id}','pause')">暂停</button><button onclick="batchJobAction('${j.job_id}','resume')">继续</button><button class="danger" onclick="batchJobAction('${j.job_id}','cancel')">取消</button><button onclick="showBatchDetail('${j.job_id}')">详情</button><button onclick="retryBatchFailed('${j.job_id}')">重试失败</button></div><pre id="batch-${j.job_id}" style="display:none"></pre></div>`).join('') || '<div class="panel">暂无批量任务。</div>';
  } catch(e) { toast(`加载批量任务失败：${e.message}`); }
}
async function batchJobAction(id, action) { const r=await api(`/api/batch-jobs/${id}/${action}`, {method:'POST'}); toast(r.reason || '已执行'); await loadBatchJobs(); }
async function showBatchDetail(id) {
  const box=$(`batch-${id}`); if(!box) return; if(box.style.display!=='none'){box.style.display='none'; return;}
  const data=await api(`/api/batch-jobs/${id}`);
  const failures=await api(`/api/batch-jobs/${id}/failures?page=1&page_size=80`);
  const groups=(failures.groups||[]).map(g=>`<div class="miniItem"><div><strong>${escapeHtml(g.category)}</strong><p class="hint">${g.count} 项 ｜ ${escapeHtml(g.sample_reason||'')}</p></div><button onclick="retryBatchCategory('${id}','${encodeURIComponent(g.category)}')">重试此类</button></div>`).join('');
  const failedItems=(failures.items||[]).map(x=>`<tr><td>${escapeHtml(x.item_id)}</td><td>${escapeHtml(x.category)}</td><td>${escapeHtml(x.reason)}</td></tr>`).join('');
  const remain=(data.remaining_ids||[]).slice(0,80).map(x=>`<code>${escapeHtml(x)}</code>`).join(' ');
  box.innerHTML=`<div class="panel"><div class="grid small">${stat('状态',data.status||'-')}${stat('完成',(data.completed_ids||[]).length+'/'+(data.total||0))}${stat('失败',(data.failed_ids||[]).length)}${stat('剩余',(data.remaining_ids||[]).length)}</div><h4>失败分类</h4>${groups||'<p class="hint">暂无失败分类。</p>'}<h4>失败项</h4><div class="tableWrap"><table><thead><tr><th>作品 ID</th><th>分类</th><th>原因</th></tr></thead><tbody>${failedItems||'<tr><td colspan="3">暂无失败项</td></tr>'}</tbody></table></div><h4>剩余项</h4><p class="hint">${remain||'-'}</p><h4>原始详情</h4><pre>${escapeHtml(JSON.stringify(data,null,2))}</pre></div>`;
  box.style.display='block';
}

async function retryBatchFailed(id){ const r=await api(`/api/batch-jobs/${id}/retry-failed`, {method:'POST'}); toast(r.reason || '已提交失败项重试'); await loadBatchJobs(); }
async function retryBatchCategory(id,category){ const r=await api(`/api/batch-jobs/${id}/retry-category?category=${category}`, {method:'POST'}); toast(r.reason || '已提交分类重试'); await loadBatchJobs(); }

async function loadMediaLibrary() {
  try {
    const params = new URLSearchParams({ q:$('mediaSearch').value, status:$('mediaStatus').value, media_type:$('mediaType').value, limit:'300' });
    const data = await api(`/api/media-library?${params}`); const c=data.counts||{};
    $('mediaStats').innerHTML = [stat('作品', data.total), stat('新作品', c.new || 0), stat('已下载', c.downloaded || 0), stat('失败', c.failed || 0), stat('数量变化', c.count_only || 0)].join('');
    $('mediaList').innerHTML = (data.items || []).map(item => `<div class="card"><div class="card-title"><strong>${escapeHtml(truncate(item.title || item.description || item.item_id,100))}</strong>${badge(item.status || '-')}</div><p>账号：${escapeHtml(item.account_name || '-')} ｜ ID：${escapeHtml(item.item_id || '')}</p><p class="hint">${escapeHtml(item.share_url || item.download_url || '')}</p><div class="card-actions"><button onclick="downloadItems([{account_id:'${item.account_id}', item_id:'${item.item_id}'}])">下载</button><button onclick="showMediaDetail('${item.account_id}','${item.item_id}')">预览/详情</button></div><pre id="media-${item.account_id}-${item.item_id}" style="display:none"></pre></div>`).join('') || '<div class="panel">暂无作品。</div>';
  } catch(e) { toast(`加载作品库失败：${e.message}`); }
}
async function showMediaDetail(accountId,itemId){
  const box=$(`media-${accountId}-${itemId}`); if(!box)return;
  if(box.style.display!=='none'){box.style.display='none'; return;}
  const data=await api(`/api/media/${accountId}/${itemId}`);
  const files=data.local_files||[];
  const previews=files.map((f,i)=>{
    const url=authedUrl(`/api/media/${encodeURIComponent(accountId)}/${encodeURIComponent(itemId)}/file/${i}`);
    const lower=(f.name||'').toLowerCase();
    const isVideo=lower.match(/\.(mp4|webm|mov|m4v)$/); const isImage=lower.match(/\.(jpg|jpeg|png|gif|webp)$/);
    const media=isVideo?`<video controls src="${url}" class="previewMedia"></video>`:isImage?`<img src="${url}" class="previewMedia" onclick="openMediaModal('${accountId}','${itemId}',${i})"/>`:'';
    return `<div class="miniItem"><div><strong>${escapeHtml(f.name)}</strong><p class="hint">${formatBytes(f.size)} ｜ ${escapeHtml(f.path||'')}</p>${media}</div><div class="card-actions"><button onclick="openMediaModal('${accountId}','${itemId}',${i})">沉浸预览</button><a class="button" href="${url}" target="_blank">打开/下载</a></div></div>`
  }).join('');
  const archiveUrl=authedUrl(`/api/media/${encodeURIComponent(accountId)}/${encodeURIComponent(itemId)}/archive`);
  box.innerHTML=`<div class="mediaDetail"><p>${escapeHtml(data.title||data.description||data.item_id||'')}</p><p class="hint">${escapeHtml(data.share_url||data.download_url||'')}</p><div class="card-actions"><button onclick="api('/api/media/${accountId}/${itemId}/mark-seen',{method:'POST'}).then(()=>toast('已标记已处理'))">标记已处理</button>${files.length?`<a class="button" href="${archiveUrl}" target="_blank">打包下载本作品</a><button onclick="openMediaModal('${accountId}','${itemId}',0)">打开预览器</button>`:''}</div>${previews || '<p class="hint">未找到本地媒体文件。下载后可在这里预览。</p>'}<pre>${escapeHtml(JSON.stringify(data,null,2))}</pre></div>`;
  box.style.display='block';
}
async function openMediaModal(accountId,itemId,index=0){
  const data=await api(`/api/media/${accountId}/${itemId}`);
  state.mediaPreviewFiles=data.local_files||[]; state.mediaPreviewIndex=Number(index||0);
  $('mediaPreviewTitle').textContent=data.title||data.description||data.item_id||'媒体预览';
  renderMediaModal(accountId,itemId);
  $('mediaPreviewModal').style.display='flex';
}
function closeMediaModal(){ $('mediaPreviewModal').style.display='none'; $('mediaPreviewStage').innerHTML=''; }
function renderMediaModal(accountId,itemId){
  const files=state.mediaPreviewFiles||[]; if(!files.length){ $('mediaPreviewStage').innerHTML='<p class="hint">未找到本地媒体文件。</p>'; $('mediaPreviewThumbs').innerHTML=''; return; }
  state.mediaPreviewIndex=Math.max(0,Math.min(files.length-1,state.mediaPreviewIndex));
  const f=files[state.mediaPreviewIndex]; const url=authedUrl(`/api/media/${encodeURIComponent(accountId)}/${encodeURIComponent(itemId)}/file/${state.mediaPreviewIndex}`);
  const lower=(f.name||'').toLowerCase();
  const media=lower.match(/\.(mp4|webm|mov|m4v)$/)?`<video controls autoplay src="${url}" class="modalMedia"></video>`:lower.match(/\.(jpg|jpeg|png|gif|webp)$/)?`<img src="${url}" class="modalMedia"/>`:`<p class="hint">该文件类型不支持内嵌预览，可打开下载。</p>`;
  $('mediaPreviewStage').innerHTML=`<div class="card-actions"><button onclick="state.mediaPreviewIndex--; renderMediaModal('${accountId}','${itemId}')">上一项</button><strong>${escapeHtml(f.name)} (${state.mediaPreviewIndex+1}/${files.length})</strong><button onclick="state.mediaPreviewIndex++; renderMediaModal('${accountId}','${itemId}')">下一项</button><a class="button" href="${url}" target="_blank">打开/下载</a></div>${media}`;
  $('mediaPreviewThumbs').innerHTML=files.map((x,i)=>{ const u=authedUrl(`/api/media/${encodeURIComponent(accountId)}/${encodeURIComponent(itemId)}/file/${i}`); const isImg=(x.name||'').toLowerCase().match(/\.(jpg|jpeg|png|gif|webp)$/); return `<button class="thumb ${i===state.mediaPreviewIndex?'active':''}" onclick="state.mediaPreviewIndex=${i}; renderMediaModal('${accountId}','${itemId}')">${isImg?`<img src="${u}"/>`:escapeHtml((x.name||'文件').slice(0,12))}</button>`; }).join('');
}

async function loadStorage() {
  try {
    const pathValue = $('storagePath').value || '';
    const params = new URLSearchParams({ path:pathValue, q:$('storageSearch').value, media_filter:$('storageFilter').value, sort_mode:$('storageSort').value });
    const data = await api(`/api/storage?${params}`);
    const folders = data.folders || [];
    const files = data.files || [];
    const currentRelative = normalizeStoragePath(data.current_relative ?? pathValue, data.root);
    state.storageRoot = data.root || state.storageRoot || '';
    state.storagePreviewFiles = files;
    state.storageCurrentPath = currentRelative;
    if ($('storagePath')) $('storagePath').value = currentRelative;
    renderStorageHeader(data, folders, files);
    renderStorageNavigator(currentRelative, folders);
    renderStorageItems(folders, files);
  } catch(e) { toast(`扫描存储失败：${e.message}`); }
}

function renderStorageHeader(data, folders, files){
  const currentRel = storageDisplayPath(state.storageCurrentPath || '');
  if($('storageCurrent')) $('storageCurrent').textContent = `根目录：${data.root} ｜ 当前：${currentRel}`;
  if($('storagePathBar')) $('storagePathBar').textContent = currentRel || '全部文件';
  if($('storageSummary')) $('storageSummary').innerHTML = [
    stat('文件夹', folders.length),
    stat('媒体文件', files.length),
    stat('图片', files.filter(f=>f.is_image).length),
    stat('视频', files.filter(f=>f.is_video).length)
  ].join('');
  if($('storageBreadcrumb')) $('storageBreadcrumb').innerHTML = storageBreadcrumbHtml(state.storageCurrentPath || '');
}

function renderStorageNavigator(currentPath, folders){
  if(!$('storageFolderTree')) return;
  const parent = storageParentPath(currentPath || '');
  const items = [
    `<button class="tree-item ${!currentPath?'active':''}" onclick="openStoragePath('')">🏠 全部文件</button>`,
    currentPath ? `<button class="tree-item" onclick="openStoragePath('${escapeJsArg(parent)}')">⬆ 返回上一级</button>` : '',
    ...folders.map(f => `<button class="tree-item" onclick="openStoragePath('${escapeJsArg(f.relative_path)}')">📁 ${escapeHtml(f.name)}</button>`)
  ].filter(Boolean);
  $('storageFolderTree').innerHTML = items.join('') || '<p class="hint">暂无文件夹</p>';
}

function renderStorageItems(folders, files){
  const view = state.storageViewMode || 'grid';
  const folderHtml = folders.map(f => renderStorageFolderTile(f, view));
  const fileHtml = files.map((f,i) => renderStorageFileCard(f,i,view));
  const empty = '<div class="panel emptyState"><strong>当前目录没有文件</strong><p class="hint">下载完成的视频和图片会显示在这里。可以返回上一级或切换筛选条件。</p></div>';
  $('storageList').className = `storageItems ${view === 'list' ? 'listMode' : 'gridMode'}`;
  $('storageList').innerHTML = [...folderHtml, ...fileHtml].join('') || empty;
}

function openStoragePath(path){
  const normalized = normalizeStoragePath(path);
  $('storagePath').value = normalized;
  state.storageCurrentPath = normalized;
  loadStorage();
}
function goStorageHome(){ openStoragePath(''); }
function goStorageUp(){ openStoragePath(storageParentPath(state.storageCurrentPath || $('storagePath').value || '')); }
function setStorageViewMode(mode){
  state.storageViewMode = mode === 'list' ? 'list' : 'grid';
  document.querySelectorAll('[data-storage-view]').forEach(b => b.classList.toggle('primary', b.dataset.storageView === state.storageViewMode));
  loadStorage();
}
function storageDisplayPath(path){ return path ? path : '下载根目录'; }
function normalizeStoragePath(path, root=''){
  let value = String(path || '').trim().replace(/\\/g, '/');
  const rootValue = String(root || state.storageRoot || '').trim().replace(/\\/g, '/').replace(/\/+$/, '');
  if (!value || value === '.' || value === '/') return '';
  value = value.replace(/\/+$/, '');
  if (rootValue && value === rootValue) return '';
  if (rootValue && value.startsWith(rootValue + '/')) value = value.slice(rootValue.length + 1);
  value = value.replace(/^\/+/, '');
  const parts = [];
  for (const part of value.split('/')) {
    if (!part || part === '.') continue;
    if (part === '..') { parts.pop(); continue; }
    parts.push(part);
  }
  return parts.join('/');
}
function storageParentPath(path){
  const normalized = normalizeStoragePath(path);
  const parts = normalized.split('/').filter(Boolean);
  parts.pop();
  return parts.join('/');
}
function storageBreadcrumbHtml(path){
  const parts = String(path || '').split('/').filter(Boolean);
  const crumbs = [`<button onclick="openStoragePath('')">全部文件</button>`];
  let acc = '';
  parts.forEach(part => {
    acc = acc ? `${acc}/${part}` : part;
    crumbs.push(`<span>/</span><button onclick="openStoragePath('${escapeJsArg(acc)}')">${escapeHtml(part)}</button>`);
  });
  return crumbs.join('');
}
function escapeJsArg(s){ return String(s ?? '').replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/\n/g,' '); }
function storageFileUrl(path){ return authedUrl(`/api/storage/file?path=${encodeURIComponent(path)}`); }
function storageMediaTypeLabel(f){ return f.is_video ? '视频' : f.is_image ? '图片' : '文件'; }
function renderStorageFolderTile(f, view='grid'){
  const name = escapeHtml(f.name);
  const rel = escapeHtml(f.relative_path);
  if(view === 'list'){
    return `<div class="fileRow folderRow" ondblclick="openStoragePath('${escapeJsArg(f.relative_path)}')"><div class="fileCell nameCell"><span class="fileIcon">📁</span><div><strong>${name}</strong><p>${rel}</p></div></div><div class="fileCell">文件夹</div><div class="fileCell">-</div><div class="fileActions"><button onclick="openStoragePath('${escapeJsArg(f.relative_path)}')">打开</button><button class="danger" onclick="deleteStoragePath('${escapeJsArg(f.relative_path)}')">删除</button></div></div>`;
  }
  return `<div class="fileTile folderTile" ondblclick="openStoragePath('${escapeJsArg(f.relative_path)}')"><div class="tileThumb folderThumb">📁</div><div class="tileInfo"><strong>${name}</strong><p>${rel}</p></div><div class="tileActions"><button onclick="openStoragePath('${escapeJsArg(f.relative_path)}')">打开</button><button class="danger" onclick="deleteStoragePath('${escapeJsArg(f.relative_path)}')">删除</button></div></div>`;
}
function renderStorageFileCard(f,index,view='grid'){
  const url = storageFileUrl(f.relative_path);
  const isVideo = !!f.is_video; const isImage = !!f.is_image;
  const icon = isVideo ? '🎬' : isImage ? '🖼️' : '📄';
  const name = escapeHtml(f.name);
  const rel = escapeHtml(f.relative_path);
  const size = formatBytes(f.size);
  const type = storageMediaTypeLabel(f);
  const preview = isVideo ? `<video muted preload="metadata" src="${url}" class="tileMedia"></video>` : isImage ? `<img src="${url}" class="tileMedia" loading="lazy"/>` : `<div class="tileThumb fileThumb">${icon}</div>`;
  if(view === 'list'){
    return `<div class="fileRow" ondblclick="openStoragePreview(${index})"><div class="fileCell nameCell"><span class="fileIcon">${icon}</span><div><strong>${name}</strong><p>${rel}</p></div></div><div class="fileCell">${type}</div><div class="fileCell">${size}</div><div class="fileActions"><button onclick="openStoragePreview(${index})">预览</button><a class="button" href="${url}" target="_blank">下载</a><button class="danger" onclick="deleteStoragePath('${escapeJsArg(f.relative_path)}')">删除</button></div></div>`;
  }
  return `<div class="fileTile mediaTile"><div class="tilePreview" onclick="openStoragePreview(${index})">${preview}<div class="tileOverlay"><button>预览</button></div></div><div class="tileInfo"><strong title="${name}">${name}</strong><p>${type} ｜ ${size}</p></div><div class="tileActions"><button onclick="openStoragePreview(${index})">预览</button><a class="button" href="${url}" target="_blank">下载</a><button class="danger" onclick="deleteStoragePath('${escapeJsArg(f.relative_path)}')">删除</button></div></div>`;
}
function openStoragePreview(index=0){
  const files = state.storagePreviewFiles || [];
  if(!files.length){ toast('当前目录没有可预览的媒体文件'); return; }
  state.storagePreviewIndex = Math.max(0, Math.min(files.length-1, Number(index||0)));
  $('mediaPreviewTitle').textContent = '存储媒体预览';
  renderStoragePreview();
  $('mediaPreviewModal').style.display='flex';
}
function renderStoragePreview(){
  const files = state.storagePreviewFiles || [];
  if(!files.length){ $('mediaPreviewStage').innerHTML='<p class="hint">当前目录没有可预览的媒体文件。</p>'; $('mediaPreviewThumbs').innerHTML=''; return; }
  state.storagePreviewIndex=Math.max(0,Math.min(files.length-1,state.storagePreviewIndex));
  const f=files[state.storagePreviewIndex]; const url=storageFileUrl(f.relative_path);
  const isVideo=!!f.is_video; const isImage=!!f.is_image;
  const media=isVideo?`<video controls autoplay src="${url}" class="modalMedia"></video>`:isImage?`<img src="${url}" class="modalMedia"/>`:`<p class="hint">该文件类型不支持内嵌预览，可打开下载。</p>`;
  $('mediaPreviewStage').innerHTML=`<div class="card-actions"><button onclick="state.storagePreviewIndex--; renderStoragePreview()">上一项</button><strong>${escapeHtml(f.name)} (${state.storagePreviewIndex+1}/${files.length})</strong><button onclick="state.storagePreviewIndex++; renderStoragePreview()">下一项</button><a class="button" href="${url}" target="_blank">打开/下载</a></div>${media}<p class="hint">${escapeHtml(f.relative_path)} ｜ ${formatBytes(f.size)}</p>`;
  $('mediaPreviewThumbs').innerHTML=files.map((x,i)=>{ const u=storageFileUrl(x.relative_path); return `<button class="thumb ${i===state.storagePreviewIndex?'active':''}" onclick="state.storagePreviewIndex=${i}; renderStoragePreview()">${x.is_image?`<img src="${u}"/>`:escapeHtml((x.name||'视频').slice(0,12))}</button>`; }).join('');
}
async function loadStorageStats(){ const s=await api('/api/storage/stats'); if($('storageStats')) $('storageStats').innerHTML=[stat('文件',s.total_files), stat('容量',formatBytes(s.total_size)), stat('视频',s.videos), stat('图片',s.images), stat('临时文件',s.temp_files)].join('') + (s.folders||[]).slice(0,5).map(f=>`<div class="stat"><div class="value">${formatBytes(f.size)}</div><div class="label">${escapeHtml(f.name)}</div></div>`).join(''); }
async function deleteStoragePath(path){ if(!confirm(`确认删除 ${path}？`)) return; const r=await api('/api/storage/delete',{method:'POST', body:JSON.stringify({path})}); toast(r.reason || (r.success?'已删除':'删除失败')); await loadStorage(); await loadStorageStats(); }
async function cleanupTemp(){ if(!confirm('确认清理临时/分片残留文件？')) return; const r=await api('/api/storage/cleanup-temp',{method:'POST'}); toast(`已清理 ${r.deleted||0} 个，释放 ${formatBytes(r.bytes_deleted||0)}`); await loadStorage(); await loadStorageStats(); }
function formatBytes(n){ n=Number(n||0); if(n>1024*1024*1024)return (n/1024/1024/1024).toFixed(2)+' GB'; if(n>1024*1024)return (n/1024/1024).toFixed(2)+' MB'; if(n>1024)return (n/1024).toFixed(1)+' KB'; return n+' B'; }

async function loadLogs(){ try{ const data=await api('/api/logs'); $('logFileList').innerHTML=(data.files||[]).map(f=>`<div class="card"><div class="card-title"><strong>${escapeHtml(f.name)}</strong>${badge(formatBytes(f.size))}</div><p class="hint">${escapeHtml(f.path)}</p><div class="card-actions"><button onclick="loadLogTail('${escapeHtml(f.name)}')">查看尾部</button><a class="button" href="${authedUrl('/api/logs/download?name=' + encodeURIComponent(f.name))}" target="_blank">下载</a></div></div>`).join('') || '<div class="panel">暂无日志文件。</div>'; }catch(e){toast(`加载日志失败：${e.message}`);} }
async function loadLogTail(name){ const lines=Number($('logLines').value||200); const data=await api(`/api/logs/tail?name=${encodeURIComponent(name)}&lines=${lines}`); $('logContent').textContent=data.content || data.reason || '无内容'; }
async function searchLogs(){ const q=$('logQuery').value, level=$('logLevel').value, lines=Number($('logLines').value||500); const data=await api(`/api/logs/search?q=${encodeURIComponent(q)}&level=${encodeURIComponent(level)}&lines=${lines}`); $('logSearchList').innerHTML=(data.matches||[]).map(m=>`<div class="miniItem"><div><strong>${escapeHtml(m.file)}:${m.line}</strong><p class="hint">${escapeHtml(m.content)}</p></div></div>`).join('') || '<div class="panel">没有匹配日志。</div>'; }
async function clearLogs(name=''){ if(!confirm(name?'确认清空该日志？':'确认清空全部日志？')) return; const r=await api(`/api/logs/clear?name=${encodeURIComponent(name)}`,{method:'POST'}); toast(`已清空 ${r.cleared||0} 个日志`); await loadLogs(); $('logContent').textContent=''; }

const riskControlFields = [
  ['development_bypass_risk_controls_enabled','开发模式：跳过冷却/限速/退避'],
  ['global_request_limiter_enabled','启用全局请求限速'],
  ['cookie_cooldown_enabled','启用 Cookie 失败冷却'],
  ['risk_backoff_enabled','启用风控退避']
];
async function loadRisk(){
  try{
    const data=await api('/api/network-risk');
    const c=data.cookie||{}, l=data.rate_limiter||{}, controls=data.controls||{};
    $('riskStats').innerHTML=[stat('Cookie冷却', c.cooldown||0), stat('Cookie降级', c.degraded||0), stat('限速状态', l.enabled===false?'关闭':'开启'), stat('风险账号', (data.risk_accounts||[]).length)].join('');
    if($('riskControls')) $('riskControls').innerHTML=riskControlFields.map(([key,label])=>`<label><span>${escapeHtml(label)}</span><input data-risk-control="${key}" type="checkbox" ${controls[key] ? 'checked' : ''}/></label>`).join('');
    $('riskSuggestions').innerHTML=(data.suggestions||[]).map(x=>`<p>${escapeHtml(x)}</p>`).join('');
    $('riskLimiter').innerHTML=renderKv(l);
    $('riskAccountList').innerHTML=(data.risk_accounts||[]).map(a=>`<div class="card"><div class="card-title"><strong>${escapeHtml(a.name||a.account_id)}</strong>${badge(a.status||'风险','warn')}</div><p class="hint danger">${escapeHtml(a.last_error||'')}</p></div>`).join('') || '<div class="panel">暂无明显风险账号。</div>';
  }catch(e){toast(`加载风控状态失败：${e.message}`);}
}
async function saveRiskControls(){
  const values={};
  document.querySelectorAll('[data-risk-control]').forEach(el=>{ values[el.dataset.riskControl]=el.checked; });
  if(values.development_bypass_risk_controls_enabled){
    values.global_request_limiter_enabled=false;
    values.cookie_cooldown_enabled=false;
    values.risk_backoff_enabled=false;
  }
  await api('/api/settings',{method:'PATCH', body:JSON.stringify({values})});
  toast(values.development_bypass_risk_controls_enabled ? '已开启开发模式：冷却/限速/退避已跳过' : '风控控制开关已保存');
  await loadRisk();
}
async function clearRiskCookieHealth(){
  if(!confirm('确认清理 Cookie 健康/冷却记录？不会删除 Cookie 原文。')) return;
  await api('/api/cookies/clear-health',{method:'POST'});
  toast('Cookie 冷却记录已清理');
  await loadRisk();
}

async function loadNotifications(){ try{ const data=await api('/api/notifications'); const g=data.global||{}; const channelFields=['webhook_url','telegram_bot_token','telegram_chat_id','bark_url','bark_key','serverchan_sendkey','wecom_webhook_url']; $('notificationGlobal').innerHTML=['notification_enabled','notify_on_new_work','notify_on_download_complete','notify_on_download_failed'].map(k=>`<label><span>${escapeHtml(k)}</span><input data-notify-global="${k}" type="checkbox" ${g[k]?'checked':''}></label>`).join('') + channelFields.map(k=>`<label><span>${escapeHtml(k)}</span><input data-notify-global="${k}" value="${escapeHtml(g[k]||'')}"></label>`).join(''); $('notificationAccounts').innerHTML=(data.accounts||[]).map(a=>`<div class="card"><label class="check strong"><input data-notify-account="${a.account_id}" type="checkbox" ${a.notify_enabled?'checked':''}> ${escapeHtml(a.name)}</label><p class="hint">模式：${escapeHtml(a.notify_mode||'default')}</p></div>`).join('') || '<div class="panel">暂无账号。</div>'; }catch(e){toast(`加载通知失败：${e.message}`);} }
async function saveNotifications(){ const global={}; document.querySelectorAll('[data-notify-global]').forEach(el=>{global[el.dataset.notifyGlobal]=el.type==='checkbox'?el.checked:el.value}); const accounts=[]; document.querySelectorAll('[data-notify-account]').forEach(el=>accounts.push({account_id:el.dataset.notifyAccount, notify_enabled:el.checked})); await api('/api/notifications',{method:'PATCH', body:JSON.stringify({values:{global,accounts}})}); toast('通知设置已保存'); await loadNotifications(); }
async function testNotification(allow){ const channel=($('notificationChannel')?.value || prompt('通知渠道：webhook / telegram / bark / serverchan / wecom','webhook') || 'webhook'); const r=await api('/api/notifications/test',{method:'POST', body:JSON.stringify({channel, message:'Douyin Monitor Web 通知测试', allow_network:allow})}); $('notificationTestResult').textContent=JSON.stringify(r,null,2); toast(r.reason || (r.success?'测试完成':'测试失败')); }


async function loadUpdates(){ try{ const data=await api('/api/updates'); $('updateStats').innerHTML=[stat('当前版本', data.current_version||'-'), stat('自动更新', data.enabled?'开启':'关闭'), stat('通道', data.channel||'-')].join(''); $('updateBox').textContent=JSON.stringify(data,null,2); }catch(e){$('updateBox').textContent=e.message;} }
async function checkUpdates(allow){ const data=await api(`/api/updates/check?allow_network=${allow}`, {method:'POST'}); $('updateBox').textContent=JSON.stringify(data,null,2); toast(data.reason || (data.available?'发现新版本':'没有新版本')); }

async function loadAccess(){ try{ const data=await api('/api/access'); $('accessBox').innerHTML=renderKv(data); const users=await api('/api/access/users'); const rbac=await api('/api/access/rbac'); $('accessUserList').innerHTML=(users.users||[]).map(u=>`<div class="card"><div class="card-title"><strong>${escapeHtml(u.name||u.user_id)}</strong>${badge(u.role||'viewer')}</div><p class="hint">Token：${escapeHtml(u.token_preview||'-')} ｜ 创建：${fmtTime(Number(u.created_at||0))}</p><div class="card-actions"><button onclick="rotateAccessUser('${u.user_id}')">轮换 Token</button><button class="danger" onclick="deleteAccessUser('${u.user_id}')">删除</button></div></div>`).join('') || '<div class="panel">暂无子用户。</div>'; if($('accessRbacBox')) $('accessRbacBox').innerHTML='<h3>权限矩阵</h3>'+(rbac.roles||[]).map(r=>`<div class="miniItem"><div><strong>${escapeHtml(r.role)}</strong><p class="hint">${escapeHtml(r.description)}</p></div></div>`).join('')+'<h3>审计记录</h3>'+(users.audit||[]).slice(-30).reverse().map(a=>`<div class="miniItem"><div><strong>${escapeHtml(a.action)}</strong><p class="hint">${fmtTime(a.time)} ｜ ${escapeHtml(a.method||'')} ${escapeHtml(a.path||'')} ｜ ${escapeHtml(a.role||'')}</p></div></div>`).join(''); }catch(e){toast(`加载访问控制失败：${e.message}`);} }

async function createAccessUser(){ const name=$('accessUserName').value.trim()||'web-user'; const role=$('accessUserRole').value; const r=await api('/api/access/users',{method:'POST', body:JSON.stringify({name, role})}); $('newAccessTokenBox').textContent='新 Token：'+(r.token||''); await loadAccess(); }
async function rotateAccessUser(id){ const r=await api(`/api/access/users/${id}/rotate`,{method:'POST'}); $('newAccessTokenBox').textContent='新 Token：'+(r.token||''); await loadAccess(); }
async function deleteAccessUser(id){ if(!confirm('确认删除该访问用户？')) return; await api(`/api/access/users/${id}`,{method:'DELETE'}); await loadAccess(); }
async function createBackup(full){ const data=await api(`/api/backups?full=${full}`, {method:'POST'}); $('backupResult').innerHTML=`<strong>备份已创建</strong><p>${escapeHtml(data.path)}</p><a class="button" href="${authedUrl('/api/backups/download?name=' + encodeURIComponent(data.name))}" target="_blank">下载备份</a>`; toast('备份已创建'); await loadBackups(); }
async function loadBackups(){ const data=await api('/api/backups'); if(!$('backupList')) return; $('backupList').innerHTML=(data.backups||[]).map(b=>`<div class="card"><div class="card-title"><strong>${escapeHtml(b.name)}</strong>${badge(formatBytes(b.size))}</div><p class="hint">${fmtTime(Number(b.mtime||0))} ｜ ${escapeHtml(b.path)}</p><div class="card-actions"><a class="button" href="${authedUrl('/api/backups/download?name=' + encodeURIComponent(b.name))}" target="_blank">下载</a><button onclick="$('restoreBackupName').value='${escapeHtml(b.name)}'; restoreBackup(false)">校验</button><button class="danger" onclick="$('restoreBackupName').value='${escapeHtml(b.name)}'; restoreBackup(true)">恢复</button></div></div>`).join('') || '<div class="panel">暂无备份。</div>'; }
async function restoreBackup(apply){ const file=$('restoreUploadFile')?.files?.[0]; if(apply && !confirm('确认应用恢复？会覆盖配置文件，建议先备份并恢复后重启容器。')) return; if(file){ const fd=new FormData(); fd.append('file', file); const res=await fetch(`/api/backups/upload-restore?apply=${apply}`,{method:'POST', headers:{'Authorization':'Bearer '+state.token}, body:fd}); const data=await res.json(); $('restoreResult').textContent=JSON.stringify(data,null,2); return; } const name=$('restoreBackupName').value.trim(); if(!name) return toast('请输入备份文件名或选择上传文件'); const data=await api('/api/backups/restore',{method:'POST', body:JSON.stringify({name, apply})}); $('restoreResult').textContent=JSON.stringify(data,null,2); toast(data.reason||'恢复校验完成'); }


const settingFields = [
  ['monitor_batch_concurrency','监控并发','number'], ['video_parse_concurrency','解析并发','number'], ['batch_parse_size','解析批大小','number'],
  ['batch_download_concurrency','批量下载并发','number'], ['gallery_image_concurrency','图集图片并发','number'], ['download_chunk_size_kb','下载块 KB','number'],
  ['development_bypass_risk_controls_enabled','开发模式：关闭冷却/限速','checkbox'], ['global_request_limiter_enabled','全局请求限速','checkbox'], ['cookie_cooldown_enabled','Cookie失败冷却','checkbox'], ['risk_backoff_enabled','风控退避','checkbox'], ['cookie_health_persistence_enabled','Cookie健康持久化','checkbox'], ['batch_parse_download_pipeline_enabled','边解析边下载','checkbox'],
  ['segmented_download_enabled','大视频分片','checkbox'], ['segmented_download_parts','分片数量','number'], ['segmented_download_min_size_mb','分片阈值 MB','number']
];
async function loadSettings() {
  try {
    const data = await api('/api/settings'); state.settings = data.user_config || {};
    $('settingsBox').textContent = JSON.stringify(data, null, 2);
    $('settingsForm').innerHTML = settingFields.map(([key,label,type]) => `<label><span>${escapeHtml(label)}</span><input data-setting="${key}" type="${type}" ${type==='checkbox' ? (state.settings[key] ? 'checked' : '') : `value="${escapeHtml(state.settings[key] ?? '')}"`} /></label>`).join('');
  } catch (e) { $('settingsBox').textContent = `加载失败：${e.message}`; }
}
async function saveSettings() {
  const values = {};
  document.querySelectorAll('[data-setting]').forEach(el => { values[el.dataset.setting] = el.type === 'checkbox' ? el.checked : (el.value === '' ? null : Number(el.value)); });
  await api('/api/settings', { method:'PATCH', body: JSON.stringify({ values }) }); toast('设置已保存'); await loadSettings();
}

function startLiveLog(){
  const selected = state.currentLogName;
  if(!selected) return toast('请先选择一个日志文件');
  if(state.liveLogSource) state.liveLogSource.close();
  state.liveLogSource = new EventSource(authedUrl(`/api/logs/stream?name=${encodeURIComponent(selected)}&lines=${encodeURIComponent($('logLines').value||200)}`));
  state.liveLogSource.onmessage = (msg) => { try{ const d=JSON.parse(msg.data||'{}'); $('logContent').textContent=d.content||''; }catch(_){} };
  state.liveLogSource.onerror = () => toast('实时日志连接异常，将保留当前内容');
  toast('已开始实时跟随日志');
}
function stopLiveLog(){ if(state.liveLogSource){ state.liveLogSource.close(); state.liveLogSource=null; toast('已停止实时跟随日志'); } }


document.addEventListener('click', (e) => {
  const downloadBtn = e.target.closest?.('.parseDownloadBtn');
  if (downloadBtn) downloadParsedResult(downloadBtn.dataset.key);
  const copyBtn = e.target.closest?.('.parseCopyBtn');
  if (copyBtn) {
    navigator.clipboard?.writeText(copyBtn.dataset.url || '').then(() => toast('直链已复制')).catch(() => toast('复制失败'));
  }
});

function bindEvents() {
  document.querySelectorAll('.nav').forEach(n => n.addEventListener('click', () => showTab(n.dataset.tab)));
  $('tokenInput').value = state.token;
  $('saveTokenBtn').onclick = () => { state.token = $('tokenInput').value.trim(); localStorage.setItem('douyin_monitor_web_token', state.token); toast('Token 已保存'); connectEvents(); };
  $('refreshBtn').onclick = () => showTab(currentTab());
  $('addAccountBtn').onclick = addAccount;
  $('accountSearch').oninput = applyAccountFilters; $('accountStatusFilter').onchange = applyAccountFilters;
  $('selectVisibleAccountsBtn').onclick = () => { state.visibleAccounts.forEach(a=>state.selectedAccounts.add(a.account_id)); applyAccountFilters(); };
  $('clearAccountSelectionBtn').onclick = () => { state.selectedAccounts.clear(); applyAccountFilters(); };
  $('bulkCheckBtn').onclick = bulkCheckAccounts; $('bulkSyncBtn').onclick = bulkSyncAccounts; $('bulkStartBtn').onclick = () => bulkMonitor(true); $('bulkStopBtn').onclick = () => bulkMonitor(false); $('bulkDeleteBtn').onclick = bulkDeleteAccounts;
  $('checkAllBtn')?.addEventListener('click', () => startJob('/api/monitor/check-all', '检测更新'));
  $('syncAllBtn')?.addEventListener('click', () => { if (confirm('同步全部作品会请求作品明细，账号较多时可能触发风控。继续？')) startJob('/api/monitor/sync-all', '同步作品'); });
  $('loadInboxBtn').onclick = loadInbox; $('inboxSearch').oninput = () => setTimeout(loadInbox, 150);
  $('selectAllInboxBtn').onclick = () => { state.visibleInbox.forEach(i => state.selectedItems.add(itemKey(i.account_id, i.item_id))); loadInbox(); };
  $('clearInboxSelectionBtn').onclick = () => { state.selectedItems.clear(); updateInboxSelectionSummary(); loadInbox(); };
  $('downloadSelectedInboxBtn').onclick = () => { const items=[...state.selectedItems].map(parseKey); if(!items.length) return toast('请先选择作品'); downloadItems(items); };
  $('markSeenSelectedBtn').onclick = () => { const items=[...state.selectedItems].map(parseKey); if(!items.length) return toast('请先选择作品'); markSeen(items); };
  $('previewImportBtn').onclick = previewImport; $('commitImportBtn').onclick = commitImport;
  $('parseBtn').onclick = parseText; $('clearParseBtn').onclick = () => { $('parseResult').innerHTML=''; $('parseProgress').textContent='等待解析...'; };
  $('refreshTasksBtn').onclick = loadTasks; $('refreshHistoryBtn').onclick = loadHistory; $('historyStatus').onchange = loadHistory;
  $('saveSettingsBtn').onclick = saveSettings; $('reloadSettingsBtn').onclick = loadSettings;
  $('runDiagnosticsBtn') && ($('runDiagnosticsBtn').onclick = loadDiagnostics); $('exportDiagnosticsBtn') && ($('exportDiagnosticsBtn').onclick = exportDiagnostics);
  $('saveCookieBtn') && ($('saveCookieBtn').onclick = saveCookies); $('refreshCookieBtn') && ($('refreshCookieBtn').onclick = loadCookies); $('clearCookieHealthBtn') && ($('clearCookieHealthBtn').onclick = clearCookieHealth);
  $('pauseQueueBtn') && ($('pauseQueueBtn').onclick = () => queueAction('pause')); $('resumeQueueBtn') && ($('resumeQueueBtn').onclick = () => queueAction('resume')); $('cancelQueueBtn') && ($('cancelQueueBtn').onclick = () => queueAction('cancel')); $('refreshQueueBtn') && ($('refreshQueueBtn').onclick = loadQueue); $('refreshQueueTasksBtn') && ($('refreshQueueTasksBtn').onclick = loadQueue);
  $('refreshBatchJobsBtn') && ($('refreshBatchJobsBtn').onclick = loadBatchJobs);
  $('refreshMediaBtn') && ($('refreshMediaBtn').onclick = loadMediaLibrary); $('mediaSearch') && ($('mediaSearch').oninput = () => setTimeout(loadMediaLibrary, 150)); $('mediaStatus') && ($('mediaStatus').onchange = loadMediaLibrary); $('mediaType') && ($('mediaType').onchange = loadMediaLibrary);
  $('refreshStorageBtn') && ($('refreshStorageBtn').onclick = () => { loadStorage(); loadStorageStats(); }); $('storageStatsBtn') && ($('storageStatsBtn').onclick = loadStorageStats); $('cleanupTempBtn') && ($('cleanupTempBtn').onclick = cleanupTemp); $('scanEmptyBtn') && ($('scanEmptyBtn').onclick = scanEmptyFiles); $('scanDuplicateBtn') && ($('scanDuplicateBtn').onclick = scanDuplicateFiles);
  $('refreshLogsBtn') && ($('refreshLogsBtn').onclick = loadLogs); $('searchLogsBtn') && ($('searchLogsBtn').onclick = searchLogs); $('liveLogBtn') && ($('liveLogBtn').onclick = startLiveLog); $('stopLiveLogBtn') && ($('stopLiveLogBtn').onclick = stopLiveLog);
  $('refreshRiskBtn') && ($('refreshRiskBtn').onclick = loadRisk); $('saveRiskControlsBtn') && ($('saveRiskControlsBtn').onclick = saveRiskControls); $('clearRiskCookieHealthBtn') && ($('clearRiskCookieHealthBtn').onclick = clearRiskCookieHealth);
  $('saveNotificationsBtn') && ($('saveNotificationsBtn').onclick = saveNotifications); $('reloadNotificationsBtn') && ($('reloadNotificationsBtn').onclick = loadNotifications);
  $('refreshUpdatesBtn') && ($('refreshUpdatesBtn').onclick = loadUpdates); $('checkUpdatesDryBtn') && ($('checkUpdatesDryBtn').onclick = () => checkUpdates(false)); $('checkUpdatesNetworkBtn') && ($('checkUpdatesNetworkBtn').onclick = () => checkUpdates(true));
  $('createFullBackupBtn') && ($('createFullBackupBtn').onclick = () => createBackup(true)); $('createConfigBackupBtn') && ($('createConfigBackupBtn').onclick = () => createBackup(false)); $('refreshBackupsBtn') && ($('refreshBackupsBtn').onclick = loadBackups);

  $('selectAllCookiesBtn') && ($('selectAllCookiesBtn').onclick = selectAllCookies); $('bulkDisableCookiesBtn') && ($('bulkDisableCookiesBtn').onclick = () => bulkCookie(true)); $('bulkEnableCookiesBtn') && ($('bulkEnableCookiesBtn').onclick = () => bulkCookie(false));
  $('clearCurrentLogBtn') && ($('clearCurrentLogBtn').onclick = () => clearLogs('')); $('clearAllLogsBtn') && ($('clearAllLogsBtn').onclick = () => clearLogs(''));
  $('testNotificationDryBtn') && ($('testNotificationDryBtn').onclick = () => testNotification(false)); $('testNotificationNetworkBtn') && ($('testNotificationNetworkBtn').onclick = () => testNotification(true));
  $('createAccessUserBtn') && ($('createAccessUserBtn').onclick = createAccessUser);
  $('restorePreviewBtn') && ($('restorePreviewBtn').onclick = () => restoreBackup(false)); $('restoreApplyBtn') && ($('restoreApplyBtn').onclick = () => restoreBackup(true));

  $('autoRefreshTasks').onchange = setupTaskTimer;
}
function setupTaskTimer() { clearInterval(state.taskTimer); if ($('autoRefreshTasks')?.checked) state.taskTimer = setInterval(() => { if (currentTab()==='tasks') loadTasks(); }, 3000); }

bindEvents(); setupTaskTimer(); connectEvents(); loadStatus();
