# -*- coding: utf-8 -*-
"""B 站取数客户端：搜索、视频信息、评论（wbi 签名 + 游标分页）。

只用公开接口，不登录、不绕验证码。要点：
- 搜索与视频信息用老接口，简单可用；
- 评论必须走 `/x/v2/reply/wbi/main`（老接口 pn 分页已被降级，只返回数条）；
- wbi 混合密钥需要先拉 `nav` 接口，签名后带 `w_rid` 与 `wts` 请求；
- 全部串行限速，超时/风控退避重试，失败抛 `BiliError` 由上层降级。
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
_TAG_RE = re.compile(r"<[^>]+>")

# wbi 混合密钥置换表（B 站前端固定值）
_MIXIN = (
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
)

RETRYABLE = {-412, -799, -509, -500}
# 评论排序：3=热门、2=最新（wbi/main 的 mode 语义）
MODE_HOT = 3
MODE_NEW = 2


class BiliError(RuntimeError):
    pass


@dataclass
class BiliClient:
    qps: float = 1.2
    timeout: int = 30
    retries: int = 4
    calls: int = 0
    _last: float = 0.0
    _mixin_key: str = ""
    _cookie: str = ""
    log: list[str] = field(default_factory=list)

    # -- 底层 ---------------------------------------------------------------

    def _raw_get(self, url: str) -> tuple[dict, list[str]]:
        head = {"User-Agent": UA, "Referer": "https://www.bilibili.com/", "Accept": "application/json"}
        if self._cookie:
            head["Cookie"] = self._cookie
        req = urllib.request.Request(url, headers=head)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
            cookies = resp.headers.get_all("Set-Cookie") or []
        return body, cookies

    def _get(self, url: str) -> dict:
        wait = self.qps - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self.calls += 1

        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                body, cookies = self._raw_get(url)
                for raw in cookies:
                    pair = raw.split(";")[0]
                    if "=" in pair and pair.split("=")[0] in {"buvid3", "buvid4", "b_nut"}:
                        self._cookie = (self._cookie + "; " + pair).strip("; ")
                return body
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
                last = exc
                if attempt < self.retries:
                    time.sleep(2.0 * (attempt + 1) + random.random())
        raise BiliError(f"请求失败：{url}（{last}）")

    def _api(self, path: str, **params) -> dict:
        return self._get(f"https://api.bilibili.com{path}?{urllib.parse.urlencode(params)}")

    # -- wbi 签名 -----------------------------------------------------------

    def _ensure_mixin(self) -> str:
        if self._mixin_key:
            return self._mixin_key
        nav = self._api("/x/web-interface/nav")
        wbi = (nav.get("data") or {}).get("wbi_img") or {}
        img = wbi.get("img_url", "").rsplit("/", 1)[-1].split(".")[0]
        sub = wbi.get("sub_url", "").rsplit("/", 1)[-1].split(".")[0]
        if not img or not sub:
            raise BiliError("未能取得 wbi 密钥（nav 接口异常）")
        origin = img + sub
        self._mixin_key = "".join(origin[i] for i in _MIXIN)[:32]
        return self._mixin_key

    def _sign(self, params: dict) -> str:
        key = self._ensure_mixin()
        params = {**params, "wts": int(time.time())}
        filtered = {
            k: "".join(ch for ch in str(v) if ch not in "!'()*")
            for k, v in sorted(params.items())
        }
        query = urllib.parse.urlencode(filtered)
        params["w_rid"] = hashlib.md5((query + key).encode()).hexdigest()
        return urllib.parse.urlencode(params)

    # -- 搜索 ---------------------------------------------------------------

    def search_videos(self, keyword: str, pages: int = 1) -> list[dict]:
        rows: list[dict] = []
        for page in range(1, pages + 1):
            data = self._api("/x/web-interface/search/type",
                             search_type="video", keyword=keyword, page=page)
            code = data.get("code")
            if code in RETRYABLE:
                self.log.append(f"搜索被风控：{keyword} code={code}")
                break
            if code != 0:
                self.log.append(f"搜索失败：{keyword} code={code} {data.get('message')}")
                break
            for item in ((data.get("data") or {}).get("result") or []):
                rows.append(
                    {
                        "bvid": item.get("bvid"),
                        "title": _TAG_RE.sub("", item.get("title") or ""),
                        "author": item.get("author"),
                        "play": int(item.get("play") or 0),
                        "reply": int(item.get("video_review") or 0),
                        "danmaku": int(item.get("danmaku") or 0),
                        "favorite": int(item.get("favorites") or 0),
                        "pubdate": int(item.get("pubdate") or 0),
                        "duration": item.get("duration"),
                        "description": (item.get("description") or "")[:200],
                        "keyword": keyword,
                    }
                )
        return rows

    # -- 视频信息 -----------------------------------------------------------

    def video_info(self, bvid: str) -> dict:
        data = self._api("/x/web-interface/view", bvid=bvid)
        if data.get("code") != 0:
            raise BiliError(f"视频信息失败：{bvid} code={data.get('code')}")
        d = data["data"]
        stat = d.get("stat") or {}
        return {
            "bvid": bvid,
            "aid": d["aid"],
            "title": d.get("title", ""),
            "desc": (d.get("desc") or "")[:300],
            "owner": (d.get("owner") or {}).get("name", ""),
            "pubdate": int(d.get("pubdate") or 0),
            "view": int(stat.get("view") or 0),
            "like": int(stat.get("like") or 0),
            "reply": int(stat.get("reply") or 0),
            "share": int(stat.get("share") or 0),
            "favorite": int(stat.get("favorite") or 0),
            "url": f"https://www.bilibili.com/video/{bvid}",
        }

    # -- 评论（游标分页）----------------------------------------------------

    def replies(self, aid: int, bvid: str, *, mode: int = MODE_HOT, max_pages: int = 4) -> list[dict]:
        """按游标翻页。mode=3 热门、mode=2 最新。返回去重后的评论列表。"""
        offset = ""
        out: dict[str, dict] = {}
        for _ in range(max_pages):
            pagination = json.dumps({"offset": offset}, separators=(",", ":"))
            query = self._sign(
                {"oid": aid, "type": 1, "mode": mode, "pagination_str": pagination,
                 "plat": 1, "web_location": 1315875}
            )
            body = self._get(f"https://api.bilibili.com/x/v2/reply/wbi/main?{query}")
            code = body.get("code")
            if code in RETRYABLE:
                self.log.append(f"评论被风控：{bvid} code={code}")
                break
            if code != 0:
                break
            data = body.get("data") or {}
            rows = data.get("replies") or []
            if not rows:
                break
            for row in rows:
                item = _normalize_reply(row, bvid)
                out.setdefault(item["comment_id"], item)
            cursor = data.get("cursor") or {}
            offset = ((cursor.get("pagination_reply") or {}).get("next_offset")) or ""
            if cursor.get("is_end") or not offset:
                break
        return list(out.values())

    def sub_replies(self, aid: int, bvid: str, root: str, limit: int = 8) -> list[dict]:
        """楼中楼。接口偶有降级，失败返回空列表，不阻塞主流程。"""
        out: list[dict] = []
        for page in range(1, 3):
            try:
                data = self._api("/x/v2/reply/reply", type=1, oid=aid, root=root, pn=page, ps=10)
            except BiliError:
                break
            if data.get("code") != 0:
                break
            rows = ((data.get("data") or {}).get("replies")) or []
            if not rows:
                break
            for row in rows:
                out.append(_normalize_reply(row, bvid, parent=root))
            if len(out) >= limit:
                break
        return out[:limit]


def _normalize_reply(row: dict, bvid: str, parent: str | None = None) -> dict:
    content = row.get("content") or {}
    member = row.get("member") or {}
    return {
        "comment_id": f"bili:{bvid}:{row.get('rpid')}",
        "post_id": f"bili:{bvid}",
        "platform": "bilibili",
        "author": member.get("uname") or "",
        "text": (content.get("message") or "").strip(),
        "likes": int(row.get("like") or 0),
        "reply_to": str(row.get("parent")) if row.get("parent") else parent,
        "rcount": int(row.get("rcount") or 0),
        "created_at": int(row.get("ctime") or 0),
    }
