from __future__ import annotations

from pathlib import Path

import pytest
from arclet.entari import Entari
from arclet.entari.config import EntariConfig
from arclet.entari.plugin import load_plugin, unload_plugin


@pytest.fixture(scope="session")
def entari_plugin_host():
    if not EntariConfig._inited:
        EntariConfig(Path("/tmp/tenko-entari-test.yml"))
    return Entari(ignore_self_message=True)


@pytest.fixture
def loaded_plugin(entari_plugin_host, request):
    plugin_id = f"tenko.plugins.{request.param}"
    loaded = load_plugin(plugin_id)
    assert loaded is not None
    yield loaded.module
    unload_plugin(plugin_id)
