from typing import Optional, TYPE_CHECKING, List
from telegram.constants import ChatAction
from telegram.ext import filters

from core.config import config
from core.plugin import Plugin, handler
from core.services.cookies.error import TooManyRequestPublicCookies
from core.services.template.models import RenderResult
from core.services.template.services import TemplateService
from gram_core.plugin.methods.inline_use_data import IInlineUseData
from plugins.tools.genshin import GenshinHelper
from utils.log import logger
from utils.uid import mask_number

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes
    from hypernet.models.endfield.chronicle.card import EndfieldCardDetail
    from hypernet import EndfieldClient

__all__ = ("PlayerStatsPlugins",)


class PlayerStatsPlugins(Plugin):
    """玩家统计查询"""

    def __init__(self, template: TemplateService, helper: GenshinHelper):
        self.template_service = template
        self.helper = helper

    @handler.command("stats", player=True, block=False)
    @handler.message(filters.Regex("^玩家统计查询(.*)"), player=True, block=False)
    async def command_start(self, update: "Update", _: "ContextTypes.DEFAULT_TYPE") -> Optional[int]:
        user_id = await self.get_real_user_id(update)
        uid, offset = self.get_real_uid_or_offset(update)
        message = update.effective_message
        self.log_user(update, logger.info, "查询游戏用户命令请求")
        try:
            async with self.helper.genshin_or_public(user_id, uid=uid, offset=offset) as client:
                render_result = await self.render(client, client.player_id)
        except TooManyRequestPublicCookies:
            await message.reply_text("用户查询次数过多 请稍后重试")
            return
        except AttributeError as exc:
            logger.error("角色数据有误")
            logger.exception(exc)
            await message.reply_text(f"角色数据有误 估计是{config.notice.bot_name}晕了")
            return
        except ValueError as exc:
            logger.warning("获取 uid 发生错误！ 错误信息为 %s", str(exc))
            await message.reply_text("输入错误")
            return
        await message.reply_chat_action(ChatAction.UPLOAD_PHOTO)
        await render_result.reply_photo(message, filename=f"{client.player_id}.png")

    async def render(self, client: "EndfieldClient", uid: Optional[int] = None) -> RenderResult:
        if uid is None:
            uid = client.player_id

        user_info: "EndfieldCardDetail" = await client.get_endfield_card_detail(player_id=uid)

        stats = user_info.base.dict()
        stats["nickname"] = stats["name"]

        stats["main_mission"] = user_info.base.mainMission.description
        stats["achieve"] = user_info.achieve.count

        puzzle_count, trchest_count, piece_count = 0, 0, 0
        for domain in user_info.domain:
            for col in domain.collections:
                puzzle_count += col.puzzleCount
                trchest_count += col.trchestCount
                piece_count += col.pieceCount
        stats["puzzle_count"] = puzzle_count
        stats["trchest_count"] = trchest_count
        stats["piece_count"] = piece_count

        control_center_level = next(
            (room.level for room in user_info.spaceShip.rooms if room.id == "control_center"), 0
        )
        stats["control_center_level"] = control_center_level

        data = {
            "uid": mask_number(uid),
            "info": stats,
            "stats": stats,
            "explorations": user_info.domain,
            "skip_explor": [],
            "stats_labels": [
                ("使命纪事", "main_mission"),
                ("权限等阶", "level"),
                ("探索等级", "worldLevel"),
                ("干员", "charNum"),
                ("武器", "weaponNum"),
                ("档案", "docNum"),
                ("光荣之路", "achieve"),
                ("醚质", "puzzle_count"),
                ("储藏箱", "trchest_count"),
                ("维修灵感点", "piece_count"),
                ("总控中枢等级", "control_center_level"),
            ],
            "style": "wuling",
        }

        return await self.template_service.render(
            "zmd/stats/stats.jinja2",
            data,
            {"width": 950, "height": 750},
            full_page=True,
        )

    async def stats_use_by_inline(self, update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        callback_query = update.callback_query
        user = update.effective_user
        user_id = user.id
        uid = IInlineUseData.get_uid_from_context(context)

        self.log_user(update, logger.info, "查询游戏用户命令请求")
        notice = None
        try:
            async with self.helper.genshin_or_public(user_id, uid=uid) as client:
                if not client.public:
                    await client.get_record_cards()
                render_result = await self.render(client, client.player_id)
        except TooManyRequestPublicCookies:
            notice = "用户查询次数过多 请稍后重试"
        except AttributeError as exc:
            logger.error("角色数据有误")
            logger.exception(exc)
            notice = f"角色数据有误 估计是{config.notice.bot_name}晕了"
        except ValueError as exc:
            logger.warning("获取 uid 发生错误！ 错误信息为 %s", str(exc))
            notice = "UID 内部错误"

        if notice:
            await callback_query.answer(notice, show_alert=True)
            return
        await render_result.edit_inline_media(callback_query)

    async def get_inline_use_data(self) -> List[Optional[IInlineUseData]]:
        return [
            IInlineUseData(
                text="玩家统计",
                hash="stats",
                callback=self.stats_use_by_inline,
                player=True,
            ),
        ]
