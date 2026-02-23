#!/usr/bin/env python3
"""
Telegram Movie Scraper Bot
Fetches movie data from ScarperAPI and provides direct download links
with watch online feature using streaminghub.
"""

import os
import logging
import aiohttp
from aiohttp import web
from urllib.parse import quote
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
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
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
API_KEY = os.getenv("API_KEY", "YOUR_API_KEY_HERE")
PORT = int(os.getenv("PORT", "10000"))
ENABLE_HTTP_SERVER = os.getenv("ENABLE_HTTP_SERVER", "true").lower() == "true"

# Headers for API requests
HEADERS = {
    "x-api-key": API_KEY,
    "Content-Type": "application/json",
}

# Conversation states
SEARCHING, SELECTING_MOVIE = range(2)


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
            [InlineKeyboardButton("🔍 Search Movies", switch_inline_query_current_chat="")],
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


async def search_provider(session: aiohttp.ClientSession, provider: str, query: str) -> list:
    """Search movies from a specific provider."""
    search_url = f"{API_BASE_URL}/api/{provider}/search"
    params = {"q": query}
    
    try:
        async with session.get(search_url, params=params, headers=HEADERS) as response:
            if response.status == 200:
                data = await response.json()
                if data and isinstance(data, list):
                    # Add provider info to each result
                    for item in data:
                        item["provider"] = provider
                    return data
            else:
                logger.warning(f"{provider} API returned status {response.status}")
    except Exception as e:
        logger.error(f"Error searching {provider}: {e}")
    
    return []


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
            hdhub4u_task = search_provider(session, "hdhub4u", query)
            desiremovies_task = search_provider(session, "desiremovies", query)
            
            hdhub4u_results = await hdhub4u_task
            desiremovies_results = await desiremovies_task
            
            # Combine results
            all_results = []
            
            if hdhub4u_results:
                all_results.extend(hdhub4u_results)
                logger.info(f"Found {len(hdhub4u_results)} results from HdHub4U")
            
            if desiremovies_results:
                all_results.extend(desiremovies_results)
                logger.info(f"Found {len(desiremovies_results)} results from DesireMovies")
            
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
            for idx, movie in enumerate(all_results[:15]):  # Limit to 15 results
                title = movie.get("title", "Unknown")
                year = movie.get("year", "N/A")
                quality = movie.get("quality", "")
                provider = movie.get("provider", "unknown")
                
                # Provider emoji
                provider_emoji = "🟢" if provider == "hdhub4u" else "🔵"
                
                button_text = f"{provider_emoji} {title} ({year})"
                if quality:
                    button_text += f" [{quality}]"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"movie_{idx}")])
            
            keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
            
            # Source breakdown
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
                    
    except aiohttp.ClientError as e:
        logger.error(f"Network error: {e}")
        await searching_msg.edit_text(
            "❌ <b>Network Error:</b> Unable to connect to the movie database.\n"
            "Please try again later.",
            parse_mode="HTML"
        )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        await searching_msg.edit_text(
            "❌ <b>An unexpected error occurred.</b>\n"
            "Please try again later.",
            parse_mode="HTML"
        )
        return ConversationHandler.END


