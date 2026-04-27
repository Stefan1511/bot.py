import asyncio
import random
import sqlite3
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
import os

logging.basicConfig(level=logging.INFO)

bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()

# ================= DB =================

conn = sqlite3.connect("game.db")
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    rating INTEGER DEFAULT 1000,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0
)
""")
conn.commit()


def get_user(uid, name):
    cur.execute("SELECT * FROM users WHERE user_id=?", (uid,))
    user = cur.fetchone()

    if not user:
        cur.execute("INSERT INTO users (user_id, name) VALUES (?,?)", (uid, name))
        conn.commit()
        cur.execute("SELECT * FROM users WHERE user_id=?", (uid,))
        user = cur.fetchone()

    return user


def update_rating(winners, losers):
    for uid in winners:
        cur.execute("UPDATE users SET rating = rating + 10, wins = wins + 1 WHERE user_id=?", (uid,))
    for uid in losers:
        cur.execute("UPDATE users SET rating = rating - 5, losses = losses + 1 WHERE user_id=?", (uid,))
    conn.commit()


# ================= GAME =================

class Game:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.players = {}
        self.night = False
        self.victim = None
        self.saved = None
        self.votes = {}

    def alive(self):
        return {uid: p for uid, p in self.players.items() if p["alive"]}

    def clear(self):
        self.victim = None
        self.saved = None
        self.votes = {}


games = {}

ROLES = ["killer", "doctor", "sheriff", "civilian"]


def get_game(chat_id):
    if chat_id not in games:
        games[chat_id] = Game(chat_id)
    return games[chat_id]


# ================= UI =================

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Новая игра", callback_data="newgame")],
        [InlineKeyboardButton(text="📊 Профиль", callback_data="profile")]
    ])


def join_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚪 Войти", callback_data="join")]
    ])


def role_kb(role):
    buttons = []

    if role == "killer":
        buttons.append([InlineKeyboardButton(text="🔪 Убить", callback_data="kill_menu")])
    if role == "doctor":
        buttons.append([InlineKeyboardButton(text="🛡 Спасти", callback_data="save_menu")])

    return InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None


def target_kb(action, game, uid):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=p["name"], callback_data=f"{action}:{id}")]
        for id, p in game.alive().items() if id != uid
    ])


# ================= START =================

@dp.message(Command("start"))
async def start(msg: Message):
    await msg.answer("🪚 *Техасская резня*", reply_markup=main_menu(), parse_mode="Markdown")


@dp.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):
    user = get_user(call.from_user.id, call.from_user.full_name)

    await call.message.answer(
        f"📊 *Профиль*\n\n👤 {user[1]}\n🏆 {user[2]}",
        parse_mode="Markdown"
    )


# ================= GAME =================

@dp.callback_query(F.data == "newgame")
async def newgame(call: CallbackQuery):
    game = get_game(call.message.chat.id)
    game.players = {}

    await call.message.answer("🏚 Игра создана!", reply_markup=join_kb())

    asyncio.create_task(start_game(game))


@dp.callback_query(F.data == "join")
async def join(call: CallbackQuery):
    game = get_game(call.message.chat.id)

    game.players[call.from_user.id] = {
        "name": call.from_user.full_name,
        "role": None,
        "alive": True
    }

    get_user(call.from_user.id, call.from_user.full_name)

    await call.answer("Ты вошёл")


# ================= START GAME =================

async def start_game(game):
    await asyncio.sleep(10)

    players = list(game.players.keys())
    random.shuffle(players)

    for i, uid in enumerate(players):
        role = ROLES[i % len(ROLES)]
        game.players[uid]["role"] = role

        await bot.send_message(uid, f"🎭 Твоя роль: {role}", reply_markup=role_kb(role))

    game.night = True
    await bot.send_message(game.chat_id, "🌑 Ночь")
    asyncio.create_task(night_phase(game))


# ================= ACTIONS =================

@dp.callback_query(F.data.endswith("_menu"))
async def open_menu(call: CallbackQuery):
    game = get_game(call.message.chat.id)
    action = call.data.replace("_menu", "")

    await call.message.answer("Выбери цель:", reply_markup=target_kb(action, game, call.from_user.id))


@dp.callback_query(F.data.startswith("kill:"))
async def kill(call: CallbackQuery):
    game = get_game(call.message.chat.id)
    game.victim = int(call.data.split(":")[1])
    await call.answer("Выбран")


@dp.callback_query(F.data.startswith("save:"))
async def save(call: CallbackQuery):
    game = get_game(call.message.chat.id)
    game.saved = int(call.data.split(":")[1])
    await call.answer("Спасён")


# ================= NIGHT =================

async def night_phase(game):
    await asyncio.sleep(10)

    if game.victim and game.victim != game.saved:
        game.players[game.victim]["alive"] = False
        await bot.send_message(game.chat_id, f"💀 Убит: {game.players[game.victim]['name']}")
    else:
        await bot.send_message(game.chat_id, "😶 Никто не умер")

    game.night = False
    asyncio.create_task(day_phase(game))


# ================= DAY =================

async def day_phase(game):
    await bot.send_message(game.chat_id, "☀️ День")

    await asyncio.sleep(10)

    game.clear()
    game.night = True

    await bot.send_message(game.chat_id, "🌑 Ночь снова")
    asyncio.create_task(night_phase(game))


# ================= RUN =================

async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
