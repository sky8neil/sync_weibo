// 双发小助手 — popup 逻辑
// 功能：实时字数、标签（## 插入）、图片（压缩 webp ≤2MB）、发送状态条、日志、设置
const DEFAULTS = { serviceUrl: 'http://23.106.45.229:8788', token: '' };
const FALLBACK_LIMITS = {
  fanfou_max_chars: 140,
  fanfou_max_images: 1,
  akkoma_max_chars: 5000,
  max_images_per_post: 16,
  per_image_limit_bytes: 2097152,
  image_mimes: ['image/webp', 'image/jpeg', 'image/png', 'image/gif'],
};
const $ = (id) => document.getElementById(id);
let LIMITS = { ...FALLBACK_LIMITS };
let images = []; // {name, mime, data(b64), sizeKB, thumb}
let busy = false;

function getConfig() {
  return new Promise((r) => chrome.storage.sync.get(DEFAULTS, r));
}
function bg(msg) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(msg, (resp) => {
      if (chrome.runtime.lastError) resolve(null);
      else resolve(resp);
    });
  });
}
function setBtns(disabled) {
  ['sendFanfou', 'sendAkkoma', 'sendTwitter', 'sendAkTw', 'sendAll'].forEach((id) => { $(id).disabled = disabled; });
}

// ---------- 实时字数 ----------
function twitterWeight(str) {
  let w = 0;
  for (const ch of str) {
    const o = ch.codePointAt(0);
    if ((o >= 0x1100 && o <= 0x115f) || (o >= 0x2e80 && o <= 0xa4cf) || (o >= 0xac00 && o <= 0xd7a3)
        || (o >= 0xf900 && o <= 0xfaff) || (o >= 0xfe30 && o <= 0xfe4f) || (o >= 0xff00 && o <= 0xff60)
        || (o >= 0xffe0 && o <= 0xffe6) || (o >= 0x1f000 && o <= 0x1faff) || (o >= 0x20000 && o <= 0x3fffd)) {
      w += 2;
    } else {
      w += 1;
    }
  }
  return w;
}
function effectiveTwitterText(v) {
  const tags = parseTags($('tags').value);
  const missing = tags.filter((t) => !v.includes('#' + t));
  if (!missing.length) return v;
  const sep = v.includes('\n') ? '\n\n' : ' ';
  return v + sep + missing.map((t) => '#' + t).join(' ');
}
function updateCounter() {
  const v = $('msg').value;
  const n = Array.from(v).length;
  const tw = twitterWeight(effectiveTwitterText(v));
  const twMax = LIMITS.twitter_max_weight || 280;
  const el = $('counter');
  const hint = $('counterHint');
  el.textContent = n + ' 字';
  const hints = [];
  let level = '';
  if (n > LIMITS.akkoma_max_chars) {
    level = 'over';
    hints.push('超 Akkoma 上限 ' + LIMITS.akkoma_max_chars);
  }
  if (n > LIMITS.fanfou_max_chars) {
    if (!level) level = 'warn';
    hints.push('饭否将截断(' + LIMITS.fanfou_max_chars + ')');
  }
  if (tw > twMax) {
    if (!level) level = 'warn';
    hints.push('X 超限(' + tw + '/' + twMax + '，中文约 ' + Math.floor(twMax / 2) + ' 字)');
  }
  el.className = level;
  hint.textContent = hints.join('；');
}
$('msg').addEventListener('input', updateCounter);
$('tags').addEventListener('input', updateCounter);

// ---------- 标签 ## ----------
function parseTags(str) {
  return (str || '')
    .split(/[,，#\s]+/)
    .map((t) => t.trim())
    .filter(Boolean)
    .slice(0, 30);
}
$('tagBtn').addEventListener('click', () => {
  const tags = parseTags($('tags').value);
  if (!tags.length) {
    flashStatus('先在标签框输入标签，再点 ##', 'error');
    $('tags').focus();
    return;
  }
  const ta = $('msg');
  const add = tags.map((t) => '#' + t).join(' ');
  ta.value = ta.value.trim() ? ta.value.replace(/\s+$/, '') + '\n\n' + add : add;
  updateCounter();
  ta.focus();
});

// ---------- 图片：压缩为 webp（≤2MB/张）----------
async function compressImage(file, maxBytes) {
  const bitmap = await createImageBitmap(file);
  const stages = [2560, 1920, 1440, 1080];
  const quals = [0.85, 0.75, 0.65, 0.55, 0.45];
  for (const maxDim of stages) {
    let w = bitmap.width;
    let h = bitmap.height;
    const s = Math.min(1, maxDim / Math.max(w, h));
    w = Math.max(1, Math.round(w * s));
    h = Math.max(1, Math.round(h * s));
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    canvas.getContext('2d').drawImage(bitmap, 0, 0, w, h);
    for (const q of quals) {
      const blob = await new Promise((r) => canvas.toBlob(r, 'image/webp', q));
      if (blob && blob.size <= maxBytes) return blob;
    }
  }
  throw new Error('压缩后仍超 ' + Math.round(maxBytes / 1048576) + 'MB');
}
function blobToB64(blob) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result).split(',')[1]);
    fr.onerror = reject;
    fr.readAsDataURL(blob);
  });
}

