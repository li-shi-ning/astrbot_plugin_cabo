from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

try:
    from .src.engine import (
        CaboError,
        CaboGame,
        CaboPhase,
    )
    from .src.qqofficial import (
        ButtonSpec,
        extract_context,
        is_qqofficial_event,
        send_group_reply,
    )
except ImportError:  # pragma: no cover - direct local import fallback
    from src.engine import (
        CaboError,
        CaboGame,
        CaboPhase,
    )
    from src.qqofficial import (
        ButtonSpec,
        extract_context,
        is_qqofficial_event,
        send_group_reply,
    )


PLUGIN_NAME = "astrbot_plugin_cabo"


@dataclass
class CommandOutcome:
    """Result of one Cabo command."""

    text: str
    game: CaboGame | None = None
    buttons: list[ButtonSpec] | None = None
    error: bool = False


@register(
    PLUGIN_NAME,
    "Codex",
    "QQ 官方群聊 CABO 卡牌游戏：房间、发牌、抽牌、看牌、交换与 CABO 结算。",
    "1.0.0",
)
class CaboPlugin(Star):
    def __init__(self, context: Context, config: Any = None) -> None:
        super().__init__(context)
        self.config = dict(config) if config else {}
        self.max_players = self._config_int("max_players", 4, minimum=2, maximum=5)
        self.games: dict[str, CaboGame] = {}
        self.group_locks: dict[str, asyncio.Lock] = {}

    async def initialize(self) -> None:
        """Initialize the plugin."""

        logger.info("[Cabo] initialized")

    async def terminate(self) -> None:
        """Drop all in-memory games on plugin unload."""

        self.games.clear()
        self.group_locks.clear()

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------
    @filter.command("CABO菜单", alias={"CABO帮助", "CABO"})
    async def menu_command(self, event: AstrMessageEvent):
        async for result in self._handle_command(event, "menu"):
            yield result
        event.stop_event()

    @filter.command("CABO创建", alias={"CABO开局", "CABO开房"})
    async def create_command(self, event: AstrMessageEvent):
        async for result in self._handle_command(event, "create"):
            yield result
        event.stop_event()

    @filter.command("CABO加入", alias={"CABO报名"})
    async def join_command(self, event: AstrMessageEvent):
        async for result in self._handle_command(event, "join"):
            yield result
        event.stop_event()

    @filter.command("CABO退出", alias={"CABO离开"})
    async def leave_command(self, event: AstrMessageEvent):
        async for result in self._handle_command(event, "leave"):
            yield result
        event.stop_event()

    @filter.command("CABO开始", alias={"CABO发牌"})
    async def start_command(self, event: AstrMessageEvent):
        async for result in self._handle_command(event, "start"):
            yield result
        event.stop_event()

    @filter.command("CABO看", alias={"CABO状态"})
    async def status_command(self, event: AstrMessageEvent):
        async for result in self._handle_command(event, "status"):
            yield result
        event.stop_event()

    @filter.command("CABO我的牌", alias={"我的牌", "CABO看牌"})
    async def my_cards_command(self, event: AstrMessageEvent):
        async for result in self._handle_command(event, "mycards"):
            yield result
        event.stop_event()

    @filter.command("抽牌", alias={"CABO抽牌"})
    async def draw_stock_command(self, event: AstrMessageEvent):
        async for result in self._handle_command(event, "draw_stock"):
            yield result
        event.stop_event()

    @filter.command("拿弃牌", alias={"CABO拿弃牌"})
    async def draw_discard_command(self, event: AstrMessageEvent):
        async for result in self._handle_command(event, "draw_discard"):
            yield result
        event.stop_event()

    @filter.command("换", alias={"CABO换", "替换"})
    async def replace_command(self, event: AstrMessageEvent):
        async for result in self._handle_command(event, "replace"):
            yield result
        event.stop_event()

    @filter.command("弃牌", alias={"CABO弃牌"})
    async def discard_command(self, event: AstrMessageEvent):
        async for result in self._handle_command(event, "discard"):
            yield result
        event.stop_event()

    @filter.command("配对", alias={"CABO配对", "弃同牌", "打对"})
    async def match_command(self, event: AstrMessageEvent):
        async for result in self._handle_command(event, "match"):
            yield result
        event.stop_event()

    @filter.command("看自己", alias={"CABO看自己"})
    async def peek_command(self, event: AstrMessageEvent):
        async for result in self._handle_command(event, "peek"):
            yield result
        event.stop_event()

    @filter.command("看别人", alias={"CABO看别人"})
    async def spy_command(self, event: AstrMessageEvent):
        async for result in self._handle_command(event, "spy"):
            yield result
        event.stop_event()

    @filter.command("交换", alias={"CABO交换"})
    async def swap_command(self, event: AstrMessageEvent):
        async for result in self._handle_command(event, "swap"):
            yield result
        event.stop_event()

    @filter.command("CABO叫牌", alias={"CABO喊"})
    async def cabo_command(self, event: AstrMessageEvent):
        async for result in self._handle_command(event, "cabo"):
            yield result
        event.stop_event()

    @filter.command("CABO结束", alias={"CABO取消"})
    async def end_command(self, event: AstrMessageEvent):
        async for result in self._handle_command(event, "end"):
            yield result
        event.stop_event()

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    async def _handle_command(self, event: AstrMessageEvent, command: str):
        group_id, user_id, name = self._identity(event)
        if not group_id:
            yield event.plain_result("CABO 只能在群聊中使用。")
            return
        lock = self.group_locks.setdefault(group_id, asyncio.Lock())
        async with lock:
            try:
                outcome = await self._execute_command(
                    event, group_id, user_id, name, command
                )
            except CaboError as exc:
                outcome = CommandOutcome(text=str(exc), error=True)
            except Exception as exc:  # noqa: BLE001 - isolate one group
                logger.exception("[Cabo] command %s failed: %s", command, exc)
                outcome = CommandOutcome(text=f"CABO 处理失败：{exc}", error=True)
        if outcome.error:
            yield event.plain_result(outcome.text)
            return
        buttons = outcome.buttons
        if buttons is None and outcome.game is not None:
            buttons = self._game_buttons(outcome.game)
        if await self._try_send_qqofficial(event, outcome.text, buttons):
            return
        if outcome.text:
            yield event.plain_result(outcome.text)

    async def _execute_command(
        self,
        event: AstrMessageEvent,
        group_id: str,
        user_id: str,
        name: str,
        command: str,
    ) -> CommandOutcome:
        if command == "menu":
            return self._menu_outcome()
        if command == "create":
            return self._create_game(group_id, user_id, name)
        if command == "join":
            return self._join_game(group_id, user_id, name)
        if command == "leave":
            return self._leave_game(group_id, user_id)
        if command == "start":
            return self._start_game(event, group_id, user_id)
        if command == "status":
            return self._show_status(group_id, user_id)
        if command == "mycards":
            return self._show_my_cards(group_id)
        if command == "draw_stock":
            return self._draw_stock(group_id, user_id)
        if command == "draw_discard":
            return self._draw_discard(group_id, user_id)
        if command == "replace":
            return self._replace(group_id, user_id, self._message_text(event))
        if command == "discard":
            return self._discard(group_id, user_id)
        if command == "match":
            return self._match(group_id, user_id, self._message_text(event))
        if command == "peek":
            return self._peek(group_id, user_id, self._message_text(event))
        if command == "spy":
            return self._spy(group_id, user_id, self._message_text(event))
        if command == "swap":
            return self._swap(group_id, user_id, self._message_text(event))
        if command == "cabo":
            return self._call_cabo(group_id, user_id)
        if command == "end":
            return self._end_game(event, group_id, user_id)
        raise CaboError("未知指令。")

    # ------------------------------------------------------------------
    # Command implementations
    # ------------------------------------------------------------------
    def _create_game(self, group_id: str, user_id: str, name: str) -> CommandOutcome:
        existing = self.games.get(group_id)
        if existing is not None and existing.phase != CaboPhase.FINISHED:
            raise CaboError("本群已经有一局 CABO 正在进行。")
        game = CaboGame(
            group_id=group_id, owner_id=user_id, max_players=self.max_players
        )
        game.add_player(user_id, name)
        self.games[group_id] = game
        return CommandOutcome(
            text=f"CABO 房间已创建。\n人数：{len(game.players)}/{game.max_players}。",
            game=game,
        )

    def _join_game(self, group_id: str, user_id: str, name: str) -> CommandOutcome:
        game = self.games.get(group_id)
        if game is None or game.phase != CaboPhase.WAITING:
            raise CaboError("当前没有等待加入的 CABO 房间。")
        game.add_player(user_id, name)
        return CommandOutcome(
            text=f"{name} 已加入，当前 {len(game.players)}/{game.max_players} 人。",
            game=game,
        )

    def _leave_game(self, group_id: str, user_id: str) -> CommandOutcome:
        game = self.games.get(group_id)
        if game is None or game.phase != CaboPhase.WAITING:
            raise CaboError("当前没有等待加入的 CABO 房间。")
        game.remove_player(user_id)
        return CommandOutcome(text="已退出房间。", game=game)

    def _start_game(
        self, event: AstrMessageEvent, group_id: str, user_id: str
    ) -> CommandOutcome:
        game = self.games.get(group_id)
        if game is None:
            raise CaboError("当前没有 CABO 房间。")
        if game.phase != CaboPhase.WAITING:
            raise CaboError("游戏已经开始。")
        if user_id != game.owner_id and not self._is_admin(event):
            raise CaboError("只有房主或管理员可以开始游戏。")
        lines = game.start_round(random.Random())
        return CommandOutcome(text="\n".join(lines), game=game)

    def _show_status(self, group_id: str, user_id: str) -> CommandOutcome:
        game = self.games.get(group_id)
        if game is None:
            raise CaboError("当前没有 CABO 房间。")
        return CommandOutcome(text="\n".join(game.status_lines()), game=game)

    def _show_my_cards(self, group_id: str) -> CommandOutcome:
        game = self.games.get(group_id)
        if game is None or game.phase == CaboPhase.WAITING:
            raise CaboError("当前没有正在进行的 CABO 游戏。")
        return CommandOutcome(
            text="我的牌。", game=game, buttons=self._known_buttons(game)
        )

    def _draw_stock(self, group_id: str, user_id: str) -> CommandOutcome:
        game = self.games.get(group_id)
        if game is None:
            raise CaboError("当前没有 CABO 房间。")
        lines = game.draw_stock(user_id)
        card = game.drawn_card
        extra = (
            [self._hidden_card_button("查看抽到的牌", card.code, user_id)]
            if card is not None
            else []
        )
        return self._action_outcome(group_id, lines, extra)

    def _draw_discard(self, group_id: str, user_id: str) -> CommandOutcome:
        game = self.games.get(group_id)
        if game is None:
            raise CaboError("当前没有 CABO 房间。")
        return self._action_outcome(group_id, game.draw_discard(user_id))

    def _replace(self, group_id: str, user_id: str, text: str) -> CommandOutcome:
        game = self.games.get(group_id)
        if game is None:
            raise CaboError("当前没有 CABO 房间。")
        position = self._parse_int(text, "换")
        return self._action_outcome(
            group_id, game.replace_with_drawn(user_id, position)
        )

    def _discard(self, group_id: str, user_id: str) -> CommandOutcome:
        game = self.games.get(group_id)
        if game is None:
            raise CaboError("当前没有 CABO 房间。")
        return self._action_outcome(group_id, game.discard_drawn(user_id))

    def _match(self, group_id: str, user_id: str, text: str) -> CommandOutcome:
        game = self.games.get(group_id)
        if game is None:
            raise CaboError("当前没有 CABO 房间。")
        positions = self._parse_numbers(text)
        if len(positions) < 2:
            raise CaboError("格式错误，请发送“配对 1 2”或“配对 1 2 3”。")
        return self._action_outcome(group_id, game.match_with_drawn(user_id, positions))

    def _peek(self, group_id: str, user_id: str, text: str) -> CommandOutcome:
        game = self.games.get(group_id)
        if game is None:
            raise CaboError("当前没有 CABO 房间。")
        position = self._parse_int(text, "看自己")
        player = game.current_player
        if player is None or player.user_id != user_id:
            raise CaboError("还没有轮到你行动。")
        if not 1 <= position <= len(player.cards):
            raise CaboError(f"牌位必须是 1-{len(player.cards)}。")
        card = player.cards[position - 1]
        lines = game.peek_own(user_id, position)
        extra = [
            self._hidden_card_button("查看结果", f"{position}:{card.code}", user_id)
        ]
        return self._action_outcome(group_id, lines, extra)

    def _spy(self, group_id: str, user_id: str, text: str) -> CommandOutcome:
        game = self.games.get(group_id)
        if game is None:
            raise CaboError("当前没有 CABO 房间。")
        numbers = self._parse_numbers(text)
        if len(numbers) < 2:
            raise CaboError("格式错误，请发送“看别人 玩家编号 牌位”。")
        target_number, position = numbers[0], numbers[1]
        target = game._player_by_number(target_number)
        if not 1 <= position <= len(target.cards):
            raise CaboError(f"牌位必须是 1-{len(target.cards)}。")
        card = target.cards[position - 1]
        lines = game.spy_opponent(user_id, target_number, position)
        extra = [
            self._hidden_card_button(
                "查看结果", f"{target.name} {position}:{card.code}", user_id
            )
        ]
        return self._action_outcome(group_id, lines, extra)

    def _swap(self, group_id: str, user_id: str, text: str) -> CommandOutcome:
        game = self.games.get(group_id)
        if game is None:
            raise CaboError("当前没有 CABO 房间。")
        numbers = self._parse_numbers(text)
        if len(numbers) < 4:
            raise CaboError("格式错误，请发送“交换 玩家A 牌位A 玩家B 牌位B”。")
        return self._action_outcome(
            group_id,
            game.swap_cards(user_id, numbers[0], numbers[1], numbers[2], numbers[3]),
        )

    def _call_cabo(self, group_id: str, user_id: str) -> CommandOutcome:
        game = self.games.get(group_id)
        if game is None:
            raise CaboError("当前没有 CABO 房间。")
        return self._action_outcome(group_id, game.call_cabo(user_id))

    def _end_game(
        self, event: AstrMessageEvent, group_id: str, user_id: str
    ) -> CommandOutcome:
        game = self.games.get(group_id)
        if game is None:
            raise CaboError("当前没有 CABO 房间。")
        if user_id != game.owner_id and not self._is_admin(event):
            raise CaboError("只有房主或管理员可以结束房间。")
        self.games.pop(group_id, None)
        return CommandOutcome(text="CABO 房间已结束。", game=None, buttons=[])

    def _action_outcome(
        self,
        group_id: str,
        lines: list[str],
        extra_buttons: list[ButtonSpec] | None = None,
    ) -> CommandOutcome:
        game = self.games.get(group_id)
        if game is None:
            return CommandOutcome(text="\n".join(lines), game=None, buttons=[])
        if game.phase == CaboPhase.FINISHED:
            result = game.reveal_round()
            lines.extend(result.lines)
            self.games.pop(group_id, None)
            return CommandOutcome(text="\n".join(lines), game=None, buttons=[])
        buttons = list(extra_buttons or []) + self._game_buttons(game)
        return CommandOutcome(text="\n".join(lines), game=game, buttons=buttons)

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def _menu_outcome(self) -> CommandOutcome:
        text = (
            "CABO 规则：\n"
            "1. 每人 4 张暗牌，开局自动知道第 1、2 张。\n"
            "2. 轮到你时抽牌堆或拿弃牌，或直接喊 CABO。\n"
            "3. 抽牌后可替换自己任意一张牌；拿弃牌必须替换。\n"
            "4. 抽牌后可选择 2-4 张同点数牌配对：用抽到的牌替换整组，手牌减少。\n"
            "5. 7/8 看自己，9/10 看别人，J/Q 交换任意两张桌上牌。\n"
            "6. 喊 CABO 后其他玩家各获得最后一回合，随后摊牌。\n"
            "7. 点数最低者获胜。K♦=0，其他 K=13，Q=12，J=11，A=1。\n"
            "命令：CABO创建 / CABO加入 / CABO开始 / 抽牌 / 拿弃牌 / "
            "换 1 / 配对 1 2 / 弃牌 / 看自己 1 / 看别人 2 3 / "
            "交换 1 1 2 2 / CABO叫牌"
        )
        return CommandOutcome(text=text, buttons=self._menu_buttons())

    def _menu_buttons(self) -> list[ButtonSpec]:
        return [
            ButtonSpec("cabo_menu_create", "创建房间", "CABO创建"),
            ButtonSpec("cabo_menu_join", "加入", "CABO加入"),
            ButtonSpec("cabo_menu_start", "开始", "CABO开始"),
            ButtonSpec("cabo_menu_status", "状态", "CABO看"),
            ButtonSpec("cabo_menu_mycards", "我的牌", "CABO我的牌"),
            ButtonSpec("cabo_menu_help", "CABO帮助", "CABO帮助"),
            ButtonSpec("cabo_menu_end", "结束", "CABO结束"),
        ]

    def _game_buttons(self, game: CaboGame) -> list[ButtonSpec]:
        if game.phase == CaboPhase.WAITING:
            return [
                ButtonSpec("cabo_wait_join", "加入", "CABO加入"),
                ButtonSpec(
                    "cabo_wait_start", "开始", "CABO开始", only_for=game.owner_id
                ),
                ButtonSpec("cabo_wait_status", "状态", "CABO看"),
                ButtonSpec("cabo_wait_end", "结束", "CABO结束", only_for=game.owner_id),
            ]
        buttons = self._known_buttons(game)
        actor = game.current_player
        if game.phase in {CaboPhase.TURN, CaboPhase.FINAL_TURN} and actor is not None:
            buttons.extend(
                [
                    ButtonSpec("cabo_act_draw", "抽牌", "抽牌", only_for=actor.user_id),
                    ButtonSpec(
                        "cabo_act_take", "拿弃牌", "拿弃牌", only_for=actor.user_id
                    ),
                    ButtonSpec(
                        "cabo_act_cabo", "CABO", "CABO叫牌", only_for=actor.user_id
                    ),
                ]
            )
        elif (
            game.phase in {CaboPhase.DRAWN_STOCK, CaboPhase.DRAWN_DISCARD}
            and actor is not None
        ):
            for position in range(1, game.cards_per_player + 1):
                buttons.append(
                    ButtonSpec(
                        f"cabo_act_replace_{position}",
                        f"换{position}",
                        f"换 {position}",
                        only_for=actor.user_id,
                    )
                )
            if game.phase == CaboPhase.DRAWN_STOCK:
                buttons.append(
                    ButtonSpec(
                        "cabo_act_discard", "弃牌", "弃牌", only_for=actor.user_id
                    )
                )
            if game.drawn_card is not None:
                if game.drawn_card.rank in {"7", "8"}:
                    buttons.append(
                        ButtonSpec(
                            "cabo_act_peek", "看自己", "看自己 ", only_for=actor.user_id
                        )
                    )
                elif game.drawn_card.rank in {"9", "10"}:
                    buttons.append(
                        ButtonSpec(
                            "cabo_act_spy", "看别人", "看别人 ", only_for=actor.user_id
                        )
                    )
                elif game.drawn_card.rank in {"J", "Q"}:
                    buttons.append(
                        ButtonSpec(
                            "cabo_act_swap", "交换", "交换 ", only_for=actor.user_id
                        )
                    )
        buttons.extend(
            [
                ButtonSpec("cabo_act_status", "状态", "CABO看"),
                ButtonSpec("cabo_act_end", "结束", "CABO结束", only_for=game.owner_id),
            ]
        )
        return buttons

    def _known_buttons(self, game: CaboGame) -> list[ButtonSpec]:
        """Build per-player hidden memory buttons showing only known cards."""

        buttons: list[ButtonSpec] = []
        for index, player in enumerate(game.players, start=1):
            buttons.append(
                ButtonSpec(
                    f"cabo_known_{index}",
                    f"{player.name} 我的牌",
                    f"CABO我的牌 {player.known_text()}",
                    only_for=player.user_id,
                )
            )
        return buttons

    def _hidden_card_button(self, label: str, data: str, user_id: str) -> ButtonSpec:
        return ButtonSpec(
            f"cabo_reveal_{random.randint(1, 10**9)}",
            label,
            f"CABO看结果 {data}",
            only_for=user_id,
        )

    # ------------------------------------------------------------------
    # Platform helpers
    # ------------------------------------------------------------------
    def _identity(self, event: AstrMessageEvent) -> tuple[str, str, str]:
        group_id = str(event.get_group_id() or "")
        user_id = str(event.get_sender_id() or "")
        name = str(event.get_sender_name() or "") or f"玩家_{user_id[-6:]}"
        return group_id, user_id, name

    async def _try_send_qqofficial(
        self, event: AstrMessageEvent, text: str, buttons: list[ButtonSpec] | None
    ) -> bool:
        if not is_qqofficial_event(event):
            return False
        context = extract_context(event)
        if context is None:
            return False
        return await send_group_reply(event, context, text, buttons or [])

    def _message_text(self, event: AstrMessageEvent) -> str:
        getter = getattr(event, "get_message_str", None)
        if callable(getter):
            return str(getter() or "")
        return str(getattr(event, "message_str", "") or "")

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        try:
            return bool(event.is_admin())
        except Exception:  # noqa: BLE001 - compatibility with test doubles
            return False

    # ------------------------------------------------------------------
    # Parsers and config
    # ------------------------------------------------------------------
    def _parse_int(self, text: str, keyword: str) -> int:
        match = re.search(rf"{keyword}\s*(\d+)", str(text or ""))
        if not match:
            raise CaboError(f"格式错误，请发送“{keyword} 1”。")
        return int(match.group(1))

    def _parse_numbers(self, text: str) -> list[int]:
        return [int(value) for value in re.findall(r"\d+", str(text or ""))]

    def _config_int(
        self,
        key: str,
        default: int,
        *,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> int:
        raw = self.config.get(key, default)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = default
        if minimum is not None:
            value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        return value
