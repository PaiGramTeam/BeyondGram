import contextlib
from datetime import datetime
from typing import Dict, Optional, List, TYPE_CHECKING

from arkowrapper import ArkoWrapper
from hypernet import EndfieldClient, Region
from hypernet.client.cookies import CookiesModel
from hypernet.errors import DataNotPublic, InvalidCookies, BadRequest as SimnetBadRequest
from hypernet.models.lab.game_role import GameRoleBindingRole as Account
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, TelegramObject
from telegram.ext import ConversationHandler, filters
from telegram.helpers import escape_markdown

from core.basemodel import RegionEnum
from core.plugin import Plugin, conversation, handler
from core.services.cookies.models import CookiesDataBase as Cookies, CookiesStatusEnum
from core.services.cookies.services import CookiesService
from core.services.players.models import PlayersDataBase as Player, PlayerInfoSQLModel
from core.services.players.services import PlayersService, PlayerInfoService
from utils.log import logger

if TYPE_CHECKING:
    from telegram import Update, Message
    from telegram.ext import ContextTypes

__all__ = ("AccountCookiesPlugin",)


class AccountIdNotFound(Exception):
    pass


class AccountCookiesPluginDeviceData(TelegramObject):
    device_id: str = ""
    device_fp: str = ""
    device_name: Optional[str] = None


class AccountCookiesPluginData(TelegramObject):
    region: RegionEnum = RegionEnum.NULL
    cookies: dict = {}
    account_id: int = 0
    # player_id: int = 0
    genshin_account: Optional[Account] = None
    genshin_accounts: List[Account] = []

    def reset(self):
        self.region = RegionEnum.NULL
        self.cookies = {}
        self.account_id = 0
        self.genshin_account = None
        self.genshin_accounts = []


CHECK_SERVER, INPUT_COOKIES, INPUT_PLAYERS, COMMAND_RESULT = range(10100, 10104)


