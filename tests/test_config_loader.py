"""Tests for configuration loading and key conversion."""

import json
from pathlib import Path

import pytest

from flowly.config.loader import (
    camel_to_snake,
    convert_keys,
    convert_to_camel,
    load_config,
    save_config,
    snake_to_camel,
)
from flowly.config.schema import Config


# ── Key conversion ──────────────────────────────────────────────────


class TestCamelToSnake:
    def test_simple(self):
        assert camel_to_snake("apiKey") == "api_key"

    def test_multiple_words(self):
        assert camel_to_snake("webhookBaseUrl") == "webhook_base_url"

    def test_single_word(self):
        assert camel_to_snake("enabled") == "enabled"

    def test_already_snake(self):
        assert camel_to_snake("api_key") == "api_key"

    def test_consecutive_uppercase(self):
        assert camel_to_snake("sttProvider") == "stt_provider"

    def test_empty(self):
        assert camel_to_snake("") == ""


class TestSnakeToCamel:
    def test_simple(self):
        assert snake_to_camel("api_key") == "apiKey"

    def test_multiple_words(self):
        assert snake_to_camel("webhook_base_url") == "webhookBaseUrl"

    def test_single_word(self):
        assert snake_to_camel("enabled") == "enabled"

    def test_already_camel(self):
        # Not ideal but expected behavior
        assert snake_to_camel("apiKey") == "apiKey"

    def test_empty(self):
        assert snake_to_camel("") == ""


class TestConvertKeys:
    def test_flat_dict(self):
        data = {"apiKey": "sk-123", "maxTokens": 1024}
        result = convert_keys(data)
        assert result == {"api_key": "sk-123", "max_tokens": 1024}

    def test_nested_dict(self):
        data = {"providers": {"openRouter": {"apiKey": "key"}}}
        result = convert_keys(data)
        assert result == {"providers": {"open_router": {"api_key": "key"}}}

    def test_list_of_dicts(self):
        data = {"allowFrom": [{"userId": "123"}]}
        result = convert_keys(data)
        assert result == {"allow_from": [{"user_id": "123"}]}

    def test_non_dict(self):
        assert convert_keys("hello") == "hello"
        assert convert_keys(42) == 42
        assert convert_keys(None) is None

    def test_list_of_primitives(self):
        data = {"items": [1, 2, 3]}
        result = convert_keys(data)
        assert result == {"items": [1, 2, 3]}


class TestConvertToCamel:
    def test_flat_dict(self):
        data = {"api_key": "sk-123", "max_tokens": 1024}
        result = convert_to_camel(data)
        assert result == {"apiKey": "sk-123", "maxTokens": 1024}

    def test_nested_dict(self):
        data = {"providers": {"open_router": {"api_key": "key"}}}
        result = convert_to_camel(data)
        assert result == {"providers": {"openRouter": {"apiKey": "key"}}}

    def test_roundtrip(self):
        """camelCase → snake_case → camelCase should preserve keys."""
        original = {"apiKey": "test", "webhookBaseUrl": "http://x", "maxTokens": 100}
        snake = convert_keys(original)
        camel = convert_to_camel(snake)
        assert camel == original


# ── Config load/save ────────────────────────────────────────────────


class TestLoadConfig:
    def test_default_when_no_file(self, tmp_path: Path):
        config = load_config(tmp_path / "nonexistent.json")
        assert isinstance(config, Config)
        assert config.gateway.port == 18790

    def test_load_camel_case_json(self, tmp_path: Path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "gateway": {"port": 9999},
            "providers": {"openrouter": {"apiKey": "sk-test"}},
            "agents": {"defaults": {"maxTokens": 4096}},
        }))
        config = load_config(config_file)
        assert config.gateway.port == 9999
        assert config.providers.openrouter.api_key == "sk-test"
        assert config.agents.defaults.max_tokens == 4096

    def test_invalid_json_returns_default(self, tmp_path: Path):
        config_file = tmp_path / "config.json"
        config_file.write_text("not json{{{")
        config = load_config(config_file)
        assert isinstance(config, Config)
        assert config.gateway.port == 18790

    def test_empty_file_returns_default(self, tmp_path: Path):
        config_file = tmp_path / "config.json"
        config_file.write_text("")
        config = load_config(config_file)
        assert isinstance(config, Config)


class TestSaveConfig:
    def test_save_creates_file(self, tmp_path: Path):
        config = Config()
        config_file = tmp_path / "subdir" / "config.json"
        save_config(config, config_file)
        assert config_file.exists()

    def test_save_uses_camel_case(self, tmp_path: Path):
        config = Config()
        config_file = tmp_path / "config.json"
        save_config(config, config_file)

        data = json.loads(config_file.read_text())
        # Top-level keys should be camelCase (though single-word keys are same)
        assert "gateway" in data
        # Nested keys should be camelCase
        assert "maxTokens" in data["agents"]["defaults"]
        assert "apiKey" in data["providers"]["openrouter"]

    def test_roundtrip(self, tmp_path: Path):
        """Save and reload should produce equivalent config."""
        original = Config()
        original.gateway.port = 12345
        original.providers.openrouter.api_key = "sk-roundtrip"

        config_file = tmp_path / "config.json"
        save_config(original, config_file)
        loaded = load_config(config_file)

        assert loaded.gateway.port == 12345
        assert loaded.providers.openrouter.api_key == "sk-roundtrip"
