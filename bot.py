import os
import asyncio
import calendar
import logging
import re
import sqlite3
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("BOT_TOKEN", "")

MASTER_ADMIN_ID = 8546035374
VODAFONE_NUMBER = "01030637131"

DB_FILE = "bot.db"

PLANS = {
    1: {"months": 1, "price": 200},
    2: {"months": 2, "price": 400},
    3: {"months": 3, "price": 600},
    6: {"months": 6, "price": 1200},
    12: {"months": 12, "price": 2400},
}

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# =========================================================
# DATABASE
# =========================================================

def db():
    return sqlite3.connect(DB_FILE)


def setup_database():
    con = db()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            created_at TEXT,
            subscription_start TEXT,
            subscription_end TEXT,
            paid INTEGER DEFAULT 0,
            reminder_sent TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            added_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            phone TEXT,
            months INTEGER,
            amount INTEGER,
            photo_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            approved_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS monthly_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            payment_id INTEGER,
            year INTEGER,
            month INTEGER,
            amount INTEGER,
            created_at TEXT
        )
    """)

    # إضافة الماستر تلقائياً
    cur.execute("""
        INSERT OR IGNORE INTO admins
        (user_id, username, added_at)
        VALUES (?, ?, ?)
    """, (
        MASTER_ADMIN_ID,
        "Master",
        datetime.now().isoformat(),
    ))

    con.commit()
    con.close()


# =========================================================
# DATE FUNCTIONS
# =========================================================

def now():
    return datetime.now()


def now_text():
    return now().strftime("%Y-%m-%d %H:%M:%S")


def format_date(value):
    if not value:
        return "غير محدد"

    try:
        return datetime.fromisoformat(value).strftime("%Y/%m/%d")
    except Exception:
        return str(value)


def add_months(date_obj, months):
    month = date_obj.month - 1 + months
    year = date_obj.year + month // 12
    month = month % 12 + 1

    day = min(
        date_obj.day,
        calendar.monthrange(year, month)[1]
    )

    return date_obj.replace(
        year=year,
        month=month,
        day=day
    )


# =========================================================
# VALIDATION
# =========================================================

def valid_phone(phone):
    return bool(
        re.fullmatch(
            r"01[0125]\d{8}",
            phone
        )
    )


# =========================================================
# USERS
# =========================================================

def save_user(user):
    con = db()
    cur = con.cursor()

    cur.execute("""
        INSERT INTO users (
            user_id,
            username,
            first_name,
            created_at
        )
        VALUES (?, ?, ?, ?)

        ON CONFLICT(user_id)
        DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name
    """, (
        user.id,
        user.username or "",
        user.first_name or "",
        now_text(),
    ))

    con.commit()
    con.close()


def get_all_users():
    con = db()
    cur = con.cursor()

    cur.execute("""
        SELECT
            user_id,
            username,
            first_name,
            subscription_start,
            subscription_end,
            paid
        FROM users
        ORDER BY created_at DESC
    """)

    rows = cur.fetchall()
    con.close()

    return rows


def get_paid_users():
    con = db()
    cur = con.cursor()

    cur.execute("""
        SELECT
            user_id,
            username,
            first_name,
            subscription_start,
            subscription_end,
            paid
        FROM users
        WHERE paid=1
        ORDER BY subscription_end DESC
    """)

    rows = cur.fetchall()
    con.close()

    return rows


def get_unpaid_users():
    con = db()
    cur = con.cursor()

    cur.execute("""
        SELECT
            user_id,
            username,
            first_name,
            subscription_start,
            subscription_end,
            paid
        FROM users
        WHERE paid=0
        ORDER BY created_at DESC
    """)

    rows = cur.fetchall()
    con.close()

    return rows


def add_user_manual(user_id):
    con = db()
    cur = con.cursor()

    cur.execute("""
        INSERT OR IGNORE INTO users (
            user_id,
            created_at
        )
        VALUES (?, ?)
    """, (
        user_id,
        now_text(),
    ))

    con.commit()
    con.close()


def delete_user(user_id):
    con = db()
    cur = con.cursor()

    cur.execute(
        "DELETE FROM users WHERE user_id=?",
        (user_id,)
    )

    con.commit()
    con.close()


def cancel_subscription(user_id):
    con = db()
    cur = con.cursor()

    cur.execute("""
        UPDATE users
        SET
            paid=0,
            subscription_start=NULL,
            subscription_end=NULL,
            reminder_sent=NULL
        WHERE user_id=?
    """, (
        user_id,
    ))

    con.commit()
    con.close()


# =========================================================
# ADMINS
# =========================================================

def is_admin(user_id):
    if user_id == MASTER_ADMIN_ID:
        return True

    con = db()
    cur = con.cursor()

    cur.execute(
        "SELECT 1 FROM admins WHERE user_id=?",
        (user_id,)
    )

    result = cur.fetchone()

    con.close()

    return result is not None


def is_master(user_id):
    return user_id == MASTER_ADMIN_ID


def get_admins():
    con = db()
    cur = con.cursor()

    cur.execute("""
        SELECT
            user_id,
            username,
            added_at
        FROM admins
        ORDER BY added_at
    """)

    rows = cur.fetchall()

    con.close()

    return rows


# =========================================================
# ADMIN KEYBOARD
# =========================================================

def admin_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "👥 كل التجار",
                callback_data="all_users"
            ),
            InlineKeyboardButton(
                "✅ المشتركين",
                callback_data="paid_users"
            ),
        ],

        [
            InlineKeyboardButton(
                "❌ غير المشتركين",
                callback_data="unpaid_users"
            ),
            InlineKeyboardButton(
                "📊 التقارير",
                callback_data="reports"
            ),
        ],

        [
            InlineKeyboardButton(
                "➕ إضافة تاجر",
                callback_data="add_user"
            ),
            InlineKeyboardButton(
                "🗑 حذف تاجر",
                callback_data="delete_user"
            ),
        ],

        [
            InlineKeyboardButton(
                "🚫 إلغاء اشتراك",
                callback_data="cancel_sub"
            ),
        ],

        [
            InlineKeyboardButton(
                "📢 إرسال للجميع",
                callback_data="broadcast_all"
            ),
        ],

        [
            InlineKeyboardButton(
                "📢 إرسال للمشتركين",
                callback_data="broadcast_paid"
            ),

            InlineKeyboardButton(
                "📢 إرسال لغير المشتركين",
                callback_data="broadcast_unpaid"
            ),
        ],

        [
            InlineKeyboardButton(
                "👑 إدارة الأدمنية",
                callback_data="manage_admins"
            ),
        ],
    ])


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    save_user(user)

    context.user_data.clear()

    if is_admin(user.id):

        await update.message.reply_text(
            "👑 لوحة التحكم\n\n"
            "اختر العملية المطلوبة:",
            reply_markup=admin_keyboard()
        )

        return

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "1️⃣ شهر - 200ج",
                callback_data="plan_1"
            )
        ],

        [
            InlineKeyboardButton(
                "2️⃣ شهرين - 400ج",
                callback_data="plan_2"
            )
        ],

        [
            InlineKeyboardButton(
                "3️⃣ أشهر - 600ج",
                callback_data="plan_3"
            )
        ],

        [
            InlineKeyboardButton(
                "6️⃣ أشهر - 1200ج",
                callback_data="plan_6"
            )
        ],

        [
            InlineKeyboardButton(
                "🔟 سنة - 2400ج",
                callback_data="plan_12"
            )
        ],
    ])

    await update.message.reply_text(

        "💜 أهلاً بك\n\n"

        "📋 اختر مدة الاشتراك:\n\n"

        "1️⃣ شهر — 200 جنيه\n"
        "2️⃣ شهرين — 400 جنيه\n"
        "3️⃣ أشهر — 600 جنيه\n"
        "6️⃣ أشهر — 1200 جنيه\n"
        "🔟 سنة — 2400 جنيه\n\n"

        "💰 الدفع عن طريق Vodafone Cash\n"
        f"📱 الرقم: {VODAFONE_NUMBER}",

        reply_markup=keyboard
    )


# =========================================================
# PLANS
# =========================================================

async def plan_callback(update, context):

    query = update.callback_query

    await query.answer()

    match = re.fullmatch(
        r"plan_(1|2|3|6|12)",
        query.data
    )

    if not match:
        return

    months = int(match.group(1))

    price = PLANS[months]["price"]

    context.user_data["months"] = months
    context.user_data["amount"] = price

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "✅ تم الدفع",
                callback_data="paid_start"
            )
        ],

        [
            InlineKeyboardButton(
                "🔙 رجوع",
                callback_data="back_start"
            )
        ],
    ])

    await query.edit_message_text(

        "💜 تم اختيار الاشتراك\n\n"

        f"📅 المدة: {months} شهر\n"
        f"💰 المبلغ: {price} جنيه\n\n"

        "📱 قم بالتحويل على Vodafone Cash:\n"
        f"{VODAFONE_NUMBER}\n\n"

        "بعد التحويل اضغط «✅ تم الدفع».",

        reply_markup=keyboard
    )


# =========================================================
# PAYMENT START
# =========================================================

async def paid_start(update, context):

    query = update.callback_query

    await query.answer()

    if "months" not in context.user_data:

        await query.message.reply_text(
            "⚠️ اختار الباقة من /start أولاً."
        )

        return

    context.user_data["state"] = "waiting_phone"

    await query.message.reply_text(

        "📱 من فضلك أرسل رقم الموبايل "
        "الذي قمت بالتحويل منه."

    )


# =========================================================
# PAYMENT HANDLER
# =========================================================

async def handle_text_message(update, context):

    if not update.message:
        return

    user = update.effective_user

    text = update.message.text.strip()

    # -----------------------------------------------------
    # PAYMENT PHONE
    # -----------------------------------------------------

    if context.user_data.get("state") == "waiting_phone":

        phone = text

        if not valid_phone(phone):

            await update.message.reply_text(

                "❌ رقم غير صحيح.\n\n"

                "أرسل رقم مصري صحيح مثل:\n"
                "01012345678"

            )

            return

        context.user_data["phone"] = phone

        context.user_data["state"] = "waiting_photo"

        await update.message.reply_text(

            "✅ تم تسجيل رقم التحويل.\n\n"

            "📸 الآن أرسل صورة التحويل."

        )

        return

    # -----------------------------------------------------
    # ADMIN TEXT
    # -----------------------------------------------------

    if not is_admin(user.id):
        return

    state = context.user_data.get("admin_state")

    if not state:
        return

    # -----------------------------------------------------
    # ADD ADMIN
    # -----------------------------------------------------

    if state == "add_admin":

        try:
            target_id = int(text)
        except ValueError:

            await update.message.reply_text(
                "❌ Telegram ID غير صحيح."
            )

            return

        con = db()
        cur = con.cursor()

        cur.execute("""
            INSERT OR IGNORE INTO admins
            (user_id, username, added_at)
            VALUES (?, ?, ?)
        """, (
            target_id,
            "",
            now_text()
        ))

        con.commit()
        con.close()

        context.user_data.clear()

        await update.message.reply_text(
            "✅ تم إضافة الأدمن.",
            reply_markup=admin_keyboard()
        )

        return

    # -----------------------------------------------------
    # DELETE ADMIN
    # -----------------------------------------------------

    if state == "delete_admin":

        try:
            target_id = int(text)

        except ValueError:

            await update.message.reply_text(
                "❌ Telegram ID غير صحيح."
            )

            return

        if target_id == MASTER_ADMIN_ID:

            await update.message.reply_text(
                "❌ لا يمكن حذف الماستر."
            )

            return

        con = db()
        cur = con.cursor()

        cur.execute(
            "DELETE FROM admins WHERE user_id=?",
            (target_id,)
        )

        con.commit()
        con.close()

        context.user_data.clear()

        await update.message.reply_text(
            "🗑 تم حذف الأدمن.",
            reply_markup=admin_keyboard()
        )

        return

    # -----------------------------------------------------
    # ADD USER
    # -----------------------------------------------------

    if state == "add_user":

        try:
            target_id = int(text)

        except ValueError:

            await update.message.reply_text(
                "❌ Telegram ID غير صحيح."
            )

            return

        add_user_manual(target_id)

        context.user_data.clear()

        await update.message.reply_text(
            "✅ تم إضافة التاجر.",
            reply_markup=admin_keyboard()
        )

        return

    # -----------------------------------------------------
    # DELETE USER
    # -----------------------------------------------------

    if state == "delete_user":

        try:
            target_id = int(text)

        except ValueError:

            await update.message.reply_text(
                "❌ Telegram ID غير صحيح."
            )

            return

        delete_user(target_id)

        context.user_data.clear()

        await update.message.reply_text(
            "🗑 تم حذف التاجر.",
            reply_markup=admin_keyboard()
        )

        return

    # -----------------------------------------------------
    # CANCEL SUBSCRIPTION
    # -----------------------------------------------------

    if state == "cancel_sub":

        try:
            target_id = int(text)

        except ValueError:

            await update.message.reply_text(
                "❌ Telegram ID غير صحيح."
            )

            return

        cancel_subscription(target_id)

        context.user_data.clear()

        await update.message.reply_text(
            "🚫 تم إلغاء الاشتراك.",
            reply_markup=admin_keyboard()
        )

        return

    # -----------------------------------------------------
    # BROADCAST
    # -----------------------------------------------------

    if state.startswith("broadcast_"):

        if state == "broadcast_all":
            users = get_all_users()

        elif state == "broadcast_paid":
            users = get_paid_users()

        else:
            users = get_unpaid_users()

        sent = 0

        for row in users:

            try:

                await context.bot.send_message(
                    chat_id=row[0],
                    text=text
                )

                sent += 1

                await asyncio.sleep(0.05)

            except Exception:
                pass

        context.user_data.clear()

        await update.message.reply_text(

            f"📢 تم الإرسال إلى {sent} مستخدم.",

            reply_markup=admin_keyboard()
        )


# =========================================================
# PHOTO HANDLER
# =========================================================

async def handle_photo_message(update, context):

    if not update.message:
        return

    user = update.effective_user

    # لازم يكون في مرحلة إرسال صورة التحويل
    if context.user_data.get("state") != "waiting_photo":
        return

    photo = update.message.photo[-1]

    months = context.user_data.get("months")
    amount = context.user_data.get("amount")
    phone = context.user_data.get("phone")

    if not months or not amount or not phone:

        await update.message.reply_text(
            "⚠️ حدث خطأ. استخدم /start وابدأ الطلب من جديد."
        )

        context.user_data.clear()

        return

    con = db()
    cur = con.cursor()

    cur.execute("""
        INSERT INTO payments (
            user_id,
            username,
            phone,
            months,
            amount,
            photo_id,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
    """, (
        user.id,
        user.username or "",
        phone,
        months,
        amount,
        photo.file_id,
        now_text(),
    ))

    payment_id = cur.lastrowid

    con.commit()
    con.close()

    context.user_data.clear()

    await update.message.reply_text(

        "✅ تم إرسال طلب الدفع للإدارة.\n\n"
        "⏳ انتظر مراجعة التحويل."

    )

    name = (
        f"@{user.username}"
        if user.username
        else user.first_name or "بدون اسم"
    )

    admin_text = (

        "💰 طلب دفع جديد\n\n"

        f"🆔 الطلب: #{payment_id}\n"
        f"👤 المستخدم: {name}\n"
        f"🆔 Telegram ID: {user.id}\n"
        f"📱 رقم التحويل: {phone}\n"
        f"📅 المدة: {months} شهر\n"
        f"💵 المبلغ: {amount} جنيه"

    )

    keyboard = InlineKeyboardMarkup([

        [

            InlineKeyboardButton(
                "✅ تأكيد الدفع",
                callback_data=f"approve_{payment_id}"
            ),

            InlineKeyboardButton(
                "❌ رفض الدفع",
                callback_data=f"reject_{payment_id}"
            ),

        ]

    ])

    try:

        await context.bot.send_photo(

            chat_id=MASTER_ADMIN_ID,

            photo=photo.file_id,

            caption=admin_text,

            reply_markup=keyboard

        )

    except Exception as e:

        logging.error(
            f"Payment notification error: {e}"
        )


# =========================================================
# PAYMENT APPROVE / REJECT
# =========================================================

async def payment_action(update, context):

    query = update.callback_query

    if not is_master(query.from_user.id):

        await query.answer(
            "❌ الماستر فقط.",
            show_alert=True
        )

        return

    await query.answer()

    match = re.fullmatch(
        r"(approve|reject)_(\d+)",
        query.data
    )

    if not match:
        return

    action = match.group(1)

    payment_id = int(match.group(2))

    con = db()
    cur = con.cursor()

    cur.execute("""
        SELECT
            user_id,
            username,
            months,
            amount,
            status
        FROM payments
        WHERE id=?
    """, (
        payment_id,
    ))

    payment = cur.fetchone()

    if not payment:

        con.close()
        return

    user_id = payment[0]
    months = payment[2]
    amount = payment[3]
    status = payment[4]

    if status != "pending":

        con.close()
        return

    # -----------------------------------------------------
    # REJECT
    # -----------------------------------------------------

    if action == "reject":

        cur.execute("""
            UPDATE payments
            SET status='rejected'
            WHERE id=?
        """, (
            payment_id,
        ))

        con.commit()
        con.close()

        try:

            await query.edit_message_caption(

                caption=(
                    "❌ تم رفض طلب الدفع\n\n"
                    f"🆔 الطلب: #{payment_id}"
                )

            )

        except Exception:
            pass

        try:

            await context.bot.send_message(

                chat_id=user_id,

                text=(
                    "❌ تم رفض إثبات الدفع.\n\n"
                    "يمكنك إرسال طلب جديد من /start."
                )

            )

        except Exception:
            pass

        return

    # -----------------------------------------------------
    # APPROVE
    # -----------------------------------------------------

    cur.execute("""
        SELECT subscription_end
        FROM users
        WHERE user_id=?
    """, (
        user_id,
    ))

    row = cur.fetchone()

    current = now()

    if row and row[0]:

        try:
            old_end = datetime.fromisoformat(row[0])

        except Exception:
            old_end = current

        if old_end > current:
            start_date = old_end

        else:
            start_date = current

    else:

        start_date = current

    end_date = add_months(
        start_date,
        months
    )

    # تحديث الدفع
    cur.execute("""
        UPDATE payments
        SET
            status='approved',
            approved_at=?
        WHERE id=?
    """, (
        now_text(),
        payment_id
    ))

    # تحديث الاشتراك
    cur.execute("""
        UPDATE users
        SET
            subscription_start=?,
            subscription_end=?,
            paid=1,
            reminder_sent=NULL
        WHERE user_id=?
    """, (
        start_date.isoformat(),
        end_date.isoformat(),
        user_id
    ))

    # تسجيل المبلغ في شهر الدفع الفعلي
    cur.execute("""
        INSERT INTO monthly_payments (
            user_id,
            payment_id,
            year,
            month,
            amount,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        payment_id,
        current.year,
        current.month,
        amount,
        now_text()
    ))

    con.commit()
    con.close()

    try:

        await query.edit_message_caption(

            caption=(

                "✅ تم تأكيد الدفع\n\n"

                f"🆔 الطلب: #{payment_id}\n"
                f"💰 المبلغ: {amount} جنيه\n"
                f"📅 من: {start_date.strftime('%Y/%m/%d')}\n"
                f"📅 إلى: {end_date.strftime('%Y/%m/%d')}"

            )

        )

    except Exception:
        pass

    try:

        await context.bot.send_message(

            chat_id=user_id,

            text=(

                "🎉 تم تأكيد اشتراكك بنجاح!\n\n"

                f"💰 المبلغ: {amount} جنيه\n"

                f"📅 يبدأ: "
                f"{start_date.strftime('%Y/%m/%d')}\n"

                f"📅 ينتهي: "
                f"{end_date.strftime('%Y/%m/%d')}\n\n"

                "💜 شكراً لاشتراكك."

            )

        )

    except Exception:
        pass


