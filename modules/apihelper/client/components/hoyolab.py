from typing import List, Dict

from .hyperion import HyperionBase
from ..base.hyperionrequest import HyperionRequest
from ...models.genshin.hyperion import PostInfo, ArtworkImage, PostRecommend

__all__ = ("Hoyolab",)


class Hoyolab(HyperionBase):
    POST_FULL_URL = "https://zonai.skport.com/web/v1/item"
    GET_NEW_LIST_URL = "https://zonai.skport.com/web/v1/home/index"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/90.0.4430.72 Safari/537.36"
    )

    def __init__(self, *args, **kwargs):
        self.client = HyperionRequest(headers=self.get_headers(), need_sign=False, *args, **kwargs)

    def get_headers(self, lang: str = ""):
        lang = lang or self.LANG
        return {
            "User-Agent": self.USER_AGENT,
            "sk-language": lang,
        }

    async def get_official_recommended_posts(self, gids: int, type_id: int) -> List[PostRecommend]:
        return await self.get_new_list_recommended_posts(gids, type_id, 10)

    async def get_post_info(self, post_id: int) -> PostInfo:
        params = {"id": post_id}
        response = await self.client.get(self.POST_FULL_URL, params=params)
        return PostInfo.paste_data(response, hoyolab=True)

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
        return await self.client.get(url=self.GET_NEW_LIST_URL, params=params, headers=self.get_headers(lang=lang))

    async def get_new_list_recommended_posts(
        self, gids: int, type_id: int, page_size: int = 20, lang: str = ""
    ) -> List[PostRecommend]:
        resp = await self.get_new_list(gids, type_id, page_size, lang)
        data = resp["list"]
        return [PostRecommend.parse(i, gids=gids) for i in data]

    async def close(self):
        await self.client.shutdown()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