$('addImg').addEventListener('click', () => $('file').click());
$('file').addEventListener('change', async (e) => {
  const files = Array.from(e.target.files || []);
  e.target.value = '';
  for (const f of files) {
    if (images.length >= LIMITS.max_images_per_post) {
      flashStatus('最多 ' + LIMITS.max_images_per_post + ' 张图（Akkoma 实测上限）', 'error');
      break;
    }
    try {
      const blob = await compressImage(f, LIMITS.per_image_limit_bytes);
      const data = await blobToB64(blob);
      const name = f.name.replace(/\.[^.]+$/, '') + '.webp';
      images.push({
        name, mime: 'image/webp', data,
        sizeKB: Math.round(blob.size / 1024),
        thumb: URL.createObjectURL(blob),
      });
    } catch (err) {
      flashStatus('图片处理失败：' + f.name + ' — ' + (err.message || err), 'error');
    }
  }
  renderThumbs();
});

function renderThumbs() {
  const box = $('thumbs');
  box.textContent = '';
  images.forEach((im, i) => {
    const d = document.createElement('div');
    d.className = 'thumb';
    const img = document.createElement('img');
    img.src = im.thumb;
    d.appendChild(img);
    const sz = document.createElement('div');
    sz.className = 'sz';
    sz.textContent = im.sizeKB + 'K';
    d.appendChild(sz);
    const x = document.createElement('div');
    x.className = 'x';
    x.textContent = '✕';
    x.addEventListener('click', () => {
      images.splice(i, 1);
      renderThumbs();
    });
    d.appendChild(x);
    box.appendChild(d);
  });
  const total = images.reduce((a, b) => a + b.sizeKB, 0);
  let info = images.length
    ? images.length + ' 张 · 共 ' + (total / 1024).toFixed(1) + 'MB · webp'
    : '配图：饭否 1 / Akkoma 16 / X 4 张 · 自动压 webp ≤2MB';
  if (images.length >= 2) info += '（第1张→饭否，其余→Akkoma/X）';
  $('imgInfo').textContent = info;
}

// ---------- 状态条 ----------
function flashStatus(msg, cls) {
  const bar = $('statusbar');
  bar.className = cls || '';
  bar.textContent = msg;
}
function renderStatus(state) {
  const bar = $('statusbar');
  bar.textContent = '';
  if (!state) {
    bar.className = '';
    bar.textContent = '待发送';
    return;
  }
  if (state.status === 'sending') {
    bar.className = 'sending';
    bar.textContent = '⏳ 发送中…（' + (state.target || '') + '）';
    return;
  }
  const e = state.entry || {};
  const res = e.results || {};
  const main = document.createElement('div');
  const sub = document.createElement('div');
  sub.className = 'sub';
  if (state.status === 'success') {
    bar.className = 'success';
    main.textContent = '✓ 发送成功';
  } else {
    bar.className = 'error';
    main.textContent = '✗ 发送失败' + (e.summary ? '（' + e.summary + '）' : '');
  }
  // 详细行：各平台结果
  const addBit = (text) => {
    if (sub.childNodes.length) sub.appendChild(document.createTextNode(' ｜ '));
    sub.appendChild(document.createTextNode(text));
  };
  if (res.fanfou) {
    if (res.fanfou.ok) addBit('饭否 ✓' + (res.fanfou.media_count ? '（1 图）' : '') + (res.fanfou.truncated ? '（已截断）' : ''));
    else addBit('饭否 ✗ ' + String(res.fanfou.error || '').slice(0, 90));
  }
  if (res.akkoma) {
    if (res.akkoma.ok) {
      addBit('Akkoma ✓' + (res.akkoma.media_count ? '（' + res.akkoma.media_count + ' 图）' : ''));
      if (res.akkoma.url) {
        const a = document.createElement('a');
        a.href = res.akkoma.url;
        a.target = '_blank';
        a.textContent = '查看';
        sub.appendChild(document.createTextNode(' '));
        sub.appendChild(a);
      }
    } else {
      addBit('Akkoma ✗ ' + String(res.akkoma.error || '').slice(0, 90));
    }
  }
  if (res.twitter) {
    if (res.twitter.ok) {
      addBit('Twitter ✓');
      if (res.twitter.url) {
        const a = document.createElement('a');
        a.href = res.twitter.url;
        a.target = '_blank';
        a.textContent = '查看';
        sub.appendChild(document.createTextNode(' '));
        sub.appendChild(a);
      }
    } else {
      addBit('Twitter ✗ ' + String(res.twitter.error || '').slice(0, 90));
    }
  }
  if (!sub.childNodes.length && e.error) {
    sub.textContent = String(e.error).slice(0, 180);
  }
  if (!sub.childNodes.length && e.summary) {
    sub.textContent = e.summary;
  }
  bar.appendChild(main);
  if (sub.childNodes.length || sub.textContent) bar.appendChild(sub);
}

