"""Offline unit tests for the 4 Pinterest extraction tiers (httpx.MockTransport, zero network)."""

from __future__ import annotations

import asyncio
import json

import httpx
import numpy as np
from PIL import Image, ImageDraw

from pin2brand.scraper import (
    _scrape_via_html_hydration,
    _scrape_via_pidgets_api,
    _scrape_via_resource_api,
    _scrape_via_rss,
)
from pin2brand.vision_math import _sample_image_pixels_and_texture

JPEG_HEADERS = {"content-type": "image/jpeg"}
IMG = "https://i.pinimg.com"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


def _run(coro):
    return asyncio.run(coro)


# ---------- Tier 1: internal Resource API ----------


def test_resource_api_paginates_and_reads_handler(tmp_path) -> None:
    seen_handlers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/user/board/":
            return httpx.Response(200, text='<html>..."initialHandlerId":"www/[user]/[slug].js"...</html>')
        if path.endswith("/BoardResource/get/"):
            seen_handlers.append(request.headers.get("X-Pinterest-PWS-Handler", ""))
            return httpx.Response(
                200, json={"resource_response": {"data": {"id": "999", "name": "My Board"}}}
            )
        if path.endswith("/BoardFeedResource/get/"):
            data = json.loads(request.url.params["data"])
            if "bookmarks" in data["options"]:
                items = [{"id": "p3", "images": {"orig": {"url": f"{IMG}/originals/cc/3.jpg"}}}]
                bookmark = "-end-"
            else:
                items = [
                    {"id": "p1", "grid_title": "One", "images": {"orig": {"url": f"{IMG}/originals/aa/1.jpg", "width": 10, "height": 20}}},
                    {"id": "p1", "images": {"orig": {"url": f"{IMG}/originals/aa/1.jpg"}}},  # duplicate id
                    {"type": "module", "id": "ad"},
                    {"id": "p2", "images": {"736x": {"url": f"{IMG}/736x/bb/2.jpg"}}},
                ]
                bookmark = "page2"
            return httpx.Response(
                200, json={"resource_response": {"data": items, "bookmark": bookmark}}
            )
        return httpx.Response(404)

    async def go():
        async with _client(handler) as c:
            return await _scrape_via_resource_api(
                c, "www.pinterest.com", "user", "board", "https://www.pinterest.com/user/board/", 10
            )

    title, pins, private = _run(go())
    assert title == "My Board" and private is False
    assert [p.pin_id for p in pins] == ["p1", "p2", "p3"]
    assert pins[0].title == "One" and pins[0].width == 10
    assert seen_handlers == ["www/[user]/[slug].js"]  # handler read dynamically, not hardcoded


def test_resource_api_detects_private_profile() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/BoardResource/get/"):
            return httpx.Response(404, json={"resource_response": {"error": "not found"}})
        if path.endswith("/UserResource/get/"):
            return httpx.Response(
                200, json={"resource_response": {"data": {"is_private_profile": True}}}
            )
        return httpx.Response(200, text="<html></html>")

    async def go():
        async with _client(handler) as c:
            return await _scrape_via_resource_api(
                c, "www.pinterest.com", "u", "b", "https://www.pinterest.com/u/b/", 5
            )

    _title, pins, private = _run(go())
    assert pins == [] and private is True


# ---------- Tier 2: public Pidgets widget API ----------


def test_pidgets_upgrades_to_originals_and_falls_back_when_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/v3/pidgets/boards/u/b/pins/" in url:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "board": {"name": "Widget Board"},
                        "pins": [
                            {"id": "1", "description": "has original", "images": {"237x": {"url": f"{IMG}/237x/aa/one.jpg"}}},
                            {"id": "2", "description": "png only", "images": {"237x": {"url": f"{IMG}/237x/bb/two.jpg"}}},
                        ],
                    }
                },
            )
        if request.method == "HEAD":
            if "/originals/aa/one.jpg" in url or "/736x/bb/two.jpg" in url:
                return httpx.Response(200, headers=JPEG_HEADERS)
            return httpx.Response(404)  # originals/bb/two.jpg is really a .png upstream
        return httpx.Response(404)

    async def go():
        async with _client(handler) as c:
            return await _scrape_via_pidgets_api(c, "u", "b", 10)

    title, pins = _run(go())
    assert title == "Widget Board"
    assert pins[0].image_url == f"{IMG}/originals/aa/one.jpg"
    assert pins[1].image_url == f"{IMG}/736x/bb/two.jpg"  # probed, not blindly rewritten


