#!/usr/bin/env python3
"""
Telegram Movie Scraper Bot - Webhook Version
For Vercel Serverless Deployment

This version uses webhooks instead of polling for serverless environments.
"""

import os
import json
import logging
import asyncio
import aiohttp
from urllib.parse import quote
from http.server import BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
API_BASE_URL = "https://scarperapi-8lk0.onrender.com"
STREAMING_HUB_URL = "https://streaminghub.42web.io"
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_KEY = os.getenv("API_KEY", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

# Headers for API requests
HEADERS = {
    "x-api-key": API_KEY,
    "Content-Type": "application/json",
}

# Conversation states
SELECTING_MOVIE = 1

# Global application instance
_application = None


def normalize_download_links(raw_links) -> list:
    """Normalize different API download-link formats into a flat list."""
    if isinstance(raw_links, dict):
        for key in ("downloadLinks", "results", "links", "downloads", "data"):
            value = raw_links.get(key)
            if isinstance(value, list):
                raw_links = value
                break

    if not isinstance(raw_links, list):
        return []

    normalized_links = []
    seen_urls = set()

    for item in raw_links:
        if not isinstance(item, dict):
            continue

        quality = item.get("quality") or item.get("label") or "Unknown"
        size = item.get("size") or ""

        direct_url = (
            item.get("url")
            or item.get("link")
            or item.get("directLink")
            or item.get("download")
        )

        if direct_url and direct_url not in seen_urls:
            normalized_links.append({"quality": quality, "size": size, "url": direct_url})
            seen_urls.add(direct_url)

        nested_links = item.get("links") or item.get("files") or item.get("options")
        if isinstance(nested_links, list):
            for nested in nested_links:
                if not isinstance(nested, dict):
                    continue

                nested_url = nested.get("url") or nested.get("link") or nested.get("download")
                if not nested_url or nested_url in seen_urls:
                    continue

                normalized_links.append(
                    {
                        "quality": nested.get("quality") or nested.get("label") or quality,
                        "size": nested.get("size") or size,
                        "url": nested_url,
                    }
                )
                seen_urls.add(nested_url)

    return normalized_links

def get_application():
    """Get or create the Telegram application instance."""
    global _application
    if _application is None:
        _application = Application.builder().token(BOT_TOKEN).build()
        _setup_handlers(_application)
    return _application

def _setup_handlers(application):
    """Setup all handlers for the bot."""
    # Add conversation handler for search flow
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("search", search_movies),
        ],
        states={
            SELECTING_MOVIE: [
                CallbackQueryHandler(select_movie, pattern=r"^movie_\d+$"),
                CallbackQueryHandler(back_to_results, pattern="^back_to_results$"),
                CallbackQueryHandler(new_search, pattern="^new_search$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start", start),
        ],
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    
    # Add callback query handlers outside conversation
    application.add_handler(CallbackQueryHandler(select_movie, pattern=r"^movie_\d+$"))
    application.add_handler(CallbackQueryHandler(back_to_results, pattern="^back_to_results$"))
    application.add_handler(CallbackQueryHandler(new_search, pattern="^new_search$"))
    application.add_handler(CallbackQueryHandler(cancel, pattern="^cancel$"))
    
    # Add error handler
    application.add_error_handler(error_handler)


async def search_provider(session: aiohttp.ClientSession, provider: str, query: str) -> list:
    """Search movies from a specific provider."""
    search_url = f"{API_BASE_URL}/api/{provider}/search"
    params = {"q": query}
    
    try:
        async with session.get(search_url, params=params, headers=HEADERS) as response:
            if response.status == 200:
                data = await response.json()
                if data and isinstance(data, list):
                    for item in data:
                        item["provider"] = provider
                    return data
            else:
                logger.warning(f"{provider} API returned status {response.status}")
    except Exception as e:
        logger.error(f"Error searching {provider}: {e}")
    
    return []


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message when the command /start is issued."""
    welcome_text = """
🎬 <b>Welcome to Movie Scraper Bot!</b>

I can help you find and download movies with direct links from:
🟢 <b>HdHub4U</b>
🔵 <b>DesireMovies</b>

<b>Commands:</b>
🔍 /search &lt;movie_name&gt; - Search for movies
📋 /help - Show help message

<b>Features:</b>
✅ Direct download links (480p, 720p, 1080p, 4K)
✅ Watch online without downloading
✅ Fast and reliable links

<i>Send me a movie name to get started!</i>
    """
    
    await update.message.reply_text(
        welcome_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Channel", url="https://t.me/your_channel")]
        ])
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a help message when the command /help is issued."""
    help_text = """
🎬 <b>Movie Scraper Bot - Help</b>

<b>Movie Sources:</b>
🟢 <b>HdHub4U</b> - Bollywood, Hollywood, South Indian movies
🔵 <b>DesireMovies</b> - Dual audio, Hindi dubbed movies

<b>How to use:</b>

1️⃣ <b>Search for a movie:</b>
   Type: <code>/search movie_name</code>
   Example: <code>/search inception</code>

2️⃣ <b>Select a movie:</b>
   Click on the movie from search results
   🟢 = HdHub4U | 🔵 = DesireMovies

3️⃣ <b>Choose quality:</b>
   • 480p - Standard quality
   • 720p - HD quality
   • 1080p - Full HD quality
   • 4K - Ultra HD quality (if available)

4️⃣ <b>Watch or Download:</b>
   • Click "📥 Direct Link" to download
   • Click "▶️ Watch Online" to stream

<b>Commands:</b>
/start - Start the bot
/search - Search for movies
/help - Show this help message

<b>Note:</b> Some links may require a download manager.
    """
    
    await update.message.reply_text(help_text, parse_mode="HTML")


async def search_movies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Search for movies using HdHub4U and DesireMovies APIs."""
    query = " ".join(context.args)
    
    if not query:
        await update.message.reply_text(
            "❌ <b>Please provide a movie name!</b>\n\n"
            "Usage: <code>/search movie_name</code>\n"
            "Example: <code>/search inception</code>",
            parse_mode="HTML"
        )
        return ConversationHandler.END
    
    # Show searching message
    searching_msg = await update.message.reply_text(
        f"🔍 <b>Searching for:</b> <code>{query}</code>\n"
        f"🌐 <b>Sources:</b> HdHub4U & DesireMovies\n\n"
        f"Please wait...",
        parse_mode="HTML"
    )
    
    try:
        async with aiohttp.ClientSession() as session:
            # Search both providers concurrently
            hdhub4u_results = await search_provider(session, "hdhub4u", query)
            desiremovies_results = await search_provider(session, "desiremovies", query)
            
            # Combine results
            all_results = []
            
            if hdhub4u_results:
                all_results.extend(hdhub4u_results)
            
            if desiremovies_results:
                all_results.extend(desiremovies_results)
            
            if not all_results:
                await searching_msg.edit_text(
                    f"❌ <b>No results found for:</b> <code>{query}</code>\n\n"
                    f"🌐 <b>Searched:</b> HdHub4U & DesireMovies\n\n"
                    f"Try searching with a different name.",
                    parse_mode="HTML"
                )
                return ConversationHandler.END
            
            # Store search results in user context
            context.user_data["search_results"] = all_results
            
            # Create buttons for each movie
            keyboard = []
            for idx, movie in enumerate(all_results[:15]):
                title = movie.get("title", "Unknown")
                year = movie.get("year", "N/A")
                quality = movie.get("quality", "")
                provider = movie.get("provider", "unknown")
                
                provider_emoji = "🟢" if provider == "hdhub4u" else "🔵"
                
                button_text = f"{provider_emoji} {title} ({year})"
                if quality:
                    button_text += f" [{quality}]"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"movie_{idx}")])
            
            keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
            
            hdhub4u_count = len(hdhub4u_results) if hdhub4u_results else 0
            desiremovies_count = len(desiremovies_results) if desiremovies_results else 0
            
            await searching_msg.edit_text(
                f"🎬 <b>Found {len(all_results)} results for:</b> <code>{query}</code>\n\n"
                f"🟢 <b>HdHub4U:</b> {hdhub4u_count} results\n"
                f"🔵 <b>DesireMovies:</b> {desiremovies_count} results\n\n"
                f"Select a movie:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return SELECTING_MOVIE
                    
    except Exception as e:
        logger.error(f"Error: {e}")
        await searching_msg.edit_text(
            "❌ <b>An error occurred.</b> Please try again later.",
            parse_mode="HTML"
        )
        return ConversationHandler.END


async def select_movie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle movie selection and fetch details."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text(
            "❌ Search cancelled. Send /search to try again.",
            parse_mode="HTML"
        )
        return ConversationHandler.END
    
    movie_idx = int(query.data.split("_")[1])
    search_results = context.user_data.get("search_results", [])
    
    if movie_idx >= len(search_results):
        await query.edit_message_text(
            "❌ <b>Error:</b> Invalid selection. Please search again.",
            parse_mode="HTML"
        )
        return ConversationHandler.END
    
    selected_movie = search_results[movie_idx]
    movie_url = selected_movie.get("link", "")
    movie_title = selected_movie.get("title", "Unknown")
    provider = selected_movie.get("provider", "hdhub4u")
    
    provider_emoji = "🟢" if provider == "hdhub4u" else "🔵"
    provider_name = "HdHub4U" if provider == "hdhub4u" else "DesireMovies"
    
    await query.edit_message_text(
        f"🎬 <b>Fetching details for:</b> <code>{movie_title}</code>\n"
        f"{provider_emoji} <b>Source:</b> {provider_name}\n\n"
        f"Please wait...",
        parse_mode="HTML"
    )
    
    try:
        async with aiohttp.ClientSession() as session:
            details_url = f"{API_BASE_URL}/api/{provider}/details"
            params = {"url": movie_url}
            
            async with session.get(details_url, params=params, headers=HEADERS) as response:
                if response.status != 200:
                    await query.edit_message_text(
                        f"❌ <b>Error:</b> Could not fetch movie details",
                        parse_mode="HTML"
                    )
                    return ConversationHandler.END
                
                details = await response.json()
            
            magic_links = normalize_download_links(
                details.get("downloadLinks")
                or details.get("magicLinks")
                or details.get("links")
                or details.get("downloads")
            )

            if not magic_links:
                magic_url = f"{API_BASE_URL}/api/{provider}/magiclinks"
                params = {"url": movie_url}

                async with session.get(magic_url, params=params, headers=HEADERS) as response:
                    if response.status == 200:
                        magic_links = normalize_download_links(await response.json())
            
            title = details.get("title", movie_title)
            year = details.get("year", "N/A")
            rating = details.get("rating", "N/A")
            duration = details.get("duration", "N/A")
            genre = details.get("genre", "N/A")
            plot = details.get("plot", "No description available.")
            
            if len(plot) > 300:
                plot = plot[:297] + "..."
            
            movie_info = f"""
🎬 <b>{title}</b>
{provider_emoji} <b>Source:</b> {provider_name}

📅 <b>Year:</b> {year}
⭐ <b>Rating:</b> {rating}/10
⏱ <b>Duration:</b> {duration}
🎭 <b>Genre:</b> {genre}

📝 <b>Plot:</b>
{plot}

<b>Select quality below:</b>
            """.strip()
            
            keyboard = []
            
            if magic_links and isinstance(magic_links, list) and len(magic_links) > 0:
                for link_data in magic_links:
                    quality = link_data.get("quality", "Unknown")
                    download_url = link_data.get("url") or link_data.get("link") or ""
                    size = link_data.get("size", "")
                    
                    if download_url:
                        encoded_url = quote(download_url, safe='')
                        watch_url = f"{STREAMING_HUB_URL}/?url={encoded_url}"
                        
                        button_text = f"{quality}"
                        if size:
                            button_text += f" ({size})"
                        
                        keyboard.append([
                            InlineKeyboardButton(f"📥 {button_text}", url=download_url),
                            InlineKeyboardButton(f"▶️ Watch {quality}", url=watch_url)
                        ])
            else:
                keyboard.append([InlineKeyboardButton("❌ No download links available", callback_data="noop")])
            
            keyboard.append([
                InlineKeyboardButton("🔙 Back to Results", callback_data="back_to_results"),
                InlineKeyboardButton("🔍 New Search", callback_data="new_search")
            ])
            
            await query.edit_message_text(
                movie_info,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            return ConversationHandler.END
            
    except Exception as e:
        logger.error(f"Error: {e}")
        await query.edit_message_text(
            "❌ <b>An error occurred.</b> Please try again later.",
            parse_mode="HTML"
        )
        return ConversationHandler.END


async def back_to_results(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Go back to search results."""
    query = update.callback_query
    await query.answer()
    
    search_results = context.user_data.get("search_results", [])
    
    if not search_results:
        await query.edit_message_text(
            "❌ Search results expired. Please search again with /search",
            parse_mode="HTML"
        )
        return ConversationHandler.END
    
    hdhub4u_count = sum(1 for m in search_results if m.get("provider") == "hdhub4u")
    desiremovies_count = sum(1 for m in search_results if m.get("provider") == "desiremovies")
    
    keyboard = []
    for idx, movie in enumerate(search_results[:15]):
        title = movie.get("title", "Unknown")
        year = movie.get("year", "N/A")
        quality = movie.get("quality", "")
        provider = movie.get("provider", "unknown")
        
        provider_emoji = "🟢" if provider == "hdhub4u" else "🔵"
        
        button_text = f"{provider_emoji} {title} ({year})"
        if quality:
            button_text += f" [{quality}]"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"movie_{idx}")])
    
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    
    await query.edit_message_text(
        f"🎬 <b>Search Results:</b>\n\n"
        f"🟢 <b>HdHub4U:</b> {hdhub4u_count} results\n"
        f"🔵 <b>DesireMovies:</b> {desiremovies_count} results\n\n"
        f"Select a movie:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SELECTING_MOVIE


async def new_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompt user for a new search."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🔍 <b>Start a new search</b>\n\n"
        "Type: <code>/search movie_name</code>\n"
        "Example: <code>/search inception</code>",
        parse_mode="HTML"
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    await update.message.reply_text(
        "❌ Operation cancelled. Send /search to find movies.",
        parse_mode="HTML"
    )
    return ConversationHandler.END


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors caused by updates."""
    logger.error(f"Update {update} caused error {context.error}")


class handler(BaseHTTPRequestHandler):
    """Vercel serverless function handler."""
    
    def do_GET(self):
        """Handle GET requests - health check."""
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        response = {"status": "ok", "message": "Bot is running"}
        self.wfile.write(json.dumps(response).encode())
    
    def do_POST(self):
        """Handle POST requests - webhook updates from Telegram."""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            update_data = json.loads(post_data.decode('utf-8'))
            update = Update.de_json(update_data, None)
            
            # Process the update
            application = get_application()
            
            # Run async processing
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(application.process_update(update))
            loop.close()
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {"status": "ok"}
            self.wfile.write(json.dumps(response).encode())
            
        except Exception as e:
            logger.error(f"Error processing update: {e}")
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {"status": "error", "message": str(e)}
            self.wfile.write(json.dumps(response).encode())


# Initialize and set webhook on module load
if BOT_TOKEN and WEBHOOK_URL:
    try:
        app = get_application()
        # Set webhook
        webhook_url = f"{WEBHOOK_URL}/webhook"
        asyncio.get_event_loop().run_until_complete(app.bot.set_webhook(webhook_url))
        logger.info(f"Webhook set to: {webhook_url}")
    except Exception as e:
        logger.error(f"Failed to set webhook: {e}")
