# -*- coding: utf-8 -*-
"""Chrome 154（最新稳定版）兼容性验证：加载扩展 + 全流程真发（测后清理）"""
import os
import shutil
import subprocess

os.environ['DISPLAY'] = ':1'
os.environ.setdefault('XAUTHORITY', '/root/.Xauthority')

from playwright.sync_api import sync_playwright  # noqa: E402

CFT = '/tmp/chrome-linux64/chrome'
EXT = '/home/fanfou-sender/extension'
EXT_ID = 'ibkamonleimnlfoojnnnhmcnaeebjiba'
UD = '/tmp/cft154-profile'
TOKEN = open('/home/fanfou-sender/state/service_token.txt').read().strip()
SHOTS = '/home/fanfou-sender/evidence'
shutil.rmtree(UD, ignore_errors=True)

v = subprocess.run([CFT, '--version'], capture_output=True, text=True)
print('浏览器版本:', (v.stdout or v.stderr).strip())

ak_url = tw_url = None
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        UD, headless=False, executable_path=CFT,
        args=[f'--disable-extensions-except={EXT}', f'--load-extension={EXT}',
              '--no-sandbox', '--disable-dev-shm-usage',
              '--enable-unsafe-extension-debugging'],
        viewport={'width': 460, 'height': 1080},
    )
    page = ctx.new_page()
    logs = []
    page.on('console', lambda m: logs.append(f'[{m.type}] {m.text[:140]}'))
    page.on('pageerror', lambda e: logs.append(f'[pageerror] {str(e)[:180]}'))
    page.goto(f'chrome-extension://{EXT_ID}/popup.html', timeout=60000)
    page.wait_for_timeout(2000)
    print('扩展弹窗标题:', page.title())
    print('显式加载成功: 双发小助手' if '双发小助手' in page.title() else '⚠ 扩展可能未加载')

    page.evaluate("(c) => new Promise(r => chrome.storage.sync.set(c, r))",
                  {'serviceUrl': 'http://127.0.0.1:8788', 'token': TOKEN})
    page.reload()
    page.wait_for_timeout(3000)
    lim = page.evaluate("() => LIMITS")
    print('限制加载:', '成功' if lim.get('akkoma_max_chars') else '失败', '| X 权重:', lim.get('twitter_max_weight'))

    page.fill('#msg', '【通道测试】Chrome 154 最新版兼容性验证（稍后自动删除）')
    page.set_input_files('#file', '/tmp/akk_media/big.jpg')
    page.wait_for_selector('.thumb', timeout=30000)
    page.wait_for_timeout(800)
    print('图片压缩:', page.inner_text('#imgInfo'))

    page.click('#sendAkTw')
    page.wait_for_function(
        "() => ['success','error'].includes(document.getElementById('statusbar').className)",
        timeout=180000)
    page.wait_for_timeout(600)
    print('状态条:', page.inner_text('#statusbar').replace('\n', ' / '))
    links = page.eval_on_selector_all('#statusbar a', 'els => els.map(e => e.href)')
    ak_url = next((u for u in links if 'akkoma' in u), None)
    tw_url = next((u for u in links if 'x.com' in u), None)
    print('AK:', ak_url, '| TW:', tw_url)
    notifs = page.evaluate("() => new Promise(r => chrome.notifications.getAll(n => r(Object.keys(n))))")
    print('系统通知:', notifs)
    page.screenshot(path=f'{SHOTS}/popup_chrome154.png')
    print('截图: popup_chrome154.png')
    print('控制台:', logs[-8:] if logs else '（无）')
    ctx.close()

# ---- 清理本条测试（不保留）----
print()
print('== 清理 Chrome154 测试帖 ==')
import sys  # noqa: E402
sys.path.insert(0, '/home/fanfou-sender')
import requests  # noqa: E402
AKH = {'Authorization': 'Bearer ' + open('/home/fanfou-sender/state/akkoma_token.txt').read().strip()}
if ak_url:
    sid = ak_url.rsplit('/', 1)[-1]
    r = requests.delete('https://akkoma.skyneil.net/api/v1/statuses/' + sid, headers=AKH, timeout=30)
    print('  akkoma del', sid, r.status_code)
if tw_url:
    tid = tw_url.rsplit('/', 1)[-1]
    r = subprocess.run(['/home/fanfou-sender/.venv-tw/bin/python',
                        '/home/fanfou-sender/twitter_sender.py', 'delete', tid],
                       capture_output=True, text=True, timeout=120)
    print('  twitter del', tid, r.returncode)
print('DONE')