# =========================================================
# SHOW USERS
# =========================================================

async def show_users(update, rows, title):

    query = update.callback_query

    if not rows:

        await query.message.reply_text(
            f"{title}\n\nلا يوجد مستخدمون."
        )

        return

    text = f"{title}\n\n"

    for i, row in enumerate(rows, 1):

        user_id = row[0]
        username = row[1]
        first_name = row[2]
        start = row[3]
        end = row[4]
        paid = row[5]

        name = (
            f"@{username}"
            if username
            else first_name or "بدون اسم"
        )

        status = "✅" if paid else "❌"

        text += (

            f"{i}. {status} {name}\n"
            f"🆔 {user_id}\n"
            f"📅 {format_date(start)} → "
            f"{format_date(end)}\n\n"

        )

        if len(text) > 3500:

            await query.message.reply_text(text)

            text = ""

    if text:
        await query.message.reply_text(text)


# =========================================================
# REPORTS
# =========================================================

def report_month_keyboard():

    current = now()

    buttons = []

    for i in range(12):

        index = current.month - 1 - i

        year = current.year + index // 12

        month = index % 12 + 1

        buttons.append([

            InlineKeyboardButton(

                f"{month:02d}/{year}",

                callback_data=f"month_{year}_{month}"

            )

        ])

    buttons.append([

        InlineKeyboardButton(
            "🔙 رجوع",
            callback_data="admin_home"
        )

    ])

    return InlineKeyboardMarkup(buttons)


