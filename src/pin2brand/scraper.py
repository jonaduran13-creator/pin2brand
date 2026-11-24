"""Hybrid Pinterest board scraper (Resource API + RSS + HTML hydration + optional cookies)."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from bs4 import BeautifulSoup
from PIL import Image

from .models import ScrapedBoard, ScrapedPin

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
}

PINIMG_SIZE_RE = re.compile(r"https?://i\.pinimg\.com/(?:\d+x\d*|\d+x)/(.+)")
PIN_ID_RE = re.compile(r"/pin/(\d+)")


class BoardAccessError(RuntimeError):
    """Raised when a Pinterest board is private, secret, or unreachable."""


def parse_pinterest_board_url(board_url: str) -> tuple[str, str, str, str]:
    """Normalize any regional Pinterest board URL.

    Returns (canonical_url, host, username, board_slug).
    """
    raw = board_url.strip()
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw

    parsed = urlparse(raw)
    if "pinterest" not in parsed.netloc.lower():
        raise ValueError(f"URL does not appear to be a Pinterest URL: {board_url}")

    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) >= 2 and parts[1].endswith(".rss"):
        parts[1] = parts[1][:-4]

    if len(parts) < 2:
        raise ValueError(
            f"Expected a board URL like https://www.pinterest.com/<user>/<board>/, got: {board_url}"
        )

    username, board_slug = parts[0], parts[1]
    host = parsed.netloc or "www.pinterest.com"
    canonical_url = f"https://{host}/{username}/{board_slug}/"
    return canonical_url, host, username, board_slug


def _extract_pin_id(link: str, fallback_seed: str) -> str:
    match = PIN_ID_RE.search(link)
    if match:
        return match.group(1)
    return hashlib.sha1(fallback_seed.encode("utf-8")).hexdigest()[:12]


def _upgrade_candidates(image_url: str) -> list[str]:
    """Generate high-resolution candidate URLs from a pinimg thumbnail URL."""
    match = PINIMG_SIZE_RE.match(image_url.strip())
    if not match:
        return [image_url]
    tail = match.group(1)
    candidates = [
        f"https://i.pinimg.com/originals/{tail}",
        f"https://i.pinimg.com/736x/{tail}",
        image_url,
    ]
    seen: set[str] = set()
    return [c for c in candidates if not (c in seen or seen.add(c))]


def _load_optional_cookies(cookies_path: Path | None) -> dict[str, str]:
    """Load optional Pinterest cookies from JSON file or environment."""
    cookies: dict[str, str] = {}
    env_sess = os.getenv("PINTEREST_SESSION_COOKIE", "").strip()
    if env_sess:
        cookies["_pinterest_sess"] = env_sess

    target = cookies_path
    if target is None:
        env_file = os.getenv("PINTEREST_COOKIES_FILE", "").strip()
        if env_file:
            target = Path(env_file)

    if target and target.exists():
        raw_text = target.read_text(encoding="utf-8", errors="ignore").strip()
        if raw_text.startswith("[") or raw_text.startswith("{"):
            data = json.loads(raw_text)
            if isinstance(data, dict):
                for k, v in data.items():
                    cookies[str(k)] = str(v)
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "name" in item and "value" in item:
                        cookies[str(item["name"])] = str(item["value"])
        else:
            # Netscape cookies.txt format
            for line in raw_text.splitlines():
                if not line or line.startswith("#"):
                    continue
                cols = line.split("\t")
                if len(cols) >= 7:
                    cookies[cols[5]] = cols[6]
    return cookies


async def _resolve_best_image_url(client: httpx.AsyncClient, image_url: str) -> str:
    """Probe /originals/ via fast HEAD request, falling back to /736x/ or original."""
    candidates = _upgrade_candidates(image_url)
    for candidate in candidates[:-1]:
        try:
            resp = await client.head(candidate, timeout=5.0, follow_redirects=True)
            if resp.status_code == 200:
                ctype = resp.headers.get("content-type", "").lower()
                if not ctype or "image" in ctype:
                    return candidate
        except httpx.HTTPError:
            continue
    return candidates[-1]


async def _scrape_via_resource_api(
    client: httpx.AsyncClient,
    host: str,
    username: str,
    board_slug: str,
    canonical_url: str,
    max_pins: int,
) -> tuple[str, list[ScrapedPin], bool]:
    """Primary extractor using Pinterest's internal BoardResource + BoardFeedResource JSON API.

    Returns (board_title, pins, is_private_detected).
    """
    pws_handler = "www/[username]/[slug].js"
    try:
        r_page = await client.get(canonical_url, timeout=15.0)
        match_handler = re.search(r'"initialHandlerId"\s*:\s*"([^"]+)"', r_page.text)
        if match_handler:
            pws_handler = match_handler.group(1)
    except httpx.HTTPError:
        return board_slug.replace("-", " ").title(), [], False

    csrf = client.cookies.get("csrftoken", "")
    api_headers = {
        "Accept": "application/json, text/javascript, */*, q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": csrf,
        "X-Pinterest-AppState": "active",
        "X-Pinterest-PWS-Handler": pws_handler,
        "Referer": canonical_url,
    }

    board_opts = json.dumps(
        {
            "options": {
                "username": username,
                "slug": board_slug,
                "field_set_key": "detailed",
            }
        }
    )
    board_endpoint = (
        f"https://{host}/resource/BoardResource/get/"
        f"?source_url=/{username}/{board_slug}/&data={quote(board_opts)}"
    )
    try:
        r_board = await client.get(board_endpoint, headers=api_headers, timeout=15.0)
    except httpx.HTTPError:
        return board_slug.replace("-", " ").title(), [], False

    if r_board.status_code == 404:
        # Check whether the user profile is private
        is_private = False
        try:
            user_opts = json.dumps(
                {"options": {"username": username, "field_set_key": "profile"}}
            )
            r_user = await client.get(
                f"https://{host}/resource/UserResource/get/?source_url=/{username}/&data={quote(user_opts)}",
                headers={**api_headers, "X-Pinterest-PWS-Handler": "www/[username].js"},
                timeout=10.0,
            )
            if r_user.status_code == 200:
                u_data = r_user.json().get("resource_response", {}).get("data") or {}
                is_private = bool(u_data.get("is_private_profile"))
        except Exception:
            pass
        return board_slug.replace("-", " ").title(), [], is_private

    if r_board.status_code != 200:
        return board_slug.replace("-", " ").title(), [], False

    board_data = r_board.json().get("resource_response", {}).get("data") or {}
    board_id = board_data.get("id")
    board_title = str(board_data.get("name") or board_slug.replace("-", " ").title()).strip()
    if not board_id:
        return board_title, [], False

    pins: list[ScrapedPin] = []
    seen_ids: set[str] = set()
    bookmark: str | None = None

    while len(pins) < max_pins:
        feed_options: dict[str, Any] = {
            "board_id": str(board_id),
            "page_size": min(50, max_pins - len(pins) + 5),
            "field_set_key": "react_grid_pin",
        }
        if bookmark:
            feed_options["bookmarks"] = [bookmark]

        feed_opts_str = json.dumps({"options": feed_options})
        feed_url = (
            f"https://{host}/resource/BoardFeedResource/get/"
            f"?source_url=/{username}/{board_slug}/&data={quote(feed_opts_str)}"
        )
        try:
            r_feed = await client.get(feed_url, headers=api_headers, timeout=15.0)
            if r_feed.status_code != 200:
                break
            payload = r_feed.json().get("resource_response", {})
        except Exception:
            break

        items = payload.get("data") or []
        if not items:
            break

        for item in items:
            if not isinstance(item, dict) or item.get("type") == "module":
                continue
            images = item.get("images") or {}
            best_img = (
                images.get("orig")
                or images.get("736x")
                or images.get("564x")
                or images.get("474x")
                or images.get("236x")
            )
            if not isinstance(best_img, dict) or not best_img.get("url"):
                continue

            pin_id = str(item.get("id") or _extract_pin_id("", best_img["url"]))
            if pin_id in seen_ids:
                continue
            seen_ids.add(pin_id)

            raw_title = (
                item.get("grid_title")
                or item.get("title")
                or item.get("seo_alt_text")
                or item.get("description")
                or ""
            )
            clean_title = str(raw_title).strip() or f"Reference Pin {len(pins) + 1}"
            clean_desc = str(item.get("description") or item.get("seo_alt_text") or "").strip()

            pins.append(
                ScrapedPin(
                    pin_id=pin_id,
                    index=len(pins) + 1,
                    title=clean_title[:120],
                    description=clean_desc[:300],
                    pin_url=f"https://www.pinterest.com/pin/{pin_id}/",
                    image_url=str(best_img["url"]),
                    width=int(best_img.get("width") or 0),
                    height=int(best_img.get("height") or 0),
                )
            )
            if len(pins) >= max_pins:
                break

        next_bookmark = payload.get("bookmark")
        if not next_bookmark or next_bookmark == "-end-" or next_bookmark == bookmark:
            break
        bookmark = next_bookmark

    return board_title, pins, False


async def _scrape_via_pidgets_api(
    client: httpx.AsyncClient,
    username: str,
    board_slug: str,
    max_pins: int,
) -> tuple[str, list[ScrapedPin]]:
    """Fallback 1: Official public Pinterest Widgets API (zero CSRF or PWS handler required)."""
    pidget_url = f"https://widgets.pinterest.com/v3/pidgets/boards/{username}/{board_slug}/pins/"
    try:
        resp = await client.get(pidget_url, timeout=10.0)
        if resp.status_code != 200:
            return board_slug.replace("-", " ").title(), []
        payload = resp.json().get("data") or {}
    except Exception:
        return board_slug.replace("-", " ").title(), []

    board_info = payload.get("board") or {}
    board_title = str(board_info.get("name") or board_slug.replace("-", " ").title()).strip()
    raw_pins = payload.get("pins") or []
    if not raw_pins:
        return board_title, []

    raw_entries: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for item in raw_pins:
        if not isinstance(item, dict):
            continue
        images = item.get("images") or {}
        img_obj = images.get("237x") or images.get("236x") or next(iter(images.values()), None)
        if not isinstance(img_obj, dict) or not img_obj.get("url"):
            continue
        pin_id = str(item.get("id") or _extract_pin_id("", img_obj["url"]))
        if pin_id in seen_ids:
            continue
        seen_ids.add(pin_id)
        desc = str(item.get("description") or "").strip()
        raw_entries.append(
            {
                "pin_id": pin_id,
                "desc": desc,
                "raw_url": str(img_obj["url"]),
            }
        )
        if len(raw_entries) >= max_pins:
            break

    sem = asyncio.Semaphore(8)

    async def build_pidget_pin(idx: int, entry: dict[str, str]) -> ScrapedPin:
        async with sem:
            best_url = await _resolve_best_image_url(client, entry["raw_url"])
        return ScrapedPin(
            pin_id=entry["pin_id"],
            index=idx,
            title=entry["desc"][:80] or f"Reference Pin {idx}",
            description=entry["desc"][:300],
            pin_url=f"https://www.pinterest.com/pin/{entry['pin_id']}/",
            image_url=best_url,
        )

    pins = await asyncio.gather(
        *(build_pidget_pin(i + 1, item) for i, item in enumerate(raw_entries))
    )
    return board_title, list(pins)


async def _scrape_via_rss(
    client: httpx.AsyncClient,
    host: str,
    username: str,
    board_slug: str,
    max_pins: int,
) -> tuple[str, list[ScrapedPin]]:
    """Fallback 1: Fetch board pins via Pinterest's RSS feed."""
    rss_urls = [
        f"https://{host}/{username}/{board_slug}.rss",
        f"https://www.pinterest.com/{username}/{board_slug}.rss",
    ]
    xml_text = ""
    for rss_url in dict.fromkeys(rss_urls):
        try:
            resp = await client.get(rss_url, timeout=6.0)
            if resp.status_code == 200 and "<item" in resp.text:
                xml_text = resp.text
                break
        except httpx.HTTPError:
            continue

    if not xml_text:
        return board_slug.replace("-", " ").title(), []

    soup = BeautifulSoup(xml_text, "xml")
    channel_title_tag = soup.find("channel")
    board_title = board_slug.replace("-", " ").title()
    if channel_title_tag and channel_title_tag.find("title"):
        raw_title = channel_title_tag.find("title").get_text(strip=True)
        if raw_title:
            board_title = raw_title

    raw_items: list[dict[str, str]] = []
    seen_imgs: set[str] = set()

    for item in soup.find_all("item"):
        title = item.find("title").get_text(strip=True) if item.find("title") else ""
        link = item.find("link").get_text(strip=True) if item.find("link") else ""
        guid = item.find("guid").get_text(strip=True) if item.find("guid") else link
        desc_html = (
            item.find("description").get_text() if item.find("description") else ""
        )
        desc_soup = BeautifulSoup(desc_html, "html.parser")
        img_tag = desc_soup.find("img")
        if not img_tag or not img_tag.get("src"):
            continue

        img_src = img_tag["src"].strip()
        if img_src in seen_imgs:
            continue
        seen_imgs.add(img_src)

        clean_desc = desc_soup.get_text(" ", strip=True)
        raw_items.append(
            {
                "title": title or clean_desc[:80] or f"Pin {len(raw_items) + 1}",
                "description": clean_desc,
                "link": link or guid,
                "img_src": img_src,
            }
        )
        if len(raw_items) >= max_pins:
            break

    if not raw_items:
        return board_title, []

    sem = asyncio.Semaphore(8)

    async def build_pin(idx: int, entry: dict[str, str]) -> ScrapedPin:
        async with sem:
            best_url = await _resolve_best_image_url(client, entry["img_src"])
        pin_id = _extract_pin_id(entry["link"], entry["img_src"])
        return ScrapedPin(
            pin_id=pin_id,
            index=idx,
            title=entry["title"],
            description=entry["description"],
            pin_url=entry["link"],
            image_url=best_url,
        )

    pins = await asyncio.gather(
        *(build_pin(i + 1, item) for i, item in enumerate(raw_items))
    )
    return board_title, list(pins)


