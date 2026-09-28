# fanfou-sender

饭否消息发送工具：**纯代码**走饭否网页会话通道。
不使用 OAuth API、不需要浏览器、不需要视觉能力，全部是普通 HTTP 请求（Python + requests）。

## 快速开始

```bash
cd /home/fanfou-sender

python3 fanfou_sender.py send "你好，饭否！"     # 发送并核实，输出消息 ID
python3 fanfou_sender.py status                  # 查看会话状态
python3 fanfou_sender.py selftest                # 自检：发一条 → 核实 → 删掉
echo "从管道读入的内容" | python3 fanfou_sender.py send -
```

首次运行自动登录（账号在 `state/credentials.json`）。会话保存在 `state/session.json`，
有效期约 30 天，过期/失效会**自动重新登录**，日常使用无需任何人工干预。

## 命令一览

| 命令 | 说明 |
| --- | --- |
| `send "内容"` | 发消息：服务端受理 JSON + 个人主页可见性**双重核实**后才算成功 |
| `send -` | 从 stdin 读内容（适合脚本拼装、多行文本） |
| `send --truncate` | 超过 140 字时截断发送（默认直接拒绝，因为服务端会静默截断） |
| `send --no-verify` | 跳过主页核实（更快，但不保险） |
| `delete <id>` | 删除一条消息 |
| `status` / `login` | 会话状态 / 强制重新登录 |
| `selftest` | 全链路自检 |

通用选项：`--state-dir <目录>`、`--timeout <秒>`、`--verbose`。

**退出码**：`0`=成功(已核实) `1`=失败 `2`=参数/输入错误 `3`=已受理但未核实

## 输出示例

```
$ python3 fanfou_sender.py send "你好饭否"
OK id=SUogSNaFJyY verified=yes | 信息需要审核，通过后即将发出

$ python3 fanfou_sender.py selftest
1) 会话 OK：变换角色 (https://fanfou.com/~5kRwNCD-BEU)
2) 发送 OK：id=rXvAwj20VOQ verified=True | 信息需要审核，通过后即将发出
3) 删除 OK：gone=True | 信息删除成功！
自检通过 ✔
```

## 原理（大白话）

饭否网页版自己发消息，走的就是几个普通请求。本工具不看页面、不点按钮，直接复用这套请求：

1. **登录一次**：取登录页里的防伪码（CSRF token），提交账号密码 + 勾选「自动登录」→
   服务器发一张约 30 天的通行证（Cookie），存到本地 `state/session.json`；
2. **每次发消息**（3 个请求）：
   - 打开首页，取当页防伪码；
   - 提交内容（`action=msg.post`）→ 服务器返回 JSON 回执；
   - 再看一眼个人主页（服务端直出的 HTML），确认消息真的在，顺便读出消息 ID；
3. 网络抖动时**先查主页确认是否已发出、再决定要不要重试**，不会重复发送。

细节与全部取证见 `evidence/NOTES.md`。

## 稳定性设计

- 会话 30 天有效；Cookie 过期/失效自动重登（实测当前风控下无需验证码；若某天被要求验证码，
  工具会明确报错，此时在浏览器手动登录一次保留 `state/session.json` 即可）；
- 每条消息双重确认（服务器回执 + 主页可见），失败有明确区分（拒绝/超时/未核实）；
- 输出格式固定（`OK id=... verified=...`），便于被其它脚本/agent 解析；
- 仅依赖 `requests`，本机已装。

## 已知边界

- 消息上限 **140 字**（按字符计），超出服务端会**静默截断** —— 工具默认拒绝，`--truncate` 才截断；
- 所有消息受饭否审核策略影响：发出后带【审核中】标记（作者主页即时可见），属官方行为，与通道无关；
- 主页核实只看第一页（新消息都在最上面，日常足够）；
- 若饭否页面结构改版，工具会在对应步骤报错，并把现场存到 `state/last_error.txt`。

## HTTP 服务（多平台，供浏览器插件等调用）

`fanfou_service.py` 把本工具包成 HTTP 接口（饭否 + Akkoma + Twitter/X，与 CLI 共用会话和账号文件）：

```bash
python3 fanfou_service.py --host 0.0.0.0 --port 8788   # 对外暴露必须显式 --host 0.0.0.0
```

- `GET /health` 探活；`GET /send?token=..&text=..&to=..` 直接测试；`POST /send` 支持 JSON / 表单 / 纯文本 body；
- **`to` 参数**：`fanfou`（默认）/ `akkoma` / `twitter` / `both`（饭否+Akkoma）/ `all`（三平台），也支持组合（如 `akkoma,twitter`）；
- **图片**：`"images":[{"name","mime","data(base64)"}]` —— Akkoma ≤16 张/次、X ≤4 张（超出只发前 4 张到 X）；≤2MB/张（插件端压 webp）；
- **标签**：`"tags":["摄影","日常"]` —— 追加给 Akkoma 与 X（`#标签` 形式、自动去重）；`GET /limits` 查限制；
- **Twitter/X**：支持图片（≤4 张）、按权重限 280（中文约 140 字）；凭据 `state/tw_cookies.json`（twifork + `.venv-tw`）；
- 消息字段兼容 `text / message / content / notes / selection / customFields.message` 等（适配常见 webhook 插件）；
- 除探活/帮助页外均需 token（`state/service_token.txt`，首次启动自动生成）；Akkoma 凭据 `state/akkoma_token.txt`；Twitter 凭据 `state/tw_cookies.json`；
- 饭否超过 140 字自动截断（响应带 `truncated` 标记，与饭否自身行为一致），Akkoma 不截断；
- 限速 15 条/分钟；日志 `state/service.log`；状态查询 `GET /status?token=..`。

