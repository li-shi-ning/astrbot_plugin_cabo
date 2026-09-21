from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

SUITS = ("S", "H", "D", "C")
RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
RANK_VALUES = {
    "A": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "10": 10,
    "J": 11,
    "Q": 12,
    "K": 13,
}
PEEK_RANKS = {"7", "8"}
SPY_RANKS = {"9", "10"}
SWAP_RANKS = {"J", "Q"}
SUIT_SYMBOLS = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
DEFAULT_CARDS_PER_PLAYER = 4
DEFAULT_MAX_PLAYERS = 4


class CaboError(ValueError):
    """Raised when a Cabo action is not legal."""


class CaboPhase(str, Enum):
    WAITING = "waiting"
    TURN = "turn"
    DRAWN_STOCK = "drawn_stock"
    DRAWN_DISCARD = "drawn_discard"
    FINAL_TURN = "final_turn"
    FINISHED = "finished"


@dataclass(frozen=True)
class Card:
    rank: str
    suit: str

    @property
    def code(self) -> str:
        """Return a compact card code such as ``AS`` or ``10H``."""

        return f"{self.rank}{self.suit}"

    @property
    def value(self) -> int:
        """Return the Cabo score value for this card."""

        if self.rank == "K" and self.suit == "D":
            return 0
        return RANK_VALUES[self.rank]

    @property
    def is_power(self) -> bool:
        """Return whether this card has a Peek, Spy, or Swap power."""

        return self.rank in PEEK_RANKS | SPY_RANKS | SWAP_RANKS

    def label(self) -> str:
        """Return a display label with the suit symbol."""

        return f"{self.rank}{SUIT_SYMBOLS.get(self.suit, self.suit)}"


@dataclass
class PlayerState:
    user_id: str
    name: str
    cards: list[Card] = field(default_factory=list)
    known_positions: set[int] = field(default_factory=set)
    total_score: int = 0

    def hand_value(self) -> int:
        """Return the total score of this player's current hand."""

        return sum(card.value for card in self.cards)

    def known_text(self) -> str:
        """Format the positions and values this player currently knows."""

        parts = [
            f"{index + 1}:{self.cards[index].code}"
            for index in sorted(self.known_positions)
            if 0 <= index < len(self.cards)
        ]
        return " ".join(parts) if parts else "暂无已知牌"


@dataclass
class RoundResult:
    winner_id: str
    winner_name: str
    scores: dict[str, int]
    lines: list[str]


