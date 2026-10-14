import json

import pytest

from autobard.config import load_config, save_config


def write_old_config(path, history=18, timeout=8.0):
    old = {
        "tracking": {"history_size": history, "history_extra": "preserve"},
        "session": {"max_duration_s": timeout, "pointer_start_delay_ms": 125},
        "capture": {"roi_normalized": [0.2, 0.3, 0.8, 0.9]},
        "vision": {"note_band_normalized": [0.01, 0.42, 0.99, 0.57]},
        "scheduler": {"input_latency_ms": 45, "model_input_latency_ms": 50},
        "action": {"mode": "system_input", "acknowledge_online_risk": True},
        "hotkeys": {"abort": "<f7>"},
        "updates": {"enabled": False},
        "unknown_setting": {"保留": True},
    }
    original = json.dumps(old, ensure_ascii=False).encode("utf-8")
    path.write_bytes(original)
    return old, original


def test_old_updater_can_keep_config_and_new_app_migrates_it(tmp_path):
    # The old installer replaces code but deliberately leaves this file intact.
    path = tmp_path / "settings.json"
    old, original = write_old_config(path)
    loaded = load_config(path)
    assert loaded["tracking"]["history_size"] == 90
    assert loaded["session"]["max_duration_s"] == 12
    saved = json.loads(path.read_bytes())
    expected = {**old, "config_revision": 1}
    expected["tracking"] = {**old["tracking"], "history_size": 90}
    expected["session"] = {**old["session"], "max_duration_s": 12.0}
    assert saved == expected
    assert path.with_name("settings.json.pre-migration-v1.bak").read_bytes() == original


def test_custom_values_survive_migration(tmp_path):
    path = tmp_path / "settings.json"
    write_old_config(path, history=55, timeout=15)
    loaded = load_config(path)
    assert loaded["tracking"]["history_size"] == 55
    assert loaded["session"]["max_duration_s"] == 15


def test_migration_runs_once_and_later_user_choices_are_preserved(tmp_path):
    path = tmp_path / "settings.json"
    _, original = write_old_config(path)
    loaded = load_config(path)
    first_saved = path.read_bytes()
    load_config(path)
    assert path.read_bytes() == first_saved
    loaded["tracking"]["history_size"] = 18
    loaded["session"]["max_duration_s"] = 8
    save_config(loaded, path)
    reloaded = load_config(path)
    assert reloaded["tracking"]["history_size"] == 18
    assert reloaded["session"]["max_duration_s"] == 8
    assert path.with_name("settings.json.pre-migration-v1.bak").read_bytes() == original


def test_missing_new_fields_use_new_defaults_without_copying_all_defaults_to_disk(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"updates": {"enabled": false}}')
    loaded = load_config(path)
    assert loaded["tracking"]["history_size"] == 90
    assert loaded["session"]["max_duration_s"] == 12
    assert json.loads(path.read_bytes()) == {"updates": {"enabled": False}, "config_revision": 1}


def test_invalid_config_is_not_migrated_on_disk(tmp_path):
    path = tmp_path / "settings.json"
    _, original = write_old_config(path)
    invalid = json.loads(original)
    invalid["capture"]["roi_normalized"] = [0, 0, 0, 0]
    path.write_text(json.dumps(invalid))
    before = path.read_bytes()
    with pytest.raises(ValueError):
        load_config(path)
    assert path.read_bytes() == before
    assert not path.with_name("settings.json.pre-migration-v1.bak").exists()


def test_read_only_config_uses_migration_in_memory(tmp_path, monkeypatch, caplog):
    path = tmp_path / "settings.json"
    _, original = write_old_config(path)

    def deny(*args):
        raise PermissionError("read only")

    monkeypatch.setattr("autobard.config._persist_migration", deny)
    loaded = load_config(path)
    assert loaded["tracking"]["history_size"] == 90
    assert loaded["session"]["max_duration_s"] == 12
    assert path.read_bytes() == original
    assert "无法保存" in caplog.text


def test_failed_atomic_save_keeps_original(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    _, original = write_old_config(path)

    def deny(*args):
        raise PermissionError("locked")

    monkeypatch.setattr("autobard.config.os.replace", deny)
    loaded = load_config(path)
    assert loaded["tracking"]["history_size"] == 90
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))
    assert path.with_name("settings.json.pre-migration-v1.bak").read_bytes() == original


def test_future_revision_is_not_downgraded(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"config_revision": 2, "tracking": {"history_size": 18}}')
    original = path.read_bytes()
    loaded = load_config(path)
    assert loaded["config_revision"] == 2
    assert loaded["tracking"]["history_size"] == 18
    assert path.read_bytes() == original


@pytest.mark.parametrize("revision", [True, -1, "1"])
def test_invalid_revision_does_not_rewrite_file(tmp_path, revision):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"config_revision": revision}))
    original = path.read_bytes()
    with pytest.raises(ValueError, match="config_revision"):
        load_config(path)
    assert path.read_bytes() == original
