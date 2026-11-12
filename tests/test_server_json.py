"""``server.json`` (MCP Registry listing) stays valid and in step with the project."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def server() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="module")
def project() -> dict[str, Any]:
    data: dict[str, Any] = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return data


def test_matches_the_registry_schema(server: dict[str, Any]) -> None:
    # The schema is vendored from the URL named in server.json's "$schema" so CI needs no network.
    schema = json.loads((ROOT / "tests" / "data" / "mcp-server.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(server, schema)


def test_package_matches_what_is_published_to_pypi(server: dict[str, Any], project: dict[str, Any]) -> None:
    (package,) = server["packages"]
    assert package["registryType"] == "pypi"
    assert package["identifier"] == project["name"]
    assert server["version"] == package["version"] == project["version"]
    assert server["repository"]["url"] == "https://github.com/omerozkilic/citewell"


def test_readme_carries_the_ownership_marker(server: dict[str, Any]) -> None:
    # The registry checks the PyPI description (the README) for "mcp-name: <server name>".
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert re.search(rf"mcp-name: {re.escape(server['name'])}(\s|-->|<)", readme)
    assert server["name"].startswith("io.github.omerozkilic/")  # GitHub-authenticated namespace


def test_stdio_command_exists_in_the_cli(server: dict[str, Any]) -> None:
    from citewell.cli import app

    args = [a["value"] for a in server["packages"][0]["packageArguments"]]
    commands = {c.name or (c.callback.__name__ if c.callback else "") for c in app.registered_commands}
    assert args == ["mcp"] and "mcp" in commands
    assert server["packages"][0]["transport"]["type"] == "stdio"


def test_environment_variables_are_real_settings(server: dict[str, Any]) -> None:
    from citewell.config import Settings

    fields = {f"CITEWELL_{name}".upper() for name in Settings.model_fields}
    for var in server["packages"][0]["environmentVariables"]:
        assert var["name"] in fields, f"{var['name']} is not a Citewell setting"


def test_release_please_keeps_the_versions_in_step() -> None:
    config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    extra = config["packages"]["."]["extra-files"]
    paths = {(e["path"], e["jsonpath"]) for e in extra}
    assert ("server.json", "$.version") in paths
    assert ("server.json", "$.packages[0].version") in paths
    assert any(e["path"] == "uv.lock" for e in extra)  # the existing entry must survive