def _walk_json_for_pins(node: Any, collected: list[dict[str, Any]]) -> None:
    """Recursively scan hydrated Pinterest JSON for pin objects with image URLs."""
    if isinstance(node, dict):
        images = node.get("images")
        if isinstance(images, dict):
            orig = images.get("orig") or images.get("736x") or images.get("564x")
            if isinstance(orig, dict) and isinstance(orig.get("url"), str):
                url = orig["url"]
                if "i.pinimg.com" in url:
                    pin_id = str(node.get("id") or _extract_pin_id("", url))
                    title = (
                        node.get("grid_title")
                        or node.get("title")
                        or node.get("seo_alt_text")
                        or ""
                    )
                    desc = node.get("description") or node.get("seo_alt_text") or ""
                    collected.append(
                        {
                            "pin_id": pin_id,
                            "title": str(title).strip(),
                            "description": str(desc).strip(),
                            "image_url": url,
                            "pin_url": f"https://www.pinterest.com/pin/{pin_id}/",
                        }
                    )
        for val in node.values():
            _walk_json_for_pins(val, collected)
    elif isinstance(node, list):
        for item in node:
            _walk_json_for_pins(item, collected)


async def _scrape_via_html_hydration(
    client: httpx.AsyncClient,
    canonical_url: str,
    board_slug: str,
    max_pins: int,
) -> tuple[str, list[ScrapedPin]]:
    """Fallback 2: extract hydrated pin JSON embedded in the Pinterest board HTML."""
    try:
        resp = await client.get(canonical_url, timeout=15.0)
        if resp.status_code != 200:
            return board_slug.replace("-", " ").title(), []
    except httpx.HTTPError:
        return board_slug.replace("-", " ").title(), []

    soup = BeautifulSoup(resp.text, "html.parser")
    board_title = board_slug.replace("-", " ").title()
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        board_title = og_title["content"].strip()

    discovered: list[dict[str, Any]] = []
    for script in soup.find_all("script"):
        sid = script.get("id", "")
        stype = script.get("type", "")
        has_relay = script.has_attr("data-relay-response")
        if sid == "__PWS_DATA__" or has_relay or stype == "application/json":
            raw_json = script.string or script.get_text()
            if not raw_json or "pinimg.com" not in raw_json:
                continue
            try:
                data = json.loads(raw_json)
                _walk_json_for_pins(data, discovered)
            except json.JSONDecodeError:
                continue

    pins: list[ScrapedPin] = []
    seen_urls: set[str] = set()
    for entry in discovered:
        img_url = entry["image_url"]
        if img_url in seen_urls:
            continue
        seen_urls.add(img_url)
        pins.append(
            ScrapedPin(
                pin_id=entry["pin_id"],
                index=len(pins) + 1,
                title=entry["title"] or f"Reference Pin {len(pins) + 1}",
                description=entry["description"],
                pin_url=entry["pin_url"],
                image_url=img_url,
            )
        )
        if len(pins) >= max_pins:
            break

    return board_title, pins