def test_pidgets_non_200_returns_empty() -> None:
    async def go():
        async with _client(lambda r: httpx.Response(403)) as c:
            return await _scrape_via_pidgets_api(c, "u", "b", 5)

    _title, pins = _run(go())
    assert pins == []


# ---------- Tier 3: RSS ----------


def test_rss_parses_items_and_dedupes_images() -> None:
    rss = f"""<?xml version="1.0"?><rss><channel><title>RSS Board</title>
    <item><title>A</title><link>https://www.pinterest.com/pin/111/</link><guid>111</guid>
      <description>&lt;img src="{IMG}/236x/aa/a.jpg"&gt; first</description></item>
    <item><title>B</title><link>https://www.pinterest.com/pin/222/</link><guid>222</guid>
      <description>&lt;img src="{IMG}/236x/bb/b.jpg"&gt; second</description></item>
    <item><title>Dup</title><link>https://www.pinterest.com/pin/333/</link><guid>333</guid>
      <description>&lt;img src="{IMG}/236x/aa/a.jpg"&gt; same image</description></item>
    </channel></rss>"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200, headers=JPEG_HEADERS)
        if request.url.path.endswith(".rss"):
            return httpx.Response(200, text=rss)
        return httpx.Response(404)

    async def go():
        async with _client(handler) as c:
            return await _scrape_via_rss(c, "www.pinterest.com", "u", "b", 10)

    title, pins = _run(go())
    assert title == "RSS Board"
    assert [p.pin_id for p in pins] == ["111", "222"]
    assert all("/originals/" in p.image_url for p in pins)


def test_rss_404_returns_empty() -> None:
    async def go():
        async with _client(lambda r: httpx.Response(404, text="Board not found")) as c:
            return await _scrape_via_rss(c, "www.pinterest.com", "u", "b", 5)

    _title, pins = _run(go())
    assert pins == []


# ---------- Tier 4: HTML hydration ----------


def test_html_hydration_extracts_pins_from_pws_data() -> None:
    state = {
        "props": {
            "pins": [
                {"id": "10", "grid_title": "Hydrated", "images": {"orig": {"url": f"{IMG}/originals/aa/h.jpg"}}},
                {"id": "10", "images": {"orig": {"url": f"{IMG}/originals/aa/h.jpg"}}},
                {"id": "11", "images": {"736x": {"url": f"{IMG}/736x/bb/i.jpg"}}},
            ]
        }
    }
    html = (
        '<html><head><meta property="og:title" content="Hydrated Board"/></head><body>'
        f'<script id="__PWS_DATA__" type="application/json">{json.dumps(state)}</script></body></html>'
    )

    async def go():
        async with _client(lambda r: httpx.Response(200, text=html)) as c:
            return await _scrape_via_html_hydration(c, "https://www.pinterest.com/u/b/", "b", 10)

    title, pins = _run(go())
    assert title == "Hydrated Board"
    assert [p.pin_id for p in pins] == ["10", "11"]


def test_html_hydration_ignores_scripts_without_pins() -> None:
    html = '<html><script id="__PWS_DATA__" type="application/json">{"routeTree": {}}</script></html>'

    async def go():
        async with _client(lambda r: httpx.Response(200, text=html)) as c:
            return await _scrape_via_html_hydration(c, "https://www.pinterest.com/u/b/", "b", 10)

    _title, pins = _run(go())
    assert pins == []


# ---------- Vision: backdrop suppression & full-bleed textures ----------


def test_uniform_studio_backdrop_is_downweighted(tmp_path) -> None:
    img = Image.new("RGB", (300, 300), (250, 250, 250))
    ImageDraw.Draw(img).rectangle([60, 60, 240, 240], fill=(160, 50, 35))
    path = tmp_path / "product.jpg"
    img.save(path, quality=95)

    pixels, _tex, probs = _sample_image_pixels_and_texture(path, size=150)
    is_backdrop = np.linalg.norm(pixels.astype(float) - np.array([250, 250, 250.0]), axis=1) < 12
    uniform_share = float(is_backdrop.mean())
    weighted_share = float(probs[is_backdrop].sum())
    assert uniform_share > 0.3
    assert weighted_share < uniform_share * 0.6  # backdrop no longer dominates the palette


def test_full_bleed_texture_sampled_evenly(tmp_path) -> None:
    rng = np.random.default_rng(7)
    noise = rng.integers(60, 200, size=(300, 300, 3), dtype=np.uint8)  # edge-to-edge grain
    path = tmp_path / "stone.png"
    Image.fromarray(noise).save(path)

    _pixels, tex, probs = _sample_image_pixels_and_texture(path, size=150)
    assert tex >= 30.0
    assert probs.max() / probs.min() < 1.5  # near-uniform, borders not punished
