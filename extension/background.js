// 双发小助手 — 后台 Service Worker
// 职责：真正执行发送（弹窗关闭也继续）、系统通知（chrome.notifications）、错误日志持久化
const DEFAULTS = { serviceUrl: 'http://23.106.45.229:8788', token: '' };
const NOTIF_ID = 'multipost-status';
let sending = false;
const queue = [];

// ---------- 基础工具 ----------
function getConfig() {
  return new Promise((resolve) => chrome.storage.sync.get(DEFAULTS, resolve));
}
async function getLog() {
  const { log } = await chrome.storage.local.get({ log: [] });
  return log;
}
async function pushLog(entry) {
  const log = await getLog();
  log.unshift(entry);
  await chrome.storage.local.set({ log: log.slice(0, 20) });
}
async function setState(st) {
  const state = { ...st, ts: Date.now() };
  await chrome.storage.local.set({ lastState: state });
  broadcast({ type: 'update', state });
}
function broadcast(msg) {
  try {
    chrome.runtime.sendMessage(msg, () => void chrome.runtime.lastError);
  } catch (e) {
    // 弹窗未打开：正常情况
  }
}

// ---------- 系统通知 ----------
function notify(title, message, sticky) {
  const opts = {
    type: 'basic',
    iconUrl: 'icons/icon128.png',
    title,
    message: String(message || '').slice(0, 240),
    requireInteraction: !!sticky,
    priority: sticky ? 2 : 0,
  };
  return new Promise((resolve) => {
    try {
      chrome.notifications.create(NOTIF_ID, opts, () => {
        resolve(chrome.runtime.lastError ? String(chrome.runtime.lastError.message || '') : null);
      });
    } catch (e) {
      resolve(String(e));
    }
  });
}
function clearNotif() {
  try { chrome.notifications.clear(NOTIF_ID, () => void chrome.runtime.lastError); } catch (e) { /* ignore */ }
}
chrome.notifications.onClicked.addListener(() => clearNotif());

// ---------- 发送 ----------
function summarize(resp) {
  const parts = [];
  const res = resp.results || {};
  if (res.fanfou) parts.push('饭否 ' + (res.fanfou.ok ? '✓' : '✗'));
  if (res.akkoma) parts.push('Akkoma ' + (res.akkoma.ok ? '✓' : '✗'));
  if (res.twitter) parts.push('Twitter ' + (res.twitter.ok ? '✓' : '✗'));
  return parts.join(' + ') || (resp.error || '未知');
}

async function doSend(payload) {
  const cfg = await getConfig();
  if (!cfg.token) throw new Error('未配置 token（点插件右下角「设置」）');
  const url = String(cfg.serviceUrl || '').replace(/\/+$/, '') + '/send';
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Token': cfg.token },
    body: JSON.stringify({ ...payload, token: cfg.token }),
  });
  let j = null;
  try { j = await r.json(); } catch (e) { /* 非 JSON */ }
  if (!j) throw new Error('服务响应异常（HTTP ' + r.status + '）');
  return { httpStatus: r.status, resp: j };
}

async function handleOne(payload) {
  const target = payload.to || 'fanfou';
  await setState({ status: 'sending', target, textPreview: (payload.text || '').slice(0, 60) });
  await notify('双发小助手', '⏳ 发送中…（' + target + '）', false);
  let entry;
  try {
    const { httpStatus, resp } = await doSend(payload);
    const ok = !!resp.ok;
    const summary = summarize(resp);
    entry = {
      ts: Date.now(), ok, target: resp.target || target, httpStatus, summary,
      textPreview: (payload.text || '').slice(0, 80),
      images: (payload.images || []).length,
      results: resp.results || null,
      warnings: resp.warnings || null,
      error: ok ? null : (resp.error || '部分/全部失败：' + summary),
    };
    if (ok) {
      const extra = resp.warnings && resp.warnings.length ? '（' + resp.warnings.join('；') + '）' : '';
      await notify('双发小助手', '✓ 发送成功：' + summary + extra, false);
    } else {
      const detail = resp.error || JSON.stringify(resp.results || {}).slice(0, 200);
      await notify('⚠️ 发送出错', summary + ' — ' + String(detail), true);
    }
    await setState({ status: ok ? 'success' : 'error', target: entry.target, summary, entry });
  } catch (e) {
    const msg = String((e && e.message) || e);
    entry = {
      ts: Date.now(), ok: false, target, httpStatus: null, summary: '网络/服务错误',
      textPreview: (payload.text || '').slice(0, 80), images: (payload.images || []).length,
      error: msg,
    };
    await notify('⚠️ 发送出错', msg, true);
    await setState({ status: 'error', target, summary: '网络/服务错误', entry });
  }
  await pushLog(entry);
  return entry;
}

async function pump() {
  if (sending || !queue.length) return;
  sending = true;
  try {
    while (queue.length) {
      await handleOne(queue.shift());
    }
  } finally {
    sending = false;
  }
}

// ---------- 消息接口 ----------
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    try {
      if (msg && msg.type === 'send') {
        queue.push(msg.payload);
        pump();
        sendResponse({ accepted: true, queued: queue.length });
        return;
      }
      if (msg && msg.type === 'getState') {
        const { lastState } = await chrome.storage.local.get({ lastState: null });
        sendResponse({ state: lastState });
        return;
      }
      if (msg && msg.type === 'getLog') {
        sendResponse({ log: await getLog() });
        return;
      }
      if (msg && msg.type === 'clearLog') {
        await chrome.storage.local.set({ log: [] });
        sendResponse({ ok: true });
        return;
      }
      sendResponse({ error: 'unknown message' });
    } catch (e) {
      sendResponse({ error: String((e && e.message) || e) });
    }
  })();
  return true;
});

console.log('双发小助手后台已就绪');