async def _scrape_via_playwright_optional(
    canonical_url: str,
    board_slug: str,
    max_pins: int,
) -> tuple[str, list[ScrapedPin]]:
    """Optional deep fallback using Playwright headless browser if installed."""
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except ImportError:
        return board_slug.replace("-", " ").title(), []

    collected_urls: list[str] = []
    board_title = board_slug.replace("-", " ").title()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent=DEFAULT_HEADERS["User-Agent"])
        await page.goto(canonical_url, wait_until="networkidle", timeout=30000)
        board_title = await page.title() or board_title
        for _ in range(4):
            imgs = await page.eval_on_selector_all(
                "img[src*='i.pinimg.com']",
                "els => els.map(e => ({src: e.src, alt: e.alt || ''}))",
            )
            for item in imgs:
                src = item.get("src", "")
                if src and src not in collected_urls and "75x75" not in src:
                    collected_urls.append(src)
            if len(collected_urls) >= max_pins:
                break
            await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1200)
        await browser.close()

    pins = [
        ScrapedPin(
            pin_id=_extract_pin_id("", url),
            index=i + 1,
            title=f"Reference Pin {i + 1}",
            pin_url=canonical_url,
            image_url=_upgrade_candidates(url)[0],
        )
        for i, url in enumerate(collected_urls[:max_pins])
    ]
    return board_title, pins


