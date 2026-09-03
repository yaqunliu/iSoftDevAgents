from __future__ import annotations
from typing import List, Optional
from com.types.position import Position
from com.types.player_side import PlayerSide


class StateSnapshot:
    """A simple board snapshot for a square grid board.

    Board is a 2D list indexed as board[y][x]. Each cell is either None or PlayerSide.
    """

    def __init__(self, board: List[List[Optional[PlayerSide]]]):
        if not board or not isinstance(board, list) or not isinstance(board[0], list):
            raise ValueError("Board must be a non-empty 2D list")
        self._board = board
        self._height = len(board)
        self._width = len(board[0])

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self._width and 0 <= y < self._height

    def get_cell(self, x: int, y: int) -> Optional[PlayerSide]:
        if not self.in_bounds(x, y):
            raise IndexError("Position out of bounds")
        return self._board[y][x]

    def is_empty(self, x: int, y: int) -> bool:
        return self.get_cell(x, y) is None

    def legal_positions(self) -> List[Position]:
        return [Position(x, y) for y in range(self._height) for x in range(self._width) if self.is_empty(x, y)]
