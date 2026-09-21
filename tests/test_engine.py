from __future__ import annotations

import random
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from src.engine import CaboError, CaboGame, CaboPhase, Card  # noqa: E402


def make_game() -> CaboGame:
    game = CaboGame("g", "a", max_players=4)
    game.add_player("a", "A")
    game.add_player("b", "B")
    game.start_round(random.Random(0))
    return game


def card(code: str) -> Card:
    return Card(code[:-1], code[-1])


def test_start_deals_four_and_marks_first_two_cards_known() -> None:
    game = make_game()

    assert game.phase == CaboPhase.TURN
    assert len(game.players) == 2
    assert all(len(player.cards) == 4 for player in game.players)
    assert all(player.known_positions == {0, 1} for player in game.players)
    assert game.stock
    assert len(game.discard) == 1


def test_draw_stock_replace_and_advance_turn() -> None:
    game = make_game()
    actor = game.current_player
    assert actor is not None
    game.stock = [card("AS")]
    game.draw_stock(actor.user_id)
    assert game.phase == CaboPhase.DRAWN_STOCK

    game.replace_with_drawn(actor.user_id, 1)

    assert actor.cards[0].code == "AS"
    assert game.drawn_card is None
    assert game.phase == CaboPhase.TURN
    assert game.current_player is not actor


def test_draw_discard_must_be_replaced() -> None:
    game = make_game()
    actor = game.current_player
    assert actor is not None
    game.discard = [card("5H")]
    game.draw_discard(actor.user_id)
    assert game.phase == CaboPhase.DRAWN_DISCARD

    old = actor.cards[1]
    game.replace_with_drawn(actor.user_id, 2)

    assert actor.cards[1].code == "5H"
    assert game.discard[-1] == old


def test_peek_power_marks_position_known() -> None:
    game = make_game()
    actor = game.current_player
    assert actor is not None
    game.drawn_card = card("7S")
    game.phase = CaboPhase.DRAWN_STOCK

    lines = game.peek_own(actor.user_id, 3)

    assert "看了自己的第 3 张牌" in lines[0]
    assert 2 in actor.known_positions
    assert game.phase == CaboPhase.TURN


def test_swap_power_swaps_any_two_table_cards() -> None:
    game = make_game()
    actor = game.current_player
    assert actor is not None
    other = game.players[1]
    actor.cards = [card("AS"), card("2H"), card("3D"), card("4C")]
    other.cards = [card("5S"), card("6H"), card("7D"), card("8C")]
    game.drawn_card = card("JC")
    game.phase = CaboPhase.DRAWN_STOCK

    game.swap_cards(actor.user_id, 1, 1, 2, 2)

    assert actor.cards[0].code == "6H"
    assert other.cards[1].code == "AS"


def test_call_cabo_gives_other_players_one_final_turn_then_reveals() -> None:
    game = make_game()
    caller = game.current_player
    assert caller is not None
    game.call_cabo(caller.user_id)
    assert game.phase == CaboPhase.FINAL_TURN
    final_player = game.current_player
    assert final_player is not None
    assert final_player.user_id != caller.user_id

    game.stock = [card("AS")]
    game.draw_stock(final_player.user_id)
    game.replace_with_drawn(final_player.user_id, 1)

    assert game.phase == CaboPhase.FINISHED
    result = game.reveal_round()
    assert result.winner_id in {p.user_id for p in game.players}
    assert any("共" in line for line in result.lines)


def test_card_values_use_diamond_king_as_zero() -> None:
    assert card("KD").value == 0
    assert card("KC").value == 13
    assert card("QS").value == 12
    assert card("JS").value == 11
    assert card("AS").value == 1


def test_illegal_actions_are_rejected() -> None:
    game = make_game()
    other = game.players[1]

    try:
        game.draw_stock(other.user_id)
    except CaboError as exc:
        assert "还没有轮到你行动" in str(exc)
    else:  # pragma: no cover - guard against regression
        raise AssertionError("non-current player should not draw")


def test_spy_power_and_discard_drawn_end_turn() -> None:
    game = make_game()
    actor = game.current_player
    assert actor is not None
    game.drawn_card = card("9S")
    game.phase = CaboPhase.DRAWN_STOCK

    lines = game.spy_opponent(actor.user_id, 2, 1)

    assert "查看了 B 的第 1 张牌" in lines[0]
    assert game.phase == CaboPhase.TURN
    assert game.drawn_card is None

    game = make_game()
    actor = game.current_player
    assert actor is not None
    game.drawn_card = card("2S")
    game.phase = CaboPhase.DRAWN_STOCK
    game.discard_drawn(actor.user_id)
    assert game.phase == CaboPhase.TURN
    assert game.discard[-1].code == "2S"


def test_matching_pair_replaces_set_with_drawn_card() -> None:
    game = make_game()
    actor = game.current_player
    assert actor is not None
    actor.cards = [card("AS"), card("AH"), card("2S"), card("3S")]
    actor.known_positions = {0, 1}
    game.drawn_card = card("5S")
    game.phase = CaboPhase.DRAWN_STOCK

    lines = game.match_with_drawn(actor.user_id, [1, 2])

    assert "配对成功" in lines[0]
    assert [item.code for item in actor.cards] == ["2S", "3S", "5S"]
    assert actor.known_positions == {2}
    assert game.discard[-2:] == [card("AS"), card("AH")]
    assert game.phase == CaboPhase.TURN


def test_failed_match_discards_drawn_card_and_loses_turn() -> None:
    game = make_game()
    actor = game.current_player
    assert actor is not None
    actor.cards = [card("AS"), card("2H"), card("3S"), card("4C")]
    game.drawn_card = card("5S")
    game.phase = CaboPhase.DRAWN_STOCK

    lines = game.match_with_drawn(actor.user_id, [1, 2])

    assert "配对失败" in lines[0]
    assert [item.code for item in actor.cards] == ["AS", "2H", "3S", "4C"]
    assert game.discard[-1].code == "5S"
    assert game.phase == CaboPhase.TURN
    assert game.current_player is not actor
