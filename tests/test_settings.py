"""Settings persistence and reader configuration tests."""
import json

from utils.settings import SYSTEM_READER_ID, Settings


def test_defaults(temp_settings):
    assert temp_settings.get_default_reader_id() == SYSTEM_READER_ID
    assert temp_settings.get_reader_for_format("archive") == SYSTEM_READER_ID
    assert temp_settings.get_columns() == 4
    assert temp_settings.get_view("mark_read_on_open") is True


def test_save_is_atomic_and_valid_json(temp_settings):
    temp_settings.set_columns(6)
    assert temp_settings.settings_file.exists()
    data = json.loads(temp_settings.settings_file.read_text(encoding="utf-8"))
    assert data["view"]["columns"] == 6


def test_per_format_fallback(temp_settings):
    temp_settings.set_default_reader("yacreader")
    assert temp_settings.get_reader_for_format("archive") == "yacreader"
    temp_settings.set_reader_for_format("pdf", "sumatrapdf")
    assert temp_settings.get_reader_for_format("pdf") == "sumatrapdf"
    assert temp_settings.get_reader_for_format("image") == "yacreader"


def test_custom_reader_lifecycle(temp_settings):
    reader = {
        "id": "custom-test",
        "name": "Test reader",
        "path": "/tmp/test-reader",
        "formats": ["archive", "pdf"],
    }
    assert temp_settings.add_custom_reader(reader)
    assert temp_settings.get_custom_readers()[0]["id"] == "custom-test"

    temp_settings.set_default_reader("custom-test")
    assert temp_settings.get_reader_path() is None  # path does not exist

    assert temp_settings.remove_custom_reader("custom-test")
    assert temp_settings.get_custom_readers() == []
    assert temp_settings.get_default_reader_id() == SYSTEM_READER_ID


def test_legacy_reader_settings_are_migrated(tmp_path):
    settings_file = tmp_path / "settings.json"
    executable = tmp_path / "library.db"
    executable.write_bytes(b"x")
    settings_file.write_text(
        json.dumps(
            {
                "reader": {
                    "enabled": True,
                    "path": str(executable),
                    "name": "Old reader",
                    "use_system_default": False,
                },
                "view": {"columns": 5},
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(settings_file)
    assert settings.get_default_reader_id() == "custom-migrated"
    custom = settings.get_custom_readers()
    assert custom and custom[0]["name"] == "Old reader"
    assert settings.get_columns() == 5


def test_invalid_settings_file_falls_back_to_defaults(tmp_path):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("{not valid json", encoding="utf-8")
    settings = Settings(settings_file)
    assert settings.get_default_reader_id() == SYSTEM_READER_ID


def test_reader_choice_survives_a_restart(temp_settings):
    """The reader picked in the dialog is still the default after reloading."""
    from utils.settings import Settings

    temp_settings.set_default_reader("custom-probe")
    temp_settings.set_reader_for_format("archive", "custom-probe")
    assert temp_settings.save()

    reloaded = Settings(temp_settings.settings_file)
    assert reloaded.get_default_reader_id() == "custom-probe"
    assert reloaded.get_reader_for_format("archive") == "custom-probe"


def test_the_data_folder_can_be_pointed_elsewhere(tmp_path, monkeypatch):
    """The smoke test must never write into a real library.

    ``DIGITAL_LIBRARY_DATA_DIR`` is read when config is imported, so it is
    checked here by importing the module fresh.
    """
    import importlib
    import sys

    monkeypatch.setenv("DIGITAL_LIBRARY_DATA_DIR", str(tmp_path / "sandbox"))
    try:
        import config

        reloaded = importlib.reload(config)
        assert reloaded.DATA_DIR.parent == tmp_path / "sandbox"
        assert reloaded.DATABASE_PATH.parent == reloaded.DATA_DIR
    finally:
        monkeypatch.delenv("DIGITAL_LIBRARY_DATA_DIR", raising=False)
        import config

        importlib.reload(config)
        sys.modules.pop("config", None)


def test_an_old_forced_dark_theme_starts_following_windows(temp_settings):
    """2.4.x wrote "dark" without ever asking; that is not a user choice."""
    import json

    temp_settings.settings_file.write_text(
        json.dumps({"view": {"theme": "dark", "columns": 5}}), encoding="utf-8"
    )
    from utils.settings import Settings

    loaded = Settings(temp_settings.settings_file)
    assert loaded.get_view("theme") == "system"
    assert loaded.get_view("theme_chosen") is False
    assert loaded.get_view("columns") == 5


def test_a_theme_the_user_picked_is_kept(temp_settings):
    temp_settings.set_view("theme", "dark")
    temp_settings.set_view("theme_chosen", True)

    from utils.settings import Settings

    loaded = Settings(temp_settings.settings_file)
    assert loaded.get_view("theme") == "dark"
