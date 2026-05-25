import asyncio
import os
import sqlite3
import threading
import time
from typing import List, Dict, Optional, Tuple

import requests
from dotenv import load_dotenv
import discord
from discord import app_commands
from discord.ext import commands

load_dotenv()

DB_PATH = os.getenv("CHATBOT_DB", "chatbot.db")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
MODELS = [
    model.strip()
    for model in os.getenv("MODELS", "openrouter/auto").split(",")
    if model.strip()
]
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "You are a helpful chatbot. Reply clearly and concisely.",
)
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "20"))
AUTO_REPLY_CHANNELS = set()

if not OPENROUTER_API_KEY:
    raise RuntimeError("OPENROUTER_API_KEY is not set.")

intents = discord.Intents.all()

bot = commands.Bot(command_prefix="!", intents=intents)

_db_lock = threading.Lock()
_db_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_db_conn.execute("PRAGMA journal_mode=WAL;")


def parse_channel_ids(raw: str) -> set[int]:
    channel_ids = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            channel_ids.add(int(part))
        except ValueError:
            continue
    return channel_ids


AUTO_REPLY_CHANNELS = parse_channel_ids(os.getenv("AUTO_REPLY_CHANNELS", ""))
AUTO_REPLY_DMS = os.getenv("AUTO_REPLY_DMS", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DM_DELETE_SECONDS = int(os.getenv("DM_DELETE_SECONDS", "30"))


async def delete_later(message: discord.Message, delay_seconds: int) -> None:
    if delay_seconds <= 0:
        return
    await asyncio.sleep(delay_seconds)
    try:
        await message.delete()
    except (discord.NotFound, discord.Forbidden):
        return


def init_db() -> None:
    with _db_lock:
        _db_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            """
        )
        _db_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                ts INTEGER NOT NULL
            );
            """
        )
        _db_conn.commit()


def upsert_user(user: discord.User) -> None:
    with _db_lock:
        _db_conn.execute(
            """
            INSERT INTO users (user_id, username, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username=excluded.username;
            """,
            (str(user.id), user.name, int(time.time())),
        )
        _db_conn.commit()


def save_message(user_id: str, role: str, content: str) -> None:
    with _db_lock:
        _db_conn.execute(
            """
            INSERT INTO messages (user_id, role, content, ts)
            VALUES (?, ?, ?, ?);
            """,
            (user_id, role, content, int(time.time())),
        )
        _db_conn.commit()


def load_history(user_id: str, limit: int) -> List[Dict[str, str]]:
    with _db_lock:
        cursor = _db_conn.execute(
            """
            SELECT role, content
            FROM messages
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?;
            """,
            (user_id, limit),
        )
        rows = cursor.fetchall()

    rows.reverse()
    return [{"role": r[0], "content": r[1]} for r in rows]


def clear_history(user_id: str) -> None:
    with _db_lock:
        _db_conn.execute(
            "DELETE FROM messages WHERE user_id = ?;",
            (user_id,),
        )
        _db_conn.commit()


def _openrouter_request(messages: List[Dict[str, str]], model: str) -> Tuple[int, Dict]:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
    }
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=30,
    )
    return response.status_code, response.json()


def _extract_reply(data: Dict) -> Optional[str]:
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        return None


def call_openrouter(messages: List[Dict[str, str]]) -> str:
    for model in MODELS:
        status, data = _openrouter_request(messages, model)
        reply = _extract_reply(data)
        if status < 400 and reply:
            return reply

    return "There was a problem contacting the AI. Please try again later."


@bot.event
async def on_ready() -> None:
    init_db()
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return

    if message.guild is None:
        if not AUTO_REPLY_DMS:
            return
    else:
        if not AUTO_REPLY_CHANNELS:
            return
        if message.channel.id not in AUTO_REPLY_CHANNELS:
            return

    content = message.content.strip()
    if not content:
        return

    upsert_user(message.author)
    save_message(str(message.author.id), "user", content)

    history = load_history(str(message.author.id), MAX_HISTORY)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    async with message.channel.typing():
        reply = await asyncio.to_thread(call_openrouter, messages)
        save_message(str(message.author.id), "assistant", reply)

    sent_message = await message.channel.send(reply)
    if message.guild is None:
        await delete_later(sent_message, DM_DELETE_SECONDS)


@bot.tree.command(name="chat", description="Chat with the bot")
@app_commands.describe(prompt="Your message")
async def chat_command(interaction: discord.Interaction, prompt: str) -> None:
    await interaction.response.defer(thinking=True)

    upsert_user(interaction.user)
    save_message(str(interaction.user.id), "user", prompt)

    history = load_history(str(interaction.user.id), MAX_HISTORY)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    reply = await asyncio.to_thread(call_openrouter, messages)
    save_message(str(interaction.user.id), "assistant", reply)

    await interaction.followup.send(reply)


@bot.tree.command(name="reset", description="Clear your chat history with the bot")
async def reset_command(interaction: discord.Interaction) -> None:
    user = interaction.user
    upsert_user(user)
    clear_history(str(user.id))
    await interaction.response.send_message(
        "Your history has been cleared.",
        ephemeral=True,
    )


def main() -> None:
    token = os.getenv("DISCORD_TOKEN", "")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is not set.")
    bot.run(token)


if __name__ == "__main__":
    main()
