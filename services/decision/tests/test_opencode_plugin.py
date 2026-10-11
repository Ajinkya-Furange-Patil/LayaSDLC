"""OpenCode plugin contract tests (Stage 5).

These tests verify the plugin files have the correct export shape for the
OpenCode V2 plugin API without requiring a running OpenCode instance.

The plugin API requires:
  export default Plugin.define({ id: string, setup(ctx) { ... } })

A bare function export or a missing id will cause OpenCode to reject the
plugin at load time with:
  "Plugin must export a default definition with an id and an effect or setup function."
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_FILE = REPO_ROOT / ".opencode" / "plugins" / "layasdlc.ts"
TOOLS_FILE = REPO_ROOT / ".opencode" / "tools" / "layasdlc.ts"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_plugin_file_exists():
    assert PLUGIN_FILE.is_file(), f"plugin file missing: {PLUGIN_FILE}"


def test_plugin_uses_plugin_define():
    """The default export must be Plugin.define({...}), not a bare function."""
    source = _read(PLUGIN_FILE)
    assert "Plugin.define" in source, (
        "plugin must use Plugin.define({ id, setup }) — "
        "a bare function export is rejected by OpenCode V2"
    )


def test_plugin_has_id():
    source = _read(PLUGIN_FILE)
    # Plugin.define({ id: "layasdlc", ... })
    assert re.search(r'id:\s*"layasdlc"', source), (
        'plugin must define id: "layasdlc"'
    )


def test_plugin_has_setup():
    source = _read(PLUGIN_FILE)
    assert re.search(r"setup\s*\(", source), (
        "plugin must define a setup(ctx) function"
    )


def test_plugin_subscribes_to_events():
    source = _read(PLUGIN_FILE)
    assert "ctx.event.subscribe" in source, (
        "plugin must subscribe to events via ctx.event.subscribe"
    )


def test_plugin_returns_cleanup():
    source = _read(PLUGIN_FILE)
    # The setup function should return a cleanup function that aborts the subscription
    assert "return" in source and "abort" in source, (
        "plugin setup should return a cleanup function that aborts the event subscription"
    )


def test_tools_file_exists():
    assert TOOLS_FILE.is_file(), f"tools file missing: {TOOLS_FILE}"


def test_tools_export_route():
    source = _read(TOOLS_FILE)
    assert "export const route" in source or "export default" in source


def test_tools_export_inspect():
    source = _read(TOOLS_FILE)
    assert "export const inspect" in source


def test_tools_export_approve():
    source = _read(TOOLS_FILE)
    assert "export const approve" in source


def test_tools_use_tool_helper():
    """Tools must use the tool() helper from @opencode-ai/plugin."""
    source = _read(TOOLS_FILE)
    assert "tool(" in source or "tool.schema" in source


def test_tools_use_zod_schema():
    source = _read(TOOLS_FILE)
    assert "z." in source or "zod" in source


def test_opencode_json_permissions():
    """opencode.json must set least-privilege permissions for layasdlc tools."""
    config_path = REPO_ROOT / "opencode.json"
    if not config_path.is_file():
        pytest.skip("opencode.json not found")
    import json
    config = json.loads(config_path.read_text())
    permissions = config.get("permission", {})
    assert "layasdlc_route" in permissions
    assert "layasdlc_inspect" in permissions
    assert "layasdlc_approve" in permissions
