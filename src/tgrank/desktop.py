"""流式解析 Telegram Desktop 导出的 result.json。

导出文件可能有几百 MB，容器只有 512MB，所以用 ijson 逐条构造消息，内存里只保留
「消息 id → 话题 id」这一张表（且只在确认是话题群之后才开始记）。
"""
from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import BinaryIO
from zoneinfo import ZoneInfo

import ijson

from .records import (
    ChatInfo, MessageRecord, TopicRecord, desktop_reaction, flatten_text, marked_chat_id, media_label,
)

GENERAL_TOPIC_ID = 1
NOT_EXPORT = "这个文件不是 Telegram 导出的单个聊天记录：缺少顶层 messages 字段。导出时请在群里选择「导出聊天记录」并选「机器可读的 JSON」格式。"
BAD_JSON = "文件不是有效的 JSON，可能导出或上传时被中断了。重新导出后再试。"


class DesktopFormatError(ValueError):
    pass


class DesktopExport:
    """构造时读到 messages 数组开头为止（拿到群信息），records() 再逐条产出。

    records() 结束后 `is_forum`、`first_topic_id` 才是最终值。
    """

    def __init__(self, fp: BinaryIO, tz: ZoneInfo):
        self._tz = tz
        self._events = ijson.parse(fp, use_float=True)
        self.is_forum = False
        self.first_topic_id: int | None = None
        self.info = self._read_header()

    def _read_header(self) -> ChatInfo:
        header: dict = {}
        try:
            for prefix, event, value in self._events:
                if prefix in ("name", "type", "id") and event in ("string", "number"):
                    header[prefix] = value
                elif prefix == "messages" and event == "start_array":
                    break
            else:
                raise DesktopFormatError(NOT_EXPORT)
        except ijson.JSONError:
            raise DesktopFormatError(BAD_JSON) from None
        kind = str(header.get("type") or "")
        if "id" not in header:
            raise DesktopFormatError("导出文件缺少群 id，请确认导出的是单个群的聊天记录")
        return ChatInfo(
            chat_id=marked_chat_id(header["id"], kind),
            title=str(header.get("name") or "未命名聊天"),
            kind=kind,
        )

    def _iter_raw(self) -> Iterator[dict]:
        builder = None
        try:
            for prefix, event, value in self._events:
                if prefix == "messages.item" and event == "start_map":
                    builder = ijson.ObjectBuilder()
                if builder is not None:
                    builder.event(event, value)
                    if prefix == "messages.item" and event == "end_map":
                        yield builder.value
                        builder = None
                elif prefix == "messages" and event == "end_array":
                    return
        except ijson.JSONError:
            raise DesktopFormatError(BAD_JSON) from None
        raise DesktopFormatError(BAD_JSON)  # 没读到 messages 数组结尾：文件被截断

    def records(self) -> Iterator[MessageRecord | TopicRecord]:
        topic_of: dict[int, int] = {}  # 只在出现第一个话题后才记录

        def resolve(reply_to) -> int:
            return topic_of.get(reply_to, GENERAL_TOPIC_ID) if reply_to is not None else GENERAL_TOPIC_ID

        for m in self._iter_raw():
            mid = m.get("id")
            if not isinstance(mid, int):
                continue
            reply_to = m.get("reply_to_message_id")
            reply_to = reply_to if isinstance(reply_to, int) else None

            if m.get("type") == "service":
                action = m.get("action")
                if action == "topic_created":
                    if not self.is_forum:
                        self.is_forum, self.first_topic_id = True, mid
                        yield TopicRecord(GENERAL_TOPIC_ID, "General")
                    topic_of[mid] = mid
                    yield TopicRecord(mid, str(m.get("title") or f"话题 {mid}"))
                elif action == "topic_edit" and self.is_forum and m.get("new_title"):
                    tid = resolve(reply_to)
                    topic_of[mid] = tid
                    yield TopicRecord(tid, str(m["new_title"]))
                continue
            if m.get("type") != "message":
                continue

            topic_id = None
            if self.is_forum:
                topic_id = resolve(reply_to)
                topic_of[mid] = topic_id

            reactions = tuple(r for r in map(desktop_reaction, m.get("reactions") or []) if r is not None)
            yield MessageRecord(
                msg_id=mid,
                date=self._date(m),
                sender=str(m.get("from") or m.get("author") or "匿名"),
                text=flatten_text(m.get("text")),
                media=media_label(m),
                reply_to=reply_to,
                topic_id=topic_id,
                reactions=reactions,
            )

    def _date(self, m: dict) -> int:
        raw = m.get("date_unixtime")
        if raw:
            return int(raw)
        # 老版本导出只有本地时间字符串，按部署时区解释
        return int(datetime.fromisoformat(m["date"]).replace(tzinfo=self._tz).timestamp())
