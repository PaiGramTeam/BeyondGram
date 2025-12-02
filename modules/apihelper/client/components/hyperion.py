import asyncio
import os
import re
from abc import abstractmethod, ABC
from typing import List, Tuple, Dict

from ..base.hyperionrequest import HyperionRequest
from ...models.genshin.hyperion import (
    PostInfo,
    ArtworkImage,
    PostRecommend,
    PostTypeEnum,
)

__all__ = (
    "HyperionBase",
    "Hyperion",
)


class HyperionBase(ABC):
    LANG = "zh_Hans"

    @staticmethod
    def extract_post_id(text: str) -> Tuple[int, PostTypeEnum]:
        """
        :param text:
            # https://www.skland.com/article?id=3486206
            # https://www.skport.com/article?id=1985672867407196028
        :return: post_id
        """
        rgx = re.compile(r"(?:bbs|www\.)?(?:skland|skport)\.(.*)/article\?id=(?P<article_id>\d+)")
        matches = rgx.search(text)
        if matches is None:
            return -1, PostTypeEnum.NULL
        entries = matches.groupdict()
        if entries is None:
            return -1, PostTypeEnum.NULL
        try:
            art_id = int(entries.get("article_id"))
            post_type = PostTypeEnum.CN if "skland" in text else PostTypeEnum.OS
        except (IndexError, ValueError, TypeError):
            return -1, PostTypeEnum.NULL
        return art_id, post_type

    @staticmethod
    def get_images_params() -> dict:
        # style/fullScreen
        # style/fullScreenLandscape
        # style/thirdScreen
        return {"x-oss-process": "style/fullScreen"}

    @staticmethod
    async def get_images_by_post_id_tasks(task_list: List) -> List[ArtworkImage]:
        art_list = []
        result_lists = await asyncio.gather(*task_list)
        for result_list in result_lists:
            for result in result_list:
                if isinstance(result, ArtworkImage):
                    art_list.append(result)

        def take_page(elem: ArtworkImage):
            return elem.page

        art_list.sort(key=take_page)
        return art_list

    @staticmethod
    async def download_image(client: "HyperionRequest", art_id: int, url: str, page: int = 0) -> List[ArtworkImage]:
        filename = os.path.basename(url.split("?")[0])
        _, _file_extension = os.path.splitext(filename)
        file_extension = _file_extension.lower()
        is_image = (
            file_extension in ".jpg"
            or file_extension in ".jpeg"
            or file_extension in ".png"
            or file_extension in ".webp"
        )
        response = await client.get(
            url, params=HyperionBase.get_images_params() if is_image else None, need_sign=False, de_json=False
        )
        return ArtworkImage.gen(
            art_id=art_id,
            page=page,
            file_name=filename,
            file_extension=file_extension.split(".")[-1],
            data=response.content,
            url=url,
        )

    @abstractmethod
    async def get_new_list(self, gids: int, type_id: int, page_size: int = 20, lang: str = "") -> Dict:
        """获取最新帖子"""

    @abstractmethod
    async def get_new_list_recommended_posts(
        self, gids: int, type_id: int, page_size: int = 20, lang: str = ""
    ) -> List[PostRecommend]:
        """获取最新帖子"""

    @abstractmethod
    async def get_official_recommended_posts(self, gids: int, type_id: int) -> List[PostRecommend]:
        """获取官方推荐帖子"""

    @abstractmethod
    async def get_post_info(self, post_id: int) -> PostInfo:
        """获取帖子信息"""

    @abstractmethod
    async def get_images_by_post_id(self, post_id: int) -> List[ArtworkImage]:
        """获取帖子图片"""

    @abstractmethod
    async def close(self):
        """关闭请求会话"""


class Hyperion(HyperionBase):
    """米忽悠bbs相关API请求

    该名称来源于米忽悠的安卓BBS包名结尾，考虑到大部分重要的功能确实是在移动端实现了
    """

    POST_FULL_URL = "https://zonai.skland.com/web/v1/item"
    GET_NEW_LIST_URL = "https://zonai.skland.com/web/v1/home/index"

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/90.0.4430.72 Safari/537.36"
    )

    def __init__(self, *args, **kwargs):
        self.client = HyperionRequest(headers=self.get_headers(), *args, **kwargs)

    def get_headers(self):
        return {"User-Agent": self.USER_AGENT}

    async def get_official_recommended_posts(self, gids: int, type_id: int) -> List[PostRecommend]:
        return await self.get_new_list_recommended_posts(gids, type_id)

    async def get_post_info(self, post_id: int) -> PostInfo:
        params = {"id": post_id}
        response = await self.client.get(self.POST_FULL_URL, params=params)
        return PostInfo.paste_data(response)

    async def get_images_by_post_id(self, post_id: int) -> List[ArtworkImage]:
        post_info = await self.get_post_info(post_id)
        task_list = [
            self._download_image(post_info.post_id, post_info.image_urls[page], page)
            for page in range(len(post_info.image_urls))
        ]
        return await self.get_images_by_post_id_tasks(task_list)

    async def _download_image(self, art_id: int, url: str, page: int = 0) -> List[ArtworkImage]:
        return await self.download_image(self.client, art_id, url, page)

    async def get_new_list(self, gids: int, type_id: int, page_size: int = 10, lang: str = "") -> Dict:
        params = {"gameId": gids, "pageSize": page_size, "cateId": type_id, "sortType": "2"}
        return await self.client.get(url=self.GET_NEW_LIST_URL, params=params)

    async def get_new_list_recommended_posts(
        self, gids: int, type_id: int, page_size: int = 10, lang: str = ""
    ) -> List[PostRecommend]:
        resp = await self.get_new_list(gids, type_id, page_size)
        data = resp["list"]
        return [PostRecommend.parse(i, gids=gids) for i in data]

    async def close(self):
        await self.client.shutdown()