def month_stats(year, month):

    con = db()
    cur = con.cursor()

    cur.execute("""
        SELECT
            COUNT(DISTINCT user_id),
            COALESCE(SUM(amount), 0)
        FROM monthly_payments
        WHERE year=? AND month=?
    """, (
        year,
        month
    ))

    paid_count, total = cur.fetchone()

    cur.execute(
        "SELECT COUNT(*) FROM users"
    )

    all_count = cur.fetchone()[0]

    unpaid_count = max(
        0,
        all_count - paid_count
    )

    con.close()

    return (
        all_count,
        paid_count,
        unpaid_count,
        total
    )


def month_paid_users(year, month):

    con = db()
    cur = con.cursor()

    cur.execute("""
        SELECT DISTINCT
            u.user_id,
            u.username,
            u.first_name,
            mp.amount
        FROM monthly_payments mp
        LEFT JOIN users u
            ON u.user_id=mp.user_id
        WHERE mp.year=? AND mp.month=?
        ORDER BY u.username
    """, (
        year,
        month
    ))

    rows = cur.fetchall()

    con.close()

    return rows


def month_unpaid_users(year, month):

    con = db()
    cur = con.cursor()

    cur.execute("""
        SELECT
            u.user_id,
            u.username,
            u.first_name
        FROM users u
        WHERE NOT EXISTS (
            SELECT 1
            FROM monthly_payments mp
            WHERE mp.user_id=u.user_id
              AND mp.year=?
              AND mp.month=?
        )
        ORDER BY u.username
    """, (
        year,
        month
    ))

    rows = cur.fetchall()

    con.close()

    return rows


