"""
UI Controller tests for user action dispatching and rendering feedback based on view state.
This suite verifies that UI forwards actions to GameApplication and renders via IViewRenderer
according to the provided requirements.
"""
import pytest
from unittest.mock import MagicMock

from com.ui import UI, IViewRenderer
from com.app import GameApplication, GameViewState
from com.types import Position


# Fixtures
@pytest.fixture
def app_mock():
    """Mocked GameApplication (service layer)."""
    return MagicMock(spec=GameApplication)


@pytest.fixture
def renderer_mock():
    """Mocked IViewRenderer for rendering operations."""
    return MagicMock(spec=IViewRenderer)


@pytest.fixture
def ui(app_mock, renderer_mock):
    """UI instance using mocked dependencies."""
    return UI(app_mock, renderer_mock)


class TestUserActionDispatch:
    """Tests for user action dispatch feature (M1F1)."""

    def test_onStartGame_when_allowed_should_forward_to_app_startNewGame(self, ui, app_mock, renderer_mock):
        """FR-001: When allowed, UI should forward start game request to application."""
        # Arrange
        ui.can_start = True

        # Act
        ui.onStartGame()

        # Assert
        app_mock.startNewGame.assert_called_once_with(None, None, None)
        renderer_mock.show_status.assert_not_called()

    def test_onStartGame_when_disallowed_should_not_call_app_and_show_status(self, ui, app_mock, renderer_mock):
        """FR-001 exceptions: When not in allowed view, should not trigger application and show status."""
        # Arrange
        ui.can_start = False

        # Act
        ui.onStartGame()

        # Assert
        app_mock.startNewGame.assert_not_called()
        renderer_mock.show_status.assert_called_once()
        # Verify a helpful message is shown
        msg = renderer_mock.show_status.call_args[0][0]
        assert "Start not allowed" in msg

    def test_onSelectCell_should_forward_position(self, ui, app_mock):
        """FR-028: UI should forward selected cell to application as Position."""
        # Arrange
        row, col = 2, 3

        # Act
        ui.onSelectCell(row, col)

        # Assert
        app_mock.makeMove.assert_called_once_with(Position(row=row, col=col))

    def test_onUndo_should_forward_to_app(self, ui, app_mock):
        """FR-046: UI should forward undo action to application."""
        # Act
        ui.onUndo()

        # Assert
        app_mock.undoMove.assert_called_once_with()

    def test_onOpenHistory_should_request_all_history(self, ui, app_mock):
        """FR-055: UI should forward history opening to application with no filter (all)."""
        # Act
        ui.onOpenHistory()

        # Assert
        app_mock.getHistory.assert_called_once_with(None)

    def test_onOpenReplay_should_forward_and_set_replay_flag(self, ui, app_mock):
        """FR-055/FR-061: UI should start replay and mark internal replay mode."""
        # Arrange
        record_id = "rec-123"

        # Act
        ui.onOpenReplay(record_id)

        # Assert
        app_mock.startReplay.assert_called_once_with(record_id)
        assert ui.in_replay_mode is True

    def test_onReplayStepChange_should_forward_to_app(self, ui, app_mock):
        """FR-055: UI should forward replay step change to application."""
        # Arrange
        idx = 5

        # Act
        ui.onReplayStepChange(idx)

        # Assert
        app_mock.goToReplayStep.assert_called_once_with(idx)

    def test_onOpenSettings_should_render_settings_from_state(self, ui, app_mock, renderer_mock):
        """FR-066/FR-074/FR-100: UI should fetch current settings and render settings panel."""
        # Arrange
        state = GameViewState(settings={"difficulty": "hard", "rule": "standard"})
        app_mock.getCurrentViewState.return_value = state

        # Act
        ui.onOpenSettings()

        # Assert
        app_mock.getCurrentViewState.assert_called_once_with()
        renderer_mock.show_settings.assert_called_once_with(state.settings)

    def test_onChangeSetting_should_forward_settings_map(self, ui, app_mock):
        """FR-066/FR-074: UI should forward setting change to application as a map."""
        # Arrange
        key, value = "difficulty", "medium"

        # Act
        ui.onChangeSetting(key, value)

        # Assert
        app_mock.updateSettings.assert_called_once_with({key: value})

    def test_onBackToMain_when_in_replay_should_exit_replay_and_reset_flag(self, ui, app_mock):
        """FR-055/FR-061: When in replay, back to main should exit replay via application and reset flag."""
        # Arrange
        ui.in_replay_mode = True

        # Act
        ui.onBackToMain()

        # Assert
        app_mock.exitReplay.assert_called_once_with()
        assert ui.in_replay_mode is False

    def test_onBackToMain_when_not_in_replay_should_do_nothing(self, ui, app_mock):
        """FR-055/FR-061: When not in replay, back to main should not call exitReplay."""
        # Arrange
        ui.in_replay_mode = False

        # Act
        ui.onBackToMain()

        # Assert
        app_mock.exitReplay.assert_not_called()


