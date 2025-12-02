from collections import OrderedDict

import ujson
from datetime import datetime, timedelta
from enum import Enum
from io import BytesIO
from typing import Any, List, Optional, Dict

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, PrivateAttr

__all__ = (
    "ArtworkImage",
    "PostInfo",
    "LiveInfo",
    "LiveCode",
    "LiveCodeHoYo",
    "PostTypeEnum",
    "PostRecommend",
    "HoYoPostMultiLang",
)

GAME_ID_MAP = {"endfield": 3}
GAME_STR_MAP = {v: k for k, v in GAME_ID_MAP.items()}


class ArtworkImage(BaseModel):
    art_id: int
    page: int = 0
    data: bytes = b""
    file_name: Optional[str] = None
    file_extension: Optional[str] = None
    is_error: bool = False
    url: str = ""

    @property
    def is_video(self) -> bool:
        return self.file_extension == "mp4"

    @property
    def is_gif(self) -> bool:
        return self.file_extension == "gif"

    @property
    def format(self) -> Optional[str]:
        if not self.is_error:
            try:
                with BytesIO(self.data) as stream, Image.open(stream) as im:
                    return im.format
            except UnidentifiedImageError:
                pass
        return None

    @staticmethod
    def gen(*args, **kwargs) -> List["ArtworkImage"]:
        data = [ArtworkImage(*args, **kwargs)]
        if data[0].file_extension and data[0].file_extension in ["gif", "mp4"]:
            return data
        try:
            with BytesIO(data[0].data) as stream, Image.open(stream) as image:
                width, height = image.size
                min_px = min(width, height)
                if min_px == height:
                    bio = BytesIO()
                    image = image.convert("RGB")
                    image.save(bio, "JPEG", quality=95)
                    kwargs["data"] = bio.getvalue()
                    kwargs["file_extension"] = "jpg"
                    return [ArtworkImage(*args, **kwargs)]
                max_px = min_px * 2.2
                need_crop = height if min_px == width else width
                crop_num = int(need_crop / max_px)
                u = need_crop % max_px
                if u > (max_px / 2):
                    crop_num += 1
                new_data = []
                for i in range(crop_num):
                    h = max_px * i
                    if min_px == width:
                        box = (0, h, width, height if crop_num == i + 1 else (h + max_px))
                    else:
                        box = (h, 0, width if crop_num == i + 1 else (h + max_px), height)
                    slice_image = image.crop(box)
                    bio = BytesIO()
                    slice_image = slice_image.convert("RGB")
                    slice_image.save(bio, "JPEG", quality=95)
                    kwargs["data"] = bio.getvalue()
                    kwargs["file_extension"] = "jpg"
                    new_data.append(ArtworkImage(*args, **kwargs))
                return new_data
        except UnidentifiedImageError:
            return data


class PostRecommend(BaseModel):
    hoyolab: bool = False
    gids: int
    post_id: int
    subject: str = ""

    @staticmethod
    def parse(data: Dict, gids: int, hoyolab: bool = False):
        _post = data.get("item")
        post_id = _post.get("id")
        subject = _post.get("title", "")
        return PostRecommend(hoyolab=hoyolab, gids=gids, post_id=post_id, subject=subject)

    @property
    def type_enum(self) -> "PostTypeEnum":
        return PostTypeEnum.CN if not self.hoyolab else PostTypeEnum.OS

    @property
    def short_name(self) -> str:
        return GAME_STR_MAP.get(self.gids)

    def get_url(self) -> str:
        if not self.hoyolab:
            return f"https://www.skland.com/article?id={self.post_id}"
        return f"https://www.skport.com/article?id={self.post_id}"

    def get_fix_url(self) -> str:
        url = self.get_url()
        return url.replace(".com/", ".pp.ua/")


class PostInfo(PostRecommend):
    _data: dict = PrivateAttr()

    user_uid: int
    image_urls: List[str]
    created_at: int
    video_urls: List[str]
    format: dict
    text_slice: List[dict]
    link_slice: List[dict]

    def __init__(self, _data: dict, **data: Any):
        super().__init__(**data)
        self._data = _data

    @classmethod
    def paste_data(cls, data: dict, hoyolab: bool = False) -> "PostInfo":
        post = data["item"]
        gids = post["gameId"]
        post_id = post["id"]
        subject = post["title"]
        image_list = post.get("imageListSlice", [])
        image_urls = list(OrderedDict.fromkeys([image["url"] for image in image_list]))
        key1, key2 = ("video", "resolution") if hoyolab else ("videoListSlice", "resolutions")
        vod_list = post.get(key1, [])
        if not isinstance(vod_list, list):
            vod_list = [vod_list]
        video_urls = [vod[key2][0]["playURL"] for vod in vod_list if vod]
        created_at = post["createdAtTs"]
        user = data["user"]  # 用户数据
        user_uid = user["id"]  # 用户ID

        content_format = ujson.loads(post.get("format", "{}"))
        text_slice = post.get("textSlice", [])
        link_slice = post.get("linkSlice", [])
        return PostInfo(
            _data=data,
            gids=gids,
            hoyolab=hoyolab,
            post_id=post_id,
            user_uid=user_uid,
            subject=subject,
            image_urls=image_urls,
            video_urls=video_urls,
            created_at=created_at,
            format=content_format,
            text_slice=text_slice,
            link_slice=link_slice,
        )

    def __getitem__(self, item):
        return self._data[item]


class LiveInfo(BaseModel):
    act_type: str
    title: str
    live_time: str
    start: datetime
    end: datetime
    remain: int
    now: datetime
    is_end: bool
    code_ver: str


class LiveCode(BaseModel):
    code: str
    to_get_time: datetime

    @property
    def text(self) -> str:
        return self.code if self.code else "XXXXXXXXXXXX"


class LiveCodeHoYo(BaseModel):
    exchange_code: str
    offline_at: datetime

    @property
    def text(self) -> str:
        return self.exchange_code if self.exchange_code else "XXXXXXXXXXXX"

    @staticmethod
    def guess_offline_at() -> datetime:
        return datetime.now().replace(hour=12, minute=0, second=0, microsecond=0) + timedelta(days=1)


class PostTypeEnum(str, Enum):
    """社区类型枚举"""

    NULL = "null"
    CN = "cn"
    OS = "os"


class HoYoPostMultiLang(BaseModel):
    lang_subject: dict
