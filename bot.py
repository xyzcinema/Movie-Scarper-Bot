#!/usr/bin/env python3
"""Telegram bot using DesireMovies-only search/details endpoints."""

import os
import logging
import re
import secrets
import time
from typing import Any

import aiohttp
from aiohttp import web
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

API_BASE_URL = os.getenv("API_BASE_URL", "https://scarperapi-8lk0.onrender.com")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_KEY = os.getenv("API_KEY", "")
PORT = int(os.getenv("PORT", "10000"))
ENABLE_HTTP_SERVER = os.getenv("ENABLE_HTTP_SERVER", "true").lower() == "true"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "webhook").strip("/") or "webhook"
REDIRECT_TTL_SECONDS = int(os.getenv("REDIRECT_TTL_SECONDS", "21600"))


def infer_webhook_url() -> str:
    explicit = WEBHOOK_URL.strip()
    if explicit:
        return explicit

    candidates = (
        os.getenv("RENDER_EXTERNAL_URL", ""),
        os.getenv("RAILWAY_STATIC_URL", ""),
        os.getenv("KOYEB_PUBLIC_DOMAIN", ""),
    )
    for candidate in candidates:
        value = candidate.strip()
        if not value:
            continue
        if value.startswith("http://") or value.startswith("https://"):
            return value
        return f"https://{value}"

    return ""

HEADERS = {"x-api-key": API_KEY, "Content-Type": "application/json"}

SELECTING_ITEM = 1
TOKEN_PATTERN = re.compile(r"^\d+:[A-Za-z0-9_-]{20,}$")
LINK_REDIRECTS: dict[str, tuple[str, float]] = {}


def validate_bot_token(token: str) -> str:
    cleaned = token.strip()
    if not cleaned:
        raise RuntimeError("BOT_TOKEN is required")
    if not TOKEN_PATTERN.match(cleaned):
        raise RuntimeError("BOT_TOKEN format looks invalid. Verify the value from @BotFather.")
    return cleaned


def normalize_quality(quality: str | None) -> str:
    text = str(quality or "").strip()
    if not text or text.lower() in {"unknown", "n/a", "na", "none", "null"}:
        return "Unknown"
    return text


def normalize_size(size: str | None) -> str:
    text = str(size or "").strip()
    if not text or text.lower() in {"unknown", "n/a", "na", "none", "null"}:
        return "Unknown"
    return text