async def reports_menu(update, context):

    query = update.callback_query

    await query.edit_message_text(

        "📊 اختر الشهر:",

        reply_markup=report_month_keyboard()

    )


async def month_report(update, context):

    query = update.callback_query

    await query.answer()

    match = re.fullmatch(
        r"month_(\d{4})_(\d{1,2})",
        query.data
    )

    if not match:
        return

    year = int(match.group(1))
    month = int(match.group(2))

    (
        all_count,
        paid_count,
        unpaid_count,
        total
    ) = month_stats(
        year,
        month
    )

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(

                f"👥 كل التجار ({all_count})",

                callback_data=
                f"m_all_{year}_{month}"

            )
        ],

        [
            InlineKeyboardButton(

                f"✅ دفعوا ({paid_count})",

                callback_data=
                f"m_paid_{year}_{month}"

            )
        ],

        [
            InlineKeyboardButton(

                f"❌ ما دفعوش ({unpaid_count})",

                callback_data=
                f"m_unpaid_{year}_{month}"

            )
        ],

        [
            InlineKeyboardButton(

                f"💰 الإجمالي: {total} جنيه",

                callback_data=
                f"m_total_{year}_{month}"

            )
        ],

        [
            InlineKeyboardButton(
                "🔙 رجوع",
                callback_data="reports"
            )
        ],
    ])

    await query.edit_message_text(

        f"📊 تقرير شهر {month:02d}/{year}\n\n"

        f"👥 إجمالي التجار: {all_count}\n"
        f"✅ دفعوا: {paid_count}\n"
        f"❌ ما دفعوش: {unpaid_count}\n"
        f"💰 إجمالي المدفوع: {total} جنيه",

        reply_markup=keyboard
    )


