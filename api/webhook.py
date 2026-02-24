#!/usr/bin/env python3
"""Webhook handler for DesireMovies-only Telegram bot."""

import asyncio
import json
import logging
import os
import re
import secrets
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse
from typing import Any

import aiohttp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

API_BASE_URL = os.getenv("API_BASE_URL", "https://scarperapi-8lk0.onrender.com")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_KEY = os.getenv("API_KEY", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

HEADERS = {"x-api-key": API_KEY, "Content-Type": "application/json"}
SELECTING_ITEM = 1
_application = None
REDIRECT_TTL_SECONDS = int(os.getenv("REDIRECT_TTL_SECONDS", "21600"))
LINK_REDIRECTS: dict[str, tuple[str, float]] = {}


def normalize_quality(quality: str | None) -> str:
    text = str(quality or "").strip()
    return text if text and text.lower() not in {"unknown", "n/a", "na", "none", "null"} else "Unknown"


def normalize_size(size: str | None) -> str:
    text = str(size or "").strip()
    return text if text and text.lower() not in {"unknown", "n/a", "na", "none", "null"} else "Unknown"


def _episode_number_from_text(value: str) -> int | None:
    match = re.search(r"(?:e|ep|episode)\s*0*(\d+)", value or "", re.IGNORECASE)
    return int(match.group(1)) if match else None


def normalize_download_links(raw_links: Any) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(url: Any, quality: str = "Unknown", size: str = "Unknown") -> None:
        if not isinstance(url, str):
            return
        cleaned = url.strip()
        if not cleaned.startswith(("http://", "https://")) or cleaned in seen:
            return
        links.append({"quality": normalize_quality(quality), "size": normalize_size(size), "url": cleaned})
        seen.add(cleaned)

    def walk(node: Any, quality: str = "Unknown", size: str = "Unknown") -> None:
        if isinstance(node, str):
            add(node, quality, size)
            return
        if isinstance(node, list):
            for item in node:
                walk(item, quality, size)
            return
        if not isinstance(node, dict):
            return

        current_quality = node.get("quality") or node.get("label") or node.get("name") or quality
        current_size = node.get("size") or node.get("fileSize") or size
        add(
            node.get("url")
            or node.get("link")
            or node.get("directLink")
            or node.get("download")
            or node.get("downloadUrl")
            or node.get("href"),
            current_quality,
            current_size,
        )

        for key, value in node.items():
            next_quality = current_quality
            if isinstance(key, str) and re.search(r"\b(\d{3,4}p|4k|hd|fhd|uhd|cam|hdrip|webrip)\b", key, re.IGNORECASE):
                next_quality = key.strip()
            if isinstance(value, (str, list, dict)):
                walk(value, next_quality, current_size)

    walk(raw_links)
    return links


def normalize_details_payload(raw: dict[str, Any], fallback_title: str = "Unknown") -> dict[str, Any]:
    title = raw.get("title") or fallback_title
    payload_type = "series" if raw.get("episodes") else "movie"
    download_links = normalize_download_links(raw.get("downloadLinks") or raw.get("links") or raw.get("downloads"))

    episodes: list[dict[str, Any]] = []
    for index, episode in enumerate(raw.get("episodes") or [], start=1):
        episode_number = episode.get("episodeNumber")
        if not isinstance(episode_number, int):
            episode_number = _episode_number_from_text(str(episode.get("title") or "")) or index
        episode_links = normalize_download_links(
            episode.get("downloadLinks") or episode.get("links") or episode.get("downloads")
        )
        if episode_links:
            episodes.append({"episodeNumber": int(episode_number), "downloadLinks": episode_links})

    episodes.sort(key=lambda ep: ep["episodeNumber"])
    payload: dict[str, Any] = {"success": True, "type": "series" if episodes else payload_type, "title": title, "downloadLinks": download_links}
    if episodes:
        payload["episodes"] = episodes
    return payload


async def desiremovies_search(session: aiohttp.ClientSession, query: str) -> list[dict[str, str]]:
    endpoints = ("/api/desiremovies/search", "/api/desiremoviess/search")
    for endpoint in endpoints:
        async with session.get(f"{API_BASE_URL}{endpoint}", params={"q": query}, headers=HEADERS) as response:
            if response.status != 200:
                continue

            data = await response.json()
            items = data.get("results") if isinstance(data, dict) else data
            if not isinstance(items, list):
                continue

            results = [
                {"title": str(item.get("title") or "Unknown").strip(), "url": str(item.get("url") or item.get("link") or "").strip()}
                for item in items
                if str(item.get("url") or item.get("link") or "").strip()
            ]
            if results:
                return results
    return []


async def desiremovies_details(session: aiohttp.ClientSession, movie_url: str, fallback_title: str) -> dict[str, Any] | None:
    endpoints = ("/api/desiremovies/details", "/api/desiremoviess/details")
    for endpoint in endpoints:
        async with session.get(f"{API_BASE_URL}{endpoint}", params={"url": movie_url}, headers=HEADERS) as response:
            if response.status != 200:
                continue
            data = await response.json()
            if isinstance(data, dict):
                return normalize_details_payload(data, fallback_title=fallback_title)
    return None


def build_search_keyboard(results: list[dict[str, str]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(result["title"], callback_data=f"movie_{idx}")] for idx, result in enumerate(results)]
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)


def _build_redirect_url(target_url: str) -> str:
    base_url = WEBHOOK_URL.strip().rstrip("/")
    if not base_url:
        return target_url

    token = secrets.token_urlsafe(8)
    LINK_REDIRECTS[token] = (target_url, time.time() + REDIRECT_TTL_SECONDS)
    return f"{base_url}/r/{token}"