## Twitter / X 通道（现成方案）

- 采用现成库 **twifork**（twikit 的维护分支，MIT）：cookie 会话、不用官方 API key、纯 HTTP；
- 凭据 `state/tw_cookies.json`（浏览器导出的 `auth_token` + `ct0`，600 权限；失效后需重新导出）；
- 封装在 `twitter_sender.py`（check / post / delete）；服务端经 `.venv-tw`（Py3.12）子进程调用；
- 限制：正文按权重 280（中文约 140 字）；封号保护守则与调研见 `evidence/twitter-调研-2026-09-28.md`（低频、复用 cookie、勿过量发帖）。

## Chrome 扩展「双发小助手」

`extension/` 是配套的 Chrome 扩展（MV3，v0.4）：输入框 + 五个按钮 —— 发饭否 / 发 Akkoma / 发 Twitter / Akkoma + X / 同时发（3 平台）；
外加**实时字数、图片（Akkoma + X，自动压 webp ≤2MB/张）、#标签（Akkoma+X）、发送系统通知、错误日志**。

- 安装：`chrome://extensions/` → 打开「开发者模式」→「加载已解压的扩展程序」→ 选 `extension/` 目录；
- 配置：扩展设置页填「服务地址 + token」；
- 扩展 ID 固定：`ibkamonleimnlfoojnnnhmcnaeebjiba`（由 manifest 里的 key 决定，重装不变）。

浏览器插件配置（含其它现成插件方案）见 `浏览器插件配置.md`。

## 嵌入其它脚本

```python
import sys
sys.path.insert(0, "/home/fanfou-sender")
from fanfou_sender import FanfouClient

c = FanfouClient("/home/fanfou-sender/state")
result = c.send("来自其它脚本的消息")
print(result)  # {'fid': '...', 'server_msg': '...', 'verified': True}
```

## 文件说明

- `fanfou_sender.py` — 饭否主程序（CLI + 可导入的 `FanfouClient` 类）
- `akkoma_sender.py` — Akkoma 发送模块（官方 API，含图片上传）
- `twitter_sender.py` — Twitter/X 发送模块（twifork，cookie 会话）
- `.venv-tw/` — Twitter 通道专用虚拟环境（Py3.12 + twifork）
- `fanfou_service.py` — 多平台 HTTP 服务（饭否 + Akkoma + Twitter）
- `extension/` — Chrome 扩展「双发小助手」
- `state/credentials.json` — 饭否账号密码（600 权限）
- `state/session.json` — 饭否会话 Cookie（600 权限）
- `state/akkoma_token.txt` — Akkoma token（600 权限）
- `state/service_token.txt` — HTTP 服务 token（600 权限）
- `state/tw_cookies.json` — Twitter/X 会话 cookie（600 权限）
- `evidence/` — 逆向侦察记录与取证文件（2026-09）

## 部署与换机（state 凭据怎么带）

所有凭据与运行时状态都集中在 `state/`（目录 700、文件 600；已被 `.gitignore` 整体排除，**不会进仓库**）：

| 文件 | 内容 |
| --- | --- |
| `state/credentials.json` | 饭否账号密码 |
| `state/session.json` | 饭否会话（约 30 天，过期自动重登） |
| `state/akkoma_token.txt` | Akkoma API token |
| `state/tw_cookies.json` | X（auth_token + ct0） |
| `state/service_token.txt` | 本服务鉴权 token（插件配置用） |

换 VPS / 多机部署时，任选一种同步方式：

```bash
# 方式 A：rsync 直传（推荐，两机之间走 SSH）
rsync -avz /home/fanfou-sender/state/ root@新主机:/home/fanfou-sender/state/
ssh root@新主机 'chmod 700 /home/fanfou-sender/state && chmod 600 /home/fanfou-sender/state/*'

# 方式 B：加密打包（需要经过不可信通道时）
tar czf - state | openssl enc -aes-256-cbc -pbkdf2 -salt -out state.tar.gz.enc
# 新机解密：openssl enc -d -aes-256-cbc -pbkdf2 -in state.tar.gz.enc | tar xzf -

# 方式 C：不搬，在新机重新领取
#   Akkoma：实例设置页新建一个 token
#   X：浏览器重新导出 auth_token + ct0
#   饭否：带着 credentials.json 首次运行会自动登录（或手动重建该文件）
#   服务 token：首次启动自动生成 —— 记得把新值同步给插件「设置」页
```

> ⚠ 多机同时使用同一套 X cookie 有风控风险；建议固定一台机器、低频使用。

## 安全提示

账号密码以明文存于 `state/credentials.json`（600 权限）。
请勿把 `state/` 目录提交进任何仓库或分享给他人。