async def month_details(update, context):

    query = update.callback_query

    await query.answer()

    parts = query.data.split("_")

    kind = parts[1]

    year = int(parts[2])

    month = int(parts[3])

    title = (
        f"📅 شهر {month:02d}/{year}\n\n"
    )

    # -----------------------------------------------------
    # PAID
    # -----------------------------------------------------

    if kind == "paid":

        rows = month_paid_users(
            year,
            month
        )

        if not rows:

            await query.message.reply_text(

                title +
                "لا يوجد أشخاص دفعوا."

            )

            return

        text = title

        for i, row in enumerate(rows, 1):

            user_id = row[0]
            username = row[1]
            first_name = row[2]
            amount = row[3]

            name = (
                f"@{username}"
                if username
                else first_name or "بدون اسم"
            )

            text += (

                f"{i}. ✅ {name}\n"
                f"🆔 {user_id}\n"
                f"💰 {amount} جنيه\n\n"

            )

        await query.message.reply_text(text)

        return

    # -----------------------------------------------------
    # UNPAID
    # -----------------------------------------------------

    if kind == "unpaid":

        rows = month_unpaid_users(
            year,
            month
        )

        if not rows:

            await query.message.reply_text(

                title +
                "كل التجار دفعوا. ✅"

            )

            return

        text = title

        for i, row in enumerate(rows, 1):

            user_id = row[0]
            username = row[1]
            first_name = row[2]

            name = (
                f"@{username}"
                if username
                else first_name or "بدون اسم"
            )

            text += (

                f"{i}. ❌ {name}\n"
                f"🆔 {user_id}\n\n"

            )

        await query.message.reply_text(text)

        return

    # -----------------------------------------------------
    # ALL
    # -----------------------------------------------------

    if kind == "all":

        await show_users(

            update,

            get_all_users(),

            f"👥 كل التجار - "
            f"{month:02d}/{year}"

        )

        return

    # -----------------------------------------------------
    # TOTAL
    # -----------------------------------------------------

    if kind == "total":

        _, paid, _, total = month_stats(
            year,
            month
        )

        await query.message.reply_text(

            f"💰 تقرير {month:02d}/{year}\n\n"

            f"👥 عدد المدفوعات: {paid}\n"
            f"💵 الإجمالي: {total} جنيه"

        )


