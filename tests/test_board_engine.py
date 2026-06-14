import json
import os

import pytest

from lifeboard import board_engine
from lifeboard.board_engine import (
    save_board,
    load_board,
    checkpoint_for_undo,
    undo_board,
    add_widget,
    replace_board,
    set_theme,
    list_available_themes,
    update_widget,
    apply_layout_edits,
    auto_layout,
)


@pytest.fixture
def board_paths(tmp_path, monkeypatch):
    board_file = tmp_path / "board.json"
    backup_file = tmp_path / "board.json.prev"
    monkeypatch.setattr(board_engine, "BOARD_FILE", str(board_file))
    monkeypatch.setattr(board_engine, "BACKUP_FILE", str(backup_file))
    monkeypatch.setattr("config.BOARD_FILE", str(board_file))
    monkeypatch.setattr("config.OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setattr("config.CONFIG_DIR", str(tmp_path))
    return board_file, backup_file


@pytest.fixture
def fake_themes(tmp_path, monkeypatch):
    themes_dir = tmp_path / "themes"
    themes_dir.mkdir()
    for name in ("minimal", "hacker"):
        d = themes_dir / name
        d.mkdir()
        (d / "global.css").write_text(f"/* {name} */")
    monkeypatch.setattr(board_engine, "THEMES_DIR", str(themes_dir))
    return themes_dir


class TestSaveBoardDoesNotAutoBackup:
    def test_new_board_uses_detected_default_resolution(self, board_paths, monkeypatch):
        monkeypatch.setattr(board_engine, "get_default_resolution", lambda: [3024, 1964])

        board = load_board()

        assert board["resolution"] == [3024, 1964]

    def test_save_board_does_not_create_backup(self, board_paths):
        _, backup_file = board_paths
        save_board({"theme": "minimal", "resolution": [100, 100], "widgets": []})
        assert not backup_file.exists()

    def test_repeated_saves_do_not_create_backup(self, board_paths):
        _, backup_file = board_paths
        save_board({"theme": "minimal", "resolution": [100, 100], "widgets": []})
        save_board({"theme": "hacker", "resolution": [100, 100], "widgets": []})
        assert not backup_file.exists()


class TestCheckpointForUndo:
    def test_checkpoint_snapshots_current_board(self, board_paths):
        board_file, backup_file = board_paths
        save_board({"theme": "minimal", "resolution": [100, 100], "widgets": []})
        checkpoint_for_undo()
        assert backup_file.exists()
        snap = json.loads(backup_file.read_text())
        assert snap["theme"] == "minimal"

    def test_checkpoint_no_op_when_no_board_yet(self, board_paths):
        _, backup_file = board_paths
        checkpoint_for_undo()
        assert not backup_file.exists()

    def test_multiple_saves_after_one_checkpoint_preserve_original(self, board_paths):
        board_file, backup_file = board_paths
        # Original state
        save_board({"theme": "minimal", "resolution": [100, 100], "widgets": []})
        # Start of a logical user operation
        checkpoint_for_undo()
        # Operation does multiple internal saves
        save_board({"theme": "singapore", "resolution": [100, 100], "widgets": []})
        save_board({"theme": "singapore", "resolution": [100, 100], "widgets": [{"id": "x"}]})
        # Backup must still hold the original pre-operation state
        snap = json.loads(backup_file.read_text())
        assert snap["theme"] == "minimal"
        assert snap["widgets"] == []

    def test_undo_restores_from_checkpoint_after_multiple_saves(self, board_paths):
        save_board({"theme": "minimal", "resolution": [100, 100], "widgets": []})
        checkpoint_for_undo()
        save_board({"theme": "singapore", "resolution": [100, 100], "widgets": []})
        save_board({"theme": "singapore", "resolution": [100, 100], "widgets": [{"id": "y"}]})
        assert undo_board() is True
        restored = load_board()
        assert restored["theme"] == "minimal"
        assert restored["widgets"] == []


class TestListAvailableThemes:
    def test_lists_existing_themes(self, fake_themes):
        themes = list_available_themes()
        assert set(themes) == {"minimal", "hacker"}

    def test_returns_empty_when_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(board_engine, "THEMES_DIR", str(tmp_path / "nope"))
        assert list_available_themes() == []


class TestSetThemeValidation:
    def test_rejects_unknown_theme(self, board_paths, fake_themes):
        board = {"theme": "minimal", "resolution": [100, 100], "widgets": []}
        save_board(board)
        with pytest.raises(ValueError) as exc:
            set_theme(board, "singapore")
        assert "singapore" in str(exc.value)
        # board not mutated
        assert board["theme"] == "minimal"
        # disk not mutated
        on_disk = load_board()
        assert on_disk["theme"] == "minimal"

    def test_accepts_known_theme(self, board_paths, fake_themes):
        board = {"theme": "minimal", "resolution": [100, 100], "widgets": []}
        save_board(board)
        set_theme(board, "hacker")
        assert board["theme"] == "hacker"
        on_disk = load_board()
        assert on_disk["theme"] == "hacker"


class TestUpdateWidgetGeometry:
    def test_accepts_object_position(self, board_paths):
        board = {
            "theme": "minimal",
            "resolution": [100, 100],
            "widgets": [
                {
                    "id": "photo",
                    "description": "Photo",
                    "position": [75.5, 6.0],
                    "size": [22.5, 38.0],
                    "data": {},
                    "html_template": "",
                    "css": "",
                },
            ],
        }
        save_board(board)

        update_widget(board, "photo", {"position": {"x": 2, "y": 34}})

        assert board["widgets"][0]["position"] == [2.0, 34.0]

    def test_rejects_bad_position_without_mutating(self, board_paths):
        board = {
            "theme": "minimal",
            "resolution": [100, 100],
            "widgets": [
                {
                    "id": "photo",
                    "description": "Photo",
                    "position": [75.5, 6.0],
                    "size": [22.5, 38.0],
                    "data": {"topic": "singapore"},
                    "html_template": "",
                    "css": "",
                },
            ],
        }
        save_board(board)

        with pytest.raises(ValueError):
            update_widget(board, "photo", {"data": {"topic": "tokyo"}, "position": {"x": 2}})

        assert board["widgets"][0]["position"] == [75.5, 6.0]
        assert board["widgets"][0]["data"] == {"topic": "singapore"}

    def test_update_todo_data_resizes_from_item_count(self, board_paths):
        board = {
            "theme": "minimal",
            "resolution": [100, 100],
            "widgets": [
                {
                    "id": "todo-empty",
                    "description": "To-do list",
                    "position": [10, 10],
                    "size": [14.5, 91.0],
                    "data": {"title": "Empty", "items": []},
                    "html_template": "",
                    "css": "",
                },
            ],
        }
        save_board(board)

        update_widget(board, "todo-empty", {"data": {"items": []}})

        assert board["widgets"][0]["size"] == [14.5, 14.0]

    def test_data_only_update_does_not_move_status_widget(self, board_paths):
        board = {
            "theme": "minimal",
            "resolution": [100, 100],
            "widgets": [
                {
                    "id": "todo",
                    "description": "To-do list",
                    "position": [2, 6],
                    "size": [22.5, 41],
                    "data": {"items": []},
                    "html_template": "",
                    "css": "",
                },
                {
                    "id": "weather",
                    "description": "Current weather conditions with temperature",
                    "position": [27.2, 5.6],
                    "size": [22, 18],
                    "data": {"location": "auto"},
                    "data_provider": "weather",
                    "html_template": "",
                    "css": "",
                },
            ],
        }
        save_board(board)

        update_widget(board, "weather", {"data": {"location": "Tallinn", "units": "metric"}})

        assert board["widgets"][1]["position"] == [27.2, 5.6]
        assert board["widgets"][1]["data"]["location"] == "Tallinn"

    def test_update_position_keeps_standard_gutter(self, board_paths):
        board = {
            "theme": "minimal",
            "resolution": [100, 100],
            "widgets": [
                {
                    "id": "top",
                    "description": "Top",
                    "position": [10, 10],
                    "size": [20, 10],
                    "data": {},
                    "html_template": "",
                    "css": "",
                },
                {
                    "id": "bottom",
                    "description": "Bottom",
                    "position": [60, 60],
                    "size": [20, 10],
                    "data": {},
                    "html_template": "",
                    "css": "",
                },
            ],
        }
        save_board(board)

        update_widget(board, "bottom", {"position": [10, 20]})

        assert board["widgets"][1]["position"] != [10.0, 20.0]
        assert not board_engine._widgets_too_close(
            board["widgets"][0]["position"],
            board["widgets"][0]["size"],
            board["widgets"][1]["position"],
            board["widgets"][1]["size"],
        )


class TestAddWidgetGeometry:
    def test_add_todo_uses_content_height_before_resolving_overlap(self, board_paths):
        board = {
            "theme": "minimal",
            "resolution": [100, 100],
            "widgets": [
                {
                    "id": "news",
                    "description": "News",
                    "position": [73, 38],
                    "size": [24, 26],
                    "data": {},
                    "html_template": "",
                    "css": "",
                },
            ],
        }
        save_board(board)

        widget = add_widget(
            board,
            description="Social to-do list",
            position=[75, 6],
            size=[14.5, 91.0],
            data={"title": "Social", "items": []},
            html_template="",
            css="",
            widget_id="todo-social",
        )

        assert widget["size"] == [14.5, 14.0]
        assert widget["position"] == [75.0, 6.0]

    def test_add_widget_clamps_to_board_bounds(self, board_paths):
        board = {"theme": "minimal", "resolution": [100, 100], "widgets": []}
        save_board(board)

        widget = add_widget(board, "Note", [98, -5], [12, 1], {}, "", "", widget_id="note")

        assert widget["position"] == [88.0, 0.0]
        assert widget["size"] == [12.0, 3.0]

    def test_background_does_not_block_normal_widget_position(self, board_paths):
        board = {
            "theme": "minimal",
            "resolution": [100, 100],
            "widgets": [
                {
                    "id": "bg",
                    "description": "Background image",
                    "position": [0, 0],
                    "size": [100, 100],
                    "data": {"file_path": "/tmp/bg.jpg"},
                    "html_template": "",
                    "css": "",
                    "data_provider": "image",
                    "z_index": -1,
                },
            ],
        }
        save_board(board)

        widget = add_widget(board, "Note", [2, 6], [20, 10], {}, "", "", widget_id="note")

        assert widget["position"] == [2.0, 6.0]

    def test_add_widget_keeps_standard_gutter(self, board_paths):
        board = {
            "theme": "minimal",
            "resolution": [100, 100],
            "widgets": [
                {
                    "id": "top",
                    "description": "Top",
                    "position": [10, 10],
                    "size": [20, 10],
                    "data": {},
                    "html_template": "",
                    "css": "",
                },
            ],
        }
        save_board(board)

        widget = add_widget(board, "Bottom", [10, 20], [20, 10], {}, "", "", widget_id="bottom")

        assert widget["position"] != [10.0, 20.0]
        assert not board_engine._widgets_too_close(
            board["widgets"][0]["position"],
            board["widgets"][0]["size"],
            widget["position"],
            widget["size"],
        )


class TestReplaceBoardGeometry:
    def test_replace_board_normalizes_todo_sizes_and_overlaps(self, board_paths):
        board = {"theme": "minimal", "resolution": [100, 100], "widgets": []}
        new_board = {
            "theme": "minimal",
            "resolution": [100, 100],
            "widgets": [
                {
                    "id": "news",
                    "description": "News",
                    "position": [73, 38],
                    "size": [24, 26],
                    "data": {},
                    "html_template": "",
                    "css": "",
                },
                {
                    "id": "todo-empty",
                    "description": "To-do list",
                    "position": [75, 6],
                    "size": [14.5, 91.0],
                    "data": {"items": []},
                    "html_template": "",
                    "css": "",
                },
            ],
        }

        replace_board(board, new_board)

        assert board["widgets"][1]["size"] == [14.5, 14.0]
        assert board["widgets"][1]["position"] == [75.0, 6.0]

    def test_replace_board_normalizes_touching_widgets(self, board_paths):
        board = {"theme": "minimal", "resolution": [100, 100], "widgets": []}
        new_board = {
            "theme": "minimal",
            "resolution": [100, 100],
            "widgets": [
                {
                    "id": "top",
                    "description": "Top",
                    "position": [10, 10],
                    "size": [20, 10],
                    "data": {},
                    "html_template": "",
                    "css": "",
                },
                {
                    "id": "bottom",
                    "description": "Bottom",
                    "position": [10, 20],
                    "size": [20, 10],
                    "data": {},
                    "html_template": "",
                    "css": "",
                },
            ],
        }

        replace_board(board, new_board)

        assert board["widgets"][1]["position"] != [10.0, 20.0]
        assert not board_engine._widgets_too_close(
            board["widgets"][0]["position"],
            board["widgets"][0]["size"],
            board["widgets"][1]["position"],
            board["widgets"][1]["size"],
        )

    def test_replace_board_normalizes_null_z_index(self, board_paths):
        board = {"theme": "minimal", "resolution": [100, 100], "widgets": []}
        new_board = {
            "theme": "minimal",
            "resolution": [100, 100],
            "widgets": [
                {
                    "id": "clock",
                    "description": "Clock",
                    "position": [0, 0],
                    "size": [20, 10],
                    "data": {},
                    "html_template": "",
                    "css": "",
                    "z_index": None,
                },
            ],
        }

        replace_board(board, new_board)

        assert board["widgets"][0]["z_index"] == 0


class TestAutoLayout:
    def test_market_widgets_are_compact_even_when_previously_huge(self, board_paths):
        board = {
            "theme": "minimal",
            "resolution": [100, 100],
            "widgets": [
                {
                    "id": "notes",
                    "description": "Notes",
                    "position": [0, 0],
                    "size": [20, 18],
                    "data": {},
                    "html_template": "",
                    "css": "",
                },
                {
                    "id": "crypto",
                    "description": "Crypto ticker",
                    "position": [0, 0],
                    "size": [66, 60],
                    "data": {},
                    "html_template": "",
                    "css": "",
                    "data_provider": "crypto",
                },
                {
                    "id": "stocks",
                    "description": "Stock ticker",
                    "position": [0, 0],
                    "size": [80, 40],
                    "data": {},
                    "html_template": "",
                    "css": "",
                    "data_provider": "stock",
                },
            ],
        }

        auto_layout(board, columns=4, gutter=2.0, base_row_height=18.0)

        assert board["widgets"][1]["size"] == [22.5, 18.0]
        assert board["widgets"][2]["size"] == [22.5, 18.0]
        assert board["widgets"][1]["position"][1] >= 6.0
        assert board["widgets"][1]["position"][1] >= board["widgets"][0]["position"][1]

    def test_background_widgets_are_not_moved(self, board_paths):
        board = {
            "theme": "minimal",
            "resolution": [100, 100],
            "widgets": [
                {
                    "id": "bg",
                    "description": "Background",
                    "position": [0, 0],
                    "size": [100, 100],
                    "data": {"file_path": "/tmp/background.jpg"},
                    "html_template": "",
                    "css": "",
                    "data_provider": "image",
                    "z_index": -1,
                },
                {
                    "id": "clock",
                    "description": "Clock",
                    "position": [80, 80],
                    "size": [20, 18],
                    "data": {},
                    "html_template": "",
                    "css": "",
                    "data_provider": "datetime",
                },
            ],
        }

        auto_layout(board)

        assert board["widgets"][0]["position"] == [0, 0]
        assert board["widgets"][0]["size"] == [100, 100]
        assert board["widgets"][1]["position"] == [2.0, 6.0]

    def test_empty_image_widget_is_compacted_not_preserved_as_background(self, board_paths):
        board = {
            "theme": "minimal",
            "resolution": [100, 100],
            "widgets": [
                {
                    "id": "empty-image",
                    "description": "Display a local image",
                    "position": [28, 10],
                    "size": [70, 85],
                    "data": {"file_path": "", "fit": "cover"},
                    "html_template": "",
                    "css": "",
                    "data_provider": "image",
                    "z_index": -1,
                },
            ],
        }

        auto_layout(board, columns=4, gutter=2.0, base_row_height=18.0)

        assert board["widgets"][0]["position"] == [2.0, 6.0]
        assert board["widgets"][0]["size"] == [22.5, 18.0]
        assert board["widgets"][0]["z_index"] == 0

    def test_todo_height_expands_for_three_tasks(self, board_paths):
        board = {
            "theme": "minimal",
            "resolution": [100, 100],
            "widgets": [
                {
                    "id": "todo",
                    "description": "To-do list with checkable items",
                    "position": [0, 0],
                    "size": [22.5, 60],
                    "data": {
                        "items": [
                            {"text": "First", "done": False},
                            {"text": "Second", "done": False},
                            {"text": "Third", "done": False},
                        ]
                    },
                    "html_template": "",
                    "css": "",
                },
            ],
        }

        auto_layout(board, columns=4, gutter=2.0, base_row_height=18.0)

        assert board["widgets"][0]["size"] == [22.5, 23.0]

    def test_todo_height_continues_growing_for_longer_lists(self, board_paths):
        board = {
            "theme": "minimal",
            "resolution": [100, 100],
            "widgets": [
                {
                    "id": "todo",
                    "description": "To-do list with checkable items",
                    "position": [0, 0],
                    "size": [22.5, 60],
                    "data": {
                        "items": [
                            {"text": f"Task {i}", "done": False}
                            for i in range(1, 8)
                        ]
                    },
                    "html_template": "",
                    "css": "",
                },
            ],
        }

        auto_layout(board, columns=4, gutter=2.0, base_row_height=18.0)

        assert board["widgets"][0]["size"] == [22.5, 35.0]

    def test_compact_todo_uses_standard_gutter_after_reorganize(self, board_paths):
        board = {
            "theme": "minimal",
            "resolution": [100, 100],
            "widgets": [
                {
                    "id": "todo-empty",
                    "description": "To-do list",
                    "position": [0, 0],
                    "size": [22.5, 91],
                    "data": {"items": []},
                    "html_template": "",
                    "css": "",
                },
                {
                    "id": "note",
                    "description": "Note",
                    "position": [0, 0],
                    "size": [22.5, 18],
                    "data": {},
                    "html_template": "",
                    "css": "",
                },
            ],
        }

        auto_layout(board, columns=1, gutter=2.0, base_row_height=18.0)

        todo = board["widgets"][0]
        note = board["widgets"][1]
        assert todo["size"] == [96.0, 14.0]
        assert note["position"][1] == todo["position"][1] + todo["size"][1] + 2.0


class TestApplyLayoutEdits:
    def test_applies_exact_manual_position_and_size(self, board_paths):
        board = {
            "theme": "minimal",
            "resolution": [100, 100],
            "widgets": [
                {
                    "id": "todo",
                    "description": "To-do list",
                    "position": [2, 6],
                    "size": [22.5, 18],
                    "data": {"items": []},
                    "html_template": "<div></div>",
                    "css": ".todo {}",
                    "data_provider": "custom",
                },
            ],
        }

        apply_layout_edits(
            board,
            [{"id": "todo", "position": [12.3456, 9.8765], "size": [31.2345, 20.9876]}],
        )

        assert board["widgets"][0]["position"] == [12.346, 9.877]
        assert board["widgets"][0]["size"] == [31.235, 20.988]
        assert board["widgets"][0]["data"] == {"items": []}
        assert board["widgets"][0]["html_template"] == "<div></div>"
        assert load_board()["widgets"][0]["position"] == [12.346, 9.877]

    def test_clamps_manual_edits_to_board_bounds(self, board_paths):
        board = {
            "theme": "minimal",
            "resolution": [100, 100],
            "widgets": [
                {
                    "id": "wide",
                    "description": "Wide widget",
                    "position": [0, 0],
                    "size": [20, 20],
                    "data": {},
                    "html_template": "",
                    "css": "",
                },
            ],
        }

        apply_layout_edits(
            board,
            [{"id": "wide", "position": [98, -5], "size": [12, 1]}],
        )

        assert board["widgets"][0]["position"] == [88.0, 0.0]
        assert board["widgets"][0]["size"] == [12.0, 3.0]

    def test_ignores_unknown_widgets(self, board_paths):
        board = {
            "theme": "minimal",
            "resolution": [100, 100],
            "widgets": [
                {
                    "id": "known",
                    "description": "Known widget",
                    "position": [4, 5],
                    "size": [20, 20],
                    "data": {},
                    "html_template": "",
                    "css": "",
                },
            ],
        }

        apply_layout_edits(
            board,
            [{"id": "missing", "position": [10, 10], "size": [10, 10]}],
        )

        assert board["widgets"][0]["position"] == [4, 5]
        assert board["widgets"][0]["size"] == [20, 20]