def build_download_keyboard(download_links: list[dict[str, str]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"🎬 {normalize_quality(link.get('quality'))} | {normalize_size(link.get('size'))}", url=_build_redirect_url(link["url"]))] for link in download_links]
    rows.append([InlineKeyboardButton("🔍 New Search", callback_data="new_search")])
    return InlineKeyboardMarkup(rows)


def build_episode_keyboard(episodes: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"Episode {episode['episodeNumber']}", callback_data=f"episode_{idx}")] for idx, episode in enumerate(episodes)]
    rows.append([InlineKeyboardButton("🔍 New Search", callback_data="new_search")])
    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🎬 Welcome! Use /search <movie name> to find DesireMovies links.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Use /search <movie name>.\nMovies and series links are provided via inline buttons.")


async def search_movies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query_text = " ".join(context.args).strip()
    if not query_text:
        await update.message.reply_text("Please use /search <movie name>.")
        return ConversationHandler.END

    status = await update.message.reply_text(f"🔍 Searching: <code>{query_text}</code>", parse_mode="HTML")

    try:
        async with aiohttp.ClientSession() as session:
            results = await desiremovies_search(session, query_text)
    except aiohttp.ClientError:
        await status.edit_text("Unable to connect to API.")
        return ConversationHandler.END

    if not results:
        await status.edit_text("No results found.")
        return ConversationHandler.END

    context.user_data["search_results"] = results[:20]
    await status.edit_text("Select a movie:", reply_markup=build_search_keyboard(context.user_data["search_results"]))
    return SELECTING_ITEM


async def on_movie_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("Search cancelled.")
        return ConversationHandler.END

    results = context.user_data.get("search_results", [])
    try:
        idx = int(query.data.split("_")[1])
        selected = results[idx]
    except (ValueError, IndexError, KeyError):
        await query.edit_message_text("Invalid selection. Please search again.")
        return ConversationHandler.END

    await query.edit_message_text(f"Fetching: {selected['title']}")

    try:
        async with aiohttp.ClientSession() as session:
            details = await desiremovies_details(session, selected["url"], selected["title"])
    except aiohttp.ClientError:
        await query.edit_message_text("Unable to fetch details.")
        return ConversationHandler.END

    if not details:
        await query.edit_message_text("Invalid link or details unavailable.")
        return ConversationHandler.END

    context.user_data["selected_details"] = details
    if details.get("type") == "series" and details.get("episodes"):
        await query.edit_message_text(
            f"📺 <b>{details['title']}</b>\nSelect an episode:",
            parse_mode="HTML",
            reply_markup=build_episode_keyboard(details["episodes"]),
        )
        return SELECTING_ITEM

    links = details.get("downloadLinks") or []
    if not links:
        await query.edit_message_text("No download links found.")
        return ConversationHandler.END

    await query.edit_message_text(
        f"🎬 <b>{details['title']}</b>\nChoose quality:",
        parse_mode="HTML",
        reply_markup=build_download_keyboard(links),
    )
    return ConversationHandler.END


async def on_episode_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    details = context.user_data.get("selected_details") or {}
    episodes = details.get("episodes") or []

    try:
        idx = int(query.data.split("_")[1])
        episode = episodes[idx]
    except (ValueError, IndexError, KeyError):
        await query.edit_message_text("Invalid episode. Please search again.")
        return ConversationHandler.END

    links = episode.get("downloadLinks") or []
    if not links:
        await query.edit_message_text("No download links found for this episode.")
        return ConversationHandler.END

    await query.edit_message_text(
        f"📺 <b>{details.get('title', 'Series')}</b>\nEpisode {episode['episodeNumber']}\nChoose quality:",
        parse_mode="HTML",
        reply_markup=build_download_keyboard(links),
    )
    return ConversationHandler.END


async def new_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    callback = update.callback_query
    await callback.answer()
    await callback.edit_message_text("Start a new search with /search <movie name>")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message:
        await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Update error: %s", context.error)


def _setup_handlers(application: Application) -> None:
    conversation = ConversationHandler(
        entry_points=[CommandHandler("search", search_movies)],
        states={
            SELECTING_ITEM: [
                CallbackQueryHandler(on_movie_selected, pattern=r"^movie_\d+$"),
                CallbackQueryHandler(on_episode_selected, pattern=r"^episode_\d+$"),
                CallbackQueryHandler(new_search, pattern=r"^new_search$"),
                CallbackQueryHandler(cancel, pattern=r"^cancel$"),
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conversation)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_error_handler(error_handler)


def get_application() -> Application:
    global _application
    if _application is None:
        _application = Application.builder().token(BOT_TOKEN).build()
        _setup_handlers(_application)
    return _application


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/r/"):
            token = parsed.path.rsplit("/", 1)[-1]
            entry = LINK_REDIRECTS.get(token)
            if not entry:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Link expired or invalid")
                return

            target_url, expires_at = entry
            if time.time() > expires_at:
                LINK_REDIRECTS.pop(token, None)
                self.send_response(410)
                self.end_headers()
                self.wfile.write(b"Link expired")
                return

            self.send_response(302)
            self.send_header("Location", target_url)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok"}).encode())

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)

        try:
            update_data = json.loads(post_data.decode("utf-8"))
            update = Update.de_json(update_data, None)
            app = get_application()

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(app.process_update(update))
            loop.close()

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
        except Exception as exc:
            logger.error("Error processing webhook update: %s", exc)
            self.send_response(500)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error"}).encode())


if BOT_TOKEN and WEBHOOK_URL:
    try:
        app = get_application()
        webhook_url = f"{WEBHOOK_URL}/webhook"
        asyncio.get_event_loop().run_until_complete(app.bot.set_webhook(webhook_url))
    except Exception as exc:
        logger.error("Webhook setup failed: %s", exc)