def _episode_number_from_text(value: str) -> int | None:
    if not value:
        return None
    match = re.search(r"(?:e|ep|episode)\s*0*(\d+)", value, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


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
    image_url = str(raw.get("imageUrl") or raw.get("image") or "").strip()
    raw_type = str(raw.get("type") or "movie").lower()
    payload_type = "series" if raw_type == "series" or raw.get("episodes") else "movie"

    base_links = normalize_download_links(raw.get("downloadLinks") or raw.get("links") or raw.get("downloads"))

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

    episodes.sort(key=lambda item: item["episodeNumber"])

    clean_payload: dict[str, Any] = {
        "success": True,
        "type": "series" if episodes else payload_type,
        "title": str(title),
        "imageUrl": image_url,
        "downloadLinks": base_links,
    }
    if episodes:
        clean_payload["episodes"] = episodes

    return clean_payload


def extract_details_payload(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None

    if data.get("success") is False:
        return None

    payload = data.get("data")
    if isinstance(payload, dict):
        return payload

    return data


async def desiremovies_search(session: aiohttp.ClientSession, query: str) -> list[dict[str, Any]]:
    endpoints = ("/api/desiremovies/search", "/api/desiremoviess/search")
    for endpoint in endpoints:
        url = f"{API_BASE_URL}{endpoint}"
        async with session.get(url, params={"q": query}, headers=HEADERS) as response:
            if response.status != 200:
                continue

            data = await response.json()
            items = data.get("results") if isinstance(data, dict) else data
            if not isinstance(items, list):
                continue

            results: list[dict[str, Any]] = []
            for item in items:
                title = str(item.get("title") or "Unknown").strip()
                link = item.get("url") or item.get("link")
                if title and isinstance(link, str) and link.strip():
                    results.append(
                        {
                            "id": str(item.get("id") or "").strip(),
                            "title": title,
                            "url": link.strip(),
                            "imageUrl": str(item.get("imageUrl") or item.get("image") or "").strip(),
                            "description": str(item.get("description") or "").strip(),
                        }
                    )
            if results:
                return results
    return []


async def desiremovies_details(session: aiohttp.ClientSession, movie_url: str, fallback_title: str) -> dict[str, Any] | None:
    endpoints = ("/api/desiremovies/details", "/api/desiremoviess/details")
    for endpoint in endpoints:
        url = f"{API_BASE_URL}{endpoint}"
        async with session.get(url, params={"url": movie_url}, headers=HEADERS) as response:
            if response.status != 200:
                continue

            data = await response.json()
            payload = extract_details_payload(data)
            if not payload:
                continue
            return normalize_details_payload(payload, fallback_title=fallback_title)
    return None


def build_search_keyboard(results: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    keyboard = [[InlineKeyboardButton(item["title"], callback_data=f"movie_{index}")] for index, item in enumerate(results)]
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(keyboard)


def _build_redirect_url(target_url: str, proxy_base_url: str | None) -> str:
    if not proxy_base_url:
        return target_url

    token = secrets.token_urlsafe(8)
    LINK_REDIRECTS[token] = (target_url, time.time() + REDIRECT_TTL_SECONDS)
    return f"{proxy_base_url.rstrip('/')}/r/{token}"


def build_download_keyboard(download_links: list[dict[str, str]], proxy_base_url: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    for link in download_links:
        label = f"🎬 {normalize_quality(link.get('quality'))} | {normalize_size(link.get('size'))}"
        rows.append([InlineKeyboardButton(label, url=_build_redirect_url(link["url"], proxy_base_url))])
    rows.append([InlineKeyboardButton("🔍 New Search", callback_data="new_search")])
    return InlineKeyboardMarkup(rows)


def build_episode_keyboard(episodes: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"Episode {ep['episodeNumber']}", callback_data=f"episode_{idx}")] for idx, ep in enumerate(episodes)]
    rows.append([InlineKeyboardButton("🔍 New Search", callback_data="new_search")])
    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🎬 <b>Welcome!</b>\nUse /search &lt;movie name&gt; to find titles from DesireMovies.",
        parse_mode="HTML",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Use /search &lt;movie name&gt;\n"
        "• Select a title\n"
        "• Get premium inline download buttons\n"
        "• Web series are grouped episode-wise",
    )


async def search_movies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query_text = " ".join(context.args).strip()
    if not query_text:
        await update.message.reply_text("Please provide a movie name.\nExample: /search inception")
        return ConversationHandler.END

    status_message = await update.message.reply_text(f"🔍 Searching for: <code>{query_text}</code>", parse_mode="HTML")

    try:
        async with aiohttp.ClientSession() as session:
            results = await desiremovies_search(session, query_text)
        if not results:
            await status_message.edit_text("No results found.")
            return ConversationHandler.END

        context.user_data["search_results"] = results[:20]
        await status_message.edit_text(
            "Select a movie:",
            reply_markup=build_search_keyboard(context.user_data["search_results"]),
        )
        return SELECTING_ITEM
    except aiohttp.ClientError:
        await status_message.edit_text("Unable to reach the API right now. Please try again.")
        return ConversationHandler.END


async def on_movie_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("Search cancelled.")
        return ConversationHandler.END

    search_results = context.user_data.get("search_results", [])
    try:
        movie_index = int(query.data.split("_")[1])
        selected = search_results[movie_index]
    except (ValueError, IndexError, KeyError):
        await query.edit_message_text("Invalid selection. Please search again.")
        return ConversationHandler.END

    await query.edit_message_text(f"Fetching: {selected['title']}")

    try:
        async with aiohttp.ClientSession() as session:
            details = await desiremovies_details(session, selected["url"], selected["title"])

        if not details:
            await query.edit_message_text("Invalid link or details not available.")
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

        proxy_base_url = context.bot_data.get("public_base_url")
        await query.edit_message_text(
            f"🎬 <b>{details['title']}</b>\nChoose quality:",
            parse_mode="HTML",
            reply_markup=build_download_keyboard(links, proxy_base_url=proxy_base_url),
        )
        return ConversationHandler.END
    except aiohttp.ClientError:
        await query.edit_message_text("Unable to fetch details right now.")
        return ConversationHandler.END


async def on_episode_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    details = context.user_data.get("selected_details") or {}
    episodes = details.get("episodes") or []

    try:
        episode_index = int(query.data.split("_")[1])
        episode = episodes[episode_index]
    except (ValueError, IndexError, KeyError):
        await query.edit_message_text("Invalid episode. Please search again.")
        return ConversationHandler.END

    episode_links = episode.get("downloadLinks") or []
    if not episode_links:
        await query.edit_message_text("No download links found for this episode.")
        return ConversationHandler.END

    proxy_base_url = context.bot_data.get("public_base_url")
    await query.edit_message_text(
        f"📺 <b>{details.get('title', 'Series')}</b>\nEpisode {episode['episodeNumber']}\nChoose quality:",
        parse_mode="HTML",
        reply_markup=build_download_keyboard(episode_links, proxy_base_url=proxy_base_url),
    )
    return ConversationHandler.END


async def redirect_download(request: web.Request) -> web.Response:
    token = request.match_info.get("token", "")
    entry = LINK_REDIRECTS.get(token)
    if not entry:
        return web.Response(status=404, text="Link expired or invalid")

    target_url, expires_at = entry
    if time.time() > expires_at:
        LINK_REDIRECTS.pop(token, None)
        return web.Response(status=410, text="Link expired")

    return web.HTTPFound(location=target_url)


async def new_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    callback = update.callback_query
    await callback.answer()
    await callback.edit_message_text("Start a new search with /search <movie name>")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.message or (update.callback_query.message if update.callback_query else None)
    if message:
        await message.reply_text("Operation cancelled.")
    return ConversationHandler.END


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text or update.message.text.startswith("/"):
        return ConversationHandler.END
    context.args = update.message.text.split()
    return await search_movies(update, context)


async def health_check(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def search_api(request: web.Request) -> web.Response:
    query = (request.query.get("q") or "").strip()
    if not query:
        return web.json_response({"success": False, "error": "Missing query parameter: q"}, status=400)

    try:
        async with aiohttp.ClientSession() as session:
            results = await desiremovies_search(session, query)
    except aiohttp.ClientError:
        return web.json_response({"success": False, "error": "Unable to reach upstream API"}, status=502)

    return web.json_response({"query": query, "results": results})


async def details_api(request: web.Request) -> web.Response:
    movie_url = (request.query.get("url") or "").strip()
    if not movie_url:
        return web.json_response({"success": False, "error": "Missing query parameter: url"}, status=400)

    fallback_title = (request.query.get("title") or "Unknown").strip() or "Unknown"
    try:
        async with aiohttp.ClientSession() as session:
            details = await desiremovies_details(session, movie_url, fallback_title)
    except aiohttp.ClientError:
        return web.json_response({"success": False, "error": "Unable to reach upstream API"}, status=502)

    if not details:
        return web.json_response({"success": False, "error": "Details not found"}, status=404)

    return web.json_response(details)


async def start_http_server(application: Application) -> None:
    if not ENABLE_HTTP_SERVER:
        return
    http_app = web.Application()
    http_app.router.add_get("/", health_check)
    http_app.router.add_get("/health", health_check)
    http_app.router.add_get("/r/{token}", redirect_download)
    http_app.router.add_get("/api/desiremovies/search", search_api)
    http_app.router.add_get("/api/desiremovies/details", details_api)

    runner = web.AppRunner(http_app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()
    application.bot_data["http_runner"] = runner


async def stop_http_server(application: Application) -> None:
    runner = application.bot_data.get("http_runner")
    if runner:
        await runner.cleanup()


async def initialize_polling(application: Application) -> None:
    await application.bot.delete_webhook(drop_pending_updates=True)
    await start_http_server(application)


def main() -> None:
    token = validate_bot_token(BOT_TOKEN)
    if not API_KEY:
        raise RuntimeError("API_KEY is required")

    resolved_webhook_url = infer_webhook_url()

    builder = Application.builder().token(token)
    if not resolved_webhook_url:
        builder = builder.post_init(initialize_polling).post_shutdown(stop_http_server)

    app = builder.build()
    app.bot_data["public_base_url"] = resolved_webhook_url or ""

    conversation = ConversationHandler(
        entry_points=[
            CommandHandler("search", search_movies),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
        ],
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

    app.add_handler(conversation)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))

    if resolved_webhook_url:
        webhook_target = f"{resolved_webhook_url.rstrip('/')}/{WEBHOOK_PATH}"
        logger.info("Starting bot in webhook mode at %s", webhook_target)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH,
            webhook_url=webhook_target,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        return

    logger.info("Starting bot in polling mode")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