async def select_movie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle movie selection and fetch details from the correct provider."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text(
            "❌ Search cancelled. Send /search to try again.",
            parse_mode="HTML"
        )
        return ConversationHandler.END
    
    # Extract movie index from callback data
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
    provider = selected_movie.get("provider", "hdhub4u")  # Default to hdhub4u
    
    # Provider emoji and name
    provider_emoji = "🟢" if provider == "hdhub4u" else "🔵"
    provider_name = "HdHub4U" if provider == "hdhub4u" else "DesireMovies"
    
    # Show loading message
    await query.edit_message_text(
        f"🎬 <b>Fetching details for:</b> <code>{movie_title}</code>\n"
        f"{provider_emoji} <b>Source:</b> {provider_name}\n\n"
        f"Please wait...",
        parse_mode="HTML"
    )
    
    try:
        async with aiohttp.ClientSession() as session:
            # Fetch movie details from the correct provider
            details_url = f"{API_BASE_URL}/api/{provider}/details"
            params = {"url": movie_url}
            
            async with session.get(details_url, params=params, headers=HEADERS) as response:
                if response.status != 200:
                    await query.edit_message_text(
                        f"❌ <b>Error:</b> Could not fetch movie details (Status: {response.status})\n"
                        f"Provider: {provider_name}",
                        parse_mode="HTML"
                    )
                    return ConversationHandler.END
                
                details = await response.json()
            
            # Fetch download links from the correct provider
            magic_url = f"{API_BASE_URL}/api/{provider}/magiclinks"
            params = {"url": movie_url}
            
            async with session.get(magic_url, params=params, headers=HEADERS) as response:
                if response.status != 200:
                    await query.edit_message_text(
                        f"❌ <b>Error:</b> Could not fetch download links (Status: {response.status})\n"
                        f"Provider: {provider_name}",
                        parse_mode="HTML"
                    )
                    return ConversationHandler.END
                
                magic_links = await response.json()
            
            # Build movie info message
            title = details.get("title", movie_title)
            year = details.get("year", "N/A")
            rating = details.get("rating", "N/A")
            duration = details.get("duration", "N/A")
            genre = details.get("genre", "N/A")
            plot = details.get("plot", "No description available.")
            poster = details.get("poster", "")
            
            # Truncate plot if too long
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
            
            # Create quality buttons
            keyboard = []
            
            # Process download links
            if magic_links and isinstance(magic_links, list) and len(magic_links) > 0:
                for link_data in magic_links:
                    quality = link_data.get("quality", "Unknown")
                    download_url = link_data.get("link", "")
                    size = link_data.get("size", "")
                    
                    if download_url:
                        # Create watch online URL
                        encoded_url = quote(download_url, safe='')
                        watch_url = f"{STREAMING_HUB_URL}/?url={encoded_url}"
                        
                        button_text = f"{quality}"
                        if size:
                            button_text += f" ({size})"
                        
                        # Add buttons for this quality
                        keyboard.append([
                            InlineKeyboardButton(f"📥 {button_text}", url=download_url),
                            InlineKeyboardButton(f"▶️ Watch {quality}", url=watch_url)
                        ])
            else:
                # No download links found
                keyboard.append([InlineKeyboardButton("❌ No download links available", callback_data="noop")])
            
            # Add back and cancel buttons
            keyboard.append([
                InlineKeyboardButton("🔙 Back to Results", callback_data="back_to_results"),
                InlineKeyboardButton("🔍 New Search", callback_data="new_search")
            ])
            
            # Store movie data for later use
            context.user_data["selected_movie"] = {
                "title": title,
                "info": movie_info,
                "poster": poster,
                "links": magic_links,
                "provider": provider
            }
            
            await query.edit_message_text(
                movie_info,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
            return ConversationHandler.END
            
    except aiohttp.ClientError as e:
        logger.error(f"Network error: {e}")
        await query.edit_message_text(
            "❌ <b>Network Error:</b> Unable to fetch movie details.\n"
            "Please try again later.",
            parse_mode="HTML"
        )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        await query.edit_message_text(
            "❌ <b>An unexpected error occurred.</b>\n"
            "Please try again later.",
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
    
    # Count results by provider
    hdhub4u_count = sum(1 for m in search_results if m.get("provider") == "hdhub4u")
    desiremovies_count = sum(1 for m in search_results if m.get("provider") == "desiremovies")
    
    # Recreate buttons for each movie
    keyboard = []
    for idx, movie in enumerate(search_results[:15]):
        title = movie.get("title", "Unknown")
        year = movie.get("year", "N/A")
        quality = movie.get("quality", "")
        provider = movie.get("provider", "unknown")
        
        # Provider emoji
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


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages - treat them as search queries."""
    text = update.message.text
    
    # If message looks like a command, ignore it
    if text.startswith("/"):
        return
    
    # Treat as search query
    context.args = text.split()
    await search_movies(update, context)


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors caused by updates."""
    logger.error(f"Update {update} caused error {context.error}")


async def health_check(request: web.Request) -> web.Response:
    """Health check endpoint for hosting platforms that expect an open HTTP port."""
    return web.json_response({"status": "ok", "service": "telegram-movie-bot"})


async def start_http_server(application: Application) -> None:
    """Start an optional HTTP server for Render web-service style deployments."""
    if not ENABLE_HTTP_SERVER:
        logger.info("HTTP server disabled (ENABLE_HTTP_SERVER=false)")
        return

    http_app = web.Application()
    http_app.router.add_get("/", health_check)
    http_app.router.add_get("/health", health_check)

    runner = web.AppRunner(http_app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()

    application.bot_data["http_runner"] = runner
    logger.info("HTTP health server running on 0.0.0.0:%s", PORT)


async def stop_http_server(application: Application) -> None:
    """Gracefully stop the optional HTTP server."""
    runner = application.bot_data.get("http_runner")
    if runner:
        await runner.cleanup()
        logger.info("HTTP health server stopped")


def main() -> None:
    """Start the bot."""
    # Check for required environment variables
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("Please set the BOT_TOKEN environment variable!")
        print("❌ Error: Please set the BOT_TOKEN environment variable!")
        print("Example: export BOT_TOKEN='your_bot_token_here'")
        return
    
    if API_KEY == "YOUR_API_KEY_HERE":
        logger.error("Please set the API_KEY environment variable!")
        print("❌ Error: Please set the API_KEY environment variable!")
        print("Example: export API_KEY='your_api_key_here'")
        return
    
    # Create the Application
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(start_http_server)
        .post_shutdown(stop_http_server)
        .build()
    )
    
    # Add conversation handler for search flow
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("search", search_movies),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
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
    
    # Start the Bot
    logger.info("Starting Movie Scraper Bot...")
    print("🎬 Movie Scraper Bot is starting...")
    print("✅ Bot is running! Press Ctrl+C to stop.")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
