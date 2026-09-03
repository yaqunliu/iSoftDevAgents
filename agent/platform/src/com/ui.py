from typing import List, Dict, Optional

from com.app import GameApplication, GameViewState
from com.types import Position


class IViewRenderer:
    """A very simple rendering interface to be driven by UI."""

    def show_main_menu(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def show_board(self, board_view: List[List[str]]) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def show_status(self, message: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def show_history(self, history_items: List[str]) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def show_replay(self, replay_moves: List[str], step_index: int) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def show_settings(self, settings_data: Dict[str, str]) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def refresh(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class UI:
    """UI controller that forwards user actions to GameApplication and renders via IViewRenderer.

    It does not implement business rules, only dispatching and rendering.
    """

    def __init__(self, app: GameApplication, renderer: IViewRenderer) -> None:
        self._app = app
        self._renderer = renderer
        # simple UI state flags used to guard triggering in some methods
        self.can_start: bool = True
        self.in_replay_mode: bool = False

    # User action dispatching
    def onStartGame(self) -> None:
        if not self.can_start:
            # Not allowed context - do not trigger application
            self._renderer.show_status("Start not allowed in current view")
            return
        # Forward to application layer with placeholders; actual values are decided by app
        self._app.startNewGame(None, None, None)

    def onSelectCell(self, row: int, col: int) -> None:
        # forward to application layer
        self._app.makeMove(Position(row=row, col=col))

    def onUndo(self) -> None:
        self._app.undoMove()

    def onOpenHistory(self) -> None:
        # pass None to get all summaries
        self._app.getHistory(None)

    def onOpenReplay(self, recordId: str) -> None:
        self._app.startReplay(recordId)
        # mark replay mode so that back-to-main can exit
        self.in_replay_mode = True

    def onReplayStepChange(self, stepIndex: int) -> None:
        self._app.goToReplayStep(stepIndex)

    def onOpenSettings(self) -> None:
        # obtain current settings from app and render settings panel
        state = self._safe_get_state()
        if state:
            self._renderer.show_settings(state.settings)

    def onChangeSetting(self, key: str, value: str) -> None:
        # forward settings change to application layer
        self._app.updateSettings({key: value})

    def onBackToMain(self) -> None:
        # If in replay mode, exit replay, otherwise nothing special
        if self.in_replay_mode:
            self._app.exitReplay()
            self.in_replay_mode = False

    # Render methods
    def renderMainMenu(self) -> None:
        self._renderer.show_main_menu()

    def renderBoard(self, boardView: List[List[str]]) -> None:
        self._renderer.show_board(boardView)

    def renderStatus(self, message: str) -> None:
        self._renderer.show_status(message)

    def renderHistory(self, historyItems: List[str]) -> None:
        self._renderer.show_history(historyItems)

    def renderReplay(self, replayMoves: List[str], stepIndex: int) -> None:
        self._renderer.show_replay(replayMoves, stepIndex)

    def renderSettings(self, settingsData: Dict[str, str]) -> None:
        self._renderer.show_settings(settingsData)

    def refresh(self) -> None:
        """Refresh view according to current GameViewState from application."""
        state = self._safe_get_state()
        if state is None:
            return

        # Distinguish replay mode explicitly
        if state.is_replay_mode:
            self._renderer.show_replay(state.replay_moves, state.step_index)
        else:
            self._renderer.show_board(state.board)

        # Always display settings and status if available
        if state.settings is not None:
            self._renderer.show_settings(state.settings)
        if state.message:
            self._renderer.show_status(state.message)

        # keep internal replay flag in sync
        self.in_replay_mode = bool(state.is_replay_mode)

        # final renderer refresh hook
        try:
            self._renderer.refresh()
        except Exception:
            # renderer refresh should not break UI refresh
            pass

    # Helper
    def _safe_get_state(self) -> Optional[GameViewState]:
        try:
            return self._app.getCurrentViewState()
        except Exception as ex:  # surface generic errors
            self._renderer.show_status(f"Error: {ex}")
            return None
