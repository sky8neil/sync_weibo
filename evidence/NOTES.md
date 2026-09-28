# 逆向侦察记录（2026-09-28）

目标：不依赖 OAuth API / 浏览器 / 视觉能力，纯代码稳定发送饭否消息。
本目录是达成目标过程中的全部侦察脚本与取证文件。

## 结论：跑通的请求（全部实测）

| 操作 | 请求 | 要点 |
| --- | --- | --- |
| 登录页 | `GET /login` | 取 `<input name="token">`（CSRF，与 PHPSESSID 绑定） |
| 登录 | `POST /login` | `loginname / loginpass / action=login / token / auto_login=on` → 长效 Cookie `al`/`m`/`u`（30 天） |
| 发消息 | `POST /home` | `token / ajax=yes / action=msg.post / content / repost_status_id / in_reply_to_status_id` → JSON `{"status":1,"msg":"信息需要审核，通过后即将发出"}` |
| 删除 | `POST /home` | `action=msg.del / msg=<id> / token / ajax=yes` + `X-Requested-With: XMLHttpRequest` → JSON `{"status":1,"msg":"信息删除成功！"}` |
| 核实 | `GET /~<user>` | 个人主页是服务端渲染，消息即时可见（审核中带【审核中】）；`ffid="..."` 即消息 ID |

## 关键事实

- 登录页虽有图形验证码输入框，但实测**不强制**（全天连续 5+ 次登录均直接成功，未触发验证码）；
- 勾选 `auto_login=on` 后 Cookie 有效期 **30 天**（`al` 字段）；
- 消息上限 **140 个码点**：服务端会**静默截断**（实测 71🐱+70A 提交后存为 71🐱+69A，恰 140 码点）；
- 消息发出后进入审核队列（作者主页即时可见【审核中】），删除不受审核状态影响；
- `/home` 时间线是 JS 异步加载（不能用于核实）；个人主页 `/~<user>` 是服务端渲染（可以）；
- 发帖/删除的 ajax 响应统一为 `{"status": 0|1, "msg": "..."}`，`status=1` 为成功；
- 删除的真实参数是 `msg=<id>`（不是 href）；POST 到站内任意已登录页面均可（工具使用 `/home`）；
- 曾用 `href=/msg.del/<id>` 试删 → 服务器返回 `success` 但**实际无效**，不可作为删除成功依据（已用真浏览器抓包纠错）。

## 取证文件

- `login_test1.py` — 无验证码登录成功（`resp_nocaptcha.html`）
- `post_test.py` — 第一条消息发送成功（`profile_after_post.html`）
- `cookie_reuse_test.py` — 纯 Cookie 复用发送（不带密码，`saved_session.json`）
- `ajax_test.py` — JSON 回执格式 + 连发测试
- `limit_test.py` / `emoji_test.py` — 140 码点截断边界（`emoji_status.html`）
- `browser_delete_capture2.py` — Playwright 真浏览器抓删除请求（`profile_after_ui_delete.png`，本目录最有价值的一份抓包）
- `delete_correct.py` — 正确参数删除复核
- `delete_test.py` / `delete_check2.py` — 错误参数（href 方案）反例记录
- `fanfou.js` — 站点前端 JS（消息提交/删除逻辑出处，静态资源存档）
- `home.html` / `profile_check2.html` — 关键页面存档

## 最终验证（2026-09-28）

- 工具全链路验收通过：发送 / 核实 / 删除 / 过期自动重登 / 连发 / 140 边界 / 超长拒绝 / 截断 / stdin / 非法参数 共 10 项；
- 所有测试消息已清理（13 条删除确认消失），保留 1 条正式验证消息（`WolsLeoSsqI`）；
- `final_profile.png` — 清理后主页截图（顶部为工具发送的验证消息）。
