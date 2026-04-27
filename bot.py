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
    return cur.fetchone()

def update_rating(winners, losers):
    for uid in winners:
        cur.execute("UPDATE users SET rating = rating + 10, wins = wins + 1 WHERE user_id=?", (uid,))
    for uid in losers:
        cur.execute("UPDATE users SET rating = rating - 5, losses = losses + 1 WHERE user_id=?", (uid,))
    conn.commit()

# ================= GAME =================

class Game:
    def __init__(self):
        self.players = {}
        self.active = False
        self.chat_id = None
        self.night = False
        self.victim = None
        self.saved = None
        self.trapped = None
        self.checked = None
        self.votes = {}

    def alive(self):
        return {uid: p for uid, p in self.players.items() if p["alive"]}

    def reset(self):
        self.__init__()

game = Game()

ROLES = ["killer", "sheriff", "doctor", "hitchhiker", "cook", "civilian"]

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
    if role == "sheriff":
        buttons.append([InlineKeyboardButton(text="🚨 Арест", callback_data="arrest_menu")])
    if role == "hitchhiker":
        buttons.append([InlineKeyboardButton(text="🪤 Ловушка", callback_data="trap_menu")])
    if role == "cook":
        buttons.append([InlineKeyboardButton(text="🍖 Проверить", callback_data="check_menu")])

    return InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None

def target_kb(action):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=p["name"], callback_data=f"{action}:{uid}")]
        for uid, p in game.alive().items()
    ])

# ================= START =================

@dp.message(Command("start"))
async def start(msg: Message):
    await msg.answer("🪚 *Техасская резня*", reply_markup=main_menu(), parse_mode="Markdown")

# ================= PROFILE =================

@dp.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):
    user = get_user(call.from_user.id, call.from_user.full_name)

    text = (
        f"📊 *Профиль*\n\n"
        f"👤 {user[1]}\n"
        f"🏆 Рейтинг: {user[2]}\n"
        f"✅ Победы: {user[3]}\n"
        f"❌ Поражения: {user[4]}"
    )

    await call.message.answer(text, parse_mode="Markdown")

# ================= GAME =================

@dp.callback_query(F.data == "newgame")
async def newgame(call: CallbackQuery):
    game.reset()
    game.active = True
    game.chat_id = call.message.chat.id

    await call.message.answer("🏚 *Игра началась!*\nЖми кнопку:", reply_markup=join_kb(), parse_mode="Markdown")

    asyncio.create_task(auto_start())

@dp.callback_query(F.data == "join")
async def join(call: CallbackQuery):
    uid = call.from_user.id

    game.players[uid] = {
        "name": call.from_user.full_name,
        "role": None,
        "alive": True,
        "team": None
    }

    get_user(uid, call.from_user.full_name)

    await call.answer("Ты в игре")

# ================= START GAME =================

async def auto_start():
    await asyncio.sleep(15)
    await start_game()

async def start_game():
    roles = ROLES.copy()
    random.shuffle(roles)

    for i, uid in enumerate(game.players):
        role = roles[i]
        game.players[uid]["role"] = role
        game.players[uid]["team"] = "evil" if role in ["killer", "hitchhiker", "cook"] else "good"

        await bot.send_message(uid, f"🎭 *Роль:* {role}", reply_markup=role_kb(role), parse_mode="Markdown")

    await notify_family()

    game.night = True
    await bot.send_message(game.chat_id, "🌑 *Ночь началась...*", parse_mode="Markdown")
    asyncio.create_task(night_phase())

# ================= FAMILY =================

async def notify_family():
    family = [p for p in game.players.values() if p["team"] == "evil"]

    text = "\n".join([f"🔪 {p['name']}" for p in family])

    for uid, p in game.players.items():
        if p["team"] == "evil":
            await bot.send_message(uid, f"👥 *Семья:*\n{text}", parse_mode="Markdown")

# ================= ACTIONS =================

@dp.callback_query(F.data.endswith("_menu"))
async def open_menu(call: CallbackQuery):
    action = call.data.replace("_menu", "")
    await call.message.answer("Выбери цель:", reply_markup=target_kb(action))

@dp.callback_query(F.data.startswith("kill:"))
async def kill(call: CallbackQuery):
    game.victim = int(call.data.split(":")[1])
    await call.answer("Цель выбрана")

@dp.callback_query(F.data.startswith("save:"))
async def save(call: CallbackQuery):
    game.saved = int(call.data.split(":")[1])
    await call.answer("Спасён")

@dp.callback_query(F.data.startswith("trap:"))
async def trap(call: CallbackQuery):
    game.trapped = int(call.data.split(":")[1])
    await call.answer("В ловушке")

@dp.callback_query(F.data.startswith("check:"))
async def check(call: CallbackQuery):
    uid = int(call.data.split(":")[1])
    role = game.players[uid]["role"]
    await call.message.answer(f"🍖 Его роль: *{role}*", parse_mode="Markdown")

# ================= NIGHT =================

async def night_phase():
    await asyncio.sleep(15)

    if game.victim and game.victim != game.saved:
        game.players[game.victim]["alive"] = False
        await bot.send_message(game.chat_id, f"💀 Убит: {game.players[game.victim]['name']}")
    else:
        await bot.send_message(game.chat_id, "😶 Никто не умер")

    game.night = False
    await start_day()

# ================= DAY =================

async def start_day():
    await bot.send_message(game.chat_id, "☀️ *День. Голосуйте!*", reply_markup=target_kb("vote"), parse_mode="Markdown")
    asyncio.create_task(day_phase())

@dp.callback_query(F.data.startswith("vote:"))
async def vote(call: CallbackQuery):
    uid = int(call.data.split(":")[1])
    game.votes[uid] = game.votes.get(uid, 0) + 1
    await call.answer("Голос принят")

async def day_phase():
    await asyncio.sleep(15)

    if game.votes:
        target = max(game.votes, key=game.votes.get)
        game.players[target]["alive"] = False
        await bot.send_message(game.chat_id, f"☠️ Казнён: {game.players[target]['name']}")

    game.votes = {}

    if check_win():
        return

    game.night = True
    await bot.send_message(game.chat_id, "🌑 Новая ночь")
    asyncio.create_task(night_phase())

# ================= WIN =================

def check_win():
    alive = game.alive()
    killers = [p for p in alive.values() if p["team"] == "evil"]

    if not killers:
        winners = [uid for uid, p in game.players.items() if p["team"] == "good"]
        losers = [uid for uid, p in game.players.items() if p["team"] == "evil"]

        update_rating(winners, losers)
        asyncio.create_task(bot.send_message(game.chat_id, "🏆 Мирные победили"))
        return True

    if len(killers) >= len(alive) - len(killers):
        winners = [uid for uid, p in game.players.items() if p["team"] == "evil"]
        losers = [uid for uid, p in game.players.items() if p["team"] == "good"]

        update_rating(winners, losers)
        asyncio.create_task(bot.send_message(game.chat_id, "💀 Маньяки победили"))
        return True

    return False

# ================= RUN =================

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