def _scrape_local_folder(folder_path: Path, max_pins: int) -> ScrapedBoard:
    """Ingest local images (.jpg, .jpeg, .png, .webp) from a directory as a ScrapedBoard."""
    allowed_exts = {".jpg", ".jpeg", ".png", ".webp"}
    files = sorted(
        [
            f
            for f in folder_path.iterdir()
            if f.is_file() and f.suffix.lower() in allowed_exts and f.name != "contact_sheet.jpg"
        ],
        key=lambda p: p.name.lower(),
    )[:max_pins]

    if not files:
        raise BoardAccessError(
            f"No valid images (.jpg, .png, .webp) found in local directory: {folder_path}"
        )

    slug = re.sub(r"[^a-z0-9-_]+", "-", folder_path.resolve().name.lower()).strip("-") or "local-board"
    title = folder_path.resolve().name.replace("-", " ").replace("_", " ").title()
    pins = [
        ScrapedPin(
            pin_id=hashlib.sha1(str(f.resolve()).encode("utf-8")).hexdigest()[:12],
            index=idx,
            title=f.stem.replace("-", " ").replace("_", " ").title(),
            description=f"Local reference image {f.name}",
            pin_url=f"local://{slug}/{f.name}",
            image_url=f.resolve().as_uri(),
            local_path=str(f.resolve()),
        )
        for idx, f in enumerate(files, start=1)
    ]
    return ScrapedBoard(
        board_url=f"local://{slug}/",
        canonical_url=f"local://{slug}/",
        username="local",
        board_slug=slug,
        board_title=title,
        source_method="local_folder",
        pins=pins,
    )


