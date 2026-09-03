"""
AIEngine 服务层的pytest单元测试
覆盖场景：
- FR-010: 首步/空盘携带难度与种子，生成候选落点（可复现）
- FR-035: 玩家步后生成排序候选列表，满盘返回空
- FR-036: 仅返回合法坐标且不修改棋盘快照（纯计算）
- FR-045: 性能在合理阈值内
"""
import time
import pytest
from unittest.mock import Mock

from com.ai.ai_engine import AiEngine
from com.domain.state_snapshot import StateSnapshot
from com.types.position import Position
from com.types.player_side import PlayerSide
from com.types.difficulty import Difficulty


@pytest.fixture
def engine():
    """提供 AiEngine 实例"""
    return AiEngine()


def make_board(matrix):
    """根据二维列表构造 StateSnapshot。None 表示空，其它为 PlayerSide。"""
    return StateSnapshot(matrix)


class TestAiEngine:
    """AiEngine 行为测试"""

    def test_getCandidateMoves_when_empty_board_with_seed_should_return_legal_permutation_and_be_reproducible(self, engine):
        """FR-010: 空棋盘 + 种子 -> 返回全部合法点的某排列；相同seed结果可复现；仅包含空位。"""
        # Arrange
        board = make_board([[None, None, None], [None, None, None], [None, None, None]])
        side = PlayerSide.WHITE
        difficulty = Difficulty.EASY
        seed = 42

        # Act
        result1 = engine.getCandidateMoves(board, side, difficulty, seed)
        result2 = engine.getCandidateMoves(board, side, difficulty, seed)
        legal = engine.collectLegalMoves(board)

        # Assert: 结果是合法集合的一个排列
        assert { (p.x, p.y) for p in result1 } == { (p.x, p.y) for p in legal }
        assert { (p.x, p.y) for p in result2 } == { (p.x, p.y) for p in legal }
        # 相同seed可复现
        assert result1 == result2
        # 均为空位
        for p in result1:
            assert board.is_empty(p.x, p.y)

    def test_getCandidateMoves_when_full_board_should_return_empty_list(self, engine):
        """FR-035: 满盘无合法位时应返回空列表。"""
        # Arrange
        board = make_board([
            [PlayerSide.WHITE, PlayerSide.BLACK],
            [PlayerSide.BLACK, PlayerSide.WHITE],
        ])

        # Act
        result = engine.getCandidateMoves(board, PlayerSide.WHITE, Difficulty.NORMAL, seed=1)

        # Assert
        assert result == []

    def test_getCandidateMoves_when_mixed_board_should_be_sorted_desc_and_legal_and_not_modify_board(self, engine):
        """FR-035/FR-036: 混合局面返回按分数降序的合法坐标，且不修改棋盘。"""
        # Arrange
        matrix = [
            [PlayerSide.WHITE, None, PlayerSide.BLACK],
            [None, None, None],
            [PlayerSide.BLACK, None, PlayerSide.WHITE],
        ]
        board = make_board(matrix)
        side = PlayerSide.WHITE
        difficulty = Difficulty.NORMAL
        # 记录调用前快照
        before = tuple(tuple(board.get_cell(x, y) for x in range(board.width)) for y in range(board.height))

        # Act
        result = engine.getCandidateMoves(board, side, difficulty)

        # Assert: 仅返回空位
        legal_set = { (p.x, p.y) for p in engine.collectLegalMoves(board) }
        assert len(result) == len(legal_set)
        for p in result:
            assert (p.x, p.y) in legal_set
            assert board.is_empty(p.x, p.y)
        # 按分数降序
        scores = [engine.scoreMove(board, side, Position(p.x, p.y), difficulty) for p in result]
        assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))
        # 不修改原棋盘
        after = tuple(tuple(board.get_cell(x, y) for x in range(board.width)) for y in range(board.height))
        assert before == after

    def test_scoreMove_when_difficulty_should_dispatch_to_corresponding_method(self, engine, monkeypatch):
        """验证 scoreMove 会根据 Difficulty 调用对应的评分方法。"""
        # Arrange
        board = make_board([[None]])
        pos = Position(0, 0)

        called = {"easy": False, "normal": False, "hard": False}

        def fake_easy(b, s, p):
            called["easy"] = True
            return 11

        def fake_normal(b, s, p):
            called["normal"] = True
            return 22

        def fake_hard(b, s, p):
            called["hard"] = True
            return 33

        monkeypatch.setattr(engine, "scoreEasy", fake_easy)
        monkeypatch.setattr(engine, "scoreNormal", fake_normal)
        monkeypatch.setattr(engine, "scoreHard", fake_hard)

        # Act & Assert: EASY
        called.update({"easy": False, "normal": False, "hard": False})
        assert engine.scoreMove(board, PlayerSide.WHITE, pos, Difficulty.EASY) == 11
        assert called["easy"] is True and called["normal"] is False and called["hard"] is False

        # NORMAL
        called.update({"easy": False, "normal": False, "hard": False})
        assert engine.scoreMove(board, PlayerSide.WHITE, pos, Difficulty.NORMAL) == 22
        assert called["easy"] is False and called["normal"] is True and called["hard"] is False

        # HARD
        called.update({"easy": False, "normal": False, "hard": False})
        assert engine.scoreMove(board, PlayerSide.WHITE, pos, Difficulty.HARD) == 33
        assert called["easy"] is False and called["normal"] is False and called["hard"] is True

    def test_collectLegalMoves_should_return_all_empty_positions(self, engine):
        """验证 collectLegalMoves 返回所有空位。"""
        # Arrange
        board = make_board([
            [None, PlayerSide.WHITE],
            [PlayerSide.BLACK, None],
        ])

        # Act
        legal = engine.collectLegalMoves(board)

        # Assert
        coords = {(p.x, p.y) for p in legal}
        assert coords == {(0, 0), (1, 1)}

    def test_getCandidateMoves_should_meet_performance_target_on_medium_board(self, engine):
        """FR-045: 中等大小棋盘下应在性能目标内返回候选列表。"""
        # Arrange: 30x30 空盘
        size = 30
        board = make_board([[None for _ in range(size)] for _ in range(size)])

        # Act
        start = time.perf_counter()
        result = engine.getCandidateMoves(board, PlayerSide.BLACK, Difficulty.HARD, seed=123)
        elapsed = time.perf_counter() - start

        # Assert: 应返回全部空位且耗时在阈值内
        assert len(result) == size * size
        assert elapsed < 1.5
