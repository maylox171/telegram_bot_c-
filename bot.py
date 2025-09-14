# bot.py
import sqlite3
import asyncio
from typing import List, Tuple, Optional
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# ---------------- Config ----------------
ADMIN_IDS = [1000207683, 1485565692]  # <- ваші адміни
DB_NAME = "bot.db"
TOKEN = "8170304629:AAHqpnJsBboChDLnn0PPix6Vtoogof4c8Ts"

# ---------------- States ----------------
(
    LOGIN, PASSWORD,
    MENU_USER, MENU_ADMIN,
    SELECT_DAY, VIEW_TASK, ENTER_TASK_TEXT, CHOOSE_TARGET_USER,
    MANAGE_LOGINS, ADD_USER_LOGIN, ADD_USER_PASSWORD
) = range(11)

# ---------------- Async DB helper ----------------
async def async_db_execute(sql: str, params: tuple = (), fetch: bool = False):
    loop = asyncio.get_running_loop()
    def db_op():
        with sqlite3.connect(DB_NAME) as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            if fetch:
                return cur.fetchall()
            else:
                conn.commit()
                return None
    return await loop.run_in_executor(None, db_op)

# ---------------- Init DB ----------------
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT,
                type TEXT,
                content TEXT,
                user_login TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                login TEXT UNIQUE,
                password TEXT,
                is_active INTEGER DEFAULT 1,
                telegram_id INTEGER
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS support_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_login TEXT,
                message TEXT,
                answered INTEGER DEFAULT 0
            )
        """)
        conn.commit()

# ---------------- DB Utility ----------------
async def get_active_user_logins() -> List[str]:
    rows = await async_db_execute("SELECT login FROM users WHERE is_active=1", fetch=True)
    return [r[0] for r in rows]

async def get_days_for_type(ttype: str) -> List[str]:
    rows = await async_db_execute("SELECT DISTINCT day FROM tasks WHERE type=? ORDER BY id", (ttype,), fetch=True)
    return [r[0] for r in rows]

async def insert_task(day: str, ttype: str, content: str, user_login: str):
    await async_db_execute(
        "INSERT INTO tasks (day, type, content, user_login) VALUES (?, ?, ?, ?)",
        (day, ttype, content, user_login)
    )

async def get_task_for_day_and_type(day: str, ttype: str) -> List[Tuple[int, str, str]]:
    return await async_db_execute(
        "SELECT id, content, user_login FROM tasks WHERE day=? AND type=?", (day, ttype), fetch=True
    )

async def get_tasks_for_user_and_type(user_login: str, ttype: str) -> List[Tuple[str, str]]:
    return await async_db_execute(
        "SELECT day, content FROM tasks WHERE type=? AND user_login=?", (ttype, user_login), fetch=True
    )

async def add_user(login: str, password: str) -> bool:
    try:
        await async_db_execute("INSERT INTO users (login, password) VALUES (?, ?)", (login, password))
        return True
    except:
        return False

async def block_user(login: str):
    await async_db_execute("UPDATE users SET is_active=0 WHERE login=?", (login,))

async def set_user_telegram_id_by_login(login: str, tg_id: int):
    await async_db_execute("UPDATE users SET telegram_id=? WHERE login=?", (tg_id, login))

async def get_user_by_telegram_id(tg_id: int) -> Optional[str]:
    rows = await async_db_execute("SELECT login FROM users WHERE telegram_id=? LIMIT 1", (tg_id,), fetch=True)
    return rows[0][0] if rows else None

# ---------------- Bot Handlers ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in ADMIN_IDS:
        kb = [["Надіслати завдання (Теорія)", "Надіслати завдання (Практика)"],
              ["Підтримка", "Керувати логінами"]]
        await update.message.reply_text("✅ Вхід як *Адміністратор*", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
        return MENU_ADMIN
    else:
        await update.message.reply_text("Введіть свій логін:")
        return LOGIN

# ---- User Login ----
async def ask_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["login"] = update.message.text.strip()
    await update.message.reply_text("Введіть пароль:")
    return PASSWORD

async def check_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    login = context.user_data.get("login")
    password = update.message.text.strip()
    rows = await async_db_execute("SELECT id, is_active FROM users WHERE login=? AND password=?", (login, password), fetch=True)
    if rows and rows[0][1] == 1:
        await set_user_telegram_id_by_login(login, update.effective_user.id)
        kb = [["Теорія", "Практика"], ["Надіслати код", "Зв'язатися з адміністратором"]]
        await update.message.reply_text("✅ Авторизація успішна! Оберіть дію:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
        return MENU_USER
    else:
        await update.message.reply_text("⛔ Невірний логін/пароль або заблоковано. /start")
        return ConversationHandler.END

# ---- User Menu ----
async def menu_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    login = context.user_data.get("login") or await get_user_by_telegram_id(update.effective_user.id)
    context.user_data["login"] = login
    if text in ["Теорія", "Практика"]:
        ttype = "theory" if text == "Теорія" else "practice"
        rows = await get_tasks_for_user_and_type(login, ttype)
        if not rows:
            await update.message.reply_text(f"📘 Для вас ще немає {text.lower()} завдань.")
        else:
            msg = "\n\n".join([f"{r[0]}:\n{r[1]}" for r in rows])
            await update.message.reply_text(f"📘 {text}:\n\n" + msg)
    else:
        await update.message.reply_text("Будь ласка, оберіть дію з меню.")
    return MENU_USER

# ---- Admin Menu ----
async def menu_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text in ["Надіслати завдання (Теорія)", "Надіслати завдання (Практика)"]:
        context.user_data["task_type"] = "theory" if "Теорія" in text else "practice"
        days = await get_days_for_type(context.user_data["task_type"])
        kb = [[d] for d in days] + [["Додати новий день", "Назад"]]
        await update.message.reply_text("Оберіть день або додайте новий:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
        return SELECT_DAY
    elif text == "Керувати логінами":
        kb = [["Додати користувача", "Видалити користувача", "Дані користувачів"], ["Назад"]]
        await update.message.reply_text("Меню керування логінами:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
        return MANAGE_LOGINS
    else:
        await update.message.reply_text("Оберіть дію адміністратора.")
    return MENU_ADMIN

# ---- Select Day (Admin) ----
async def select_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text
    if choice == "Назад":
        return await start(update, context)
    if choice == "Додати новий день":
        await update.message.reply_text("✍️ Введіть назву нового дня:")
        context.user_data["creating_new_day"] = True
        return ENTER_TASK_TEXT
    # Existing day
    context.user_data["current_day"] = choice
    await update.message.reply_text(f"Введіть текст завдання для {choice}:")
    return ENTER_TASK_TEXT

# ---- Enter Task Text ----
async def enter_task_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    context.user_data["pending_task_text"] = text
    users = await get_active_user_logins()
    kb = [[u] for u in users] + [["Всі користувачі"], ["Назад"]]
    await update.message.reply_text("Оберіть користувача для завдання:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    return CHOOSE_TARGET_USER

# ---- Choose Target User ----
async def choose_target_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text
    if choice == "Назад":
        return await start(update, context)
    day = context.user_data.get("current_day") or context.user_data.get("new_day_name")
    if context.user_data.get("creating_new_day"):
        day = context.user_data.pop("creating_new_day_name", None) or context.user_data.pop("pending_task_text")
        context.user_data["new_day_name"] = day
    task_text = context.user_data.pop("pending_task_text")
    ttype = context.user_data.get("task_type")
    if choice == "Всі користувачі":
        users = await get_active_user_logins()
        for u in users:
            await insert_task(day, ttype, task_text, u)
    else:
        await insert_task(day, ttype, task_text, choice)
    await update.message.reply_text(f"✅ Завдання збережено для {day} → {choice}")
    return await menu_admin(update, context)

# ---- Manage Logins ----
async def manage_logins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "Назад":
        return await menu_admin(update, context)
    await update.message.reply_text("Ця функція тимчасово відключена.")
    return MANAGE_LOGINS

# ---- Unknown ----
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Невідома команда або натисніть /start.")

# ---------------- Main ----------------
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_password)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, check_password)],
            MENU_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, menu_user)],
            MENU_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, menu_admin)],
            SELECT_DAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_day)],
            ENTER_TASK_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_task_text)],
            CHOOSE_TARGET_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_target_user)],
            MANAGE_LOGINS: [MessageHandler(filters.TEXT & ~filters.COMMAND, manage_logins)],
        },
        fallbacks=[MessageHandler(filters.ALL, unknown)],
        allow_reentry=True
    )
    app.add_handler(conv)
    print("Бот запущено!")
    app.run_polling()

if __name__ == "__main__":
    main()
