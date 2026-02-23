#!/bin/bash

# Telegram Movie Scraper Bot Setup Script

echo "🎬 Telegram Movie Scraper Bot Setup"
echo "===================================="
echo ""

# Check Python version
echo "Checking Python version..."
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Found Python $python_version"

# Check if Python 3.8+ is installed
if python3 -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)"; then
    echo "✅ Python 3.8+ is installed"
else
    echo "❌ Python 3.8 or higher is required"
    exit 1
fi

echo ""
echo "Installing dependencies..."
pip3 install -r requirements.txt

if [ $? -eq 0 ]; then
    echo "✅ Dependencies installed successfully"
else
    echo "❌ Failed to install dependencies"
    exit 1
fi

echo ""
echo "===================================="
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "1. Set environment variables:"
echo "   export BOT_TOKEN='your_telegram_bot_token'"
echo "   export API_KEY='your_scarper_api_key'"
echo ""
echo "2. Run the bot:"
echo "   python3 bot.py"
echo ""
echo "📖 For more information, see README.md"
echo "===================================="
