"""The /ui search page: served as static files, read-only, no external assets, no inline code."""

from __future__ import annotations

import re
from importlib import resources

from fastapi.testclient import TestClient

from citewell.api import UI_ASSETS, create_app
from citewell.app import Citewell

from .conftest import make_settings


def _client(**overrides: object) -> TestClient:
    # No `with`: the lifespan (database check) is not needed for static files.
    return TestClient(create_app(Citewell(make_settings(**overrides)), mount_mcp=False))


def _file(name: str) -> str:
    return resources.files("citewell").joinpath("ui", name).read_text(encoding="utf-8")


def test_ui_is_served_with_strict_headers() -> None:
    client = _client()
    pages = {path: client.get(path) for path in ("/ui", "/ui/", "/ui/app.js", "/ui/style.css")}
    assert {p: r.status_code for p, r in pages.items()} == dict.fromkeys(pages, 200)
    assert pages["/ui"].text == pages["/ui/"].text and "<title>Citewell</title>" in pages["/ui"].text
    assert pages["/ui/app.js"].headers["content-type"].startswith("text/javascript")
    assert pages["/ui/style.css"].headers["content-type"].startswith("text/css")
    for response in pages.values():
        csp = response.headers["content-security-policy"]
        assert "default-src 'none'" in csp and "script-src 'self'" in csp and "'unsafe-inline'" not in csp
        assert "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
    assert client.head("/ui/app.js").status_code == 200
    assert client.get("/ui/other.js").status_code == 404
    assert client.get("/ui/../config.py").status_code == 404


def test_ui_can_be_switched_off() -> None:
    client = _client(ui=False)
    assert [client.get(p).status_code for p in ("/ui", "/ui/app.js")] == [404, 404]


def test_ui_loads_without_a_token_but_the_api_still_needs_one() -> None:
    client = _client(api_token="s3cret")
    assert [client.get(p).status_code for p in ("/ui", "/ui/app.js", "/ui/style.css")] == [200, 200, 200]
    assert client.get("/v1/collections").status_code == 401
    assert client.post("/v1/search", json={"query": "x"}).status_code == 401


def test_ui_with_ui_off_keeps_every_path_behind_the_token() -> None:
    client = _client(ui=False, api_token="s3cret")
    assert client.get("/ui").status_code == 401  # not exempt: nothing is served there


def test_assets_exist_in_the_package() -> None:
    for name, _ in UI_ASSETS.values():
        assert _file(name).strip()


def test_no_external_assets_no_inline_code() -> None:
    for name in ("index.html", "app.js", "style.css"):
        text = _file(name)
        assert not re.search(r"https?://", text), f"{name} references an external URL"
        assert "@import" not in text
    html = _file("index.html")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html), "inline <script>"
    assert not re.search(r"<style|\sstyle=|\son[a-z]+=", html), "inline style or event handler"
    assert 'href="/ui/style.css"' in html and 'src="/ui/app.js"' in html


def test_document_text_is_never_inserted_as_markup() -> None:
    js = _file("app.js")
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert banned not in js, banned


def test_the_page_is_read_only() -> None:
    js = _file("app.js")
    assert set(re.findall(r'"(/v1/[a-z/]+)"', js)) == {"/v1/collections", "/v1/search"}
    assert not re.search(r'method:\s*"(PUT|PATCH|DELETE)"', js)
    assert js.count('method: "POST"') == 1  # the search itself


def test_form_controls_are_labelled_and_the_page_has_landmarks() -> None:
    html = _file("index.html")
    assert '<html lang="en">' in html and 'name="viewport"' in html
    for tag in ("<main>", "<header>", "<footer>", 'role="search"', 'aria-live="polite"', 'role="alert"'):
        assert tag in html
    ids = re.findall(r'<(?:input|select)\b[^>]*\bid="([^"]+)"', html)
    assert {"q", "collection", "mode", "k", "rerank", "token"} <= set(ids)
    for control in ids:
        assert f'for="{control}"' in html, f"{control} has no <label>"
    assert 'class="skip"' in html  # skip link for keyboard users
    assert ":focus-visible" in _file("style.css")


def test_both_languages_cover_every_string_the_page_uses() -> None:
    js, html = _file("app.js"), _file("index.html")
    blocks = {
        lang: set(re.findall(r"\b([a-zA-Z]+):", block))
        for lang, block in zip(
            ("en", "tr"), re.findall(r"\n  (?:en|tr): \{(.*?)\n  \},", js, re.S), strict=True
        )
    }
    used = set(re.findall(r'data-i18n="([^"]+)"', html)) | set(re.findall(r"\bS\.([a-zA-Z]+)", js))
    assert used, "no strings found"
    for lang, keys in blocks.items():
        assert used <= keys, f"{lang} lacks {sorted(used - keys)}"


def test_wheel_includes_the_ui_files() -> None:
    pyproject = (resources.files("citewell").parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert 'packages = ["src/citewell"]' in pyproject  # hatch ships every file inside the package


def _luminance(hex_colour: str) -> float:
    channels = [int(hex_colour.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_colours_meet_wcag_aa_in_light_and_dark() -> None:
    css = _file("style.css")
    light_block, dark_block = re.findall(r":root \{(.*?)\n\s*\}", css, re.S)[:2]

    def palette(block: str) -> dict[str, str]:
        return dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6});", block))

    light = palette(light_block)
    dark = {**light, **palette(dark_block)}
    for name, p in (("light", light), ("dark", dark)):
        for fg, bg in (
            ("fg", "bg"),
            ("fg", "card"),
            ("muted", "bg"),
            ("muted", "card"),
            ("accent-fg", "accent"),
            ("accent", "bg"),
            ("fg", "mark"),
            ("warn-fg", "warn-bg"),
            ("err", "bg"),
        ):
            assert _contrast(p[fg], p[bg]) >= 4.5, f"{name}: {fg} on {bg}"
        assert _contrast(p["border"], p["bg"]) >= 3.0, f"{name}: control borders"