class TestViewRenderingFeedback:
    """Tests for rendering feedback feature (M1F2)."""

    def test_renderMainMenu_should_call_renderer_show_main_menu(self, ui, renderer_mock):
        """Rendering main menu should call renderer.show_main_menu."""
        # Act
        ui.renderMainMenu()

        # Assert
        renderer_mock.show_main_menu.assert_called_once_with()

    def test_renderBoard_should_call_renderer_show_board(self, ui, renderer_mock):
        """Rendering board should call renderer.show_board with the provided board view."""
        # Arrange
        board = [[".", "."], ["X", "O"]]

        # Act
        ui.renderBoard(board)

        # Assert
        renderer_mock.show_board.assert_called_once_with(board)

    def test_renderStatus_should_call_renderer_show_status(self, ui, renderer_mock):
        """Rendering status should call renderer.show_status with message."""
        # Arrange
        msg = "AI thinking..."

        # Act
        ui.renderStatus(msg)

        # Assert
        renderer_mock.show_status.assert_called_once_with(msg)

    def test_renderHistory_should_call_renderer_show_history(self, ui, renderer_mock):
        """Rendering history should call renderer.show_history with items."""
        # Arrange
        history = ["game1", "game2"]

        # Act
        ui.renderHistory(history)

        # Assert
        renderer_mock.show_history.assert_called_once_with(history)

    def test_renderReplay_should_call_renderer_show_replay(self, ui, renderer_mock):
        """Rendering replay should call renderer.show_replay with moves and step index."""
        # Arrange
        moves = ["A1", "B2", "C3"]
        step = 2

        # Act
        ui.renderReplay(moves, step)

        # Assert
        renderer_mock.show_replay.assert_called_once_with(moves, step)

    def test_renderSettings_should_call_renderer_show_settings(self, ui, renderer_mock):
        """Rendering settings should call renderer.show_settings with settings data."""
        # Arrange
        settings = {"difficulty": "hard", "rule": "standard"}

        # Act
        ui.renderSettings(settings)

        # Assert
        renderer_mock.show_settings.assert_called_once_with(settings)

    def test_refresh_when_new_game_state_should_show_board_settings_status_and_refresh(self, ui, app_mock, renderer_mock):
        """FR-009: Should display board, settings, and status for a new game state."""
        # Arrange
        board = [[".", "."], [".", "."]]
        settings = {"difficulty": "easy", "rule": "standard"}
        message = "Current: HUMAN"
        state = GameViewState(board=board, settings=settings, message=message)
        app_mock.getCurrentViewState.return_value = state

        # Act
        ui.refresh()

        # Assert
        renderer_mock.show_board.assert_called_once_with(board)
        renderer_mock.show_settings.assert_called_once_with(settings)
        renderer_mock.show_status.assert_called_once_with(message)
        renderer_mock.refresh.assert_called_once_with()
        assert ui.in_replay_mode is False

    def test_refresh_when_ai_turn_should_show_wait_message_and_board(self, ui, app_mock, renderer_mock):
        """FR-040: On AI turn, should show wait message and keep board unchanged."""
        # Arrange
        board = [["X", "."], [".", "O"]]
        message = "Wait for AI"
        state = GameViewState(board=board, message=message, is_ai_turn=True)
        app_mock.getCurrentViewState.return_value = state

        # Act
        ui.refresh()

        # Assert
        renderer_mock.show_board.assert_called_once_with(board)
        renderer_mock.show_status.assert_called_once_with(message)
        renderer_mock.refresh.assert_called_once_with()

    def test_refresh_when_invalid_move_should_show_error_and_keep_board(self, ui, app_mock, renderer_mock):
        """FR-041: On invalid move, should show error message and keep board unchanged."""
        # Arrange
        board = [["X", "O"], [".", "."]]
        message = "Invalid move: occupied"
        state = GameViewState(board=board, message=message, last_move_valid=False)
        app_mock.getCurrentViewState.return_value = state

        # Act
        ui.refresh()

        # Assert
        renderer_mock.show_board.assert_called_once_with(board)
        renderer_mock.show_status.assert_called_once_with(message)
        renderer_mock.refresh.assert_called_once_with()

    def test_refresh_when_game_over_should_show_game_over_message_and_keep_board(self, ui, app_mock, renderer_mock):
        """FR-042: After game over, should show message and keep board unchanged."""
        # Arrange
        board = [["X", "O"], ["X", "O"]]
        message = "Game ended"
        state = GameViewState(board=board, message=message, is_game_over=True)
        app_mock.getCurrentViewState.return_value = state

        # Act
        ui.refresh()

        # Assert
        renderer_mock.show_board.assert_called_once_with(board)
        renderer_mock.show_status.assert_called_once_with(message)
        renderer_mock.refresh.assert_called_once_with()

    def test_refresh_when_ai_thinking_should_show_ai_thinking_message(self, ui, app_mock, renderer_mock):
        """FR-045: When AI is thinking, should show an appropriate status message."""
        # Arrange
        board = [[".", "."], [".", "."]]
        message = "AI thinking..."
        state = GameViewState(board=board, message=message, ai_thinking=True, is_ai_turn=True)
        app_mock.getCurrentViewState.return_value = state

        # Act
        ui.refresh()

        # Assert
        renderer_mock.show_board.assert_called_once_with(board)
        renderer_mock.show_status.assert_called_once_with(message)
        renderer_mock.refresh.assert_called_once_with()

    def test_refresh_when_replay_mode_should_show_replay_and_settings_and_status(self, ui, app_mock, renderer_mock):
        """FR-061: In replay mode, should render replay view and not the board, plus settings/status."""
        # Arrange
        replay_moves = ["A1", "B2", "C3"]
        step_index = 1
        settings = {"difficulty": "hard", "rule": "standard"}
        message = "Viewing replay"
        state = GameViewState(
            is_replay_mode=True,
            replay_moves=replay_moves,
            step_index=step_index,
            settings=settings,
            message=message,
        )
        app_mock.getCurrentViewState.return_value = state

        # Act
        ui.refresh()

        # Assert
        renderer_mock.show_replay.assert_called_once_with(replay_moves, step_index)
        renderer_mock.show_board.assert_not_called()
        renderer_mock.show_settings.assert_called_once_with(settings)
        renderer_mock.show_status.assert_called_once_with(message)
        renderer_mock.refresh.assert_called_once_with()
        assert ui.in_replay_mode is True

    def test_refresh_should_display_current_settings(self, ui, app_mock, renderer_mock):
        """FR-100: Should always display currently effective settings."""
        # Arrange
        state = GameViewState(board=[["."]], settings={"difficulty": "medium", "rule": "fast"})
        app_mock.getCurrentViewState.return_value = state

        # Act
        ui.refresh()

        # Assert
        renderer_mock.show_settings.assert_called_once_with({"difficulty": "medium", "rule": "fast"})
        renderer_mock.refresh.assert_called_once_with()

    def test_refresh_when_get_state_fails_should_show_error_and_not_render_board_or_replay(self, ui, app_mock, renderer_mock):
        """FR-101: On failure to get state, should show a clear error message and not render board or replay."""
        # Arrange
        app_mock.getCurrentViewState.side_effect = Exception("boom")

        # Act
        ui.refresh()

        # Assert
        renderer_mock.show_status.assert_called_once()
        msg = renderer_mock.show_status.call_args[0][0]
        assert msg.startswith("Error: ") and "boom" in msg
        renderer_mock.show_board.assert_not_called()
        renderer_mock.show_replay.assert_not_called()

    def test_refresh_should_swallow_renderer_refresh_exception(self, ui, app_mock, renderer_mock):
        """Renderer refresh errors should not break UI refresh flow."""
        # Arrange
        state = GameViewState(board=[[".", "."]])
        app_mock.getCurrentViewState.return_value = state
        renderer_mock.refresh.side_effect = Exception("device lost")

        # Act
        ui.refresh()  # Should not raise

        # Assert
        renderer_mock.show_board.assert_called_once_with([[".", "."]])
        renderer_mock.refresh.assert_called_once_with()
