# -*- coding: utf-8 -*-
"""插件 v0.3 测试：发 Twitter 按钮 + 字数提示（真链接真账号）"""
import os
import shutil
import subprocess

os.environ['DISPLAY'] = ':1'
os.environ.setdefault('XAUTHORITY', '/root/.Xauthority')

from playwright.sync_api import sync_playwright  # noqa: E402

EXT = '/home/fanfou-sender/extension'
EXT_ID = 'ibkamonleimnlfoojnnnhmcnaeebjiba'
UD = '/tmp/ext-tw-test-v4'
TOKEN = open('/home/fanfou-sender/state/service_token.txt').read().strip()
SHOTS = '/home/fanfou-sender/evidence'
shutil.rmtree(UD, ignore_errors=True)

tid = None
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        UD, headless=False, executable_path='/usr/bin/chromium',
        args=[f'--disable-extensions-except={EXT}', f'--load-extension={EXT}',
              '--no-sandbox', '--disable-dev-shm-usage'],
        viewport={'width': 460, 'height': 1050},
    )
    page = ctx.new_page()
    logs = []
    page.on('console', lambda m: logs.append(f'[{m.type}] {m.text[:120]}'))
    page.on('pageerror', lambda e: logs.append(f'[pageerror] {str(e)[:160]}'))
    page.goto(f'chrome-extension://{EXT_ID}/popup.html')
    page.wait_for_timeout(1200)
    page.evaluate("(c) => new Promise(r => chrome.storage.sync.set(c, r))",
                  {'serviceUrl': 'http://127.0.0.1:8788', 'token': TOKEN})
    page.reload()
    page.wait_for_timeout(2500)

    print('按钮存在:', page.evaluate("() => ['sendFanfou','sendAkkoma','sendTwitter','sendAll'].map(id => !!document.getElementById(id))"))

    page.fill('#msg', '测' * 141)
    page.wait_for_timeout(300)
    print('141字提示:', page.inner_text('#counterHint'), '| class:', page.get_attribute('#counter', 'class'))
    page.fill('#msg', '')

    page.fill('#msg', '【通道测试】插件 · 发 Twitter 按钮联调（稍后自动删除）')
    page.wait_for_timeout(300)
    page.screenshot(path=f'{SHOTS}/popup_v3_filled.png')
    page.click('#sendTwitter')
    page.wait_for_function("() => ['success','error'].includes(document.getElementById('statusbar').className)", timeout=150000)
    page.wait_for_timeout(500)
    print('状态条:', page.inner_text('#statusbar').replace('\n', ' / '))
    href = page.eval_on_selector('#statusbar a', 'a => a && a.href')
    print('推文链接:', href)
    tid = href.rsplit('/', 1)[-1] if href else None
    page.screenshot(path=f'{SHOTS}/popup_v3_success.png')
    print('日志首条:', page.eval_on_selector('#log .item', 'el => el && el.innerText'))
    print('控制台:', logs[-6:] if logs else '（无）')
    ctx.close()

if tid:
    r = subprocess.run(['/home/fanfou-sender/.venv-tw/bin/python',
                        '/home/fanfou-sender/twitter_sender.py', 'delete', tid],
                       capture_output=True, text=True, timeout=120)
    print('删除测试推:', r.returncode, (r.stdout or r.stderr).strip()[:120])
print('DONE')