class AccountCookiesPlugin(Plugin.Conversation):
    """Cookie绑定"""

    def __init__(
        self,
        players_service: PlayersService = None,
        cookies_service: CookiesService = None,
        player_info_service: PlayerInfoService = None,
    ):
        self.cookies_service = cookies_service
        self.players_service = players_service
        self.player_info_service = player_info_service

    # noinspection SpellCheckingInspection
    @staticmethod
    def parse_cookie(cookie: Dict[str, str]) -> Dict[str, str]:
        cookies = {}

        v1_keys = ["hg_token", "hg_id", "cred"]

        for k in v1_keys:
            cookies[k] = cookie.get(k)

        return {k: v for k, v in cookies.items() if v is not None}

    async def _parse_args(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> Optional[int]:
        args = self.get_args(context)
        account_cookies_plugin_data: AccountCookiesPluginData = context.chat_data.get("account_cookies_plugin_data")
        if len(args) < 2:
            return None
        regions = {"森空岛": RegionEnum.HYPERION, "skport": RegionEnum.HOYOLAB}
        if args[0] not in regions:
            return None
        cookies = " ".join(args[1:])
        account_cookies_plugin_data.region = regions[args[0]]
        if ret := await self.parse_cookies(update, context, cookies):
            return ret
        return await self.check_cookies(update, context)

    @staticmethod
    async def quit_conversation(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> int:
        message = update.effective_message
        context.chat_data.pop("bind_account_plugin_data", None)
        context.chat_data.pop("account_cookies_plugin_data", None)
        await message.reply_text("退出任务", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    @staticmethod
    async def has_another_conversation(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> Optional[int]:
        if context.chat_data.get("bind_account_plugin_data") is not None:
            message = update.effective_message
            await message.reply_text("你已经有一个绑定任务在进行中，请先退出后再试")
            return ConversationHandler.END
        return None

    @conversation.fallback
    @handler.command(command="cancel", block=False)
    async def cancel(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> int:
        return await self.quit_conversation(update, context)

    @conversation.entry_point
    @handler.command(command="setcookie", filters=filters.ChatType.PRIVATE, block=False)
    @handler.command(command="setcookies", filters=filters.ChatType.PRIVATE, block=False)
    @handler.command(command="start", filters=filters.ChatType.PRIVATE & filters.Regex("set_cookie$"), block=False)
    async def command_start(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> int:
        user = update.effective_user
        message = update.effective_message
        logger.info("用户 %s[%s] 绑定账号命令请求 cookie", user.full_name, user.id)
        if await self.has_another_conversation(update, context) is not None:
            return ConversationHandler.END
        account_cookies_plugin_data: AccountCookiesPluginData = context.chat_data.get("account_cookies_plugin_data")
        if account_cookies_plugin_data is None:
            account_cookies_plugin_data = AccountCookiesPluginData()
            context.chat_data["account_cookies_plugin_data"] = account_cookies_plugin_data
        else:
            account_cookies_plugin_data.reset()

        if ret := await self._parse_args(update, context):
            return ret

        text = f'你好 {user.mention_markdown_v2()} {escape_markdown("！请选择要绑定的服务器！或回复退出取消操作")}'
        reply_keyboard = [["森空岛", "skport"], ["退出"]]
        await message.reply_markdown_v2(text, reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True))
        return CHECK_SERVER

    @conversation.state(state=CHECK_SERVER)
    @handler.message(filters=filters.TEXT & ~filters.COMMAND, block=False)
    async def check_server(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> int:
        message = update.effective_message
        account_cookies_plugin_data: AccountCookiesPluginData = context.chat_data.get("account_cookies_plugin_data")
        if message.text == "退出":
            return await self.quit_conversation(update, context)
        if message.text == "森空岛":
            region = RegionEnum.HYPERION
            bbs_name = "森空岛"
        elif message.text == "skport":
            bbs_name = "skport"
            region = RegionEnum.HOYOLAB
        else:
            await message.reply_text("选择错误，请重新选择")
            return CHECK_SERVER
        account_cookies_plugin_data.region = region
        await message.reply_text(f"请输入{bbs_name}的 Token ！或回复退出取消操作", reply_markup=ReplyKeyboardRemove())
        await message.reply_html("<b>关于如何获取 Token</b>\n\nhttps://telegra.ph/paigramteam-bot-settoken-01-26")
        return INPUT_COOKIES

    @conversation.state(state=INPUT_COOKIES)
    @handler.message(filters=filters.TEXT & ~filters.COMMAND, block=False)
    async def input_cookies(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> int:
        message = update.effective_message
        if message.text == "退出":
            return await self.quit_conversation(update, context)
        if ret := await self.parse_cookies(update, context, message.text):
            return ret
        return await self.check_cookies(update, context)

    async def parse_cookies(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE", text: str) -> Optional[int]:
        user = update.effective_user
        message = update.effective_message
        account_cookies_plugin_data: AccountCookiesPluginData = context.chat_data.get("account_cookies_plugin_data")
        try:
            # cookie str to dict
            if ";" in text:
                wrapped = (
                    ArkoWrapper(("".join(text.split("\n"))).split(";"))
                    .filter(lambda x: x != "")
                    .map(lambda x: x.strip())
                    .map(lambda x: ((y := x.split("=", 1))[0], y[1]))
                )
                cookie = {x[0]: x[1] for x in wrapped}
            else:
                cookie = {"hg_token": text.strip()}
            cookies = self.parse_cookie(cookie)
            if cookies:
                CookiesModel.model_validate(cookies)
        except (AttributeError, ValueError, IndexError) as exc:
            logger.info("用户 %s[%s] Token 解析出现错误\ntext:%s", user.full_name, user.id, message.text)
            logger.debug("解析Cookies出现错误", exc_info=exc)
            await message.reply_text("解析 Token 出现错误，请检查是否正确", reply_markup=ReplyKeyboardRemove())
            return await self.quit_conversation(update, context)
        if not cookies:
            logger.info("用户 %s[%s] Token 格式有误", user.full_name, user.id)
            await message.reply_text("Token 格式有误，请检查后重新尝试绑定", reply_markup=ReplyKeyboardRemove())
            return await self.quit_conversation(update, context)
        account_cookies_plugin_data.cookies = cookies

    async def check_cookies(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> int:
        user = update.effective_user
        message = update.effective_message
        account_cookies_plugin_data: AccountCookiesPluginData = context.chat_data.get("account_cookies_plugin_data")
        cookies = CookiesModel(**account_cookies_plugin_data.cookies)
        if account_cookies_plugin_data.region == RegionEnum.HYPERION:
            region = Region.CHINESE
        elif account_cookies_plugin_data.region == RegionEnum.HOYOLAB:
            region = Region.OVERSEAS
        else:
            logger.error("用户 %s[%s] region 异常", user.full_name, user.id)
            await message.reply_text("数据错误", reply_markup=ReplyKeyboardRemove())
            return await self.quit_conversation(update, context)
        async with EndfieldClient(cookies=cookies.to_dict(), region=region) as client:
            if not cookies.hg_token:
                await message.reply_text(
                    "检测到缺少 hg_token，请尝试添加 hg_token 后重新绑定。", reply_markup=ReplyKeyboardRemove()
                )
                return await self.quit_conversation(update, context)
            try:
                new_cookies = await client.refresh_cookies_by_hg_token()
                logger.success("用户 %s[%s] 绑定时获取所有 token 成功", user.full_name, user.id)
                cookies = CookiesModel(**new_cookies.to_dict())
            except SimnetBadRequest as exc:
                logger.warning(
                    "用户 %s[%s] 获取账号信息发生错误 [%s]%s", user.full_name, user.id, exc.ret_code, exc.original
                )
                await message.reply_text("hg_token 无效，请重新绑定。", reply_markup=ReplyKeyboardRemove())
                return await self.quit_conversation(update, context)
            except UnicodeEncodeError:
                await message.reply_text("hg_token 非法，请重新绑定。", reply_markup=ReplyKeyboardRemove())
                return await self.quit_conversation(update, context)
            try:
                if cookies.hg_id is None:
                    logger.info("正在尝试获取用户 %s[%s] hg_id", user.full_name, user.id)
                    account_info = await client.get_account_info_by_hg_token()
                    account_id = account_info.hgId
                    cookies.hg_id = account_id
                    logger.success("获取用户 %s[%s] hg_id[%s] 成功", user.full_name, user.id, account_id)
                logger.info("正在尝试获取用户 %s[%s] lab_user_id", user.full_name, user.id)
                lab_user_id = await client.get_lab_show_user_id()
                account_cookies_plugin_data.account_id = lab_user_id
                cookies.lab_user_id = lab_user_id
                logger.success("获取用户 %s[%s] lab_user_id[%s] 成功", user.full_name, user.id, lab_user_id)

                accounts = await client.get_endfield_accounts()
                genshin_accounts = []
                for account in accounts:
                    for bind in account.bindingList:
                        genshin_accounts.extend(bind.roles)
            except DataNotPublic:
                logger.info("用户 %s[%s] 账号疑似被注销", user.full_name, user.id)
                await message.reply_text("账号疑似被注销，请检查账号状态", reply_markup=ReplyKeyboardRemove())
                return await self.quit_conversation(update, context)
            except InvalidCookies:
                logger.info("用户 %s[%s] Token 已经过期", user.full_name, user.id)
                await message.reply_text(
                    "获取账号信息失败，返回 Token 已经过期，请尝试在无痕浏览器中登录获取 Token。",
                    reply_markup=ReplyKeyboardRemove(),
                )
                return await self.quit_conversation(update, context)
            except SimnetBadRequest as exc:
                logger.info(
                    "用户 %s[%s] 获取账号信息发生错误 [%s]%s", user.full_name, user.id, exc.ret_code, exc.original
                )
                await message.reply_text(
                    f"获取账号信息发生错误，错误信息为 {exc.original}，请检查 Token 或者账号是否正常",
                    reply_markup=ReplyKeyboardRemove(),
                )
                return await self.quit_conversation(update, context)
            except AccountIdNotFound:
                logger.info("用户 %s[%s] 无法获取账号ID", user.full_name, user.id)
                await message.reply_text("无法获取账号ID，请检查Cookie是否正常", reply_markup=ReplyKeyboardRemove())
                return await self.quit_conversation(update, context)
            except (AttributeError, ValueError) as exc:
                logger.warning("用户 %s[%s] Token 错误", user.full_name, user.id)
                logger.debug("用户 %s[%s] Token 错误", user.full_name, user.id, exc_info=exc)
                await message.reply_text("Token 错误，请检查是否正确", reply_markup=ReplyKeyboardRemove())
                return await self.quit_conversation(update, context)
        if account_cookies_plugin_data.account_id is None:
            await message.reply_text("无法获取账号ID，请检查Cookie是否正确或请稍后重试")
            return await self.quit_conversation(update, context)
        if not genshin_accounts:
            await message.reply_text("未找到游戏账号，请确认账号信息无误。")
            return await self.quit_conversation(update, context)
        account_cookies_plugin_data.cookies = cookies.to_dict()
        account_cookies_plugin_data.genshin_accounts = genshin_accounts
        await self.send_choose_players_message(message, genshin_accounts)
        return INPUT_PLAYERS

    async def choose_to_save_player(
        self, update: "Update", account_cookies_plugin_data: AccountCookiesPluginData
    ) -> int:
        user = update.effective_user
        message = update.effective_message
        genshin_account = account_cookies_plugin_data.genshin_account
        player_info = await self.players_service.get(
            user.id, player_id=genshin_account.uid, region=account_cookies_plugin_data.region
        )
        if player_info:
            cookies_database = await self.cookies_service.get(
                user.id, player_info.account_id, account_cookies_plugin_data.region
            )
            if cookies_database:
                await message.reply_text("警告，你已经绑定 Token，如果继续操作会覆盖当前 Token。")
        reply_keyboard = [["确认", "退出"]]
        await message.reply_text("获取角色基础信息成功，请检查是否正确！")
        logger.info(
            "用户 %s[%s] 获取账号 %s[%s] 信息成功",
            user.full_name,
            user.id,
            genshin_account.nickname,
            genshin_account.uid,
        )
        text = (
            f"*角色信息*\n"
            f"角色名称：{escape_markdown(genshin_account.nickname, version=2)}\n"
            f"角色等级：{genshin_account.level}\n"
            f"UID：`{genshin_account.uid}`\n"
            f"服务器名称：`{genshin_account.server_name}`\n"
        )
        await message.reply_markdown_v2(text, reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True))
        return COMMAND_RESULT

    @staticmethod
    async def send_choose_players_message(message: "Message", genshin_accounts: List["Account"]):
        text = "请选择要绑定的角色！"
        reply_keyboard = [[f"{escape_markdown(x.nickname, version=2)} - {x.uid}"] for x in genshin_accounts]
        reply_keyboard.append(["退出"])
        await message.reply_text(text, reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True))

    @conversation.state(state=INPUT_PLAYERS)
    @handler.message(filters=filters.TEXT & ~filters.COMMAND, block=False)
    async def input_players(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> int:
        message = update.effective_message
        account_cookies_plugin_data: AccountCookiesPluginData = context.chat_data.get("account_cookies_plugin_data")
        if message.text == "退出":
            return await self.quit_conversation(update, context)
        uid = None
        with contextlib.suppress(ValueError, IndexError):
            uid = int(message.text.split("-")[-1].strip())
        if not uid:
            await message.reply_text("选择错误，请重新选择")
            return INPUT_PLAYERS
        genshin_account = next((x for x in account_cookies_plugin_data.genshin_accounts if x.uid == uid), None)
        if not genshin_account:
            await message.reply_text("选择错误，请重新选择")
            return INPUT_PLAYERS
        account_cookies_plugin_data.genshin_account = genshin_account
        return await self.choose_to_save_player(update, account_cookies_plugin_data)

    async def update_player(self, uid: int, genshin_account: Account, region: RegionEnum, account_id: int):
        player = await self.players_service.get(uid, player_id=genshin_account.uid, region=region)
        if player:
            if player.account_id != account_id:
                player.account_id = account_id
                await self.players_service.update(player)
        else:
            player_model = Player(
                user_id=uid,
                account_id=account_id,
                player_id=genshin_account.uid,
                region=region,
                is_chosen=True,  # todo 多账号
            )
            await self.update_player_info(player_model, genshin_account.nickname)
            await self.players_service.add(player_model)

    async def update_player_info(self, player: Player, nickname: str):
        player_info = await self.player_info_service.get(player)
        if player_info is None:
            player_info = PlayerInfoSQLModel(
                user_id=player.user_id,
                player_id=player.player_id,
                nickname=nickname,
                create_time=datetime.now(),
                is_update=True,
            )  # 不添加更新时间
            await self.player_info_service.add(player_info)

    async def update_cookies(self, uid: int, account_id: int, region: RegionEnum, cookies: Dict):
        cookies_data_base = await self.cookies_service.get(uid, account_id, region)
        if cookies_data_base:
            cookies_data_base.data = cookies
            cookies_data_base.status = CookiesStatusEnum.STATUS_SUCCESS
            await self.cookies_service.update(cookies_data_base)
        else:
            cookies = Cookies(
                user_id=uid,
                account_id=account_id,
                data=cookies,
                region=region,
                status=CookiesStatusEnum.STATUS_SUCCESS,
                is_share=True,  # todo 用户可以自行选择是否将Cookies加入公共池
            )
            await self.cookies_service.add(cookies)

    @conversation.state(state=COMMAND_RESULT)
    @handler.message(filters=filters.TEXT & ~filters.COMMAND, block=False)
    async def command_result(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> int:
        user = update.effective_user
        message = update.effective_message
        account_cookies_plugin_data: AccountCookiesPluginData = context.chat_data.get("account_cookies_plugin_data")
        if message.text == "退出":
            return await self.quit_conversation(update, context)
        if message.text == "确认":
            genshin_account = account_cookies_plugin_data.genshin_account
            await self.update_player(
                user.id, genshin_account, account_cookies_plugin_data.region, account_cookies_plugin_data.account_id
            )
            await self.update_cookies(
                user.id,
                account_cookies_plugin_data.account_id,
                account_cookies_plugin_data.region,
                account_cookies_plugin_data.cookies,
            )
            logger.info("用户 %s[%s] 绑定账号成功", user.full_name, user.id)
            await message.reply_text("保存成功", reply_markup=ReplyKeyboardRemove())
            return await self.quit_conversation(update, context)
        await message.reply_text("回复错误，请重新输入")
        return COMMAND_RESULT
