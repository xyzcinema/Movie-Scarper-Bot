# 🎬 Telegram Movie Scraper Bot

A powerful Telegram bot that fetches movie data from **HdHub4U** and **DesireMovies** via ScarperAPI and provides direct download links with watch online functionality.

## ✨ Features

- 🔍 **Search Movies** - Find movies from HdHub4U & DesireMovies
- 🟢 **HdHub4U** - Bollywood, Hollywood, South Indian movies
- 🔵 **DesireMovies** - Dual audio, Hindi dubbed movies
- 📥 **Direct Download Links** - Get links for 480p, 720p, 1080p, 4K qualities
- ▶️ **Watch Online** - Stream movies without downloading
- 🎬 **Movie Details** - View ratings, year, duration, genre, and plot
- ⚡ **Fast & Reliable** - Built with async Python for speed

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher
- A Telegram Bot Token (get from [@BotFather](https://t.me/BotFather))
- ScarperAPI Key (get from [scarperapi-8lk0.onrender.com](https://scarperapi-8lk0.onrender.com))

### Installation

1. **Clone or download this repository:**
```bash
git clone <repository-url>
cd telegram-movie-bot
```

2. **Install dependencies:**
```bash
pip install -r requirements.txt
```

3. **Set environment variables:**
```bash
export BOT_TOKEN="your_telegram_bot_token_here"
export API_KEY="your_scarper_api_key_here"
```

4. **Run the bot:**
```bash
python bot.py
```

## 🛠 Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `BOT_TOKEN` | Your Telegram bot token from @BotFather | ✅ Yes |
| `API_KEY` | Your ScarperAPI key | ✅ Yes |

### Getting a Bot Token

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Start a chat and send `/newbot`
3. Follow the instructions to create your bot
4. Copy the bot token provided

### Getting an API Key

1. Visit [scarperapi-8lk0.onrender.com](https://scarperapi-8lk0.onrender.com)
2. Sign up for an account
3. Go to Dashboard → APIs
4. Generate a new API key
5. Copy the API key

## 📱 Usage

### Commands

- `/start` - Start the bot and see welcome message
- `/search <movie_name>` - Search for movies
- `/help` - Show help message

### Examples

```
/search inception
/search the dark knight
/search interstellar
```

Or simply type the movie name without any command:
```
inception
the dark knight
```

### How It Works

1. Send a movie name or use `/search <movie_name>`
2. Bot searches both **HdHub4U** 🟢 and **DesireMovies** 🔵
3. Select a movie from the combined search results
4. Choose your preferred quality (480p, 720p, 1080p, 4K)
5. Click "📥 Direct Link" to download or "▶️ Watch Online" to stream

## 🌐 Deployment

### Deploy on Heroku

1. Create a `Procfile`:
```
worker: python bot.py
```

2. Create `runtime.txt`:
```
python-3.11.0
```

3. Deploy to Heroku and set environment variables in the dashboard.

### Deploy on Railway

1. Fork this repository
2. Connect to Railway
3. Add environment variables in Railway dashboard
4. Deploy

### Deploy on VPS/Server

1. Clone the repository on your server
2. Install dependencies: `pip install -r requirements.txt`
3. Set environment variables
4. Run with screen or tmux:
```bash
screen -S movie-bot
python bot.py
# Press Ctrl+A, then D to detach
```

Or use systemd for auto-start:

Create `/etc/systemd/system/movie-bot.service`:
```ini
[Unit]
Description=Telegram Movie Scraper Bot
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/telegram-movie-bot
Environment=BOT_TOKEN=your_bot_token
Environment=API_KEY=your_api_key
ExecStart=/usr/bin/python3 /path/to/telegram-movie-bot/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable movie-bot
sudo systemctl start movie-bot
```

## 📝 API Endpoints Used

The bot uses the following ScarperAPI endpoints:

### HdHub4U
- `GET /api/hdhub4u/search?q={query}` - Search movies
- `GET /api/hdhub4u/details?url={url}` - Get movie details
- `GET /api/hdhub4u/magiclinks?url={url}` - Get download links

### DesireMovies
- `GET /api/desiremovies/search?q={query}` - Search movies
- `GET /api/desiremovies/details?url={url}` - Get movie details
- `GET /api/desiremovies/magiclinks?url={url}` - Get download links

## 🔗 Watch Online Feature

The bot integrates with [streaminghub.42web.io](https://streaminghub.42web.io) to provide online streaming:

```
https://streaminghub.42web.io/?url=<encoded_direct_link>
```

## 🐛 Troubleshooting

### Bot not responding
- Check if `BOT_TOKEN` is correct
- Ensure the bot is running
- Check logs for errors

### API errors
- Verify `API_KEY` is valid
- Check API quota limits
- Ensure network connectivity

### Search returns no results
- Try different search terms
- Check if the movie exists in the database
- Verify API is accessible

## 📄 License

This project is open source and available under the MIT License.

## 🙏 Credits

- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) - Telegram Bot API wrapper
- [ScarperAPI](https://scarperapi-8lk0.onrender.com) - Movie data API
- [StreamingHub](https://streaminghub.42web.io) - Online streaming service

## 📞 Support

For support, please open an issue or contact the developer.

---

**Enjoy watching movies! 🎬🍿**