@dataclass
class CaboGame:
    group_id: str
    owner_id: str
    cards_per_player: int = DEFAULT_CARDS_PER_PLAYER
    max_players: int = DEFAULT_MAX_PLAYERS
    players: list[PlayerState] = field(default_factory=list)
    phase: CaboPhase = CaboPhase.WAITING
    current_index: int = 0
    stock: list[Card] = field(default_factory=list)
    discard: list[Card] = field(default_factory=list)
    drawn_card: Card | None = None
    drawn_from_discard: bool = False
    cabo_caller_index: int | None = None
    final_turn_queue: list[int] = field(default_factory=list)
    round_no: int = 0

    @property
    def current_player(self) -> PlayerState | None:
        """Return the player whose turn it is, if any."""

        if self.phase in {CaboPhase.WAITING, CaboPhase.FINISHED}:
            return None
        if not self.players:
            return None
        return self.players[self.current_index % len(self.players)]

    def get_player(self, user_id: str) -> PlayerState | None:
        """Return a player by user id, or ``None`` when absent."""

        return next(
            (player for player in self.players if player.user_id == user_id), None
        )

    def player_index(self, user_id: str) -> int | None:
        """Return a player index by user id, or ``None`` when absent."""

        return next(
            (
                index
                for index, player in enumerate(self.players)
                if player.user_id == user_id
            ),
            None,
        )

    def add_player(self, user_id: str, name: str) -> None:
        """Add a player to a waiting room."""

        if self.phase != CaboPhase.WAITING:
            raise CaboError("游戏已经开始，不能加入。")
        if self.get_player(user_id) is not None:
            raise CaboError("你已经加入本局。")
        if len(self.players) >= self.max_players:
            raise CaboError("房间人数已满。")
        self.players.append(PlayerState(user_id=user_id, name=name))

    def remove_player(self, user_id: str) -> None:
        """Remove a player from a waiting room."""

        if self.phase != CaboPhase.WAITING:
            raise CaboError("游戏已经开始，不能退出。")
        player = self.get_player(user_id)
        if player is None:
            raise CaboError("你还没有加入本局。")
        if player.user_id == self.owner_id:
            raise CaboError("房主不能退出，请直接结束房间。")
        self.players.remove(player)

    def start_round(self, rng: random.Random | None = None) -> list[str]:
        """Shuffle, deal four cards to each player, and reveal one discard."""

        if self.phase != CaboPhase.WAITING:
            raise CaboError("游戏已经开始。")
        if len(self.players) < 2:
            raise CaboError("至少需要两名玩家才能开始。")
        rng = rng or random.Random()
        rng.shuffle(self.players)
        deck = [Card(rank, suit) for suit in SUITS for rank in RANKS]
        rng.shuffle(deck)
        for player in self.players:
            player.cards = []
            player.known_positions = set()
        for _ in range(self.cards_per_player):
            for player in self.players:
                player.cards.append(deck.pop())
        for index in range(min(2, self.cards_per_player)):
            for player in self.players:
                player.known_positions.add(index)
        self.stock = deck
        self.discard = []
        if self.stock:
            self.discard.append(self.stock.pop())
        self.phase = CaboPhase.TURN
        self.current_index = 0
        self.drawn_card = None
        self.drawn_from_discard = False
        self.cabo_caller_index = None
        self.final_turn_queue = []
        self.round_no += 1
        return [f"随机先手：{self.players[0].name}。"]

    def draw_stock(self, user_id: str) -> list[str]:
        """Draw the top stock card for the current player."""

        self._require_turn(user_id)
        if not self.stock:
            raise CaboError("牌堆已空，请直接 CABO。")
        player = self.current_player
        assert player is not None
        self.drawn_card = self.stock.pop()
        self.drawn_from_discard = False
        self.phase = CaboPhase.DRAWN_STOCK
        return [f"{player.name} 从牌堆抽了一张牌。"]

    def draw_discard(self, user_id: str) -> list[str]:
        """Take the top discard card for the current player."""

        self._require_turn(user_id)
        if not self.discard:
            raise CaboError("弃牌堆为空，不能拿弃牌。")
        player = self.current_player
        assert player is not None
        self.drawn_card = self.discard.pop()
        self.drawn_from_discard = True
        self.phase = CaboPhase.DRAWN_DISCARD
        return [f"{player.name} 拿了弃牌堆的 {self.drawn_card.code}。"]

    def replace_with_drawn(self, user_id: str, position: int) -> list[str]:
        """Replace one own face-down card with the drawn/discard card."""

        if self.phase not in {CaboPhase.DRAWN_STOCK, CaboPhase.DRAWN_DISCARD}:
            raise CaboError("当前没有可以替换的抽牌。")
        player = self.current_player
        if player is None or player.user_id != user_id:
            raise CaboError("还没有轮到你行动。")
        index = self._card_index(position, player)
        assert self.drawn_card is not None
        old_card = player.cards[index]
        player.cards[index] = self.drawn_card
        self.discard.append(old_card)
        player.known_positions.add(index)
        self._finish_turn()
        return [f"{player.name} 替换了第 {position} 张牌。"]

    def discard_drawn(self, user_id: str) -> list[str]:
        """Discard the card drawn from the stock without using its power."""

        if self.phase != CaboPhase.DRAWN_STOCK:
            raise CaboError("只有从牌堆抽牌后可以直接弃牌。")
        player = self.current_player
        if player is None or player.user_id != user_id:
            raise CaboError("还没有轮到你行动。")
        assert self.drawn_card is not None
        self.discard.append(self.drawn_card)
        self._finish_turn()
        return [f"{player.name} 弃掉了抽到的牌。"]

    def match_with_drawn(self, user_id: str, positions: list[int]) -> list[str]:
        """Use the drawn/discard card to replace a set of 2-4 matching cards.

        Matching removes the selected face-down set and places the drawn card
        into the layout, reducing the hand by ``len(positions) - 1`` cards.  A
        failed match reveals and returns the selected cards, discards the
        drawn card, and loses the turn.
        """

        if self.phase not in {CaboPhase.DRAWN_STOCK, CaboPhase.DRAWN_DISCARD}:
            raise CaboError("当前没有可以配对的抽牌。")
        player = self.current_player
        if player is None or player.user_id != user_id:
            raise CaboError("还没有轮到你行动。")
        if not 2 <= len(positions) <= 4:
            raise CaboError("配对需要选择 2-4 张牌。")
        indices = [self._card_index(position, player) for position in positions]
        if len(set(indices)) != len(indices):
            raise CaboError("不能重复选择同一张牌。")
        selected = [player.cards[index] for index in indices]
        assert self.drawn_card is not None
        if len({card.rank for card in selected}) != 1:
            failed = "、".join(card.code for card in selected)
            self.discard.append(self.drawn_card)
            self._finish_turn()
            return [
                f"{player.name} 配对失败：{failed} 不是同点数，"
                "已展示并放回；抽到的牌被弃掉。"
            ]

        rank = selected[0].rank
        index_set = set(indices)
        remaining: list[Card] = []
        new_known: set[int] = set()
        for index, card in enumerate(player.cards):
            if index in index_set:
                continue
            new_index = len(remaining)
            remaining.append(card)
            if index in player.known_positions:
                new_known.add(new_index)
        remaining.append(self.drawn_card)
        new_known.add(len(remaining) - 1)
        player.cards = remaining
        player.known_positions = new_known
        self.discard.extend(selected)
        self._finish_turn()
        return [
            f"{player.name} 配对成功，弃掉 {len(selected)} 张 {rank}，"
            f"剩余 {len(player.cards)} 张牌。"
        ]

    def peek_own(self, user_id: str, position: int) -> list[str]:
        """Use a 7/8 Peek power on one of the current player's cards."""

        if self.phase != CaboPhase.DRAWN_STOCK or self.drawn_card is None:
            raise CaboError("当前不能使用看牌技能。")
        if self.drawn_card.rank not in PEEK_RANKS:
            raise CaboError("这张牌没有看牌技能。")
        player = self.current_player
        if player is None or player.user_id != user_id:
            raise CaboError("还没有轮到你行动。")
        index = self._card_index(position, player)
        player.known_positions.add(index)
        self.discard.append(self.drawn_card)
        self._finish_turn()
        return [f"{player.name} 看了自己的第 {position} 张牌。"]

    def spy_opponent(
        self, user_id: str, target_player: int, position: int
    ) -> list[str]:
        """Use a 9/10 Spy power on another player's card."""

        if self.phase != CaboPhase.DRAWN_STOCK or self.drawn_card is None:
            raise CaboError("当前不能使用侦查技能。")
        if self.drawn_card.rank not in SPY_RANKS:
            raise CaboError("这张牌没有侦查技能。")
        player = self.current_player
        if player is None or player.user_id != user_id:
            raise CaboError("还没有轮到你行动。")
        target = self._player_by_number(target_player)
        if target.user_id == player.user_id:
            raise CaboError("请选择其他玩家。")
        index = self._card_index(position, target)
        _ = target.cards[index]  # validated by main for the private reveal
        self.discard.append(self.drawn_card)
        self._finish_turn()
        return [f"{player.name} 查看了 {target.name} 的第 {position} 张牌。"]

    def swap_cards(
        self,
        user_id: str,
        player_a: int,
        position_a: int,
        player_b: int,
        position_b: int,
    ) -> list[str]:
        """Use a J/Q Swap power to exchange any two table cards blind."""

        if self.phase != CaboPhase.DRAWN_STOCK or self.drawn_card is None:
            raise CaboError("当前不能使用交换技能。")
        if self.drawn_card.rank not in SWAP_RANKS:
            raise CaboError("这张牌没有交换技能。")
        actor = self.current_player
        if actor is None or actor.user_id != user_id:
            raise CaboError("还没有轮到你行动。")
        target_a = self._player_by_number(player_a)
        target_b = self._player_by_number(player_b)
        index_a = self._card_index(position_a, target_a)
        index_b = self._card_index(position_b, target_b)
        if target_a is target_b and index_a == index_b:
            raise CaboError("不能交换同一张牌。")
        target_a.cards[index_a], target_b.cards[index_b] = (
            target_b.cards[index_b],
            target_a.cards[index_a],
        )
        target_a.known_positions.discard(index_a)
        target_b.known_positions.discard(index_b)
        self.discard.append(self.drawn_card)
        self._finish_turn()
        return [f"{actor.name} 交换了两张牌。"]

    def call_cabo(self, user_id: str) -> list[str]:
        """Call Cabo; every other player gets exactly one final turn."""

        if self.phase != CaboPhase.TURN:
            raise CaboError("CABO 已经喊过，当前只能进行最后一回合。")
        self._require_turn(user_id)
        player = self.current_player
        assert player is not None
        self.cabo_caller_index = self.current_index
        self.final_turn_queue = [
            (self.current_index + offset) % len(self.players)
            for offset in range(1, len(self.players))
        ]
        self.phase = CaboPhase.FINAL_TURN
        self.current_index = self.final_turn_queue.pop(0)
        return [f"{player.name} 喊了 CABO！其余玩家各获得最后一回合。"]

    def reveal_round(self) -> RoundResult:
        """Reveal all cards and return the round result."""

        if self.phase not in {CaboPhase.FINAL_TURN, CaboPhase.FINISHED}:
            raise CaboError("当前不能结算。")
        self.phase = CaboPhase.FINISHED
        scores = {player.user_id: player.hand_value() for player in self.players}
        winner = min(self.players, key=lambda player: scores[player.user_id])
        lines = ["CABO 结算："]
        for player in self.players:
            cards = " ".join(card.code for card in player.cards)
            lines.append(f"- {player.name}：{cards}，共 {scores[player.user_id]} 分")
        lines.append(f"本局最低分：{winner.name}，{scores[winner.user_id]} 分。")
        return RoundResult(
            winner_id=winner.user_id,
            winner_name=winner.name,
            scores=scores,
            lines=lines,
        )

    def status_lines(self) -> list[str]:
        """Build public status text without revealing hidden cards."""

        labels = {
            CaboPhase.WAITING: "等待加入",
            CaboPhase.TURN: "等待抽牌",
            CaboPhase.DRAWN_STOCK: "已抽牌",
            CaboPhase.DRAWN_DISCARD: "已拿弃牌",
            CaboPhase.FINAL_TURN: "CABO 最后一回合",
            CaboPhase.FINISHED: "已结束",
        }
        lines = [f"阶段：{labels[self.phase]}"]
        if self.phase != CaboPhase.WAITING:
            lines.append(f"牌堆：{len(self.stock)} 张")
            top = self.discard[-1].code if self.discard else "无"
            lines.append(f"弃牌堆顶：{top}")
        if self.current_player is not None:
            lines.append(f"当前玩家：{self.current_player.name}")
        lines.append("玩家：")
        for player in self.players:
            lines.append(
                f"- {player.name}：{len(player.cards)} 张牌，已看 {len(player.known_positions)} 张"
            )
        return lines

    def _require_turn(self, user_id: str) -> None:
        """Validate that it is the given player's turn."""

        if self.phase not in {CaboPhase.TURN, CaboPhase.FINAL_TURN}:
            raise CaboError("当前不能抽牌或喊 CABO。")
        player = self.current_player
        if player is None or player.user_id != user_id:
            raise CaboError("还没有轮到你行动。")

    def _finish_turn(self) -> None:
        """Clear drawn state and advance to the next player or reveal."""

        self.drawn_card = None
        self.drawn_from_discard = False
        if self.cabo_caller_index is not None:
            if self.final_turn_queue:
                self.current_index = self.final_turn_queue.pop(0)
                self.phase = CaboPhase.FINAL_TURN
            else:
                self.phase = CaboPhase.FINISHED
            return
        self.phase = CaboPhase.TURN
        self.current_index = (self.current_index + 1) % len(self.players)

    def _card_index(self, position: int, player: PlayerState) -> int:
        """Convert a 1-based card position to a list index for *player*."""

        if not 1 <= int(position) <= len(player.cards):
            raise CaboError(f"牌位必须是 1-{len(player.cards)}。")
        return int(position) - 1

    def _player_by_number(self, number: int) -> PlayerState:
        """Resolve a 1-based player number from the current table order."""

        number = int(number)
        if not 1 <= number <= len(self.players):
            raise CaboError(f"玩家编号必须是 1-{len(self.players)}。")
        return self.players[number - 1]

    def to_summary(self) -> dict[str, Any]:
        """Serialize the game state for diagnostics or tests."""

        return {
            "group_id": self.group_id,
            "owner_id": self.owner_id,
            "phase": self.phase.value,
            "current_index": self.current_index,
            "stock": len(self.stock),
            "discard": [card.code for card in self.discard],
            "drawn_card": self.drawn_card.code if self.drawn_card else None,
            "players": [
                {
                    "user_id": player.user_id,
                    "name": player.name,
                    "cards": [card.code for card in player.cards],
                    "known": sorted(player.known_positions),
                }
                for player in self.players
            ],
        }
