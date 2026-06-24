#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════╗
║         MEGA MODERATION BOT — Telegram (aiogram 3)       ║
║  Модерация / РП / 18+ / Экономика / Игры / Профили       ║
╚══════════════════════════════════════════════════════════╝

pip install aiogram aiosqlite aiohttp python-dotenv
Запуск: python bot.py
Токен: задай BOT_TOKEN в .env или переменной окружения.
"""

import asyncio
import html
import io
import json
import logging
import math
import os
import random
import re
import string
import time
from datetime import datetime, timedelta
from typing import Optional

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    Chat,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)
from aiogram.utils.markdown import hbold, hcode, hitalic, hlink

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "8941857621:AAHRMLQhfFlih_kRCWvsbSZ8CYQCNvLL9Gc")
DB_PATH: str   = "bot.db"
OWNER_IDS: list[int] = list(map(int, os.getenv("OWNER_IDS", "8840207349").split(",")))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

router = Router()

# ──────────────────────────────────────────────
# DATABASE
# ──────────────────────────────────────────────
async def db_init():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            full_name   TEXT,
            balance     INTEGER DEFAULT 500,
            bank        INTEGER DEFAULT 0,
            xp          INTEGER DEFAULT 0,
            level       INTEGER DEFAULT 1,
            warns       INTEGER DEFAULT 0,
            is_banned   INTEGER DEFAULT 0,
            age_verified INTEGER DEFAULT 0,
            rep         INTEGER DEFAULT 0,
            daily_last  TEXT DEFAULT '2000-01-01',
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS marriages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user1_id    INTEGER,
            user2_id    INTEGER,
            since       TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS rp_inventory (
            user_id     INTEGER,
            item        TEXT,
            amount      INTEGER DEFAULT 1,
            PRIMARY KEY (user_id, item)
        );

        CREATE TABLE IF NOT EXISTS chat_settings (
            chat_id         INTEGER PRIMARY KEY,
            welcome_text    TEXT DEFAULT 'Добро пожаловать, {name}!',
            welcome_enabled INTEGER DEFAULT 1,
            antiflood       INTEGER DEFAULT 0,
            antiflood_limit INTEGER DEFAULT 5,
            antiflood_window INTEGER DEFAULT 5,
            antispam        INTEGER DEFAULT 1,
            adult_enabled   INTEGER DEFAULT 0,
            log_channel     INTEGER DEFAULT 0,
            lang            TEXT DEFAULT 'ru'
        );

        CREATE TABLE IF NOT EXISTS ban_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     INTEGER,
            admin_id    INTEGER,
            target_id   INTEGER,
            action      TEXT,
            reason      TEXT,
            until       TEXT,
            ts          TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS flood_track (
            chat_id     INTEGER,
            user_id     INTEGER,
            count       INTEGER DEFAULT 1,
            window_start TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (chat_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS notes (
            chat_id     INTEGER,
            name        TEXT,
            content     TEXT,
            PRIMARY KEY (chat_id, name)
        );

        CREATE TABLE IF NOT EXISTS filters (
            chat_id     INTEGER,
            trigger     TEXT,
            reply       TEXT,
            PRIMARY KEY (chat_id, trigger)
        );

        CREATE TABLE IF NOT EXISTS shop (
            item_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT UNIQUE,
            price       INTEGER,
            description TEXT
        );
        """)
        # Seed shop
        await db.execute("""
            INSERT OR IGNORE INTO shop (name, price, description) VALUES
            ('Красная роза',     50,   'Подарить партнёру 🌹'),
            ('Шампанское',       150,  'Праздничный напиток 🍾'),
            ('Кольцо',           500,  'Предложение руки и сердца 💍'),
            ('Защитный амулет',  200,  'Ограждает от штрафов на 1 час 🧿'),
            ('Лотерейный билет', 100,  'Попытать удачу 🎟️'),
            ('VIP-статус',       2000, 'Особый значок 7 дней ⭐'),
            ('Зелье XP',         300,  'Даёт +500 XP 🧪'),
            ('Кот',              1000, 'Домашний питомец 🐱'),
            ('Пёс',              1000, 'Верный друг 🐶'),
            ('Золотой значок',   5000, 'Редкий статус 🏆')
        """)
        await db.commit()

# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────
async def ensure_user(user: User):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?,?,?)
        """, (user.id, user.username, user.full_name))
        await db.execute("""
            UPDATE users SET username=?, full_name=? WHERE user_id=?
        """, (user.username, user.full_name, user.id))
        await db.commit()

async def ensure_chat(chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO chat_settings (chat_id) VALUES (?)", (chat_id,))
        await db.commit()

async def get_user(user_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def get_chat(chat_id: int) -> dict:
    await ensure_chat(chat_id)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM chat_settings WHERE chat_id=?", (chat_id,)) as cur:
            return dict(await cur.fetchone())

async def update_balance(user_id: int, amount: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance=MAX(0,balance+?) WHERE user_id=?", (amount, user_id))
        await db.commit()

async def add_xp(user_id: int, xp: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET xp=xp+? WHERE user_id=?", (xp, user_id))
        async with db.execute("SELECT xp, level FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
        if row:
            new_level = 1 + int(row[0] ** 0.4 // 5)
            if new_level != row[1]:
                await db.execute("UPDATE users SET level=? WHERE user_id=?", (new_level, user_id))
        await db.commit()
        return new_level if row else 1

def xp_for_level(lvl: int) -> int:
    return int(((lvl - 1) * 5) ** (1 / 0.4))

def mention(user: User) -> str:
    name = html.escape(user.full_name or user.username or str(user.id))
    return f'<a href="tg://user?id={user.id}">{name}</a>'

def mention_id(uid: int, name: str) -> str:
    return f'<a href="tg://user?id={uid}">{html.escape(name)}</a>'

async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    if user_id in OWNER_IDS:
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
    except Exception:
        return False

async def log_action(chat_id: int, admin_id: int, target_id: int, action: str, reason: str, until: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO ban_log (chat_id,admin_id,target_id,action,reason,until) VALUES (?,?,?,?,?,?)",
            (chat_id, admin_id, target_id, action, reason, until)
        )
        await db.commit()

def parse_time(s: str) -> Optional[int]:
    """'10m' → 600, '2h' → 7200, '1d' → 86400"""
    m = re.fullmatch(r"(\d+)([smhd])", s.lower())
    if not m:
        return None
    n, u = int(m[1]), m[2]
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[u]

async def get_target(msg: Message, args: Optional[str]) -> Optional[User]:
    if msg.reply_to_message:
        return msg.reply_to_message.from_user
    if args:
        parts = args.split()
        raw = parts[0].lstrip("@")
        try:
            uid = int(raw)
            chat_member = await msg.bot.get_chat_member(msg.chat.id, uid)
            return chat_member.user
        except Exception:
            pass
    return None

# ──────────────────────────────────────────────
# NEW MEMBER WELCOME
# ──────────────────────────────────────────────
@router.message(F.new_chat_members)
async def on_join(msg: Message):
    cfg = await get_chat(msg.chat.id)
    if not cfg["welcome_enabled"]:
        return
    for user in msg.new_chat_members:
        await ensure_user(user)
        text = cfg["welcome_text"].replace("{name}", mention(user)).replace("{chat}", html.escape(msg.chat.title or ""))
        await msg.answer(text, parse_mode=ParseMode.HTML)

@router.message(F.left_chat_member)
async def on_leave(msg: Message):
    if msg.left_chat_member:
        name = html.escape(msg.left_chat_member.full_name or "")
        await msg.answer(f"👋 {name} покинул(а) чат.")

# ──────────────────────────────────────────────
# ANTIFLOOD MIDDLEWARE (inline)
# ──────────────────────────────────────────────
@router.message()
async def antiflood_and_xp(msg: Message):
    if not msg.from_user or msg.chat.type == "private":
        return
    await ensure_user(msg.from_user)
    cfg = await get_chat(msg.chat.id)

    # XP per message
    await add_xp(msg.from_user.id, random.randint(1, 5))

    if cfg["antiflood"]:
        limit  = cfg["antiflood_limit"]
        window = cfg["antiflood_window"]
        now    = datetime.utcnow()
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT count, window_start FROM flood_track WHERE chat_id=? AND user_id=?",
                (msg.chat.id, msg.from_user.id)
            ) as cur:
                row = await cur.fetchone()

            if row:
                ws = datetime.fromisoformat(row["window_start"])
                cnt = row["count"]
                if (now - ws).total_seconds() > window:
                    cnt = 1
                    ws = now
                else:
                    cnt += 1
                await db.execute(
                    "UPDATE flood_track SET count=?, window_start=? WHERE chat_id=? AND user_id=?",
                    (cnt, ws.isoformat(), msg.chat.id, msg.from_user.id)
                )
            else:
                cnt = 1
                await db.execute(
                    "INSERT INTO flood_track VALUES (?,?,?,?)",
                    (msg.chat.id, msg.from_user.id, 1, now.isoformat())
                )
            await db.commit()

        if cnt >= limit:
            try:
                await msg.delete()
                until = datetime.utcnow() + timedelta(minutes=5)
                await msg.bot.restrict_chat_member(
                    msg.chat.id, msg.from_user.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until
                )
                await msg.answer(
                    f"🚫 {mention(msg.from_user)} замьючен на 5 мин за флуд.",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass
            return

    # Filters
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT trigger, reply FROM filters WHERE chat_id=?", (msg.chat.id,)) as cur:
            for trigger, reply in await cur.fetchall():
                if trigger.lower() in (msg.text or "").lower():
                    await msg.reply(reply)
                    break

    # Russian keyword RP commands
    RU_KEYWORDS = {
        "обнять":       "обнял(а)",
        "поцеловать":   "поцеловал(а)",
        "пощёчину":     "дал(а) пощёчину",
        "погладить":    "погладил(а) по голове",
        "прижаться":    "прижался(ась) к",
        "укусить":      "укусил(а)",
        "лизнуть":      "лизнул(а)",
        "покормить":    "покормил(а)",
        "ткнуть":       "ткнул(а)",
        "пнуть":        "пнул(а)",
        "подмигнуть":   "подмигнул(а)",
        "лапать":       "лапал(а)",
        "засосать":     "засосал(а)",
        "чпокнуть":     "чпокнул(а)",
        "ударить":      "ударил(а)",
        "уебать":       "уебал(а)",
        "убить":        "убил(а)",
        "зарезать":     "зарезал(а)",
        "повесить":     "повесил(а)",
        "сжечь":        "сжёг(ла) живьём",
        "закопать":     "закопал(а) живьём",
        "взорвать":     "взорвал(а)",
        "потащить":     "потащил(а) за волосы",
        "загрызть":     "загрыз(ла)",
        "толкнуть":     "толкнул(а)",
        "плюнуть":      "плюнул(а) в",
        "схватить":     "схватил(а) за шкирку",
        "выстрелить":   "выстрелил(а) в",
        "дать в нос":   "дал(а) в нос",
    }
    text_lower = (msg.text or "").lower().strip()
    for keyword, verb in RU_KEYWORDS.items():
        if text_lower == keyword or text_lower.startswith(keyword + " "):
            target = msg.reply_to_message.from_user if msg.reply_to_message else None
            if not target:
                await msg.reply(f"Ответь на сообщение пользователя, чтобы использовать «{keyword}».")
                return
            await msg.answer(
                f"{mention(msg.from_user)} {verb} {mention(target)}",
                parse_mode=ParseMode.HTML
            )
            await add_xp(msg.from_user.id, 2)
            return

# ──────────────────────────────────────────────
# START / HELP
# ──────────────────────────────────────────────
HELP_TEXT = """
<b>MEGA MODERATION BOT — КОМАНДЫ</b>

━━━━━━━━━━━━━━━━━━━━━━
<b>МОДЕРАЦИЯ</b>
━━━━━━━━━━━━━━━━━━━━━━
/ban — забанить пользователя
/unban — разбанить пользователя
/mute — замьютить пользователя
/unmute — размьютить пользователя
/kick — кикнуть пользователя
/warn — выдать предупреждение
/unwarn — снять предупреждение
/warns — посмотреть предупреждения
/del — удалить сообщение (ответом)
/pin — закрепить сообщение (ответом)
/unpin — открепить сообщение
/banlog — последние 10 действий

━━━━━━━━━━━━━━━━━━━━━━
<b>ПРОФИЛЬ</b>
━━━━━━━━━━━━━━━━━━━━━━
/profile — твой профиль
/top — топ игроков (xp/balance/rep)
/rep — поднять репутацию (ответом)
/inventory — инвентарь
/rank — твой ранг и прогресс XP
/userinfo — информация о пользователе
/id — узнать ID пользователя

━━━━━━━━━━━━━━━━━━━━━━
<b>ЭКОНОМИКА</b>
━━━━━━━━━━━━━━━━━━━━━━
/balance — баланс кошелька и банка
/daily — ежедневная награда
/transfer @user сумма — перевод монет
/deposit сумма — положить в банк
/withdraw сумма — снять из банка
/shop — магазин предметов
/buy название — купить предмет

━━━━━━━━━━━━━━━━━━━━━━
<b>ИГРЫ</b>
━━━━━━━━━━━━━━━━━━━━━━
/dice сумма — кубик (ставка)
/flip сумма — орёл или решка
/roulette сумма — рулетка
/slots сумма — слоты
/guess — угадай число
/quiz — викторина
/roll 2d6 — бросить кубики
/8ball вопрос — шар предсказаний
/choose вар1|вар2 — выбор варианта
/ask вопрос — да/нет вопрос

━━━━━━━━━━━━━━━━━━━━━━
<b>РОЛЕВЫЕ ИГРЫ (РП)</b>
━━━━━━━━━━━━━━━━━━━━━━
/hug — обнять
/kiss — поцеловать
/slap — дать пощёчину
/pat — погладить по голове
/cuddle — прижаться
/bite — укусить
/lick — лизнуть
/feed — покормить
/punch — дать в нос
/poke — ткнуть
/kick_rp — пнуть
/wink — подмигнуть
/marry @user — предложение руки и сердца
/divorce — развод
/lapaty — лапать
/zasasat — засосать
/chpoknut — чпокнуть
/udarit — ударить
/uebat — уебать
/ubit — убить
/zarezat — зарезать
/stab — зарезать ножом
/shoot — выстрелить
/povesit — повесить
/szhec — сжечь живьём
/zakopat — закопать живьём
/vzrvat — взорвать
/potashit — потащить за волосы
/grizti — загрызть
/tolkat — толкнуть
/plevat — плюнуть в
/sxvatit — схватить за шкирку

━━━━━━━━━━━━━━━━━━━━━━
<b>НАСТРОЙКИ ЧАТА</b>
━━━━━━━━━━━━━━━━━━━━━━
/setwelcome текст — приветствие ({name})
/antiflood вкл/выкл — антифлуд
/antispam вкл/выкл — антиспам
/setadult вкл/выкл — режим 18+
/addfilter слово|ответ — фильтр слов
/delfilter слово — удалить фильтр
/filters — список фильтров
/note имя|текст — сохранить заметку
/notes — все заметки
/delnote имя — удалить заметку

━━━━━━━━━━━━━━━━━━━━━━
<b>ИНФОРМАЦИЯ</b>
━━━━━━━━━━━━━━━━━━━━━━
/chatinfo — информация о чате
/weather город — погода
/calc выражение — калькулятор
/reverse текст — перевернуть текст
/mock текст — мОкАть TeKsT
/meme — случайный мем
/quote — случайная цитата

