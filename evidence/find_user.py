# -*- coding: utf-8 -*-
import re
t = open("home.html").read()
# all tokens
print("all token inputs:", re.findall(r'name="token" value="([^"]+)"', t))
# profile links - look for avatar or username area
for pat in [r'class="avatar"[^>]*', r'href="/([^"/]+)"[^>]*class="[^"]*avatar', r'<a href="/([^"]+)"[^>]*>\s*<img[^>]*avatar', r'"my_profile"', r'个人主页', r'我的首页']:
    m = re.findall(pat, t)
    if m:
        print(pat, "->", m[:10])
# find snippet around 'avatar'
i = t.find('avatar')
print("\n--- around first 'avatar' ---")
print(t[max(0,i-300):i+400])
