from gram_core.base_service import BaseService
from gram_core.basemodel import RegionEnum
from gram_core.services.cookies.error import CookieServiceError
from gram_core.services.cookies.models import CookiesStatusEnum, CookiesDataBase as Cookies
from gram_core.services.cookies.services import (
    CookiesService,
    PublicCookiesService as BasePublicCookiesService,
    NeedContinue,
)

from hypernet import EndfieldClient, Region
from hypernet.errors import InvalidCookies, TooManyRequests, BadRequest as SimnetBadRequest

from utils.log import logger

__all__ = ("CookiesService", "PublicCookiesService")


class PublicCookiesService(BaseService, BasePublicCookiesService):
    async def initialize(self) -> None:
        logger.info("正在初始化公共Cookies池")
        await self.refresh()
        logger.success("刷新公共Cookies池成功")

    async def check_public_cookie(self, region: RegionEnum, cookies: Cookies, public_id: int):  # skipcq: PY-R1000 #
        if region == RegionEnum.HYPERION:
            client = EndfieldClient(cookies=cookies.data, region=Region.CHINESE)
        elif region == RegionEnum.HOYOLAB:
            client = EndfieldClient(cookies=cookies.data, region=Region.OVERSEAS, lang="zh-cn")
        else:
            raise CookieServiceError
        try:
            if client.account_id is None:
                raise RuntimeError("account_id not found")
            await client.check_lab_user()
        except InvalidCookies as exc:
            logger.warning("Cookies无效 ")
            logger.exception(exc)
            cookies.status = CookiesStatusEnum.INVALID_COOKIES
            await self._repository.update(cookies)
            await self._cache.delete_public_cookies(cookies.user_id, region)
            raise NeedContinue
        except TooManyRequests:
            logger.warning("用户 [%s] 查询次数太多或操作频繁", public_id)
            cookies.status = CookiesStatusEnum.TOO_MANY_REQUESTS
            await self._repository.update(cookies)
            await self._cache.delete_public_cookies(cookies.user_id, region)
            raise NeedContinue
        except SimnetBadRequest as exc:
            if "invalid content type" in exc.message:
                raise exc
            logger.warning("用户 [%s] 获取账号信息发生错误，错误信息为", public_id)
            logger.exception(exc)
            await self._cache.delete_public_cookies(cookies.user_id, region)
            raise NeedContinue
        except RuntimeError as exc:
            if "account_id not found" in str(exc):
                cookies.status = CookiesStatusEnum.INVALID_COOKIES
                await self._repository.update(cookies)
                await self._cache.delete_public_cookies(cookies.user_id, region)
                raise NeedContinue
            raise exc
        except Exception as exc:
            await self._cache.delete_public_cookies(cookies.user_id, region)
            raise exc
        finally:
            await client.shutdown()
