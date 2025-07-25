from __future__ import annotations

import base64
import mimetypes
import os
import random
import re
from copy import deepcopy
from datetime import datetime, UTC
from typing import Optional, TYPE_CHECKING, Dict, Any, Union, List
from urllib import parse

import httpx
import orjson as json
from PIL import Image as PILImage
from attrs import define
from filetype import filetype
from japanera import EraDate
from tenacity import retry, stop_after_attempt

from core.logger import Logger
from core.utils.cache import random_cache_path

if TYPE_CHECKING:
    from core.builtins.session.info import SessionInfo


class BaseElement:

    @classmethod
    def __name__(cls):
        return cls.__name__


@define
class PlainElement(BaseElement):
    """
    文本元素。

    :param text: 文本。
    """

    text: str
    disable_joke: bool = False

    @classmethod
    def assign(cls, *texts: Any, disable_joke: bool = False):
        """
        :param texts: 文本内容。
        :param disable_joke: 是否禁用玩笑功能。（默认为False）
        """
        text = "".join([str(x) for x in texts])
        disable_joke = bool(disable_joke)
        return deepcopy(cls(text=text, disable_joke=disable_joke))

    def kecode(self):
        return f"[KE:plain,text={self.text}]"

    def __str__(self):
        return self.text


@define
class URLElement(BaseElement):
    """
    URL元素。

    :param url: URL。
    """

    url: str
    applied_mm: bool | None = None
    applied_md_format: bool = False
    md_format_name: Optional[str] = None

    @classmethod
    def assign(
            cls,
            url: str,
            use_mm: bool | None = None,
            md_format: bool = False,
            md_format_name: Optional[str] = None):
        """
        :param url: URL。
        :param use_mm: 是否使用链接跳板，覆盖全局设置。（默认为 None，为 None 时将根据客户端情况选择是否使用跳板）
        :param md_format: 是否使用Markdown格式。（默认为False）
        :param md_format_name: Markdown格式的链接名称。（默认为None，使用URL本身）
        """
        if use_mm:
            mm_url = "https://mm.teahouse.team/?source=akaribot&rot13=%s"
            rot13 = str.maketrans(
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
                "nopqrstuvwxyzabcdefghijklmNOPQRSTUVWXYZABCDEFGHIJKLM",
            )
            url = mm_url % parse.quote(parse.unquote(url).translate(rot13))
        if md_format:
            url = f"[{md_format_name if md_format_name else url}]({url})"
        return deepcopy(cls(url=url, applied_mm=use_mm, applied_md_format=md_format, md_format_name=md_format_name))

    def kecode(self):
        return f"[KE:plain,text={self.url}]"

    def __str__(self):
        return self.url