// ---------- 日志 ----------
function fmtTime(ts) {
  const d = new Date(ts);
  const p = (n) => String(n).padStart(2, '0');
  return p(d.getHours()) + ':' + p(d.getMinutes());
}
function renderLog(log) {
  const box = $('log');
  box.textContent = '';
  if (!log || !log.length) {
    const d = document.createElement('div');
    d.className = 'hint';
    d.textContent = '暂无记录';
    box.appendChild(d);
    return;
  }
  log.forEach((e) => {
    const d = document.createElement('div');
    d.className = 'item';
    const t = document.createElement('span');
    t.className = 'time';
    t.textContent = fmtTime(e.ts);
    const m = document.createElement('span');
    m.className = e.ok ? 'ok' : 'bad';
    let text = (e.summary || '') + (e.images ? '（' + e.images + ' 图）' : '');
    if (!e.ok && e.error) text += ' — ' + String(e.error).slice(0, 140);
    m.textContent = text;
    d.appendChild(t);
    d.appendChild(m);
    box.appendChild(d);
  });
}

// ---------- 发送 ----------
async function send(to) {
  if (busy) return;
  const text = $('msg').value.trim();
  const tags = parseTags($('tags').value);
  if (!text && !images.length) {
    flashStatus('先写点内容或加张图片', 'error');
    return;
  }
  const cfg = await getConfig();
  if (!cfg.token) {
    flashStatus('还没配置 token → 点右下角「设置」', 'error');
    return;
  }
  const payload = {
    text,
    to,
    tags,
    images: images.map((im) => ({ name: im.name, mime: im.mime, data: im.data })),
  };
  busy = true;
  setBtns(true);
  flashStatus('⏳ 发送中…（' + to + '）', 'sending');
  const resp = await bg({ type: 'send', payload });
  if (!resp || !resp.accepted) {
    flashStatus('发送请求未被接收：' + ((resp && resp.error) || '后台无响应'), 'error');
    busy = false;
    setBtns(false);
  }
}

// ---------- 初始化 ----------
document.addEventListener('DOMContentLoaded', async () => {
  updateCounter();
  renderThumbs();

  $('openOptions').addEventListener('click', (e) => {
    e.preventDefault();
    chrome.runtime.openOptionsPage();
  });
  $('clearLog').addEventListener('click', async () => {
    await bg({ type: 'clearLog' });
    renderLog([]);
  });
  $('sendFanfou').addEventListener('click', () => send('fanfou'));
  $('sendAkkoma').addEventListener('click', () => send('akkoma'));
  $('sendTwitter').addEventListener('click', () => send('twitter'));
  $('sendAkTw').addEventListener('click', () => send('akkoma,twitter'));
  $('sendAll').addEventListener('click', () => send('all'));

  // 配置提示
  const cfg = await getConfig();
  try {
    const u = new URL(cfg.serviceUrl);
    $('cfgHint').textContent = '→ ' + u.host + (cfg.token ? '' : '（未配 token）');
  } catch (e) {
    $('cfgHint').textContent = '服务地址无效，请设置';
  }

  // 拉取平台限制（失败用默认值）
  if (cfg.token) {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 8000);
      const r = await fetch(cfg.serviceUrl.replace(/\/+$/, '') + '/status?token=' + encodeURIComponent(cfg.token), { signal: ctrl.signal });
      const j = await r.json();
      clearTimeout(t);
      if (j && j.limits) {
        LIMITS = { ...FALLBACK_LIMITS, ...j.limits };
        updateCounter();
        renderThumbs();
      }
    } catch (e) {
      // 用默认限制
    }
  }

  // 历史状态 / 日志
  const st = await bg({ type: 'getState' });
  if (st && st.state) renderStatus(st.state);
  const lg = await bg({ type: 'getLog' });
  renderLog(lg && lg.log);

  // 实时更新（发送过程中 / 关闭重开后）
  chrome.runtime.onMessage.addListener((msg) => {
    if (!msg || msg.type !== 'update' || !msg.state) return;
    renderStatus(msg.state);
    if (msg.state.status === 'success') {
      $('msg').value = '';
      $('tags').value = '';
      images = [];
      renderThumbs();
      updateCounter();
    }
    if (msg.state.status === 'success' || msg.state.status === 'error') {
      busy = false;
      setBtns(false);
    }
    bg({ type: 'getLog' }).then((r) => renderLog(r && r.log));
  });
});
