from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class GameViewState:
    board: List[List[str]] = field(default_factory=list)
    message: str = ""
    is_ai_turn: bool = False
    ai_thinking: bool = False
    is_game_over: bool = False
    is_replay_mode: bool = False
    settings: Dict[str, str] = field(default_factory=dict)
    replay_moves: List[str] = field(default_factory=list)
    step_index: int = 0
    current_player: str = "HUMAN"
    last_move_valid: bool = True


class GameApplication:
    """Service Layer placeholder. Methods are expected to be mocked in tests."""

    def startNewGame(self, mode, player_side, settings) -> GameViewState:  # pragma: no cover
        raise NotImplementedError

    def makeMove(self, position) -> GameViewState:  # pragma: no cover
        raise NotImplementedError

    def undoMove(self) -> GameViewState:  # pragma: no cover
        raise NotImplementedError

    def getHistory(self, filter_id: Optional[str]) -> GameViewState:  # pragma: no cover
        raise NotImplementedError

    def startReplay(self, record_id: str) -> GameViewState:  # pragma: no cover
        raise NotImplementedError

    def goToReplayStep(self, step_index: int) -> GameViewState:  # pragma: no cover
        raise NotImplementedError

    def exitReplay(self) -> GameViewState:  # pragma: no cover
        raise NotImplementedError

    def updateSettings(self, settings) -> GameViewState:  # pragma: no cover
        raise NotImplementedError

    def getCurrentViewState(self) -> GameViewState:  # pragma: no cover
        raise NotImplementedError