async def scrape_board(
    board_url: str,
    max_pins: int = 24,
    cookies_path: Path | None = None,
) -> ScrapedBoard:
    """Scrape pins from a Pinterest board URL or ingest from a local image directory."""
    candidate_path = Path(board_url.strip())
    if not board_url.strip().startswith(("http://", "https://")) and candidate_path.is_dir():
        return _scrape_local_folder(candidate_path, max_pins=max_pins)

    canonical_url, host, username, board_slug = parse_pinterest_board_url(board_url)
    cookies = _load_optional_cookies(cookies_path)

    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS,
        cookies=cookies,
        follow_redirects=True,
        http2=False,
    ) as client:
        board_title, api_pins, is_private = await _scrape_via_resource_api(
            client, host, username, board_slug, canonical_url, max_pins
        )
        if api_pins:
            return ScrapedBoard(
                board_url=board_url,
                canonical_url=canonical_url,
                username=username,
                board_slug=board_slug,
                board_title=board_title,
                source_method="resource_api",
                pins=api_pins[:max_pins],
            )

        pidget_title, pidget_pins = await _scrape_via_pidgets_api(
            client, username, board_slug, max_pins
        )
        if pidget_pins:
            return ScrapedBoard(
                board_url=board_url,
                canonical_url=canonical_url,
                username=username,
                board_slug=board_slug,
                board_title=pidget_title,
                source_method="pidgets_api",
                pins=pidget_pins[:max_pins],
            )

        rss_title, rss_pins = await _scrape_via_rss(
            client, host, username, board_slug, max_pins
        )
        if rss_pins:
            return ScrapedBoard(
                board_url=board_url,
                canonical_url=canonical_url,
                username=username,
                board_slug=board_slug,
                board_title=rss_title,
                source_method="rss",
                pins=rss_pins[:max_pins],
            )

        html_title, html_pins = await _scrape_via_html_hydration(
            client, canonical_url, board_slug, max_pins
        )
        if html_pins:
            return ScrapedBoard(
                board_url=board_url,
                canonical_url=canonical_url,
                username=username,
                board_slug=board_slug,
                board_title=html_title,
                source_method="html_hydration",
                pins=html_pins[:max_pins],
            )

    pw_title, pw_pins = await _scrape_via_playwright_optional(
        canonical_url, board_slug, max_pins
    )
    if pw_pins:
        return ScrapedBoard(
            board_url=board_url,
            canonical_url=canonical_url,
            username=username,
            board_slug=board_slug,
            board_title=pw_title,
            source_method="playwright",
            pins=pw_pins[:max_pins],
        )

    if is_private:
        raise BoardAccessError(
            f"El perfil '@{username}' o el tablero '{board_slug}' es privado/secreto en Pinterest "
            f"(is_private_profile=True). Para extraerlo: haz público el perfil/tablero en Pinterest "
            f"o pasa tus cookies de sesión con `--cookies cookies.json` (o `PINTEREST_SESSION_COOKIE`)."
        )

    raise BoardAccessError(
        f"No se pudieron extraer pines de {canonical_url}. "
        "Verifica que el tablero exista y sea público (o usa `--cookies` si es privado)."
    )


