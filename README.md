# OpenRouter Discord Chatbot

A clean Discord chatbot in Python with OpenRouter, model fallback, and per-user history. Supports slash commands, optional auto-reply channels, and optional DM auto-replies.

## Features

- Slash commands: `/chat` and `/reset`
- Optional auto-reply channel(s) for direct message handling
- Optional DM auto-reply with timed deletion to reduce clutter
- Automatic fallback to a secondary model
- Per-user conversation history stored in SQLite
- Simple `.env` configuration

## Quick Start

1. Install Python 3.10+
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Create a `.env` file in the project root
4. Set `DISCORD_TOKEN` and `OPENROUTER_API_KEY` in `.env`

## Run

```
python bot.py
```

## Usage

- `/chat` sends a prompt to the bot
- `/reset` clears your saved history
- If `AUTO_REPLY_CHANNELS` is set, the bot replies to every message in those channel IDs
- If `AUTO_REPLY_DMS=true`, the bot replies to DMs and deletes its own reply after `DM_DELETE_SECONDS`

## Configuration

Example `.env`:

```
DISCORD_TOKEN=your_discord_bot_token
OPENROUTER_API_KEY=your_openrouter_key
MODELS=baidu/cobuddy:free,openrouter/owl-alpha,nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free,deepseek/deepseek-v4-flash:free,google/gemma-4-26b-a4b-it:free,google/gemma-4-26b-a4b-it:free
SYSTEM_PROMPT=You are a helpful chatbot. Reply clearly and concisely.
MAX_HISTORY=20
CHATBOT_DB=chatbot.db
AUTO_REPLY_CHANNELS=123456789012345678,234567890123456789
AUTO_REPLY_DMS=true
DM_DELETE_SECONDS=30
```

## Notes

- History is stored in a local SQLite database file
- The fallback model list is tried in order until one succeeds
- For auto-reply channels, enable Message Content Intent in the Discord Developer Portal