# =========================================================
# ADMIN MANAGEMENT
# =========================================================

async def manage_admins(update, context):

    query = update.callback_query

    if not is_master(query.from_user.id):

        await query.answer(
            "❌ الماستر فقط.",
            show_alert=True
        )

        return

    admins = get_admins()

    text = "👑 قائمة الأدمنية\n\n"

    for i, admin in enumerate(admins, 1):

        user_id = admin[0]

        username = admin[1]

        role = (
            "👑 Master"
            if user_id == MASTER_ADMIN_ID
            else "🛡 Admin"
        )

        name = (
            f"@{username}"
            if username
            else str(user_id)
        )

        text += (

            f"{i}. {role}\n"
            f"{name}\n"
            f"🆔 {user_id}\n\n"

        )

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "➕ إضافة أدمن",
                callback_data="add_admin"
            )
        ],

        [
            InlineKeyboardButton(
                "🗑 حذف أدمن",
                callback_data="delete_admin"
            )
        ],

        [
            InlineKeyboardButton(
                "🔙 رجوع",
                callback_data="admin_home"
            )
        ],
    ])

    await query.edit_message_text(

        text,

        reply_markup=keyboard

    )


async def admin_management_action(update, context):

    query = update.callback_query

    if not is_master(query.from_user.id):

        await query.answer(
            "❌ الماستر فقط.",
            show_alert=True
        )

        return

    await query.answer()

    if query.data == "add_admin":

        context.user_data["admin_state"] = "add_admin"

        await query.message.reply_text(

            "👑 أرسل Telegram ID للأدمن الجديد."

        )

    elif query.data == "delete_admin":

        context.user_data["admin_state"] = "delete_admin"

        await query.message.reply_text(

            "🗑 أرسل Telegram ID للأدمن الذي تريد حذفه."

        )


