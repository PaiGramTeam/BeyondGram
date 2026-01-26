from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import CallbackContext
from telegram.ext import filters

from core.config import config
from core.plugin import Plugin, handler
from core.services.task.models import Task as SignUser, TaskStatusEnum
from core.services.task.services import SignServices
from core.services.users.services import UserAdminService
from plugins.tools.genshin import GenshinHelper, PlayerNotFoundError, CookiesNotFoundError
from plugins.tools.sign import SignSystem
from utils.log import logger


class Sign(Plugin):
    """每日签到"""

    CHECK_SERVER, COMMAND_RESULT = range(10400, 10402)

    def __init__(
        self,
        genshin_helper: GenshinHelper,
        sign_service: SignServices,
        user_admin_service: UserAdminService,
        sign_system: SignSystem,
    ):
        self.user_admin_service = user_admin_service
        self.sign_service = sign_service
        self.sign_system = sign_system
        self.genshin_helper = genshin_helper

    async def _process_auto_sign(self, user_id: int, player_id: int, offset: int, chat_id: int, method: str) -> str:
        try:
            c = await self.genshin_helper.get_genshin_client(user_id, player_id=player_id, offset=offset)
            player_id = c.player_id
        except (PlayerNotFoundError, CookiesNotFoundError):
            return config.notice.user_not_found
        user: SignUser = await self.sign_service.get_by_user_id(user_id, player_id)
        if user:
            if method == "关闭":
                await self.sign_service.remove(user)
                return f"UID {player_id} 关闭自动签到成功"
            if method == "开启":
                if user.chat_id == chat_id:
                    return f"UID {player_id} 自动签到已经开启过了"
                user.chat_id = chat_id
                user.status = TaskStatusEnum.STATUS_SUCCESS
                await self.sign_service.update(user)
                return f"UID {player_id} 修改自动签到通知对话成功"
        elif method == "关闭":
            return f"UID {player_id} 您还没有开启自动签到"
        elif method == "开启":
            user = self.sign_service.create(user_id, player_id, chat_id, TaskStatusEnum.STATUS_SUCCESS)
            await self.sign_service.add(user)
            return f"UID {player_id} 开启自动签到成功"

    @handler.command(command="sign", cookie=True, block=False)
    @handler.message(filters=filters.Regex("^每日签到(.*)"), cookie=True, block=False)
    @handler.command(command="start", filters=filters.Regex("sign$"), block=False)
    async def command_start(self, update: Update, context: CallbackContext) -> None:
        user_id = await self.get_real_user_id(update)
        uid, offset = self.get_real_uid_or_offset(update)
        message = update.effective_message
        args = self.get_args(context)
        if len(args) >= 1:
            msg = None
            if args[0] == "开启自动签到":
                if await self.user_admin_service.is_admin(user_id):
                    msg = await self._process_auto_sign(user_id, uid, offset, message.chat_id, "开启")
                else:
                    msg = await self._process_auto_sign(user_id, uid, offset, user_id, "开启")
            elif args[0] == "关闭自动签到":
                msg = await self._process_auto_sign(user_id, uid, offset, message.chat_id, "关闭")
            if msg:
                self.log_user(update, logger.info, "自动签到命令请求 || 参数 %s", args[0])
                reply_message = await message.reply_text(msg)
                if filters.ChatType.GROUPS.filter(message):
                    self.add_delete_message_job(reply_message, delay=30)
                    self.add_delete_message_job(message, delay=30)
                return
        self.log_user(update, logger.info, "每日签到命令请求")
        if filters.ChatType.GROUPS.filter(message):
            self.add_delete_message_job(message)
        async with self.genshin_helper.genshin(user_id, player_id=uid, offset=offset) as client:
            await message.reply_chat_action(ChatAction.TYPING)
            sign_text = await self.sign_system.start_sign(client)
        reply_message = await message.reply_text(sign_text)
        if filters.ChatType.GROUPS.filter(reply_message):
            self.add_delete_message_job(reply_message)
