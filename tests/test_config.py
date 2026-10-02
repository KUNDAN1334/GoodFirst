"""Tests for the config module and the pure helpers in the Ollama check script."""

import sys
from pathlib import Path

import pytest

from goodfirst.config import ConfigError, load_settings

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from check_ollama import model_is_available, normalize_model_name  # noqa: E402


def test_defaults_when_env_is_empty():
    s = load_settings({})
    assert s.ollama_model == "gemma3:4b"
    assert s.num_ctx == 8192
    assert s.confidence_floor == 0.6
    assert s.no_docs_confidence_cap == 0.3
    assert s.github_token is None
    assert s.ollama_base_url == "http://localhost:11434"


def test_overrides_are_read():
    s = load_settings(
        {
            "OLLAMA_MODEL": "gemma3:1b",
            "OLLAMA_NUM_CTX": "4096",
            "CONFIDENCE_FLOOR": "0.7",
            "GITHUB_TOKEN": "  abc  ",
            "OLLAMA_BASE_URL": "http://127.0.0.1:11434/",
        }
    )
    assert s.ollama_model == "gemma3:1b"
    assert s.num_ctx == 4096
    assert s.confidence_floor == 0.7
    assert s.github_token == "abc"
    assert s.ollama_base_url == "http://127.0.0.1:11434"  # trailing slash removed


def test_blank_token_means_no_token():
    assert load_settings({"GITHUB_TOKEN": "   "}).github_token is None


@pytest.mark.parametrize(
    "env",
    [
        {"OLLAMA_NUM_CTX": "lots"},
        {"OLLAMA_NUM_CTX": "100"},       # below minimum
        {"CONFIDENCE_FLOOR": "1.5"},     # out of range
        {"CONFIDENCE_FLOOR": "high"},
    ],
)
def test_bad_values_raise_friendly_error(env):
    with pytest.raises(ConfigError):
        load_settings(env)


def test_model_name_matching():
    tags = {"models": [{"name": "gemma3:4b"}, {"name": "llama3:latest"}]}
    assert model_is_available(tags, "gemma3:4b")
    assert model_is_available(tags, "llama3")          # implicit :latest
    assert not model_is_available(tags, "gemma3:1b")
    assert normalize_model_name("gemma3") == "gemma3:latest"
