#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fanfou_sender.py — 饭否消息发送工具（纯代码网页会话通道）

不使用饭否 OAuth API，不需要浏览器、不需要视觉能力：
直接复用饭否网页版自己的请求（会话 Cookie + 页面 CSRF token），
全部是普通 HTTP 请求（requests）。2026-09 实测跑通，细节见 evidence/NOTES.md：

  登录    GET  /login 取 token → POST /login (auto_login=on) → 长效 Cookie（约 30 天）
  发消息  POST /home   action=msg.post  → JSON {"status":1,...}（>140 字服务端会静默截断）
  核实    GET  /~<user> 个人主页（服务端渲染）→ 提取 ffid（消息 ID）
  删除    POST /home   action=msg.del&msg=<id> → JSON {"status":1,...}

CLI 用法:
  fanfou_sender.py send "消息内容" [--truncate] [--no-verify]
  fanfou_sender.py send -            # 从 stdin 读入内容
  fanfou_sender.py status
  fanfou_sender.py login [--force]
  fanfou_sender.py delete <status_id>
  fanfou_sender.py selftest
  （通用选项：--state-dir 目录  --timeout 秒  --verbose）

退出码: 0=成功(已核实)  1=失败  2=参数/输入错误  3=已受理但未核实
"""

from __future__ import annotations

import argparse
import html as _html
import json
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import unquote

import requests

BASE = "https://fanfou.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
MAX_LEN = 140            # 饭否单条消息上限（服务端按码点截断）
DEFAULT_TIMEOUT = 30

_USER_TOP_RE = re.compile(r'id="user_top">(.*?)</div>', re.S)
_LI_RE = re.compile(r"<li\b.*?</li>", re.S)
_CONTENT_RE = re.compile(r'<span class="content">(.*?)</span>', re.S)
_FFID_RE = re.compile(r'ffid="([^"]+)"')
_TOKEN_RE = re.compile(r'name="token" value="([0-9a-zA-Z]+)"')


class UsageError(Exception):
    """参数/输入错误"""


class FanfouError(Exception):
    """业务失败（被拒 / 认证失败 / 页面结构变化）"""


class _Retryable(Exception):
    """网络或响应异常（重试前需先核实是否已提交）"""


def _norm_text(s: str) -> str:
    """归一化：去 HTML 标签、反转义、去掉全部空白，用于内容匹配。"""
    s = re.sub(r"<[^>]+>", "", s)
    s = _html.unescape(s)
    s = re.sub(r"\s+", "", s)
    return s


class FanfouClient:
    def __init__(self, state_dir: str, timeout: int = DEFAULT_TIMEOUT, verbose: bool = False):
        self.state_dir = os.path.abspath(state_dir)
        self.timeout = timeout
        self.verbose = verbose
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA})
        self._loaded = False
        self._force_relogin = False
        self._display_name = None
        self._profile_path = None

    # ---------------- 基础设施 ----------------

    def _log(self, *a):
        if self.verbose:
            print("[fanfou]", *a, file=sys.stderr)

    @property
    def _session_file(self) -> str:
        return os.path.join(self.state_dir, "session.json")

    @property
    def _credentials_file(self) -> str:
        return os.path.join(self.state_dir, "credentials.json")

    def _write_json_secure(self, path: str, obj) -> None:
        os.makedirs(self.state_dir, mode=0o700, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)

    def _save_debug(self, tag: str, text: str) -> None:
        try:
            os.makedirs(self.state_dir, mode=0o700, exist_ok=True)
            p = os.path.join(self.state_dir, "last_error.txt")
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"# {datetime.now().isoformat()} tag={tag}\n{text[:5000]}")
            os.chmod(p, 0o600)
        except OSError:
            pass

    # ---------------- 凭证与会话 ----------------

    def load_credentials(self) -> dict:
        try:
            with open(self._credentials_file, encoding="utf-8") as f:
                obj = json.load(f)
        except FileNotFoundError:
            raise FanfouError(f"缺少账号文件 {self._credentials_file}（需要 loginname / loginpass）")
        except ValueError as e:
            raise FanfouError(f"账号文件不是合法 JSON: {e}")
        if not obj.get("loginname") or not obj.get("loginpass"):
            raise FanfouError("账号文件缺少 loginname / loginpass 字段")
        return obj

    def load_session(self) -> bool:
        try:
            with open(self._session_file, encoding="utf-8") as f:
                obj = json.load(f)
        except (OSError, ValueError):
            return False
        cookies = obj.get("cookies") or {}
        for name, meta in cookies.items():
            self.s.cookies.set(
                name,
                meta.get("value", ""),
                domain=meta.get("domain") or ".fanfou.com",
                path=meta.get("path") or "/",
                expires=meta.get("expires"),
            )
        self._display_name = obj.get("display_name")
        self._profile_path = obj.get("profile_path")
        self._log(f"载入本地会话（{len(cookies)} 个 cookie）")
        return bool(cookies)

    def save_session(self) -> None:
        cookies = {}
        for c in self.s.cookies:
            cookies[c.name] = {
                "value": c.value,
                "expires": c.expires,
                "domain": c.domain,
                "path": c.path or "/",
            }
        self._write_json_secure(self._session_file, {
            "cookies": cookies,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "display_name": self._display_name,
            "profile_path": self._profile_path,
        })

    # ---------------- 页面解析 ----------------

    @staticmethod
    def _logged_in(text: str) -> bool:
        return ('id="user_top"' in text) or ('退出' in text and 'id="loginname"' not in text)

    @staticmethod
    def _is_login_page(text: str) -> bool:
        return ('id="loginpass"' in text) and ('id="user_top"' not in text)

    @staticmethod
    def _fetch_token(text: str):
        m = _TOKEN_RE.search(text)
        return m.group(1) if m else None

    def _identity_from(self, text: str) -> None:
        m = _USER_TOP_RE.search(text)
        if m:
            blk = m.group(1)
            a = re.search(r'<a\s+href="([^"]+)"', blk)
            h = re.search(r"<h3>([^<]*)</h3>", blk)
            if a and a.group(1).startswith("/"):
                self._profile_path = a.group(1)
            if h:
                self._display_name = h.group(1).strip()
        if not self._profile_path:
            c = next((c for c in self.s.cookies if c.name == "u"), None)
            if c:
                self._profile_path = "/" + unquote(c.value)

    # ---------------- 登录 / 会话 ----------------

    def login(self) -> None:
        cred = self.load_credentials()
        self._log("执行登录…")
        self.s.cookies.clear()
        r = self.s.get(f"{BASE}/login", timeout=self.timeout)
        token = self._fetch_token(r.text)
        if not token:
            self._save_debug("login-page", r.text)
            raise FanfouError("登录页结构异常：未找到 CSRF token（饭否可能改版，见 state/last_error.txt）")
        r2 = self.s.post(
            f"{BASE}/login",
            data={
                "loginname": cred["loginname"],
                "loginpass": cred["loginpass"],
                "action": "login",
                "token": token,
                "auto_login": "on",
            },
            timeout=self.timeout,
        )
        if self._logged_in(r2.text):
            self._force_relogin = False
            self.save_session()
            self._log("登录成功")
            return
        self._save_debug("login-failed", r2.text)
        hint = self._extract_login_error(r2.text)
        raise FanfouError(f"登录失败：{hint}")

    @staticmethod
    def _extract_login_error(text: str) -> str:
        for pat in (r'class="errmsg"[^>]*>(.*?)</div>',
                    r'class="error"[^>]*>(.*?)<',
                    r"(验证码[^<]{2,40})",
                    r"(密码[^<]{2,40})",
                    r"(尝试[^<]{2,40})"):
            m = re.search(pat, text, re.S)
            if m:
                s = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                if s:
                    return s
        return "服务器未返回明确原因；如提示需要验证码，请在浏览器手动登录一次并留意风控"

    def ensure_session(self, force: bool = False) -> str:
        """保证拿到一个已登录的 /home 页面 HTML，返回其文本。"""
        if not self._loaded:
            self._loaded = True
            if not self.load_session():
                self._log("无本地会话，直接登录")
                self.login()
        elif force or self._force_relogin:
            self.login()
        home = self.s.get(f"{BASE}/home", timeout=self.timeout)
        if not self._logged_in(home.text):
            self._log("本地会话失效，重新登录")
            self.login()
            home = self.s.get(f"{BASE}/home", timeout=self.timeout)
        if not self._logged_in(home.text):
            self._save_debug("after-login-home", home.text)
            raise FanfouError("登录后仍无法进入 /home（见 state/last_error.txt）")
        self._identity_from(home.text)
        self.save_session()
        return home.text

    # ---------------- 发送 ----------------

    def _post_msg(self, token: str, content: str) -> dict:
        data = {
            "token": token,
            "ajax": "yes",
            "action": "msg.post",
            "content": content,
            "repost_status_id": "",
            "in_reply_to_status_id": "",
        }
        try:
            r = self.s.post(f"{BASE}/home", data=data,
                            headers={"X-Requested-With": "XMLHttpRequest"},
                            timeout=self.timeout)
        except requests.RequestException as e:
            raise _Retryable(f"网络错误：{e}")
        if r.status_code != 200:
            raise _Retryable(f"HTTP {r.status_code}")
        try:
            j = r.json()
        except ValueError:
            if self._is_login_page(r.text):
                self._force_relogin = True
                raise _Retryable("会话失效（响应为登录页）")
            self._save_debug("post-response", r.text)
            raise _Retryable(f"响应不是 JSON：{r.text[:120]!r}")
        return j

    def send(self, content: str, truncate: bool = False, verify: bool = True) -> dict:
        """发送消息。

        返回 {"fid": 消息ID或None, "server_msg": 服务器提示, "verified": True/False/None}
        verified: True=主页核实到; False=未核实到; None=跳过核实
        """
        content = content.strip()
        if not content:
            raise UsageError("消息内容为空")
        if len(content) > MAX_LEN:
            if not truncate:
                raise UsageError(
                    f"消息 {len(content)} 字，超过饭否 {MAX_LEN} 字上限（服务端会静默截断）；"
                    f"如确要截断发送请加 --truncate")
            self._log(f"内容 {len(content)} 字，截断为 {MAX_LEN} 字")
            content = content[:MAX_LEN]

        attempts = 2 if verify else 1
        last_err = None
        for attempt in range(1, attempts + 1):
            try:
                home = self.ensure_session()
                token = self._fetch_token(home)
                if not token:
                    self._save_debug("home-no-token", home)
                    raise FanfouError("/home 页面未找到 token（饭否可能改版）")
                j = self._post_msg(token, content)
                if j.get("status") != 1:
                    raise FanfouError(f"发送被拒绝：{j.get('msg')}")
                server_msg = str(j.get("msg") or "")
                fid = self.verify_visible(content) if verify else None
                return {"fid": fid, "server_msg": server_msg, "verified": (fid is not None) if verify else None}
            except _Retryable as e:
                last_err = e
                if verify:
                    fid = self.verify_visible(content)
                    if fid:
                        return {"fid": fid, "server_msg": "(重试前核实：消息已在主页)", "verified": True}
                if attempt < attempts:
                    self._log(f"第 {attempt} 次异常（{e}），先核实未发现消息，重试…")
                    continue
        raise FanfouError(f"发送失败：{last_err}")

    # ---------------- 核实 / 查询 ----------------

    def _get_profile_html(self) -> str:
        if not self._profile_path:
            self.ensure_session()
        if not self._profile_path:
            raise FanfouError("无法确定个人主页地址（请先运行 status 检查）")
        r = self.s.get(f"{BASE}{self._profile_path}", timeout=self.timeout)
        if self._is_login_page(r.text):
            self.login()
            r = self.s.get(f"{BASE}{self._profile_path}", timeout=self.timeout)
        return r.text

    @staticmethod
    def _scan_statuses(page_html: str):
        """从主页 HTML 提取 [(ffid, 归一化内容), ...]（按页面顺序，最新在前）。"""
        out = []
        for li in _LI_RE.findall(page_html):
            cm = _CONTENT_RE.search(li)
            if not cm:
                continue
            fm = _FFID_RE.search(li)
            out.append((fm.group(1) if fm else None, _norm_text(cm.group(1))))
        return out

    def verify_visible(self, content: str, attempts: int = 3, delay: float = 2.0):
        """在个人主页找消息，返回 ffid；找不到返回 None。"""
        want = _norm_text(content)
        for i in range(attempts):
            try:
                page = self._get_profile_html()
                for fid, text in self._scan_statuses(page):
                    if want and want in text:
                        return fid
            except requests.RequestException:
                pass
            if i < attempts - 1:
                time.sleep(delay)
        return None

    # ---------------- 删除 ----------------

    def delete(self, status_id: str) -> dict:
        status_id = status_id.strip()
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", status_id):
            raise UsageError(f"消息 ID 不合法：{status_id!r}")
        home = self.ensure_session()
        token = self._fetch_token(home)
        if not token:
            raise FanfouError("/home 页面未找到 token（饭否可能改版）")
        r = self.s.post(
            f"{BASE}/home",
            data={"action": "msg.del", "msg": status_id, "token": token, "ajax": "yes"},
            headers={"X-Requested-With": "XMLHttpRequest"},
            timeout=self.timeout,
        )
        try:
            j = r.json()
        except ValueError:
            self._save_debug("delete-response", r.text)
            raise FanfouError(f"删除响应异常：{r.text[:120]!r}")
        if j.get("status") != 1:
            raise FanfouError(f"删除被拒绝：{j.get('msg')}")
        gone = None
        try:
            page = self._get_profile_html()
            gone = (f'ffid="{status_id}"' not in page) and (f"/msg.del/{status_id}" not in page)
        except (requests.RequestException, FanfouError):
            pass
        return {"fid": status_id, "server_msg": str(j.get("msg") or ""), "gone": gone}

    # ---------------- 状态 ----------------

    def status(self) -> dict:
        self.ensure_session()
        al = next((c for c in self.s.cookies if c.name == "al"), None)
        expires = None
        if al is not None and al.expires:
            expires = datetime.fromtimestamp(al.expires).strftime("%Y-%m-%d %H:%M")
        return {
            "display_name": self._display_name,
            "profile_path": self._profile_path,
            "session_expires": expires,
        }


# ---------------- CLI ----------------

def _client_from_args(a) -> FanfouClient:
    return FanfouClient(state_dir=a.state_dir, timeout=a.timeout, verbose=a.verbose)


def cmd_send(a) -> int:
    content = a.text
    if content == "-":
        content = sys.stdin.read()
    client = _client_from_args(a)
    try:
        res = client.send(content, truncate=a.truncate, verify=not a.no_verify)
    except UsageError as e:
        print(f"参数错误：{e}", file=sys.stderr)
        return 2
    except (FanfouError, requests.RequestException) as e:
        print(f"失败：{e}", file=sys.stderr)
        return 1
    if res["verified"] is False:
        print(f"已受理但未核实：{res['server_msg']}（请稍后到个人主页确认）", file=sys.stderr)
        return 3
    fid = res["fid"] or "-"
    verify_str = {True: "yes", False: "no", None: "skipped"}[res["verified"]]
    msg = f" | {res['server_msg']}" if res["server_msg"] else ""
    print(f"OK id={fid} verified={verify_str}{msg}")
    return 0


def cmd_delete(a) -> int:
    client = _client_from_args(a)
    try:
        res = client.delete(a.status_id)
    except UsageError as e:
        print(f"参数错误：{e}", file=sys.stderr)
        return 2
    except (FanfouError, requests.RequestException) as e:
        print(f"失败：{e}", file=sys.stderr)
        return 1
    gone = {True: "yes", False: "no", None: "unknown"}[res["gone"]]
    print(f"OK deleted={res['fid']} gone={gone} | {res['server_msg']}")
    return 0


def cmd_status(a) -> int:
    client = _client_from_args(a)
    try:
        st = client.status()
    except (FanfouError, requests.RequestException) as e:
        print(f"失败：{e}", file=sys.stderr)
        return 1
    print(f"OK user={st['display_name']} profile={BASE}{st['profile_path']} "
          f"session_expires={st['session_expires'] or '未知'}")
    return 0


def cmd_login(a) -> int:
    client = _client_from_args(a)
    try:
        client.ensure_session(force=True)
        st = client.status()
    except (FanfouError, requests.RequestException) as e:
        print(f"失败：{e}", file=sys.stderr)
        return 1
    print(f"OK logged_in user={st['display_name']} session_expires={st['session_expires'] or '未知'}")
    return 0


def cmd_selftest(a) -> int:
    client = _client_from_args(a)
    stamp = datetime.now().strftime("%m%d-%H%M%S")
    text = f"【fanfou-sender 自检】{stamp}：发送 / 核实 / 删除全链路。"
    try:
        st = client.status()
        print(f"1) 会话 OK：{st['display_name']} ({BASE}{st['profile_path']})")
        res = client.send(text)
        print(f"2) 发送 OK：id={res['fid']} verified={res['verified']} | {res['server_msg']}")
        if not res["fid"]:
            print("× 未能核实到消息，中止自检", file=sys.stderr)
            return 1
        dres = client.delete(res["fid"])
        print(f"3) 删除 OK：gone={dres['gone']} | {dres['server_msg']}")
        if dres["gone"] is False:
            print("× 删除后仍在主页可见", file=sys.stderr)
            return 1
    except UsageError as e:
        print(f"参数错误：{e}", file=sys.stderr)
        return 2
    except (FanfouError, requests.RequestException) as e:
        print(f"失败：{e}", file=sys.stderr)
        return 1
    print("自检通过 ✔")
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--state-dir", default=os.path.join(os.path.dirname(os.path.realpath(__file__)), "state"),
                        help="状态目录（会话/账号文件所在，默认 ./state）")
    common.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="HTTP 超时秒数（默认 30）")
    common.add_argument("--verbose", action="store_true", help="输出过程日志")

    p = argparse.ArgumentParser(
        prog="fanfou_sender.py",
        description="饭否消息发送工具（网页会话通道，无 OAuth、无浏览器）",
        epilog="退出码：0=成功(已核实)  1=失败  2=参数/输入错误  3=已受理但未核实",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("send", parents=[common], help="发送消息（内容传 - 则从 stdin 读取）")
    sp.add_argument("text", help="消息内容，或 - 表示从标准输入读取")
    sp.add_argument("--truncate", action="store_true", help="超过 140 字时截断发送（默认拒绝）")
    sp.add_argument("--no-verify", action="store_true", help="跳过个人主页核实（不推荐，无法发现审核异常）")
    sp.set_defaults(func=cmd_send)

    sp = sub.add_parser("delete", parents=[common], help="删除一条消息")
    sp.add_argument("status_id", help="消息 ID（如 send 输出中的 id=xxx）")
    sp.set_defaults(func=cmd_delete)

    sp = sub.add_parser("status", parents=[common], help="查看会话状态")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("login", parents=[common], help="强制重新登录")
    sp.add_argument("--force", action="store_true", help="（登录命令本身即强制，此参数保留）")
    sp.set_defaults(func=cmd_login)

    sp = sub.add_parser("selftest", parents=[common], help="自检：发送+核实+删除全链路")
    sp.set_defaults(func=cmd_selftest)

    return p


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
