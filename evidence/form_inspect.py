# -*- coding: utf-8 -*-
import re
t = open("home.html").read()
i = t.find('id="message"')
print("=== message form HTML ===")
print(t[i-100:i+1800])
print()
# find user profile link / username
m = re.findall(r'href="/([A-Za-z0-9_\-\.]+)"[^>]*>([^<]{0,20})</a>', t)
print("=== some links ===")
for a in m[:40]:
    print(a)
