from typing import Optional, TYPE_CHECKING

from hypernet.models.lab.game_role import GameRoleId

from gram_core.dependence.redisdb import RedisDB
from gram_core.plugin import Plugin

if TYPE_CHECKING:
    from hypernet import EndfieldClient


class RoleTokenData(GameRoleId):
    role_token: str


class RoleTokenHelper(Plugin):
    def __init__(self, redis: RedisDB):
        self.client = redis.client
        self.qname = "role_token:"
        self.expire = 7 * 24 * 60 * 60  # 7 days

    def get_key(self, player_id: int) -> str:
        return f"{self.qname}{player_id}"

    async def set_role_token(self, player_id: int, role_token: RoleTokenData) -> bool:
        key = self.get_key(player_id)
        role_token_str = role_token.json()
        return await self.client.set(key, role_token_str, ex=self.expire)

    async def get_role_token_by_cache(self, player_id: int) -> Optional[RoleTokenData]:
        key = self.get_key(player_id)
        role_token = await self.client.get(key)
        if role_token is None:
            return None
        role_token_str = role_token.decode("utf-8")
        return RoleTokenData.parse_raw(role_token_str)

    async def remove_role_token(self, player_id: int) -> bool:
        key = self.get_key(player_id)
        return await self.client.delete(key)

    @staticmethod
    async def get_role_token_by_client(client: "EndfieldClient") -> RoleTokenData:
        player_id = client.player_id
        token = await client.get_binding_token_by_hg_token()
        role_id = await client.get_role_id_by_player_id(token, player_id)
        role_token_str = await client.get_role_token_by_binding_token(
            token,
            role_id.role_id,
        )
        return RoleTokenData(
            **role_id.dict(),
            role_token=role_token_str,
        )

    async def get_role_token(self, client: "EndfieldClient") -> RoleTokenData:
        player_id = client.player_id
        role_token = await self.get_role_token_by_cache(player_id)
        if role_token is not None:
            return role_token
        role_token = await self.get_role_token_by_client(client)
        await self.set_role_token(player_id, role_token)
        return role_token
