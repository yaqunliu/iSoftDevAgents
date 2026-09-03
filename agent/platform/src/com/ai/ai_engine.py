from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Tuple
from random import Random

from com.domain.state_snapshot import StateSnapshot
from com.types.position import Position
from com.types.player_side import PlayerSide
from com.types.difficulty import Difficulty


@dataclass
class ScoredMove:
    position: Position
    score: int


class AiEngine:
    """AI strategy engine.

    Pure computation based on a board snapshot, side and difficulty. It does not
    modify the board or persist any state.
    """

    def getCandidateMoves(
        self,
        boardSnapshot: StateSnapshot,
        side: PlayerSide,
        difficulty: Difficulty,
        seed: Optional[int] = None,
    ) -> List[Position]:
        legal_moves = self.collectLegalMoves(boardSnapshot)
        if not legal_moves:
            return []

        scored: List[ScoredMove] = []
        for pos in legal_moves:
            s = self.scoreMove(boardSnapshot, side, pos, difficulty)
            scored.append(ScoredMove(pos, s))

        # Sort by score desc; if scores tie and a seed is provided, use a deterministic shuffle
        # based on the provided seed to ensure reproducibility across invocations.
        # We create a random key for tie-breaking using a seeded RNG.
        if seed is not None:
            rng = Random(seed)
            # generate a reproducible random number per position to break ties
            tie_keys = {m.position: rng.random() for m in scored}
            scored.sort(key=lambda m: (-m.score, tie_keys[m.position]))
        else:
            scored.sort(key=lambda m: m.score, reverse=True)

        return [m.position for m in scored]

    # Internal methods
    def collectLegalMoves(self, boardSnapshot: StateSnapshot) -> List[Position]:
        return boardSnapshot.legal_positions()

    def scoreMove(
        self,
        boardSnapshot: StateSnapshot,
        side: PlayerSide,
        pos: Position,
        difficulty: Difficulty,
    ) -> int:
        if difficulty == Difficulty.EASY:
            return self.scoreEasy(boardSnapshot, side, pos)
        if difficulty == Difficulty.NORMAL:
            return self.scoreNormal(boardSnapshot, side, pos)
        if difficulty == Difficulty.HARD:
            return self.scoreHard(boardSnapshot, side, pos)
        # Default fall-back
        return self.scoreEasy(boardSnapshot, side, pos)

    def scoreEasy(self, boardSnapshot: StateSnapshot, side: PlayerSide, pos: Position) -> int:
        # Simple heuristic: prioritize positions adjacent to own pieces
        return self.evaluateLinePotential(boardSnapshot, side, pos)

    def scoreNormal(self, boardSnapshot: StateSnapshot, side: PlayerSide, pos: Position) -> int:
        # Combine offense and defense
        offense = self.evaluateLinePotential(boardSnapshot, side, pos)
        defense = self.evaluateBlockValue(boardSnapshot, side, pos)
        return offense * 2 + defense

    def scoreHard(self, boardSnapshot: StateSnapshot, side: PlayerSide, pos: Position) -> int:
        # More weight to both offense and defense
        offense = self.evaluateLinePotential(boardSnapshot, side, pos)
        defense = self.evaluateBlockValue(boardSnapshot, side, pos)
        return offense * 3 + defense * 2

    def evaluateLinePotential(self, boardSnapshot: StateSnapshot, side: PlayerSide, pos: Position) -> int:
        # Count own pieces in 8-neighborhood as a crude measure of line potential
        x, y = pos.x, pos.y
        count = 0
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if boardSnapshot.in_bounds(nx, ny):
                    if boardSnapshot.get_cell(nx, ny) == side:
                        count += 1
        return count

    def evaluateBlockValue(self, boardSnapshot: StateSnapshot, side: PlayerSide, pos: Position) -> int:
        # Count opponent pieces in 8-neighborhood as a crude measure of block value
        x, y = pos.x, pos.y
        count = 0
        opponent = PlayerSide.WHITE if side == PlayerSide.BLACK else PlayerSide.BLACK
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if boardSnapshot.in_bounds(nx, ny):
                    if boardSnapshot.get_cell(nx, ny) == opponent:
                        count += 1
        return count