async def download_references(
    board: ScrapedBoard,
    references_dir: Path,
) -> list[ScrapedPin]:
    """Download pin images concurrently, deduplicate by content hash, and normalize to JPEG."""
    references_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(8)
    seen_hashes: set[str] = set()
    lock = asyncio.Lock()

    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True) as client:

        async def fetch_one(pin: ScrapedPin) -> ScrapedPin | None:
            content: bytes | None = None
            if pin.local_path and Path(pin.local_path).is_file():
                try:
                    content = Path(pin.local_path).read_bytes()
                except OSError:
                    content = None

            if content is None:
                candidates = _upgrade_candidates(pin.image_url)
                async with sem:
                    for url in candidates:
                        try:
                            resp = await client.get(url, timeout=20.0)
                            if resp.status_code == 200 and len(resp.content) > 1024:
                                content = resp.content
                                pin.image_url = url
                                break
                        except httpx.HTTPError:
                            continue

            if content is None:
                return None

            digest = hashlib.sha256(content).hexdigest()
            async with lock:
                if digest in seen_hashes:
                    return None
                seen_hashes.add(digest)

            try:
                img = Image.open(io.BytesIO(content))
                if img.mode in ("RGBA", "LA", "P"):
                    bg = Image.new("RGB", img.size, (255, 255, 255))
                    rgba = img.convert("RGBA")
                    bg.paste(rgba, mask=rgba.split()[3])
                    img = bg
                elif img.mode != "RGB":
                    img = img.convert("RGB")
                pin.width, pin.height = img.size
            except Exception:
                return None

            filename = f"pin_{pin.index:02d}.jpg"
            dest = references_dir / filename
            img.save(dest, format="JPEG", quality=92)
            pin.local_path = str(dest)
            return pin

        results = await asyncio.gather(*(fetch_one(p) for p in board.pins))

    valid_pins = [p for p in results if p is not None]
    for new_idx, pin in enumerate(valid_pins, start=1):
        old_path = Path(pin.local_path)
        new_path = references_dir / f"pin_{new_idx:02d}.jpg"
        if old_path != new_path and old_path.exists():
            if new_path.exists():
                new_path.unlink()
            old_path.rename(new_path)
            pin.local_path = str(new_path)
        pin.index = new_idx

    board.pins = valid_pins
    return valid_pins
