from pathlib import Path

import pytest

from personal_finance_assistant.settings import Settings


def _clear_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USER_IDS",
        "FPA_DATABASE_PATH",
        "FPA_USER_TIMEZONE",
        "FPA_LOG_LEVEL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_settings_parse_positive_numeric_allowlist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_settings(monkeypatch)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "12345, 67890,12345")

    settings = Settings.from_environment()

    assert settings.telegram_allowed_user_ids == frozenset({12345, 67890})
    assert settings.user_timezone == "Europe/Berlin"


@pytest.mark.parametrize("raw_ids", ["-100", "0", "abc", "12,broken", "123,", "12,,34"])
def test_settings_reject_invalid_allowlist_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raw_ids: str
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_settings(monkeypatch)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", raw_ids)

    with pytest.raises(ValueError, match="numeric IDs"):
        Settings.from_environment()


def test_empty_allowlist_is_not_silently_populated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_settings(monkeypatch)

    settings = Settings.from_environment()

    assert settings.telegram_allowed_user_ids == frozenset()
