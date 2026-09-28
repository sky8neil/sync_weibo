// 双发小助手 — 设置页逻辑
const DEFAULTS = { serviceUrl: 'http://23.106.45.229:8788', token: '' };
const $ = (id) => document.getElementById(id);

function setStatus(text, cls) {
  const s = $('status');
  s.textContent = text;
  s.className = cls || '';
}

function load() {
  chrome.storage.sync.get(DEFAULTS, (c) => {
    $('serviceUrl').value = c.serviceUrl || '';
    $('token').value = c.token || '';
  });
}

function normalizeUrl(raw) {
  const u = new URL(raw.trim().replace(/\/+$/, ''));
  if (u.protocol !== 'http:' && u.protocol !== 'https:') throw new Error('协议必须是 http/https');
  return u.toString().replace(/\/+$/, '');
}

function save() {
  try {
    const url = normalizeUrl($('serviceUrl').value);
    chrome.storage.sync.set({ serviceUrl: url, token: $('token').value.trim() }, () => {
      setStatus('已保存 ✓', 'ok');
    });
  } catch (e) {
    setStatus('保存失败：' + e.message, 'err');
  }
}

async function test() {
  let url;
  try {
    url = normalizeUrl($('serviceUrl').value);
  } catch (e) {
    setStatus('服务地址无效：' + e.message, 'err');
    return;
  }
  const token = $('token').value.trim();
  if (!token) {
    setStatus('先填 token 再测试', 'err');
    return;
  }
  setStatus('测试中…（首次可能需要几秒）');
  try {
    const r = await fetch(url + '/status?token=' + encodeURIComponent(token));
    const j = await r.json();
    if (!j.ok) {
      setStatus('服务返回：' + (j.error || '未知错误'), 'err');
      return;
    }
    const f = j.fanfou || {};
    const a = j.akkoma || {};
    const t = j.twitter;
    const lines = [
      '连接成功 ✓',
      '· 饭否：' + (f.ok ? f.user + '（会话至 ' + (f.session_expires || '未知') + '）' : '✗ ' + (f.error || '异常')),
      '· Akkoma：' + (a && a.ok ? a.acct + '（' + a.url + '）' : (a ? '✗ ' + (a.error || '异常') : '未配置')),
      '· Twitter/X：' + (t && t.ok ? '已连接（' + (t.user || 'cookie 有效') + '）' : (t ? '✗ ' + (t.error || '异常') : '未配置')),
    ];
    if (j.limits) {
      lines.push('· 限制：图片最多 ' + j.limits.max_images_per_post + ' 张（≤'
        + Math.round(j.limits.per_image_limit_bytes / 1048576) + 'MB/张）；Akkoma 正文上限 '
        + j.limits.akkoma_max_chars + ' 字'
        + (j.limits.twitter_max_weight ? '；X 加权上限 ' + j.limits.twitter_max_weight : ''));
    }
    setStatus(lines.join('\n'), 'ok');
  } catch (e) {
    setStatus('连接失败：' + e.message, 'err');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  load();
  $('save').addEventListener('click', save);
  $('test').addEventListener('click', test);
});
