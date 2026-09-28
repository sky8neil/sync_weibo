# -*- coding: utf-8 -*-
"""真浏览器加载扩展的端到端测试：
1) 混合内容探针：从扩展页面 fetch http://23.106.45.229:5000/（在 host_permissions 白名单）
2) 配置指向本地服务（127.0.0.1:8788），点「同时发」→ 真实发送
3) 截图保存
"""
import os
import shutil
import time

os.environ['DISPLAY'] = ':1'
os.environ.setdefault('XAUTHORITY', '/root/.Xauthority')

from playwright.sync_api import sync_playwright  # noqa: E402

EXT = '/home/fanfou-sender/extension'
EXT_ID = 'ibkamonleimnlfoojnnnhmcnaeebjiba'  # manifest 的 key 固定了这个 ID
UD = '/tmp/ext-profile-test'
shutil.rmtree(UD, ignore_errors=True)

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        UD, headless=False,
        executable_path='/usr/bin/chromium',
        args=[f'--disable-extensions-except={EXT}', f'--load-extension={EXT}',
              '--no-sandbox', '--disable-dev-shm-usage'],
        viewport={'width': 420, 'height': 640},
    )
    ext_id = None
    deadline = time.time() + 20
    while time.time() < deadline and not ext_id:
        for w in ctx.service_workers:
            if w.url.startswith('chrome-extension://'):
                ext_id = w.url.split('/')[2]
                break
        if not ext_id:
            time.sleep(0.5)
    print('extension id:', ext_id)
    assert ext_id, 'extension id not found within 20s'

    page = ctx.new_page()
    logs = []
    page.on('console', lambda m: logs.append(f'[console:{m.type}] {m.text}'))
    page.on('pageerror', lambda e: logs.append(f'[pageerror] {e}'))

    page.goto(f'chrome-extension://{ext_id}/popup.html')
    page.wait_for_timeout(600)

    # 1) 混合内容探针（docker-registry 的 /v2/ 会返回 401，但有响应就说明请求没被拦）
    probe = page.evaluate("""async () => {
      try {
        const r = await fetch('http://23.106.45.229:5000/v2/');
        return 'got response, status=' + r.status;
      } catch (e) {
        return 'ERROR: ' + e.message;
      }
    }""")
    print('probe http://23.106.45.229:5000/v2/ →', probe)

    # 2) 写入配置：指向本地服务
    token = open('/home/fanfou-sender/state/service_token.txt').read().strip()
    page.evaluate(
        "(cfg) => new Promise(r => chrome.storage.sync.set(cfg, r))",
        {'serviceUrl': 'http://127.0.0.1:8788', 'token': token},
    )
    page.reload()
    page.wait_for_timeout(800)
    print('cfgHint:', page.inner_text('#cfgHint'))

    # 3) 输入 + 点「同时发」
    page.fill('#msg', '【插件测试】来自 Chrome 扩展「双发小助手」的测试消息（稍后清理）。')
    page.click('#sendBoth')
    page.wait_for_timeout(12000)
    status = page.inner_text('#status')
    print('=== 发送结果状态栏 ===')
    print(status)
    page.screenshot(path='/home/fanfou-sender/evidence/popup_after_send.png')
    print('screenshot → /home/fanfou-sender/evidence/popup_after_send.png')

    print('=== 浏览器日志（最后 15 条）===')
    print('\n'.join(logs[-15:]))
    ctx.close()
