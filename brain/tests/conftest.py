"""Pytest-only convenience: keep report tests off the network.

CI runs `python -m unittest discover`, which never loads this file, so nothing may
depend on it. The hermetic guarantee lives in the tests themselves — this only spares
a pytest user from a stray Foundry call when their environment has one configured.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_model_environment(monkeypatch):
    monkeypatch.setenv("WAGGLE_LLM_NARRATIVE", "0")
    monkeypatch.delenv("WAGGLE_FOUNDRY_BASE_URL", raising=False)
    monkeypatch.delenv("WAGGLE_LLM_MODEL", raising=False)
    monkeypatch.delenv("WAGGLE_LLM_TIMEOUT", raising=False)