# =========================================================
# CALLBACK ROUTER
# =========================================================

async def callback_router(update, context):

    query = update.callback_query

    data = query.data

    # Plans
    if re.fullmatch(
        r"plan_(1|2|3|6|12)",
        data
    ):

        await plan_callback(
            update,
            context
        )

        return

    # Payment start
    if data == "paid_start":

        await paid_start(
            update,
            context
        )

        return

    # Approve / reject
    if re.fullmatch(
        r"(approve|reject)_\d+",
        data
    ):

        await payment_action(
            update,
            context
        )

        return

    # Month
    if re.fullmatch(
        r"month_\d{4}_\d{1,2}",
        data
    ):

        await month_report(
            update,
            context
        )

        return

    # Month details
    if re.fullmatch(
        r"m_(all|paid|unpaid|total)_\d{4}_\d{1,2}",
        data
    ):

        await month_details(
            update,
            context
        )

        return

    # Admin protection
    if not is_admin(query.from_user.id):

        await query.answer(
            "❌ غير مسموح.",
            show_alert=True
        )

        return

    await query.answer()

    # Admin home
    if data == "admin_home":

        await query.edit_message_text(

            "👑 لوحة التحكم\n\n"
            "اختر العملية المطلوبة:",

            reply_markup=admin_keyboard()

        )

        return

    # Back
    if data == "back_start":

        await query.message.reply_text(
            "استخدم /start للعودة."
        )

        return

    # All users
    if data == "all_users":

        await show_users(
            update,
            get_all_users(),
            "👥 كل التجار"
        )

        return

    # Paid users
    if data == "paid_users":

        await show_users(
            update,
            get_paid_users(),
            "✅ المشتركين"
        )

        return

    # Unpaid users
    if data == "unpaid_users":

        await show_users(
            update,
            get_unpaid_users(),
            "❌ غير المشتركين"
        )

        return

    # Reports
    if data == "reports":

        await reports_menu(
            update,
            context
        )

        return

    # Add user
    if data == "add_user":

        context.user_data["admin_state"] = "add_user"

        await query.message.reply_text(

            "➕ أرسل Telegram ID للتاجر."

        )

        return

    # Delete user
    if data == "delete_user":

        context.user_data["admin_state"] = "delete_user"

        await query.message.reply_text(

            "🗑 أرسل Telegram ID للتاجر."

        )

        return

    # Cancel subscription
    if data == "cancel_sub":

        context.user_data["admin_state"] = "cancel_sub"

        await query.message.reply_text(

            "🚫 أرسل Telegram ID لإلغاء اشتراكه."

        )

        return

    # Broadcast all
    if data == "broadcast_all":

        context.user_data["admin_state"] = "broadcast_all"

        await query.message.reply_text(

            "📢 أرسل الرسالة."

        )

        return

    # Broadcast paid
    if data == "broadcast_paid":

        context.user_data["admin_state"] = "broadcast_paid"

        await query.message.reply_text(

            "📢 أرسل الرسالة للمشتركين."

        )

        return

    # Broadcast unpaid
    if data == "broadcast_unpaid":

        context.user_data["admin_state"] = "broadcast_unpaid"

        await query.message.reply_text(

            "📢 أرسل الرسالة لغير المشتركين."

        )

        return

    # Manage admins
    if data == "manage_admins":

        await manage_admins(
            update,
            context
        )

        return

    # Add / delete admin
    if data in (
        "add_admin",
        "delete_admin"
    ):

        await admin_management_action(
            update,
            context
        )