@define
class FormattedTimeElement(BaseElement):
    """
    格式化时间消息。

    :param timestamp: UTC时间戳。
    """

    timestamp: float
    date: bool = True
    iso: bool = False
    time: bool = True
    seconds: bool = True
    timezone: bool = True

    def to_str(self, session_info: Optional[SessionInfo] = None):
        ftime_template = []
        if session_info:
            dt = datetime.fromtimestamp(self.timestamp, UTC) + session_info.timezone_offset
            if self.date:
                if self.iso:
                    ftime_template.append(session_info.locale.t("time.date.iso.format"))
                elif session_info.locale.locale == "ja_jp":
                    era_date = EraDate.from_date(dt).strftime(session_info.locale.t("time.date.format"))
                    ftime_template.append(era_date)
                else:
                    ftime_template.append(session_info.locale.t("time.date.format"))
            if self.time:
                if self.seconds:
                    ftime_template.append(session_info.locale.t("time.time.format"))
                else:
                    ftime_template.append(session_info.locale.t("time.time.nosec.format"))
            if self.timezone:
                if session_info._tz_offset == "+0":
                    ftime_template.append("(UTC)")
                else:
                    ftime_template.append(f"(UTC{session_info._tz_offset})")

            return dt.strftime(" ".join(ftime_template))

        if self.date:
            if self.iso:
                ftime_template.append("%Y-%m-%d")
            else:
                ftime_template.append("%B %d, %Y")
        if self.time:
            if self.seconds:
                ftime_template.append("%H:%M:%S")
            else:
                ftime_template.append("%H:%M")
        if self.timezone:
            tz_template = "(UTC)"
            offset = datetime.now().astimezone().utcoffset()
            if offset:
                total_min = int(offset.total_seconds() // 60)
                sign = "+" if total_min >= 0 else "-"
                abs_min = abs(total_min)
                hours = abs_min // 60
                mins = abs_min % 60

                if mins == 0:
                    tz_template = f"(UTC{sign}{hours})" if hours != 0 else "(UTC)"
                else:
                    tz_template = f"(UTC{sign}{hours}:{mins:02d})"

            ftime_template.append(tz_template)
        return datetime.fromtimestamp(self.timestamp).strftime(" ".join(ftime_template))

    def kecode(self):
        return f"[KE:plain,text={self.to_str()}]"

    def __str__(self):
        return self.to_str()

    @classmethod
    def assign(
        cls,
        timestamp: float,
        date: bool = True,
        iso: bool = False,
        time: bool = True,
        seconds: bool = True,
        timezone: bool = True,
    ):
        """
        :param timestamp: UTC时间戳。
        :param date: 是否显示日期。（默认为True）
        :param iso: 是否以ISO格式显示。（默认为False）
        :param time: 是否显示时间。（默认为True）
        :param seconds: 是否显示秒。（默认为True）
        :param timezone: 是否显示时区。（默认为True）
        """
        return deepcopy(
            cls(
                timestamp=timestamp,
                date=date,
                iso=iso,
                time=time,
                seconds=seconds,
                timezone=timezone,
            )
        )


@define
class I18NContextElement(BaseElement):
    """
    带有多语言的消息。
    """

    key: str
    disable_joke: bool
    kwargs: Dict[str, Any]

    @classmethod
    def assign(cls, key: str, disable_joke: bool = False, **kwargs: Any):
        """
        :param key: 多语言的键名。
        :param disable_joke: 是否禁用玩笑功能。（默认为False）
        :param kwargs: 多语言中的变量。
        """
        return deepcopy(cls(key=key, disable_joke=disable_joke, kwargs=kwargs))

    def kecode(self):
        if self.kwargs:
            params = ",".join(f"{k}={v}" for k, v in self.kwargs.items())
            return f"[KE:i18n,i18nkey={self.key},{params}]"
        return f"[KE:i18n,i18nkey={self.key}]"

    def __str__(self):
        if self.kwargs:
            params = ",".join(f"{k}={v}" for k, v in self.kwargs.items())
            return f"{{I18N:{self.key},{params}}}"
        return f"{{I18N:{self.key}}}"


@define
class ImageElement(BaseElement):
    """
    图片消息。

    :param path: 图片路径。
    :param headers: 获取图片时的请求头。
    """

    path: str
    need_get: bool = False
    headers: Optional[Dict[str, Any]] = None
    cached_b64: Optional[str] = None

    @classmethod
    def assign(
        cls, path: Union[str, PILImage.Image], headers: Optional[Dict[str, Any]] = None
    ):
        """
        :param path: 图片路径。
        :param headers: 获取图片时的请求头。
        """
        need_get = False
        if isinstance(path, PILImage.Image):
            save = f"{random_cache_path()}.png"
            path.convert("RGBA").save(save)
            path = save
        elif re.match("^https?://.*", path):
            need_get = True
        elif "base64" in path:
            _, encoded_img = path.split(",", 1)
            img_data = base64.b64decode(encoded_img)

            save = f"{random_cache_path()}.png"
            with open(save, "wb") as img_file:
                img_file.write(img_data)
            path = save
        return deepcopy(cls(path, need_get, headers))

    async def get(self):
        """
        获取图片。
        """
        if self.need_get:
            return os.path.abspath(await self.get_image())
        return os.path.abspath(self.path)

    @retry(stop=stop_after_attempt(3))
    async def get_image(self):
        """
        从网络下载图片。
        """
        url = self.path
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=20.0, headers=self.headers)
            raw = resp.content
            ft = filetype.match(raw).extension
            img_path = f"{random_cache_path()}.{ft}"
            with open(img_path, "wb+") as image_cache:
                image_cache.write(raw)
            return img_path

    async def get_base64(self, mime: bool = False):
        file = await self.get()

        with open(file, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("UTF-8")
        self.cached_b64 = img_b64
        Logger.debug(f"ImageElement: Cached base64 for {file}")
        if mime:
            mime_type, _ = mimetypes.guess_type(file)
            if not mime_type:
                mime_type = 'application/octet-stream'
            self.cached_b64 = f"data:{mime_type};base64,{img_b64}"
            return self.cached_b64
        return img_b64

    async def add_random_noise(self) -> "ImageElement":
        image = PILImage.open(await self.get())
        image = image.convert("RGBA")

        noise_image = PILImage.new("RGBA", (50, 50))
        for i in range(50):
            for j in range(50):
                noise_image.putpixel((i, j), (i, j, i, random.randint(0, 1)))

        image.alpha_composite(noise_image)

        save = f"{random_cache_path()}.png"
        image.save(save)
        return ImageElement.assign(save)

    def kecode(self):
        if self.headers:
            headers_b64 = base64.b64encode(json.dumps(self.headers)).decode("utf-8")
            return f"[KE:image,path={self.path},headers={headers_b64}]"
        return f"[KE:image,path={self.path}]"

    async def to_pil_image(self) -> PILImage.Image:
        """
        将图片元素转换为PIL Image对象。
        """
        path = self.path
        if self.need_get:
            path = await self.get_image()
        return PILImage.open(path)

    def __str__(self):
        return f"Image(path={self.path})"


@define
class VoiceElement(BaseElement):
    """
    语音消息。

    :param path: 语音路径。
    """

    path: str

    @classmethod
    def assign(cls, path: str):
        """
        :param path: 语音路径。
        """
        return deepcopy(cls(path))

    def kecode(self):
        return f"[KE:voice,path={self.path}]"


@define
class MentionElement(BaseElement):
    """
    提及元素。

    :param id: 提及用户ID。
    :param client: 平台。
    """

    client: str
    id: str

    @classmethod
    def assign(cls, user_id: str):
        """
        :param user_id: 用户id。
        """
        return deepcopy(cls(client=user_id.split("|")[0], id=user_id.split("|")[-1]))

    def kecode(self):
        return f"[KE:mention,userid={self.client}|{self.id}]"

    def __str__(self):
        return f"<AT:{self.client}|{self.id}>"


@define
class EmbedFieldElement(BaseElement):
    """
    Embed字段。

    :param name: 字段名。
    :param value: 字段值。
    :param inline: 是否内联。（默认为False）
    """

    name: str
    value: str
    inline: bool = False

    @classmethod
    def assign(cls, name: str, value: str, inline: bool = False):
        """
        :param name: 字段名。
        :param value: 字段值。
        :param inline: 是否内联。（默认为False）
        """
        return deepcopy(cls(name=name, value=value, inline=inline))

    def __str__(self):
        return f'[EmbedField:{self.name},{self.value},{self.inline}]'


@define
class EmbedElement(BaseElement):
    """
    Embed消息。
    :param title: 标题。
    :param description: 描述。
    :param url: 跳转 URL。
    :param color: 颜色。
    :param image: 图片。
    :param thumbnail: 缩略图。
    :param author: 作者。
    :param footer: 页脚。
    :param fields: 字段。
    """

    title: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    timestamp: float = datetime.now().timestamp()
    color: int = 0x0091FF
    image: Optional[ImageElement] = None
    thumbnail: Optional[ImageElement] = None
    author: Optional[str] = None
    footer: Optional[str] = None
    fields: Optional[List[EmbedFieldElement]] = None

    @classmethod
    def assign(
        cls,
        title: Optional[str] = None,
        description: Optional[str] = None,
        url: Optional[str] = None,
        timestamp: float = datetime.now().timestamp(),
        color: int = 0x0091FF,
        image: Optional[ImageElement] = None,
        thumbnail: Optional[ImageElement] = None,
        author: Optional[str] = None,
        footer: Optional[str] = None,
        fields: Optional[List[EmbedFieldElement]] = None,
    ):
        return deepcopy(
            cls(
                title=title,
                description=description,
                url=url,
                timestamp=timestamp,
                color=color,
                image=image,
                thumbnail=thumbnail,
                author=author,
                footer=footer,
                fields=fields,
            )
        )

    def to_message_chain(self, session_info: Optional[SessionInfo] = None):
        """
        将Embed转换为消息链。
        """
        text_lst = []
        if self.title:
            text_lst.append(self.title)
        if self.description:
            text_lst.append(self.description)
        if self.url:
            text_lst.append(self.url)
        if self.fields:
            for f in self.fields:
                if session_info:
                    text_lst.append(f"{session_info.locale.t_str(f.name)}{session_info.locale.t(
                        "message.colon")}{session_info.locale.t_str(f.value)}")
                else:
                    text_lst.append(f"{f.name}: {f.value}")
        if self.author:
            if session_info:
                text_lst.append(f"{session_info.locale.t("message.embed.author")}{
                    session_info.locale.t_str(self.author)}")
            else:
                text_lst.append(f"Author: {self.author}")
        if self.footer:
            if session_info:
                text_lst.append(session_info.locale.t_str(self.footer))
            else:
                text_lst.append(self.footer)
        message_chain = []
        if text_lst:
            message_chain.append(PlainElement.assign("\n".join(text_lst)))
        if self.image:
            message_chain.append(self.image)
        return message_chain

    def __str__(self):
        return str(self.to_message_chain())


__all__ = [
    "BaseElement",
    "PlainElement",
    "URLElement",
    "FormattedTimeElement",
    "I18NContextElement",
    "ImageElement",
    "VoiceElement",
    "EmbedFieldElement",
    "EmbedElement",
    "MentionElement",
]
