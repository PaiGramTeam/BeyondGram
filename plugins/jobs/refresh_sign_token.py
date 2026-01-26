from telegram.ext import CallbackContext

from hypernet import EndfieldClient

from core.plugin import Plugin, job
from modules.errorpush import SentryClient
from utils.log import logger

__all__ = ("RefreshSignTokenPlugin",)


class RefreshSignTokenPlugin(Plugin):

    @job.run_custom(job_kwargs={"trigger": "cron", "minute": "1"}, name="RefreshSignTokenJob")
    @SentryClient.monitor(monitor_slug="RefreshSignTokenJob")
    async def refresh(self, _: CallbackContext):
        logger.info("正在刷新签名 Token")
        await EndfieldClient.get_sign_token(True)
        logger.success("刷新签名 Token 成功")