# =========================================================
# REMINDER LOOP
# =========================================================

async def reminder_loop(application):

    while True:

        try:

            await asyncio.sleep(3600)

            con = db()
            cur = con.cursor()

            cur.execute("""
                SELECT
                    user_id,
                    subscription_end,
                    reminder_sent
                FROM users
                WHERE paid=1
                  AND subscription_end IS NOT NULL
            """)

            users = cur.fetchall()

            current = now()

            for (
                user_id,
                end_text,
                reminder_sent
            ) in users:

                try:

                    end_date = datetime.fromisoformat(
                        end_text
                    )

                except Exception:

                    continue

                remaining = (
                    end_date - current
                )

                # انتهى
                if remaining.total_seconds() <= 0:

                    cur.execute("""
                        UPDATE users
                        SET paid=0
                        WHERE user_id=?
                    """, (
                        user_id,
                    ))

                    try:

                        await application.bot.send_message(

                            chat_id=user_id,

                            text=(

                                "❌ انتهى اشتراكك.\n\n"
                                "للتجديد اضغط /start"

                            )

                        )

                    except Exception:
                        pass

                    continue

                # خلال 3 أيام
                if remaining <= timedelta(days=3):

                    today = current.strftime(
                        "%Y-%m-%d"
                    )

                    if reminder_sent != today:

                        try:

                            await application.bot.send_message(

                                chat_id=user_id,

                                text=(

                                    "⚠️ اشتراكك هينتهي "
                                    "خلال 3 أيام.\n\n"

                                    "للتجديد اضغط /start"

                                )

                            )

                        except Exception:
                            pass

                        cur.execute("""
                            UPDATE users
                            SET reminder_sent=?
                            WHERE user_id=?
                        """, (
                            today,
                            user_id
                        ))

            con.commit()
            con.close()

        except Exception as e:

            logging.error(
                f"Reminder error: {e}"
            )


# =========================================================
# POST INIT
# =========================================================

async def post_init(application):

    asyncio.create_task(
        reminder_loop(application)
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not TOKEN:

        print(
            "❌ BOT_TOKEN غير موجود."
        )

        print(
            "ضع التوكن في Environment Variable "
            "باسم BOT_TOKEN."
        )

        return

    setup_database()

    application = (

        Application.builder()

        .token(TOKEN)

        .post_init(post_init)

        .build()

    )

    # /start
    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    # Buttons
    application.add_handler(
        CallbackQueryHandler(
            callback_router
        )
    )

    # Photos
    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo_message
        )
    )

    # Text
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text_message
        )
    )

    print("==============================")
    print("✅ البوت يعمل الآن")
    print(
        f"👑 Master Admin: "
        f"{MASTER_ADMIN_ID}"
    )
    print(
        f"💜 Vodafone: "
        f"{VODAFONE_NUMBER}"
    )
    print("📅 Monthly Reports: ON")
    print("==============================")

    application.run_polling(
        drop_pending_updates=True
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