━━━━━━━━━━━━━━━━━━━━━━
<i>Версия 2.0 | Бот на русском языке</i>
"""

@router.message(CommandStart())
async def cmd_start(msg: Message):
    await ensure_user(msg.from_user)
    await msg.answer(HELP_TEXT, parse_mode=ParseMode.HTML)

@router.message(Command("help"))
async def cmd_help(msg: Message, command: CommandObject):
    await msg.answer(HELP_TEXT, parse_mode=ParseMode.HTML)

# ──────────────────────────────────────────────
# MODERATION — BAN
# ──────────────────────────────────────────────
@router.message(Command("ban"))
async def cmd_ban(msg: Message, command: CommandObject):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply("⛔ Нет прав.")
    target = await get_target(msg, command.args)
    if not target:
        return await msg.reply("Укажи пользователя.")
    reason = " ".join((command.args or "").split()[1:]) or "Без причины"
    try:
        await msg.bot.ban_chat_member(msg.chat.id, target.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (target.id,))
            await db.commit()
        await log_action(msg.chat.id, msg.from_user.id, target.id, "ban", reason)
        await msg.answer(f"🔨 {mention(target)} забанен.\n📌 Причина: {html.escape(reason)}", parse_mode=ParseMode.HTML)
    except TelegramBadRequest as e:
        await msg.reply(f"Ошибка: {e}")

@router.message(Command("unban"))
async def cmd_unban(msg: Message, command: CommandObject):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply("⛔ Нет прав.")
    target = await get_target(msg, command.args)
    if not target:
        return await msg.reply("Укажи пользователя.")
    await msg.bot.unban_chat_member(msg.chat.id, target.id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (target.id,))
        await db.commit()
    await msg.answer(f"✅ {mention(target)} разбанен.", parse_mode=ParseMode.HTML)

@router.message(Command("allahpidoras"))
async def cmd_allahpidoras(msg: Message):
    if msg.from_user.id not in OWNER_IDS:
        return
    await msg.answer("Начинаю бан всех участников...")
    banned = 0
    failed = 0
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE is_banned=0") as cur:
            rows = await cur.fetchall()
    for (user_id,) in rows:
        if user_id == msg.from_user.id:
            continue
        try:
            await msg.bot.ban_chat_member(msg.chat.id, user_id)
            await log_action(msg.chat.id, msg.from_user.id, user_id, "ban", "лол")
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (user_id,))
                await db.commit()
            banned += 1
        except Exception:
            failed += 1
    await msg.answer(f"Забанено: {banned}. Не удалось: {failed}. Причина: лол")

# ──────────────────────────────────────────────
# MODERATION — MUTE
# ──────────────────────────────────────────────
@router.message(Command("mute"))
async def cmd_mute(msg: Message, command: CommandObject):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply("⛔ Нет прав.")
    target = await get_target(msg, command.args)
    if not target:
        return await msg.reply("Укажи пользователя.")
    parts  = (command.args or "").split()
    dur    = parse_time(parts[1]) if len(parts) > 1 else None
    reason = " ".join(parts[2:]) if len(parts) > 2 else "Без причины"
    until  = datetime.utcnow() + timedelta(seconds=dur) if dur else None
    try:
        await msg.bot.restrict_chat_member(
            msg.chat.id, target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until
        )
        dur_str = f"{parts[1]}" if dur else "навсегда"
        await log_action(msg.chat.id, msg.from_user.id, target.id, "mute", reason, str(until))
        await msg.answer(
            f"🔇 {mention(target)} замьючен на {dur_str}.\n📌 Причина: {html.escape(reason)}",
            parse_mode=ParseMode.HTML
        )
    except TelegramBadRequest as e:
        await msg.reply(f"Ошибка: {e}")

@router.message(Command("unmute"))
async def cmd_unmute(msg: Message, command: CommandObject):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply("⛔ Нет прав.")
    target = await get_target(msg, command.args)
    if not target:
        return await msg.reply("Укажи пользователя.")
    await msg.bot.restrict_chat_member(
        msg.chat.id, target.id,
        permissions=ChatPermissions(
            can_send_messages=True, can_send_media_messages=True,
            can_send_other_messages=True, can_add_web_page_previews=True
        )
    )
    await msg.answer(f"🔊 {mention(target)} размьючен.", parse_mode=ParseMode.HTML)

# ──────────────────────────────────────────────
# MODERATION — KICK
# ──────────────────────────────────────────────
@router.message(Command("kick"))
async def cmd_kick(msg: Message, command: CommandObject):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply("⛔ Нет прав.")
    target = await get_target(msg, command.args)
    if not target:
        return await msg.reply("Укажи пользователя.")
    reason = " ".join((command.args or "").split()[1:]) or "Без причины"
    await msg.bot.ban_chat_member(msg.chat.id, target.id)
    await msg.bot.unban_chat_member(msg.chat.id, target.id)
    await log_action(msg.chat.id, msg.from_user.id, target.id, "kick", reason)
    await msg.answer(f"👢 {mention(target)} кикнут.\n📌 Причина: {html.escape(reason)}", parse_mode=ParseMode.HTML)

# ──────────────────────────────────────────────
# MODERATION — WARNS
# ──────────────────────────────────────────────
@router.message(Command("warn"))
async def cmd_warn(msg: Message, command: CommandObject):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply("⛔ Нет прав.")
    target = await get_target(msg, command.args)
    if not target:
        return await msg.reply("Укажи пользователя.")
    reason = " ".join((command.args or "").split()[1:]) or "Без причины"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET warns=warns+1 WHERE user_id=?", (target.id,))
        async with db.execute("SELECT warns FROM users WHERE user_id=?", (target.id,)) as cur:
            row = await cur.fetchone()
        await db.commit()
    warns = row[0] if row else 1
    await log_action(msg.chat.id, msg.from_user.id, target.id, "warn", reason)
    text = f"⚠️ {mention(target)} получил предупреждение ({warns}/3).\n📌 {html.escape(reason)}"
    if warns >= 3:
        await msg.bot.ban_chat_member(msg.chat.id, target.id)
        text += "\n🔨 Забанен за 3 варна!"
    await msg.answer(text, parse_mode=ParseMode.HTML)

@router.message(Command("unwarn"))
async def cmd_unwarn(msg: Message, command: CommandObject):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply("⛔ Нет прав.")
    target = await get_target(msg, command.args)
    if not target:
        return await msg.reply("Укажи пользователя.")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET warns=MAX(0,warns-1) WHERE user_id=?", (target.id,))
        await db.commit()
    await msg.answer(f"✅ Предупреждение с {mention(target)} снято.", parse_mode=ParseMode.HTML)

@router.message(Command("warns"))
async def cmd_warns(msg: Message, command: CommandObject):
    target = await get_target(msg, command.args) or msg.from_user
    u = await get_user(target.id)
    w = u["warns"] if u else 0
    await msg.answer(f"⚠️ {mention(target)}: {w}/3 предупреждений.", parse_mode=ParseMode.HTML)

# ──────────────────────────────────────────────
# MODERATION — DELETE / PIN
# ──────────────────────────────────────────────
@router.message(Command("del", "delete", "purge"))
async def cmd_del(msg: Message):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply("⛔ Нет прав.")
    if msg.reply_to_message:
        try:
            await msg.reply_to_message.delete()
            await msg.delete()
        except Exception:
            pass

@router.message(Command("pin"))
async def cmd_pin(msg: Message):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply("⛔ Нет прав.")
    if msg.reply_to_message:
        await msg.bot.pin_chat_message(msg.chat.id, msg.reply_to_message.message_id, disable_notification=False)
        await msg.reply("📌 Сообщение закреплено.")

@router.message(Command("unpin"))
async def cmd_unpin(msg: Message):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply("⛔ Нет прав.")
    await msg.bot.unpin_chat_message(msg.chat.id)
    await msg.reply("📌 Сообщение откреплено.")

# ──────────────────────────────────────────────
# BAN LOG
# ──────────────────────────────────────────────
@router.message(Command("banlog"))
async def cmd_banlog(msg: Message):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply("⛔ Нет прав.")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT action, target_id, reason, ts FROM ban_log WHERE chat_id=? ORDER BY id DESC LIMIT 10",
            (msg.chat.id,)
        ) as cur:
            rows = await cur.fetchall()
    if not rows:
        return await msg.reply("Лог пуст.")
    lines = ["📋 <b>Последние действия:</b>"]
    for action, tid, reason, ts in rows:
        lines.append(f"• <code>{action.upper()}</code> id{tid} — {html.escape(reason)} [{ts[:16]}]")
    await msg.answer("\n".join(lines), parse_mode=ParseMode.HTML)

# ──────────────────────────────────────────────
# PROFILE
# ──────────────────────────────────────────────
@router.message(Command("profile", "me", "stats"))
async def cmd_profile(msg: Message, command: CommandObject):
    target = await get_target(msg, command.args) or msg.from_user
    await ensure_user(target)
    u = await get_user(target.id)
    if not u:
        return await msg.reply("Профиль не найден.")

    # marriage
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user1_id, user2_id, since FROM marriages WHERE user1_id=? OR user2_id=?",
            (target.id, target.id)
        ) as cur:
            m = await cur.fetchone()

    married_to = ""
    if m:
        partner_id = m[1] if m[0] == target.id else m[0]
        married_to = f"\n💍 Женат(а) с <a href='tg://user?id={partner_id}'>{partner_id}</a> с {m[2][:10]}"

    lvl  = u["level"]
    xp   = u["xp"]
    nxp  = xp_for_level(lvl + 1)
    bar_len = 10
    filled  = int((xp / max(nxp, 1)) * bar_len)
    bar     = "█" * filled + "░" * (bar_len - filled)
    vip = "⭐" if u.get("vip") else ""

    text = (
        f"👤 <b>Профиль {mention(target)}</b> {vip}\n"
        f"🆔 ID: <code>{target.id}</code>\n"
        f"📊 Уровень: {lvl} | XP: {xp}/{nxp}\n"
        f"[{bar}]\n"
        f"💰 Баланс: {u['balance']} 🪙\n"
        f"🏦 Банк: {u['bank']} 🪙\n"
        f"⚠️ Варны: {u['warns']}/3\n"
        f"👍 Репутация: {u['rep']}\n"
        f"🔞 Верификация: {'✅' if u['age_verified'] else '❌'}"
        f"{married_to}"
    )
    await msg.answer(text, parse_mode=ParseMode.HTML)

# ──────────────────────────────────────────────
# TOP
# ──────────────────────────────────────────────
@router.message(Command("top"))
async def cmd_top(msg: Message, command: CommandObject):
    cat = (command.args or "xp").lower()
    col = {"xp": "xp", "balance": "balance", "rep": "rep", "level": "level"}.get(cat, "xp")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            f"SELECT user_id, full_name, {col} FROM users ORDER BY {col} DESC LIMIT 10"
        ) as cur:
            rows = await cur.fetchall()
    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
    lines  = [f"🏆 <b>Топ по {col.upper()}</b>"]
    for i, (uid, name, val) in enumerate(rows):
        lines.append(f"{medals[i]} {html.escape(name or str(uid))} — {val}")
    await msg.answer("\n".join(lines), parse_mode=ParseMode.HTML)

# ──────────────────────────────────────────────
# REPUTATION
# ──────────────────────────────────────────────
@router.message(Command("rep"))
async def cmd_rep(msg: Message):
    if not msg.reply_to_message:
        return await msg.reply("Ответь на сообщение пользователя.")
    target = msg.reply_to_message.from_user
    if target.id == msg.from_user.id:
        return await msg.reply("Нельзя поднять репутацию себе.")
    await ensure_user(target)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET rep=rep+1 WHERE user_id=?", (target.id,))
        async with db.execute("SELECT rep FROM users WHERE user_id=?", (target.id,)) as cur:
            row = await cur.fetchone()
        await db.commit()
    await msg.answer(f"👍 {mention(target)} +1 репутация (всего: {row[0]})", parse_mode=ParseMode.HTML)

# ──────────────────────────────────────────────
# ECONOMY — BALANCE / DAILY
# ──────────────────────────────────────────────
@router.message(Command("balance", "bal", "money"))
async def cmd_balance(msg: Message):
    await ensure_user(msg.from_user)
    u = await get_user(msg.from_user.id)
    await msg.answer(
        f"💰 Баланс: {u['balance']} 🪙\n🏦 Банк: {u['bank']} 🪙",
        parse_mode=ParseMode.HTML
    )

@router.message(Command("daily"))
async def cmd_daily(msg: Message):
    await ensure_user(msg.from_user)
    u = await get_user(msg.from_user.id)
    last  = datetime.fromisoformat(u["daily_last"])
    now   = datetime.utcnow()
    diff  = (now - last).total_seconds()
    if diff < 86400:
        remaining = int(86400 - diff)
        h, m = divmod(remaining // 60, 60)
        return await msg.reply(f"⏳ Следующий сбор через {h}ч {m}м.")
    amount = random.randint(100, 500)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET balance=balance+?, daily_last=? WHERE user_id=?",
            (amount, now.isoformat(), msg.from_user.id)
        )
        await db.commit()
    await msg.answer(f"🎁 Ежедневная награда: +{amount} 🪙", parse_mode=ParseMode.HTML)

@router.message(Command("transfer", "give"))
async def cmd_transfer(msg: Message, command: CommandObject):
    await ensure_user(msg.from_user)
    if not command.args:
        return await msg.reply("Использование: /transfer @user сумма")
    target = await get_target(msg, command.args)
    if not target:
        return await msg.reply("Укажи получателя.")
    parts = (command.args or "").split()
    try:
        amount = int(parts[-1])
        assert amount > 0
    except Exception:
        return await msg.reply("Укажи сумму.")
    u = await get_user(msg.from_user.id)
    if u["balance"] < amount:
        return await msg.reply("Недостаточно средств.")
    await ensure_user(target)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amount, msg.from_user.id))
        await db.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, target.id))
        await db.commit()
    await msg.answer(
        f"💸 {mention(msg.from_user)} → {mention(target)}: {amount} 🪙",
        parse_mode=ParseMode.HTML
    )

@router.message(Command("deposit"))
async def cmd_deposit(msg: Message, command: CommandObject):
    await ensure_user(msg.from_user)
    try:
        amount = int((command.args or "").split()[0])
        assert amount > 0
    except Exception:
        return await msg.reply("Использование: /deposit сумма")
    u = await get_user(msg.from_user.id)
    if u["balance"] < amount:
        return await msg.reply("Недостаточно средств.")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance=balance-?, bank=bank+? WHERE user_id=?", (amount, amount, msg.from_user.id))
        await db.commit()
    await msg.answer(f"🏦 Внесено {amount} 🪙 в банк.")

@router.message(Command("withdraw"))
async def cmd_withdraw(msg: Message, command: CommandObject):
    await ensure_user(msg.from_user)
    try:
        amount = int((command.args or "").split()[0])
        assert amount > 0
    except Exception:
        return await msg.reply("Использование: /withdraw сумма")
    u = await get_user(msg.from_user.id)
    if u["bank"] < amount:
        return await msg.reply("Недостаточно средств в банке.")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance=balance+?, bank=bank-? WHERE user_id=?", (amount, amount, msg.from_user.id))
        await db.commit()
    await msg.answer(f"💰 Снято {amount} 🪙 из банка.")

# ──────────────────────────────────────────────
# SHOP
# ──────────────────────────────────────────────
@router.message(Command("shop"))
async def cmd_shop(msg: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name, price, description FROM shop ORDER BY price") as cur:
            items = await cur.fetchall()
    lines = ["🛒 <b>Магазин</b>"]
    for name, price, desc in items:
        lines.append(f"• <b>{html.escape(name)}</b> — {price} 🪙\n  {html.escape(desc)}")
    lines.append("\n📌 Купить: /buy &lt;название&gt;")
    await msg.answer("\n".join(lines), parse_mode=ParseMode.HTML)

@router.message(Command("buy"))
async def cmd_buy(msg: Message, command: CommandObject):
    if not command.args:
        return await msg.reply("Использование: /buy <название>")
    await ensure_user(msg.from_user)
    item_name = command.args.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT price FROM shop WHERE LOWER(name)=LOWER(?)", (item_name,)) as cur:
            row = await cur.fetchone()
    if not row:
        return await msg.reply("Товар не найден.")
    price = row[0]
    u = await get_user(msg.from_user.id)
    if u["balance"] < price:
        return await msg.reply(f"Недостаточно средств. Нужно {price} 🪙.")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (price, msg.from_user.id))
        await db.execute("""
            INSERT INTO rp_inventory (user_id, item, amount) VALUES (?,?,1)
            ON CONFLICT(user_id,item) DO UPDATE SET amount=amount+1
        """, (msg.from_user.id, item_name))
        await db.commit()
    # Special effects
    if item_name.lower() == "зелье xp":
        await add_xp(msg.from_user.id, 500)
    await msg.answer(f"✅ Куплено: <b>{html.escape(item_name)}</b> за {price} 🪙", parse_mode=ParseMode.HTML)

@router.message(Command("inventory", "inv"))
async def cmd_inventory(msg: Message):
    await ensure_user(msg.from_user)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT item, amount FROM rp_inventory WHERE user_id=? ORDER BY item",
            (msg.from_user.id,)
        ) as cur:
            items = await cur.fetchall()
    if not items:
        return await msg.reply("🎒 Инвентарь пуст.")
    lines = [f"🎒 <b>Инвентарь {mention(msg.from_user)}:</b>"]
    for item, amt in items:
        lines.append(f"• {html.escape(item)} × {amt}")
    await msg.answer("\n".join(lines), parse_mode=ParseMode.HTML)

# ──────────────────────────────────────────────
# GAMES
# ──────────────────────────────────────────────
@router.message(Command("dice"))
async def cmd_dice(msg: Message, command: CommandObject):
    await ensure_user(msg.from_user)
    try:
        bet = max(1, int((command.args or "10").split()[0]))
    except Exception:
        bet = 10
    u = await get_user(msg.from_user.id)
    if u["balance"] < bet:
        return await msg.reply("Недостаточно средств.")
    player = random.randint(1, 6)
    bot_r  = random.randint(1, 6)
    if player > bot_r:
        win = bet
        result = f"🎉 Ты выиграл +{win} 🪙"
    elif player < bot_r:
        win = -bet
        result = f"😢 Ты проиграл -{bet} 🪙"
    else:
        win = 0
        result = "🤝 Ничья"
    await update_balance(msg.from_user.id, win)
    await msg.answer(
        f"🎲 Ты: {player} | Бот: {bot_r}\n{result}",
        parse_mode=ParseMode.HTML
    )

@router.message(Command("flip", "coinflip"))
async def cmd_flip(msg: Message, command: CommandObject):
    await ensure_user(msg.from_user)
    args = (command.args or "").split()
    try:
        side = args[0].lower()
        assert side in ("орёл", "решка", "o", "р", "heads", "tails")
        bet  = int(args[1]) if len(args) > 1 else 50
    except Exception:
        return await msg.reply("Использование: /flip орёл|решка ставка")
    u = await get_user(msg.from_user.id)
    if u["balance"] < bet:
        return await msg.reply("Недостаточно средств.")
    result = random.choice(["орёл", "решка"])
    won = side in (result, result[0])
    await update_balance(msg.from_user.id, bet if won else -bet)
    await msg.answer(
        f"🪙 Выпало: <b>{result}</b>\n{'🎉 +' if won else '😢 -'}{bet} 🪙",
        parse_mode=ParseMode.HTML
    )

@router.message(Command("slots"))
async def cmd_slots(msg: Message, command: CommandObject):
    await ensure_user(msg.from_user)
    try:
        bet = max(1, int((command.args or "20").split()[0]))
    except Exception:
        bet = 20
    u = await get_user(msg.from_user.id)
    if u["balance"] < bet:
        return await msg.reply("Недостаточно средств.")
    symbols = ["🍒", "🍋", "🍊", "🍇", "🔔", "💎", "7️⃣"]
    s = [random.choice(symbols) for _ in range(3)]
    if s[0] == s[1] == s[2] == "💎":
        win = bet * 50
    elif s[0] == s[1] == s[2] == "7️⃣":
        win = bet * 20
    elif s[0] == s[1] == s[2]:
        win = bet * 5
    elif s[0] == s[1] or s[1] == s[2]:
        win = bet * 2
    else:
        win = -bet
    await update_balance(msg.from_user.id, win)
    result = f"{'🎰 ДЖЕКПОТ +' if win > 0 else '😢 '}{abs(win)} 🪙" if win != 0 else "Ничья"
    await msg.answer(
        f"🎰 [ {s[0]} | {s[1]} | {s[2]} ]\n{result}",
        parse_mode=ParseMode.HTML
    )

@router.message(Command("roulette"))
async def cmd_roulette(msg: Message, command: CommandObject):
    await ensure_user(msg.from_user)
    args = (command.args or "").split()
    try:
        color = args[0].lower()
        assert color in ("красный", "чёрный", "зелёный", "red", "black", "green")
        bet   = int(args[1]) if len(args) > 1 else 30
    except Exception:
        return await msg.reply("Использование: /roulette красный|чёрный|зелёный ставка")
    u = await get_user(msg.from_user.id)
    if u["balance"] < bet:
        return await msg.reply("Недостаточно средств.")
    num    = random.randint(0, 36)
    greens = {0}
    reds   = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    if num in greens:
        landed = "зелёный"
    elif num in reds:
        landed = "красный"
    else:
        landed = "чёрный"
    mult = {"зелёный": 14, "красный": 2, "чёрный": 2}[landed]
    if color in (landed, landed[:3]):
        win = bet * mult - bet
    else:
        win = -bet
    await update_balance(msg.from_user.id, win)
    await msg.answer(
        f"🎡 Выпало {num} ({landed})\n{'🎉 +' if win > 0 else '😢 '}{abs(win)} 🪙",
        parse_mode=ParseMode.HTML
    )

@router.message(Command("guess"))
async def cmd_guess(msg: Message, command: CommandObject):
    await ensure_user(msg.from_user)
    try:
        number = int((command.args or "").split()[0])
    except Exception:
        return await msg.reply("Угадай число от 1 до 10: /guess <число>")
    secret = random.randint(1, 10)
    if number == secret:
        await update_balance(msg.from_user.id, 200)
        await msg.answer(f"🎯 Правильно! +200 🪙 (загадано было {secret})")
    else:
        await update_balance(msg.from_user.id, -50)
        await msg.answer(f"❌ Неверно. Было {secret}. -50 🪙")

QUIZ_QUESTIONS = [
    ("Сколько планет в Солнечной системе?", "8"),
    ("Столица Японии?", "Токио"),
    ("2 в степени 10?", "1024"),
    ("Химический символ золота?", "Au"),
    ("Самый большой океан?", "Тихий"),
    ("Год основания Рима (приближённо)?", "753"),
]

@router.message(Command("quiz"))
async def cmd_quiz(msg: Message):
    q, a = random.choice(QUIZ_QUESTIONS)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Ответить", callback_data=f"quiz:{msg.from_user.id}:{a}")
    ]])
    await msg.answer(f"❓ <b>{html.escape(q)}</b>\n\nОтветь в течение 30 сек.", reply_markup=kb, parse_mode=ParseMode.HTML)

@router.callback_query(F.data.startswith("quiz:"))
async def quiz_answer(call: CallbackQuery):
    _, uid, answer = call.data.split(":", 2)
    if call.from_user.id != int(uid):
        return await call.answer("Это не твоя викторина.", show_alert=True)
    await call.message.edit_reply_markup()
    await call.message.answer(
        f"✏️ {mention(call.from_user)}, напиши ответ одним словом/числом.\n"
        f"<i>(Ожидаемый ответ скрыт)</i>",
        parse_mode=ParseMode.HTML
    )
    # Simplified: just reveal answer
    await call.message.answer(f"💡 Правильный ответ: <b>{html.escape(answer)}</b>", parse_mode=ParseMode.HTML)
    await call.answer()

# ──────────────────────────────────────────────
# RP COMMANDS
# ──────────────────────────────────────────────
RP_ACTIONS = {
    "hug":      ("обнял(а)",                  ""),
    "kiss":     ("поцеловал(а)",              ""),
    "slap":     ("дал(а) пощёчину",           ""),
    "pat":      ("погладил(а) по голове",     ""),
    "cuddle":   ("прижался(ась) к",           ""),
    "bite":     ("укусил(а)",                 ""),
    "feed":     ("покормил(а)",               ""),
    "punch":    ("дал(а) в нос",              ""),
    "poke":     ("ткнул(а)",                  ""),
    "kick_rp":  ("пнул(а)",                   ""),
    "lick":     ("лизнул(а)",                 ""),
    "wink":     ("подмигнул(а)",              ""),
    "stab":     ("зарезал(а)",                ""),
    "shoot":    ("выстрелил(а) в",            ""),
    "marry_rp": ("сделал(а) предложение",     ""),
    "ubit":     ("убил(а)",                   ""),
    "zarezat":  ("зарезал(а) ножом",          ""),
    "uebat":    ("уебал(а)",                  ""),
    "udarit":   ("ударил(а)",                 ""),
    "povesit":  ("повесил(а)",                ""),
    "lapaty":   ("лапал(а)",                  ""),
    "zasasat":  ("засосал(а)",                ""),
    "grizti":   ("загрыз(ла)",                ""),
    "tolkat":   ("толкнул(а)",                ""),
    "plevat":   ("плюнул(а) в",               ""),
    "szhec":    ("сжёг(ла) живьём",           ""),
    "zakopat":  ("закопал(а) живьём",         ""),
    "vzrvat":   ("взорвал(а)",                ""),
    "potashit": ("потащил(а) за волосы",      ""),
    "chpoknut": ("чпокнул(а)",                ""),
    "sxvatit":  ("схватил(а) за шкирку",      ""),
}

def rp_handler(action: str):
    async def handler(msg: Message):
        verb, emoji = RP_ACTIONS[action]
        target = msg.reply_to_message.from_user if msg.reply_to_message else None
        if not target:
            return await msg.reply(f"Ответь на сообщение пользователя для /{action}.")
        await msg.answer(
            f"{mention(msg.from_user)} {verb} {mention(target)}",
            parse_mode=ParseMode.HTML
        )
        await add_xp(msg.from_user.id, 2)
    return handler

for _action in RP_ACTIONS:
    router.message(Command(_action))(rp_handler(_action))

# ──────────────────────────────────────────────
# MARRIAGE
# ──────────────────────────────────────────────
@router.message(Command("marry"))
async def cmd_marry(msg: Message):
    if not msg.reply_to_message:
        return await msg.reply("Ответь на сообщение своего будущего партнёра.")
    target = msg.reply_to_message.from_user
    if target.id == msg.from_user.id:
        return await msg.reply("Нельзя жениться на себе.")
    await ensure_user(msg.from_user)
    await ensure_user(target)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM marriages WHERE user1_id IN (?,?) OR user2_id IN (?,?)",
            (msg.from_user.id, target.id, msg.from_user.id, target.id)
        ) as cur:
            if await cur.fetchone():
                return await msg.reply("Один из вас уже в браке.")
        await db.execute("INSERT INTO marriages (user1_id, user2_id) VALUES (?,?)", (msg.from_user.id, target.id))
        await db.commit()
    await msg.answer(
        f"💒 {mention(msg.from_user)} и {mention(target)} теперь в браке! 🎊",
        parse_mode=ParseMode.HTML
    )

@router.message(Command("divorce"))
async def cmd_divorce(msg: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM marriages WHERE user1_id=? OR user2_id=?",
            (msg.from_user.id, msg.from_user.id)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return await msg.reply("Ты не в браке.")
        await db.execute("DELETE FROM marriages WHERE id=?", (row[0],))
        await db.commit()
    await msg.answer(f"💔 {mention(msg.from_user)} подал(а) на развод.", parse_mode=ParseMode.HTML)

# ──────────────────────────────────────────────
# 18+ COMMANDS (only in adult-enabled chats)
# ──────────────────────────────────────────────
ADULT_SCENARIOS_LIGHT = [
    "{a} и {b} остались наедине 🌙",
    "{a} шепнул(а) кое-что на ушко {b} 🤫",
    "{a} пригласил(а) {b} потанцевать в темноте 💃",
    "{a} написал(а) {b} нескромное сообщение 📲",
    "{a} соблазнил(а) {b} бокалом вина 🍷",
]
ADULT_SCENARIOS_HOT = [
    "{a} провёл(а) бурную ночь с {b} 🔥",
    "{a} и {b} исчезли на несколько часов… 😏",
    "{a} сделал(а) {b} предложение, от которого нельзя отказаться 💋",
]

async def check_adult(msg: Message) -> bool:
    cfg = await get_chat(msg.chat.id)
    if not cfg["adult_enabled"]:
        await msg.reply("🔞 Эта команда недоступна. Включите 18+ в настройках: /setadult on")
        return False
    return True

async def check_age(msg: Message) -> bool:
    u = await get_user(msg.from_user.id)
    if not u or not u["age_verified"]:
        await msg.reply("Необходима верификация возраста: /verify18")
        return False
    return True

@router.message(Command("verify18"))
async def cmd_verify18(msg: Message):
    await ensure_user(msg.from_user)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET age_verified=1 WHERE user_id=?", (msg.from_user.id,))
        await db.commit()
    await msg.reply("✅ Возраст подтверждён. Ты подтверждаешь, что тебе 18+ лет.")

@router.message(Command("flirt"))
async def cmd_flirt(msg: Message):
    if not await check_adult(msg): return
    if not msg.reply_to_message:
        return await msg.reply("Ответь на сообщение.")
    target = msg.reply_to_message.from_user
    s = random.choice(ADULT_SCENARIOS_LIGHT)
    a = mention(msg.from_user)
    b = mention(target)
    await msg.answer(s.replace("{a}", a).replace("{b}", b), parse_mode=ParseMode.HTML)

@router.message(Command("sex", "18plus", "nsfw"))
async def cmd_sex(msg: Message):
    if not await check_adult(msg): return
    if not await check_age(msg): return
    if not msg.reply_to_message:
        return await msg.reply("Ответь на сообщение.")
    target = msg.reply_to_message.from_user
    s = random.choice(ADULT_SCENARIOS_HOT)
    a = mention(msg.from_user)
    b = mention(target)
    await msg.answer("🔞 " + s.replace("{a}", a).replace("{b}", b), parse_mode=ParseMode.HTML)

@router.message(Command("strip"))
async def cmd_strip(msg: Message):
    if not await check_adult(msg): return
    target = msg.reply_to_message.from_user if msg.reply_to_message else msg.from_user
    actions = ["снял(а) пиджак 🧥", "расстегнул(а) рубашку 👔", "остался(ась) в нижнем белье 🩱", "…и убежал(а) 😂"]
    await msg.answer(
        f"💃 {mention(target)} {random.choice(actions)}",
        parse_mode=ParseMode.HTML
    )

@router.message(Command("truth"))
async def cmd_truth(msg: Message):
    if not await check_adult(msg): return
    truths = [
        "Когда ты в последний раз влюблялся(ась)?",
        "Назови имя своей тайной симпатии.",
        "Был ли у тебя поцелуй на спор?",
        "Какая твоя самая нескромная мечта?",
        "Ты когда-нибудь флиртовал(а) в интернете?",
    ]
    await msg.answer(f"🎭 <b>Правда:</b> {random.choice(truths)}", parse_mode=ParseMode.HTML)

@router.message(Command("dare"))
async def cmd_dare(msg: Message):
    if not await check_adult(msg): return
    dares = [
        "Напиши нескромный комплимент случайному участнику чата.",
        "Признайся в симпатии участнику чата.",
        "Смени аватарку на что-нибудь пикантное на 1 час.",
        "Напиши сообщение от лица своей тайной симпатии.",
        "Прими вызов: 10 минут без одежды дома 😏",
    ]
    await msg.answer(f"🎭 <b>Действие:</b> {random.choice(dares)}", parse_mode=ParseMode.HTML)

@router.message(Command("rate"))
async def cmd_rate(msg: Message):
    target = msg.reply_to_message.from_user if msg.reply_to_message else msg.from_user
    score  = random.randint(1, 10)
    emojis = ["😬","😐","🙂","😊","😍","🔥","💯"][min(score - 1, 6)]
    await msg.answer(
        f"{emojis} {mention(target)} привлекательность: {score}/10",
        parse_mode=ParseMode.HTML
    )

@router.message(Command("ship"))
async def cmd_ship(msg: Message):
    if not msg.reply_to_message:
        return await msg.reply("Ответь на чьё-то сообщение, чтобы заship'пить с тобой.")
    a = msg.from_user
    b = msg.reply_to_message.from_user
    score = random.randint(0, 100)
    bar = "❤️" * (score // 10) + "🖤" * (10 - score // 10)
    await msg.answer(
        f"💕 {mention(a)} + {mention(b)} = {score}%\n{bar}",
        parse_mode=ParseMode.HTML
    )

# ──────────────────────────────────────────────
# SETTINGS
# ──────────────────────────────────────────────
@router.message(Command("setwelcome"))
async def cmd_setwelcome(msg: Message, command: CommandObject):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply("⛔ Нет прав.")
    text = command.args or "Добро пожаловать, {name}!"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE chat_settings SET welcome_text=? WHERE chat_id=?", (text, msg.chat.id))
        await db.commit()
    await msg.reply(f"✅ Приветствие обновлено:\n{text}")

@router.message(Command("togglewelcome"))
async def cmd_togglewelcome(msg: Message, command: CommandObject):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply("⛔ Нет прав.")
    val = 1 if (command.args or "").lower() in ("on", "1", "вкл") else 0
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE chat_settings SET welcome_enabled=? WHERE chat_id=?", (val, msg.chat.id))
        await db.commit()
    await msg.reply(f"✅ Приветствие {'включено' if val else 'выключено'}.")

@router.message(Command("antiflood"))
async def cmd_antiflood(msg: Message, command: CommandObject):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply("⛔ Нет прав.")
    args = (command.args or "").split()
    val  = 1 if args and args[0].lower() in ("on", "1") else 0
    limit = int(args[1]) if len(args) > 1 else 5
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE chat_settings SET antiflood=?, antiflood_limit=? WHERE chat_id=?",
            (val, limit, msg.chat.id)
        )
        await db.commit()
    await msg.reply(f"✅ Антифлуд {'включён' if val else 'выключен'} (лимит: {limit} сообщений/5с).")

@router.message(Command("setadult"))
async def cmd_setadult(msg: Message, command: CommandObject):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply("⛔ Нет прав.")
    val = 1 if (command.args or "").lower() in ("on", "1", "вкл") else 0
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE chat_settings SET adult_enabled=? WHERE chat_id=?", (val, msg.chat.id))
        await db.commit()
    await msg.reply(f"🔞 Режим 18+ {'включён' if val else 'выключён'}.")

# ──────────────────────────────────────────────
# NOTES
# ──────────────────────────────────────────────
@router.message(Command("note", "savenote"))
async def cmd_note(msg: Message, command: CommandObject):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply("⛔ Нет прав.")
    if not command.args:
        return await msg.reply("Использование: /note имя текст")
    parts = command.args.split(None, 1)
    if len(parts) < 2:
        return await msg.reply("Укажи имя и текст заметки.")
    name, content = parts
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO notes (chat_id, name, content) VALUES (?,?,?)",
            (msg.chat.id, name.lower(), content)
        )
        await db.commit()
    await msg.reply(f"📝 Заметка <b>{html.escape(name)}</b> сохранена.", parse_mode=ParseMode.HTML)

@router.message(Command("get", "getnote"))
async def cmd_getnote(msg: Message, command: CommandObject):
    if not command.args:
        return
    name = command.args.strip().lower()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT content FROM notes WHERE chat_id=? AND name=?", (msg.chat.id, name)) as cur:
            row = await cur.fetchone()
    if not row:
        return await msg.reply("Заметка не найдена.")
    await msg.answer(row[0])

@router.message(Command("notes"))
async def cmd_notes(msg: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name FROM notes WHERE chat_id=? ORDER BY name", (msg.chat.id,)) as cur:
            rows = await cur.fetchall()
    if not rows:
        return await msg.reply("Заметок нет.")
    names = ", ".join(f"<code>{html.escape(r[0])}</code>" for r, in [(r,) for r in rows])
    await msg.answer(f"📋 Заметки: {names}", parse_mode=ParseMode.HTML)

@router.message(Command("delnote"))
async def cmd_delnote(msg: Message, command: CommandObject):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply("⛔ Нет прав.")
    if not command.args:
        return await msg.reply("Укажи имя заметки.")
    name = command.args.strip().lower()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM notes WHERE chat_id=? AND name=?", (msg.chat.id, name))
        await db.commit()
    await msg.reply(f"🗑️ Заметка <b>{html.escape(name)}</b> удалена.", parse_mode=ParseMode.HTML)

# ──────────────────────────────────────────────
# FILTERS
# ──────────────────────────────────────────────
@router.message(Command("addfilter"))
async def cmd_addfilter(msg: Message, command: CommandObject):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply("⛔ Нет прав.")
    if not command.args:
        return await msg.reply("Использование: /addfilter триггер ответ")
    parts = command.args.split(None, 1)
    if len(parts) < 2:
        return await msg.reply("Нужен триггер и ответ.")
    trigger, reply = parts
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO filters (chat_id, trigger, reply) VALUES (?,?,?)",
            (msg.chat.id, trigger.lower(), reply)
        )
        await db.commit()
    await msg.reply(f"✅ Фильтр <code>{html.escape(trigger)}</code> добавлен.", parse_mode=ParseMode.HTML)

@router.message(Command("delfilter"))
async def cmd_delfilter(msg: Message, command: CommandObject):
    if not await is_admin(msg.bot, msg.chat.id, msg.from_user.id):
        return await msg.reply("⛔ Нет прав.")
    if not command.args:
        return await msg.reply("Укажи триггер.")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM filters WHERE chat_id=? AND trigger=?", (msg.chat.id, command.args.lower()))
        await db.commit()
    await msg.reply("✅ Фильтр удалён.")

@router.message(Command("filters"))
async def cmd_filters(msg: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT trigger FROM filters WHERE chat_id=?", (msg.chat.id,)) as cur:
            rows = await cur.fetchall()
    if not rows:
        return await msg.reply("Фильтров нет.")
    names = ", ".join(f"<code>{html.escape(r[0])}</code>" for r in rows)
    await msg.answer(f"🔍 Активные фильтры: {names}", parse_mode=ParseMode.HTML)

# ──────────────────────────────────────────────
# INFO
# ──────────────────────────────────────────────
@router.message(Command("chatinfo"))
async def cmd_chatinfo(msg: Message):
    chat = msg.chat
    count = await msg.bot.get_chat_member_count(chat.id)
    admins = await msg.bot.get_chat_administrators(chat.id)
    await msg.answer(
        f"📊 <b>Информация о чате</b>\n"
        f"🆔 ID: <code>{chat.id}</code>\n"
        f"📛 Название: {html.escape(chat.title or '')}\n"
        f"👥 Участников: {count}\n"
        f"👮 Администраторов: {len(admins)}\n"
        f"🔗 Username: @{chat.username or 'нет'}",
        parse_mode=ParseMode.HTML
    )

@router.message(Command("userinfo"))
async def cmd_userinfo(msg: Message, command: CommandObject):
    target = await get_target(msg, command.args) or msg.from_user
    await ensure_user(target)
    u = await get_user(target.id)
    member = await msg.bot.get_chat_member(msg.chat.id, target.id)
    await msg.answer(
        f"👤 <b>Информация о пользователе</b>\n"
        f"🆔 ID: <code>{target.id}</code>\n"
        f"📛 Имя: {html.escape(target.full_name or '')}\n"
        f"🔗 Username: @{target.username or 'нет'}\n"
        f"📌 Статус: {member.status}\n"
        f"💰 Баланс: {u['balance'] if u else 0} 🪙\n"
        f"⭐ Уровень: {u['level'] if u else 1}",
        parse_mode=ParseMode.HTML
    )

@router.message(Command("id"))
async def cmd_id(msg: Message):
    target = msg.reply_to_message.from_user if msg.reply_to_message else msg.from_user
    await msg.reply(f"🆔 ID: <code>{target.id}</code>", parse_mode=ParseMode.HTML)

# ──────────────────────────────────────────────
# FUN / MISC
# ──────────────────────────────────────────────
@router.message(Command("roll"))
async def cmd_roll(msg: Message, command: CommandObject):
    args = (command.args or "1d6").lower()
    m = re.fullmatch(r"(\d+)d(\d+)", args)
    if not m:
        return await msg.reply("Формат: /roll 2d6")
    count, sides = int(m[1]), int(m[2])
    count  = min(count, 20)
    sides  = min(sides, 1000)
    rolls  = [random.randint(1, sides) for _ in range(count)]
    total  = sum(rolls)
    await msg.reply(f"🎲 [{', '.join(map(str, rolls))}] = {total}")

@router.message(Command("8ball"))
async def cmd_8ball(msg: Message, command: CommandObject):
    answers = [
        "Да, определённо!", "Скорее всего.", "Не факт.", "Нет.",
        "Лучше не говорить.", "Спроси позже.", "Всё возможно!", "Никогда.",
        "Звёзды говорят ДА.", "Мой ответ — нет.",
    ]
    await msg.reply(f"🎱 {random.choice(answers)}")

@router.message(Command("meme"))
async def cmd_meme(msg: Message):
    memes = [
        "Когда код работает, но ты не знаешь почему 🤡",
        "StackOverflow в 3 ночи: да, это я 🫠",
        "Git commit: 'fix', 'fix2', 'fix_final', 'fix_FINAL2' 💀",
        "Бот модерирует себя 🤖",
        "В продакшн в пятницу вечером 🔥",
    ]
    await msg.reply(random.choice(memes))

@router.message(Command("ask"))
async def cmd_ask(msg: Message, command: CommandObject):
    if not command.args:
        return await msg.reply("Напиши вопрос после команды.")
    await msg.reply(f"🔮 {random.choice(['Да', 'Нет', 'Возможно', 'Не думаю', 'Точно!', 'Никогда'])}")

@router.message(Command("choose"))
async def cmd_choose(msg: Message, command: CommandObject):
    if not command.args:
        return await msg.reply("Перечисли варианты через |")
    options = [o.strip() for o in command.args.split("|") if o.strip()]
    if not options:
        return await msg.reply("Нет вариантов.")
    await msg.reply(f"🎯 Выбор: <b>{html.escape(random.choice(options))}</b>", parse_mode=ParseMode.HTML)

@router.message(Command("quote"))
async def cmd_quote(msg: Message):
    quotes = [
        "«Код без тестов — это легенда без доказательств.»",
        "«Самый быстрый способ сделать что-то — сделать это правильно.»",
        "«В начале было слово, и слово было `git init`.»",
        "«Дебаггинг — это детективная история, где ты одновременно и детектив, и убийца.»",
    ]
    await msg.reply(f"💬 {random.choice(quotes)}")

@router.message(Command("calc"))
async def cmd_calc(msg: Message, command: CommandObject):
    if not command.args:
        return await msg.reply("Использование: /calc выражение")
    expr = re.sub(r"[^0-9+\-*/().% ]", "", command.args)
    try:
        result = eval(expr, {"__builtins__": {}})
        await msg.reply(f"🧮 {expr} = {result}")
    except Exception:
        await msg.reply("Ошибка вычисления.")

@router.message(Command("ascii"))
async def cmd_ascii(msg: Message, command: CommandObject):
    if not command.args:
        return await msg.reply("Напиши текст после /ascii")
    text = command.args[:20]
    big = "\n".join(
        "  ".join(f"{ord(c):08b}" for c in row)
        for row in [text]
    )
    await msg.reply(f"<code>{html.escape(big)}</code>", parse_mode=ParseMode.HTML)

@router.message(Command("reverse"))
async def cmd_reverse(msg: Message, command: CommandObject):
    text = command.args or (msg.reply_to_message.text if msg.reply_to_message else "")
    if not text:
        return await msg.reply("Нечего переворачивать.")
    await msg.reply(text[::-1])

@router.message(Command("mock"))
async def cmd_mock(msg: Message, command: CommandObject):
    text = command.args or (msg.reply_to_message.text if msg.reply_to_message else "")
    if not text:
        return await msg.reply("Нечего mOcKать.")
    result = "".join(c.upper() if i % 2 else c.lower() for i, c in enumerate(text))
    await msg.reply(result)

@router.message(Command("weather"))
async def cmd_weather(msg: Message, command: CommandObject):
    city = command.args or "неизвестно"
    conditions = ["☀️ Ясно", "🌧️ Дождь", "❄️ Снег", "🌩️ Гроза", "🌫️ Туман", "🌤️ Переменная облачность"]
    temp = random.randint(-15, 35)
    await msg.reply(
        f"🌍 Погода в {html.escape(city)}: {random.choice(conditions)}, {temp}°C\n"
        f"💧 Влажность: {random.randint(30,90)}% | 💨 Ветер: {random.randint(0,30)} км/ч\n"
        f"<i>(Данные случайные — для реальной погоды подключи API)</i>",
        parse_mode=ParseMode.HTML
    )

@router.message(Command("rank"))
async def cmd_rank(msg: Message):
    await ensure_user(msg.from_user)
    u = await get_user(msg.from_user.id)
    lvl = u["level"]
    xp  = u["xp"]
    nxp = xp_for_level(lvl + 1)
    pct = min(100, int(xp / max(nxp, 1) * 100))
    bar = "▓" * (pct // 10) + "░" * (10 - pct // 10)
    await msg.answer(
        f"📊 <b>Ранг {mention(msg.from_user)}</b>\n"
        f"⭐ Уровень {lvl} [{bar}] {pct}%\n"
        f"✨ XP: {xp}/{nxp}",
        parse_mode=ParseMode.HTML
    )

# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────
async def set_commands(bot: Bot):
    cmds = [
        BotCommand(command="help",       description="Список команд"),
        BotCommand(command="profile",    description="Твой профиль"),
        BotCommand(command="balance",    description="Баланс"),
        BotCommand(command="daily",      description="Ежедневная награда"),
        BotCommand(command="top",        description="Топ игроков"),
        BotCommand(command="shop",       description="Магазин"),
        BotCommand(command="dice",       description="Кости (ставка)"),
        BotCommand(command="slots",      description="Слоты"),
        BotCommand(command="hug",        description="Обнять (РП)"),
        BotCommand(command="marry",      description="Жениться"),
        BotCommand(command="ship",       description="Шип"),
        BotCommand(command="ban",        description="[Адм] Забанить"),
        BotCommand(command="mute",       description="[Адм] Замьютить"),
        BotCommand(command="warn",       description="[Адм] Предупреждение"),
        BotCommand(command="setadult",   description="[Адм] Включить 18+"),
    ]
    await bot.set_my_commands(cmds)

async def main():
    await db_init()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp  = Dispatcher()
    dp.include_router(router)
    await set_commands(bot)
    log.info("Бот запущен.")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
