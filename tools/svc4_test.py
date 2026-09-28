# -*- coding: utf-8 -*-
"""服务 v4 端到端：Twitter 通道 + 三平台全发（含清理）"""
import json
import subprocess
import sys

sys.path.insert(0, '/home/fanfou-sender')
import requests  # noqa: E402
from fanfou_sender import FanfouClient  # noqa: E402

TOKEN = open('/home/fanfou-sender/state/service_token.txt').read().strip()
S = 'http://127.0.0.1:8788'
AK = 'https://akkoma.skyneil.net'
AKH = {'Authorization': 'Bearer ' + open('/home/fanfou-sender/state/akkoma_token.txt').read().strip()}
TW_PY = '/home/fanfou-sender/.venv-tw/bin/python'
TW_SENDER = '/home/fanfou-sender/twitter_sender.py'
fan = FanfouClient('/home/fanfou-sender/state')


def send(payload, timeout=180):
    r = requests.post(S + '/send', json=payload, timeout=timeout)
    return r.status_code, r.json()


def tw_delete(tid):
    r = subprocess.run([TW_PY, TW_SENDER, 'delete', str(tid)],
                       capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stdout or r.stderr).strip()[:120]


print('== 0) /status（应含 twitter 已连接）==')
st = requests.get(S + '/status?token=' + TOKEN, timeout=120).json()
print('  fanfou:', st['fanfou'].get('ok'), '| akkoma:', st['akkoma'].get('ok'),
      '| twitter:', json.dumps(st.get('twitter'), ensure_ascii=False)[:100])
print('  limits.twitter_max_weight:', st['limits'].get('twitter_max_weight'))

cleanup_tw = []

print('== a) to=twitter 发送 ==')
code, j = send({'token': TOKEN, 'text': '【通道测试】多平台服务 · Twitter 链路（稍后自动删除）', 'to': 'twitter'})
print(' ', code, json.dumps(j, ensure_ascii=False)[:220])
if j.get('results', {}).get('twitter', {}).get('ok'):
    cleanup_tw.append(j['results']['twitter']['id'])

print('== b) 超限（141 个汉字 = 282 权重，应拒绝且不发）==')
code, j = send({'token': TOKEN, 'text': '测' * 141, 'to': 'twitter'})
print(' ', code, j.get('error'))

print('== c) 图片 + to=twitter（应 400）==')
import base64  # noqa: E402
WEBP = base64.b64encode(open('/tmp/akk_media/test.webp', 'rb').read()).decode()
code, j = send({'token': TOKEN, 'text': 'x', 'to': 'twitter',
                'images': [{'name': 'a.webp', 'mime': 'image/webp', 'data': WEBP}]})
print(' ', code, j.get('error'))

print('== d) to=all 三平台全发 ==')
code, j = send({'token': TOKEN, 'text': '【通道测试】三平台全发联调（稍后自动删除）', 'to': 'all'})
print(' ', code, json.dumps(j, ensure_ascii=False)[:400])
fan_id = j.get('results', {}).get('fanfou', {}).get('id')
ak_id = j.get('results', {}).get('akkoma', {}).get('id')
if j.get('results', {}).get('twitter', {}).get('ok'):
    cleanup_tw.append(j['results']['twitter']['id'])

print()
print('== 清理 ==')
for tid in cleanup_tw:
    rc, out = tw_delete(tid)
    print('  tw del', tid, rc, out[:60])
if fan_id:
    d = fan.delete(fan_id)
    print('  fanfou del', fan_id, d['gone'])
if ak_id:
    r = requests.delete(AK + '/api/v1/statuses/' + ak_id, headers=AKH, timeout=30)
    print('  akkoma del', ak_id, r.status_code)

# 复核
me = requests.get(AK + '/api/v1/accounts/verify_credentials', headers=AKH, timeout=30).json()
sts = requests.get(AK + "/api/v1/accounts/%s/statuses?limit=5" % me['id'], headers=AKH, timeout=30).json()
print('akkoma 剩余帖子:', len(sts))
c = FanfouClient('/home/fanfou-sender/state')
fsts = c._scan_statuses(c._get_profile_html())
left = [(f, t) for f, t in fsts if '【通道测试】' in t]
print('饭否【通道测试】残留:', len(left))
print('DONE')
