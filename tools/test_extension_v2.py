# -*- coding: utf-8 -*-
"""双发小助手 v2 端到端测试（Playwright + 真服务 + 真 Akkoma）
覆盖：字数统计 / 标签## / 图片压缩 / 状态条 / 系统通知 / 关闭弹窗后台发送 / 错误日志
"""
import os
import shutil
import time

os.environ['DISPLAY'] = ':1'
os.environ.setdefault('XAUTHORITY', '/root/.Xauthority')

from playwright.sync_api import sync_playwright  # noqa: E402
import requests  # noqa: E402

EXT = '/home/fanfou-sender/extension'
EXT_ID = 'ibkamonleimnlfoojnnnhmcnaeebjiba'
UD = '/tmp/ext-tw-test-v2'
TOKEN = open('/home/fanfou-sender/state/service_token.txt').read().strip()
SHOTS = '/home/fanfou-sender/evidence'
AKH = {'Authorization': 'Bearer ' + open('/home/fanfou-sender/state/akkoma_token.txt').read().strip()}
AK = 'https://akkoma.skyneil.net'


def log(*a):
    print(*a, flush=True)


shutil.rmtree(UD, ignore_errors=True)
created_posts = []

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        UD, headless=False,
        executable_path='/usr/bin/chromium',
        args=[f'--disable-extensions-except={EXT}', f'--load-extension={EXT}',
              '--no-sandbox', '--disable-dev-shm-usage'],
        viewport={'width': 420, 'height': 900},
    )
    page = ctx.new_page()
    logs = []
    page.on('console', lambda m: logs.append(f'[{m.type}] {m.text[:160]}'))
    page.on('pageerror', lambda e: logs.append(f'[pageerror] {str(e)[:200]}'))
    page.goto(f'chrome-extension://{EXT_ID}/popup.html')
    page.wait_for_timeout(1500)

    # ---------- 0) 配置 ----------
    page.evaluate("(c) => new Promise(r => chrome.storage.sync.set(c, r))",
                  {'serviceUrl': 'http://127.0.0.1:8788', 'token': TOKEN})
    page.reload()
    page.wait_for_timeout(3000)
    lim = page.evaluate("() => LIMITS")
    log('0) 限制加载:', lim)

    # ---------- 1) 实时字数 ----------
    try:
        page.fill('#msg', '你好世界')
        page.wait_for_timeout(300)
        log('1a) 4字:', page.inner_text('#counter'), '| class=', page.get_attribute('#counter', 'class'))
        page.fill('#msg', '超' * 150)
        page.wait_for_timeout(300)
        log('1b) 150字:', page.inner_text('#counter'), '| class=', page.get_attribute('#counter', 'class'),
            '| hint=', page.inner_text('#counterHint'))
        page.fill('#msg', '')
    except Exception as e:
        log('1) 字数测试异常:', e)

    # ---------- 2) 标签 ## ----------
    try:
        page.fill('#tags', '插件功能测试标签 日常')
        page.click('#tagBtn')
        page.wait_for_timeout(300)
        log('2) ## 后的正文:', repr(page.input_value('#msg')[:80]))
    except Exception as e:
        log('2) 标签测试异常:', e)

    # ---------- 3) 图片添加 + 压缩 ----------
    try:
        page.set_input_files('#file', ['/tmp/akk_media/big.jpg', '/tmp/akk_media/big2.jpg'])
        page.wait_for_selector('.thumb', timeout=30000)
        page.wait_for_timeout(1200)
        log('3a) 缩略图数:', page.eval_on_selector_all('.thumb', 'els => els.length'))
        log('3b) imgInfo:', page.inner_text('#imgInfo'))
        meta = page.evaluate("() => images.map(i => ({name: i.name, kb: i.sizeKB, mime: i.mime}))")
        log('3c) 压缩结果:', meta)
        log('3d) 原图大小: big.jpg', os.path.getsize('/tmp/akk_media/big.jpg') // 1024,
            'KB / big2.jpg', os.path.getsize('/tmp/akk_media/big2.jpg') // 1024, 'KB')
    except Exception as e:
        log('3) 图片测试异常:', e)

    # ---------- 4) 发送到 Akkoma（带图 + 标签）----------
    try:
        page.click('#sendAkkoma')
        page.wait_for_function("() => document.getElementById('statusbar').className === 'success' || document.getElementById('statusbar').className === 'error'", timeout=120000)
        page.wait_for_timeout(500)
        log('4a) 状态条:', page.inner_text('#statusbar').replace('\n', ' / '))
        href = page.eval_on_selector('#statusbar a', 'a => a && a.href')
        log('4b) 帖子链接:', href)
        if href:
            created_posts.append(href.rsplit('/', 1)[-1])
        page.screenshot(path=f'{SHOTS}/popup_v2_features.png')
        log('4c) 截图: popup_v2_features.png')
    except Exception as e:
        log('4) 发送测试异常:', e)

    # ---------- 5) 系统通知 ----------
    try:
        notifs = page.evaluate("() => new Promise(r => chrome.notifications.getAll(n => r(Object.keys(n))))")
        log('5) 通知列表:', notifs)
    except Exception as e:
        log('5) 通知检查异常:', e)

    # ---------- 6) 关闭弹窗，后台继续发送 ----------
    try:
        page.fill('#msg', '【插件功能测试】关闭弹窗场景：后台继续发送。')
        page.fill('#tags', '')
        page.click('#sendAkkoma')
        page.wait_for_timeout(400)
        page.close()
        log('6a) 弹窗已关闭，等待后台发送完成…')
        time.sleep(18)
        page2 = ctx.new_page()
        page2.goto(f'chrome-extension://{EXT_ID}/popup.html')
        page2.wait_for_timeout(3000)
        log('6b) 重开后状态条:', page2.inner_text('#statusbar').replace('\n', ' / '))
        logcount = page2.evaluate("() => new Promise(r => chrome.runtime.sendMessage({type:'getLog'}, resp => r((resp&&resp.log||[]).length)))")
        log('6c) 日志条数:', logcount)
        notifs2 = page2.evaluate("() => new Promise(r => chrome.notifications.getAll(n => r(Object.keys(n))))")
        log('6d) 通知:', notifs2)
        page2.screenshot(path=f'{SHOTS}/popup_v2_reopened.png')
        # 找到该帖 id（按内容扫）
        me = requests.get(AK + '/api/v1/accounts/verify_credentials', headers=AKH, timeout=30).json()
        sts = requests.get(AK + "/api/v1/accounts/%s/statuses?limit=10" % me['id'], headers=AKH, timeout=30).json()
        for s in sts:
            c = (s.get('content') or '')
            if '关闭弹窗场景' in c:
                created_posts.append(s['id'])
        log('6e) 已记录待清理帖子:', created_posts)
    except Exception as e:
        log('6) 关窗测试异常:', e)

    # ---------- 7) 错误场景 + 日志 ----------
    try:
        page2.evaluate("(c) => new Promise(r => chrome.storage.sync.set(c, r))",
                       {'serviceUrl': 'http://127.0.0.1:8788', 'token': 'WRONG-TOKEN'})
        page2.reload()
        page2.wait_for_timeout(2500)
        page2.fill('#msg', '【插件功能测试】错误场景（token 错误）')
        page2.click('#sendFanfou')
        page2.wait_for_function("() => document.getElementById('statusbar').className === 'error'", timeout=60000)
        page2.wait_for_timeout(500)
        log('7a) 错误状态条:', page2.inner_text('#statusbar').replace('\n', ' / ')[:160])
        logrow = page2.eval_on_selector('#log .item', 'el => el && el.innerText')
        log('7b) 日志首条:', (logrow or '')[:150])
        notifs3 = page2.evaluate("() => new Promise(r => chrome.notifications.getAll(n => r(Object.keys(n))))")
        log('7c) 错误通知存在:', notifs3)
        page2.screenshot(path=f'{SHOTS}/popup_v2_error.png')
        log('7d) 截图: popup_v2_error.png')
        # 恢复正确 token
        page2.evaluate("(c) => new Promise(r => chrome.storage.sync.set(c, r))",
                       {'serviceUrl': 'http://127.0.0.1:8788', 'token': TOKEN})
    except Exception as e:
        log('7) 错误场景测试异常:', e)

    # 浏览器日志
    log('=== 浏览器控制台（最后 12 条）===')
    for line in logs[-12:]:
        log(' ', line)

    ctx.close()

# ---------- 清理 ----------
log('=== 清理 Akkoma 测试帖 ===')
for sid in created_posts:
    r = requests.delete(AK + '/api/v1/statuses/' + sid, headers=AKH, timeout=30)
    log('  del', sid, r.status_code)
me = requests.get(AK + '/api/v1/accounts/verify_credentials', headers=AKH, timeout=30).json()
sts = requests.get(AK + "/api/v1/accounts/%s/statuses?limit=10" % me['id'], headers=AKH, timeout=30).json()
log('账号剩余帖子数:', len(sts))
for s in sts:
    log(' -', s['id'], (s.get('content') or '')[:40].replace('<p>', ''))
log('DONE')
