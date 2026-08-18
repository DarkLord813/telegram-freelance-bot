#!/usr/bin/env python3

import logging
import os
import json
import base64
import urllib.request
import urllib.parse
import threading
import shutil
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import asyncio
import re

load_dotenv()

class Config:
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '').split(',') if id.strip()]
    REPORT_THRESHOLD = 5
    UNBAN_FEE = 50
    
    # YOUR Telegram account details
    RECEIVER_USERNAME = 'rexoronsaye'
    RECEIVER_TELEGRAM_ID = 7713987088
    
    # GitHub Backup Configuration
    GITHUB_TOKEN = os.getenv('GITHUB_TOKEN', '')
    GITHUB_REPO_OWNER = os.getenv('GITHUB_REPO_OWNER', '')
    GITHUB_REPO_NAME = os.getenv('GITHUB_REPO_NAME', '')
    GITHUB_BACKUP_BRANCH = os.getenv('GITHUB_BACKUP_BRANCH', 'main')
    GITHUB_BACKUP_PATH = os.getenv('GITHUB_BACKUP_PATH', 'backups/freelance_bot.db')
    GITHUB_ENABLED = bool(GITHUB_TOKEN and GITHUB_REPO_OWNER and GITHUB_REPO_NAME)
    
    FORCE_JOIN_CHANNELS = [
        {'username': 'PulseProfit012', 'id': -1003931660594, 'url': 'https://t.me/PulseProfit012'},
        {'username': 'moneyplugngx', 'id': -1004466219117, 'url': 'https://t.me/moneyplugngx'},
        {'username': 'aidropupdatesx', 'id': -1004412219960, 'url': 'https://t.me/aidropupdatesx'},
        {'username': 'PulseProfitWithdrawals', 'id': -1004322387526, 'url': 'https://t.me/PulseProfitWithdrawals'}
    ]
    
    CURRENCIES = {
        'USD': {'symbol': '$', 'name': 'US Dollar', 'emoji': '🇺🇸'},
        'EUR': {'symbol': '€', 'name': 'Euro', 'emoji': '🇪🇺'},
        'GBP': {'symbol': '£', 'name': 'British Pound', 'emoji': '🇬🇧'},
        'NGN': {'symbol': '₦', 'name': 'Nigerian Naira', 'emoji': '🇳🇬'},
        'CAD': {'symbol': 'C$', 'name': 'Canadian Dollar', 'emoji': '🇨🇦'},
        'AUD': {'symbol': 'A$', 'name': 'Australian Dollar', 'emoji': '🇦🇺'},
        'INR': {'symbol': '₹', 'name': 'Indian Rupee', 'emoji': '🇮🇳'},
        'JPY': {'symbol': '¥', 'name': 'Japanese Yen', 'emoji': '🇯🇵'},
        'CNY': {'symbol': '¥', 'name': 'Chinese Yuan', 'emoji': '🇨🇳'},
        'BRL': {'symbol': 'R$', 'name': 'Brazilian Real', 'emoji': '🇧🇷'},
        'ZAR': {'symbol': 'R', 'name': 'South African Rand', 'emoji': '🇿🇦'},
        'KES': {'symbol': 'KSh', 'name': 'Kenyan Shilling', 'emoji': '🇰🇪'},
        'GHS': {'symbol': '₵', 'name': 'Ghanaian Cedi', 'emoji': '🇬🇭'},
        'EGP': {'symbol': 'E£', 'name': 'Egyptian Pound', 'emoji': '🇪🇬'},
    }
    DEFAULT_CURRENCY = 'USD'

# ==================== DATABASE SETUP ====================

DATABASE_FILE = Path('freelance_bot.db')
Base = declarative_base()
engine = create_engine(f'sqlite:///{DATABASE_FILE}')
Session = sessionmaker(bind=engine)

# ==================== GITHUB BACKUP SYSTEM ====================

_github_push_lock = threading.Lock()
_last_backup_time = 0.0
_MIN_BACKUP_INTERVAL = 30

def _gh_api(method, path, payload=None):
    """Raw GitHub Contents API call. Returns (http_status, response_dict)."""
    if not Config.GITHUB_ENABLED:
        return 0, {"error": "GitHub not configured"}
    
    url = (f"https://api.github.com/repos/{Config.GITHUB_REPO_OWNER}/"
           f"{Config.GITHUB_REPO_NAME}/contents/{path}")
    headers = {
        "Authorization": f"Bearer {Config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except:
            return e.code, {}
    except Exception as ex:
        return 0, {"error": str(ex)}

def _db_has_data():
    """Return True only when the database contains real rows."""
    if not DATABASE_FILE.exists():
        return False
    if DATABASE_FILE.stat().st_size < 8192:
        return False
    try:
        conn = sqlite3.connect(str(DATABASE_FILE))
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM jobs")
        jobs = c.fetchone()[0]
        conn.close()
        return users > 0 or jobs > 0
    except Exception:
        return False

def github_restore_db():
    """
    Download the database from GitHub and write to freelance_bot.db.
    Called automatically on startup.
    """
    if not Config.GITHUB_ENABLED:
        print("ℹ️ GitHub backup not configured — skipping restore")
        return False

    print(f"🔄 Restoring from GitHub → "
          f"{Config.GITHUB_REPO_OWNER}/{Config.GITHUB_REPO_NAME}/{Config.GITHUB_BACKUP_PATH}")

    status, resp = _gh_api("GET", Config.GITHUB_BACKUP_PATH)

    if status == 404:
        print("ℹ️ No backup found on GitHub — starting fresh")
        return False
    if status != 200:
        print(f"⚠️ GitHub restore HTTP {status}: {resp.get('message', resp)}")
        return False

    try:
        raw_b64 = resp.get("content", "").replace("\n", "")
        db_bytes = base64.b64decode(raw_b64)

        if len(db_bytes) < 1024:
            print("⚠️ GitHub backup is too small — skipping restore")
            return False

        # Close any open connections
        Session.close_all()
        
        with open(DATABASE_FILE, "wb") as f:
            f.write(db_bytes)

        size_kb = len(db_bytes) / 1024
        print(f"✅ Database restored from GitHub ({size_kb:.1f} KB)")
        return True
    except Exception as e:
        print(f"❌ GitHub restore error: {e}")
        return False

def github_backup_db(reason: str = "auto", force: bool = False):
    """
    Upload freelance_bot.db to GitHub. Thread-safe via push lock.
    """
    global _last_backup_time

    if not Config.GITHUB_ENABLED:
        return False
    if not _db_has_data():
        print(f"⏭️ Backup skipped ({reason}): database has no data")
        return False

    now = time.time()
    if not force and now - _last_backup_time < _MIN_BACKUP_INTERVAL:
        return False

    if force:
        acquired = _github_push_lock.acquire(blocking=True, timeout=15)
    else:
        acquired = _github_push_lock.acquire(blocking=False)
    if not acquired:
        return False

    try:
        with open(DATABASE_FILE, "rb") as f:
            db_bytes = f.read()

        if len(db_bytes) < 1024:
            return False

        content_b64 = base64.b64encode(db_bytes).decode()

        sha = None
        status, resp = _gh_api("GET", Config.GITHUB_BACKUP_PATH)
        if status == 200:
            sha = resp.get("sha")
        elif status not in (200, 404):
            print(f"⚠️ GitHub SHA lookup failed (HTTP {status})")
            return False

        commit = {
            "message": f"backup: {reason} — {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "content": content_b64,
            "branch": Config.GITHUB_BACKUP_BRANCH,
        }
        if sha:
            commit["sha"] = sha

        status, resp = _gh_api("PUT", Config.GITHUB_BACKUP_PATH, commit)

        if status in (200, 201):
            _last_backup_time = time.time()
            print(f"✅ DB backed up to GitHub ({len(db_bytes)/1024:.1f} KB) — {reason}")
            return True
        else:
            print(f"⚠️ GitHub backup HTTP {status}: {resp.get('message', resp)}")
            return False

    except Exception as e:
        print(f"❌ GitHub backup error: {e}")
        return False
    finally:
        _github_push_lock.release()

def async_backup(reason: str = "auto"):
    """Fire-and-forget backup."""
    if Config.GITHUB_ENABLED:
        threading.Thread(
            target=github_backup_db, args=(reason,),
            daemon=True, name="GitHubBackup"
        ).start()

def _periodic_backup_thread():
    """Safety-net: flush a backup every 30 minutes."""
    time.sleep(300)
    while True:
        try:
            github_backup_db("periodic")
        except Exception as e:
            print(f"⚠️ Periodic backup error: {e}")
        time.sleep(1800)

# ==================== DATABASE MODELS ====================

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True)
    username = Column(String, nullable=True)
    full_name = Column(String)
    role = Column(String, default='freelancer')
    currency = Column(String, default='USD')
    contact_method = Column(String, default='telegram')
    contact_info = Column(String, nullable=True)
    is_banned = Column(Boolean, default=False)
    ban_reason = Column(String, nullable=True)
    ban_count = Column(Integer, default=0)
    report_count = Column(Integer, default=0)
    warning_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

class Job(Base):
    __tablename__ = 'jobs'
    id = Column(Integer, primary_key=True)
    poster_id = Column(Integer, ForeignKey('users.telegram_id'))
    title = Column(String)
    description = Column(Text)
    category = Column(String)
    currency = Column(String, default='USD')
    budget_min = Column(Float, default=0)
    budget_max = Column(Float, default=0)
    contact_method = Column(String)
    contact_info = Column(String)
    is_active = Column(Boolean, default=True)
    is_completed = Column(Boolean, default=False)
    freelancer_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    completed_at = Column(DateTime, nullable=True)

class Rating(Base):
    __tablename__ = 'ratings'
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey('jobs.id'))
    reviewer_id = Column(Integer, ForeignKey('users.telegram_id'))
    reviewee_id = Column(Integer, ForeignKey('users.telegram_id'))
    rating = Column(Integer)
    review = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class Report(Base):
    __tablename__ = 'reports'
    id = Column(Integer, primary_key=True)
    reporter_id = Column(Integer, ForeignKey('users.telegram_id'))
    reported_id = Column(Integer, ForeignKey('users.telegram_id'))
    job_id = Column(Integer, ForeignKey('jobs.id'), nullable=True)
    reason = Column(Text)
    status = Column(String, default='pending')
    warning_sent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(Integer, nullable=True)

class UnbanPayment(Base):
    __tablename__ = 'unban_payments'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.telegram_id'))
    amount = Column(Integer, default=50)
    gift_id = Column(String, nullable=True)
    status = Column(String, default='pending')
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

class BroadcastMessage(Base):
    __tablename__ = 'broadcast_messages'
    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer)
    message_type = Column(String)
    caption = Column(Text, nullable=True)
    file_id = Column(String, nullable=True)
    button_text = Column(String, nullable=True)
    button_url = Column(String, nullable=True)
    sent_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

def init_db():
    """Create tables if they don't exist."""
    Base.metadata.create_all(engine)

# ==================== CONVERSATION STATES ====================

TITLE, DESCRIPTION, CATEGORY, CURRENCY, BUDGET_MIN, BUDGET_MAX, CONTACT_METHOD, CONTACT_INFO = range(8)
RATING_SCORE, RATING_REVIEW = range(2)
REPORT_REASON = range(1)
BROADCAST_PHOTO, BROADCAST_CAPTION, BROADCAST_BUTTONS = range(3)
UNBAN_PAYMENT = range(1)
SEARCH_USERS = range(1)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class FreelanceBot:
    def __init__(self):
        # Restore from GitHub FIRST before anything else
        print("=" * 60)
        print("🔍 Checking for GitHub backup...")
        restore_success = github_restore_db()
        if restore_success:
            print("✅ Database restored from GitHub")
        else:
            print("ℹ️ No backup found or restore skipped — using existing/local DB")
        print("=" * 60)
        
        # Now initialize database
        init_db()
        
        # Start periodic backup thread
        threading.Thread(target=_periodic_backup_thread, daemon=True, name="PeriodicBackup").start()
        
        self.application = Application.builder().token(Config.BOT_TOKEN).build()
        self.setup_handlers()
        logger.info("Bot initialized successfully!")
        
    def setup_handlers(self):
        self.application.add_handler(CommandHandler('start', self.start))
        self.application.add_handler(CallbackQueryHandler(self.callback_handler))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.text_handler))
        self.application.add_handler(MessageHandler(filters.PHOTO, self.photo_handler))

    # ==================== CHECK FORCE JOIN ====================
    async def check_force_join(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        for channel in Config.FORCE_JOIN_CHANNELS:
            try:
                member = await context.bot.get_chat_member(chat_id=channel['id'], user_id=user_id)
                if member.status not in ['member', 'administrator', 'creator']:
                    keyboard = []
                    for ch in Config.FORCE_JOIN_CHANNELS:
                        keyboard.append([InlineKeyboardButton(f"📢 Join {ch['username']}", url=ch['url'])])
                    keyboard.append([InlineKeyboardButton("✅ I've Joined All", callback_data="check_joined")])
                    
                    if update.message:
                        await update.message.reply_text(
                            "⚠️ <b>Please join our channels first!</b>\n\n"
                            "You need to join all channels to use this bot.\n"
                            "Click the buttons below to join each channel:\n\n"
                            "After joining all, click <b>'I've Joined All'</b> to continue.",
                            parse_mode='HTML',
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                    else:
                        await update.callback_query.edit_message_text(
                            "⚠️ <b>Please join our channels first!</b>\n\n"
                            "You need to join all channels to use this bot.\n"
                            "Click the buttons below to join each channel:\n\n"
                            "After joining all, click <b>'I've Joined All'</b> to continue.",
                            parse_mode='HTML',
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                    return False
            except Exception as e:
                logger.error(f"Force join check error for {channel['username']}: {e}")
                continue
        
        return True

    # ==================== MAIN MENU ====================
    def get_main_menu(self, is_admin=False):
        keyboard = [
            [InlineKeyboardButton("📋 Browse Jobs", callback_data="browse_jobs")],
            [InlineKeyboardButton("💰 Post a Job", callback_data="post_job")],
            [InlineKeyboardButton("👤 My Profile", callback_data="my_profile")],
            [InlineKeyboardButton("📂 My Jobs", callback_data="my_jobs")],
            [InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
            [InlineKeyboardButton("❓ Help", callback_data="help")]
        ]
        if is_admin:
            keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel")])
        return InlineKeyboardMarkup(keyboard)

    # ==================== ADMIN MENU ====================
    def get_admin_menu(self):
        keyboard = [
            [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
            [InlineKeyboardButton("📢 Send Broadcast", callback_data="admin_broadcast")],
            [InlineKeyboardButton("📋 Pending Reports", callback_data="admin_reports")],
            [InlineKeyboardButton("💰 Pending Unban Payments", callback_data="admin_payments")],
            [InlineKeyboardButton("👥 All Users", callback_data="admin_users")],
            [InlineKeyboardButton("🔍 Search Users", callback_data="admin_search_users")],
            [InlineKeyboardButton("🔓 Unban User", callback_data="admin_unban")],
            [InlineKeyboardButton("💾 Backup to GitHub", callback_data="admin_backup")],
            [InlineKeyboardButton("📥 Restore from GitHub", callback_data="admin_restore")],
            [InlineKeyboardButton("📤 Download DB File", callback_data="admin_download_db")],
            [InlineKeyboardButton("🏠 Back to Main Menu", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    # ==================== SETTINGS MENUS ====================
    def get_settings_menu(self, user):
        role_emoji = "💼" if user.role == "client" else "💻" if user.role == "freelancer" else "🔀"
        currency_info = Config.CURRENCIES.get(user.currency, Config.CURRENCIES['USD'])
        
        keyboard = [
            [InlineKeyboardButton(f"{role_emoji} Role: {user.role.title()}", callback_data="change_role")],
            [InlineKeyboardButton(f"{currency_info['emoji']} Currency: {user.currency}", callback_data="change_currency")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    def get_role_keyboard(self):
        keyboard = [
            [InlineKeyboardButton("💼 Client - Post Jobs", callback_data="role_client")],
            [InlineKeyboardButton("💻 Freelancer - Find Work", callback_data="role_freelancer")],
            [InlineKeyboardButton("🔀 Both", callback_data="role_both")],
            [InlineKeyboardButton("🔙 Back", callback_data="settings")]
        ]
        return InlineKeyboardMarkup(keyboard)

    def get_currency_keyboard(self, selected=None):
        keyboard = []
        row = []
        for code, data in Config.CURRENCIES.items():
            emoji = data['emoji']
            symbol = data['symbol']
            label = f"{emoji} {code} ({symbol})"
            if selected and selected == code:
                label = f"✅ {label}"
            row.append(InlineKeyboardButton(label, callback_data=f"cur_{code}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="settings")])
        return InlineKeyboardMarkup(keyboard)

    def get_categories_keyboard(self):
        categories = [
            'Web Development', 'Mobile Development', 'Design & Creative',
            'Writing & Translation', 'Digital Marketing', 'Data Entry',
            'Virtual Assistant', 'Customer Support', 'Other'
        ]
        keyboard = []
        for cat in categories:
            keyboard.append([InlineKeyboardButton(cat, callback_data=f"cat_{cat}")])
        keyboard.append([InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")])
        return InlineKeyboardMarkup(keyboard)

    def get_contact_keyboard(self):
        keyboard = [
            [InlineKeyboardButton("📱 Telegram", callback_data="contact_method_telegram")],
            [InlineKeyboardButton("📧 Email", callback_data="contact_method_email")],
            [InlineKeyboardButton("📞 Phone", callback_data="contact_method_phone")],
            [InlineKeyboardButton("💬 Other", callback_data="contact_method_other")],
            [InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    def get_job_actions_keyboard(self, job_id, poster_id):
        keyboard = [
            [InlineKeyboardButton("📞 Contact Client", callback_data=f"contact_job_{job_id}")],
            [InlineKeyboardButton("📝 Rate Client", callback_data=f"rate_{poster_id}_{job_id}")],
            [InlineKeyboardButton("🚨 Report Scam", callback_data=f"report_{poster_id}_{job_id}")],
            [InlineKeyboardButton("🔙 Back to Browse", callback_data="browse_jobs")]
        ]
        return InlineKeyboardMarkup(keyboard)

    def get_reports_menu(self, reports):
        keyboard = []
        for report in reports[:10]:
            user = report[0]
            report_obj = report[1]
            keyboard.append([
                InlineKeyboardButton(
                    f"📋 Report #{report_obj.id} - {user.full_name[:20]}", 
                    callback_data=f"view_report_{report_obj.id}"
                )
            ])
        keyboard.append([InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")])
        return InlineKeyboardMarkup(keyboard)

    def get_payments_menu(self, payments):
        keyboard = []
        for payment in payments[:10]:
            user = payment[0]
            keyboard.append([
                InlineKeyboardButton(
                    f"💰 {user.full_name[:20]} - {payment.amount} Stars", 
                    callback_data=f"view_payment_{payment.id}"
                )
            ])
        keyboard.append([InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")])
        return InlineKeyboardMarkup(keyboard)

    def get_users_menu(self, users, page=0, total_pages=1, search_term=""):
        keyboard = []
        for user in users:
            status = "🚫" if user.is_banned else "✅"
            keyboard.append([
                InlineKeyboardButton(
                    f"{status} {user.full_name[:20]} (@{user.username or 'No username'})", 
                    callback_data=f"view_user_{user.telegram_id}"
                )
            ])
        
        # Pagination buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"users_page_{page-1}_{search_term}"))
        nav_buttons.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"users_page_{page+1}_{search_term}"))
        if nav_buttons:
            keyboard.append(nav_buttons)
        
        keyboard.append([InlineKeyboardButton("🔍 Search Users", callback_data="admin_search_users")])
        keyboard.append([InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")])
        return InlineKeyboardMarkup(keyboard)

    def get_user_actions_menu(self, user_id):
        keyboard = [
            [InlineKeyboardButton("🔓 Unban User", callback_data=f"unban_user_{user_id}")],
            [InlineKeyboardButton("🚫 Ban User", callback_data=f"ban_user_{user_id}")],
            [InlineKeyboardButton("🔙 Back to Users", callback_data="admin_users")]
        ]
        return InlineKeyboardMarkup(keyboard)

    # ==================== START ====================
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        
        if not await self.check_force_join(update, context):
            return
        
        session = Session()
        db_user = session.query(User).filter_by(telegram_id=user.id).first()
        is_admin = user.id in Config.ADMIN_IDS
        
        if db_user and db_user.is_banned:
            await update.message.reply_text(
                f"🚫 <b>You are BANNED from this bot!</b>\n\n"
                f"Reason: {db_user.ban_reason or 'Multiple scam reports'}\n"
                f"This is your {db_user.ban_count + 1} ban.\n\n"
                f"💰 <b>To unban, send {Config.UNBAN_FEE} Stars as a gift to:</b>\n"
                f"<b>@{Config.RECEIVER_USERNAME}</b>\n\n"
                "<b>Instructions:</b>\n"
                "1. Click the button below to send Stars\n"
                f"2. Send exactly {Config.UNBAN_FEE} Stars\n"
                "3. Click 'I've Sent the Stars' button after sending\n\n"
                "⚠️ You'll be unbanned after admin confirmation.",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"⭐ Send {Config.UNBAN_FEE} Stars", url=f"https://t.me/{Config.RECEIVER_USERNAME}")],
                    [InlineKeyboardButton("✅ I've Sent the Stars", callback_data="pay_unban")],
                    [InlineKeyboardButton("🔄 Check Payment Status", callback_data="check_payment")]
                ])
            )
            session.close()
            return
        
        if not db_user:
            db_user = User(
                telegram_id=user.id,
                username=user.username,
                full_name=user.full_name
            )
            session.add(db_user)
            session.commit()
            
            await update.message.reply_text(
                f"👋 <b>Welcome to FreelanceHub, {user.full_name}!</b>\n\n"
                "Use the buttons below to navigate:",
                parse_mode='HTML',
                reply_markup=self.get_main_menu(is_admin)
            )
        else:
            currency_info = Config.CURRENCIES.get(db_user.currency, Config.CURRENCIES['USD'])
            role_emoji = "💼" if db_user.role == "client" else "💻" if db_user.role == "freelancer" else "🔀"
            
            await update.message.reply_text(
                f"👋 <b>Welcome back, {user.full_name}!</b>\n\n"
                f"{role_emoji} Role: {db_user.role.title()}\n"
                f"{currency_info['emoji']} Currency: {db_user.currency} ({currency_info['symbol']})\n"
                f"⭐ Rating: {self.get_average_rating(user.id):.1f}/5.0\n"
                f"📊 Reports: {db_user.report_count}/{Config.REPORT_THRESHOLD}\n\n"
                "Select an option below:",
                parse_mode='HTML',
                reply_markup=self.get_main_menu(is_admin)
            )
        session.close()

    # ==================== ADMIN USER SEARCH ====================
    async def admin_search_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in Config.ADMIN_IDS:
            await update.callback_query.edit_message_text("❌ You are not an admin.")
            return
        
        context.user_data['search_users'] = True
        
        await update.callback_query.edit_message_text(
            "🔍 <b>Search Users</b>\n\n"
            "Enter a name or username to search for:\n"
            "(Partial matches are supported)\n\n"
            "Examples:\n"
            "• `John` - finds users with 'John' in name\n"
            "• `@john_doe` - finds users with username\n"
            "• `123456789` - finds by Telegram ID",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Cancel", callback_data="admin_panel")]
            ])
        )

    async def handle_user_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in Config.ADMIN_IDS:
            await update.message.reply_text("❌ You are not an admin.")
            return
        
        search_term = update.message.text.strip()
        
        session = Session()
        
        # Search by name, username, or telegram_id
        query = session.query(User)
        
        if search_term.isdigit():
            # Search by Telegram ID
            query = query.filter(User.telegram_id == int(search_term))
        else:
            # Search by name or username (case-insensitive)
            search_pattern = f"%{search_term}%"
            query = query.filter(
                (User.full_name.ilike(search_pattern)) | 
                (User.username.ilike(search_pattern))
            )
        
        # Limit results
        results = query.limit(50).all()
        session.close()
        
        if not results:
            await update.message.reply_text(
                f"❌ No users found matching '<b>{search_term}</b>'\n\n"
                "Try a different search term.",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔍 Search Again", callback_data="admin_search_users")],
                    [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]
                ])
            )
            return
        
        # Build results message
        message = f"🔍 <b>Search Results</b>\n\n"
        message += f"Found <b>{len(results)}</b> user(s) matching '<b>{search_term}</b>':\n\n"
        
        for user in results:
            status = "🚫" if user.is_banned else "✅"
            username = f"@{user.username}" if user.username else "No username"
            message += f"{status} <b>{user.full_name}</b>\n"
            message += f"   ID: <code>{user.telegram_id}</code>\n"
            message += f"   Username: {username}\n"
            message += f"   Role: {user.role.title()}\n"
            message += f"   Reports: {user.report_count}\n\n"
        
        # Create user buttons for each result (max 10 to avoid message length issues)
        keyboard = []
        for user in results[:10]:
            keyboard.append([
                InlineKeyboardButton(
                    f"{'🚫' if user.is_banned else '✅'} {user.full_name[:25]}", 
                    callback_data=f"view_user_{user.telegram_id}"
                )
            ])
        keyboard.append([InlineKeyboardButton("🔍 Search Again", callback_data="admin_search_users")])
        keyboard.append([InlineKeyboardButton("👥 All Users", callback_data="admin_users")])
        keyboard.append([InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")])
        
        await update.message.reply_text(
            message[:4000],  # Telegram message limit
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    # ==================== TEXT HANDLER ====================
    async def text_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        user_id = update.effective_user.id
        is_admin = user_id in Config.ADMIN_IDS
        
        # Handle user search
        if context.user_data.get('search_users'):
            await self.handle_user_search(update, context)
            context.user_data['search_users'] = False
            return
        
        # Handle job posting
        if context.user_data.get('posting_job'):
            step = context.user_data.get('step')
            
            if step == 'title':
                context.user_data['title'] = text
                context.user_data['step'] = 'description'
                await update.message.reply_text(
                    "Great! Now enter a <b>description</b> of the job:",
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]])
                )
            
            elif step == 'description':
                context.user_data['description'] = text
                context.user_data['step'] = 'category'
                await update.message.reply_text(
                    "Choose a <b>category</b>:",
                    parse_mode='HTML',
                    reply_markup=self.get_categories_keyboard()
                )
            
            elif step == 'budget_min':
                try:
                    context.user_data['budget_min'] = float(text)
                except:
                    context.user_data['budget_min'] = 0
                context.user_data['step'] = 'budget_max'
                await update.message.reply_text(
                    "Enter the <b>maximum budget</b> (or type '0'):",
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]])
                )
            
            elif step == 'budget_max':
                try:
                    context.user_data['budget_max'] = float(text)
                except:
                    context.user_data['budget_max'] = 0
                context.user_data['step'] = 'contact_method'
                await update.message.reply_text(
                    "How should freelancers contact you?\n"
                    "Choose an option:",
                    reply_markup=self.get_contact_keyboard()
                )
            
            elif step == 'contact_info':
                await self.save_job(update, context, text)
        
        # Handle rating review
        elif context.user_data.get('rating'):
            if context.user_data.get('step') == 'review':
                await self.save_rating(update, context, text)
        
        # Handle report reason
        elif context.user_data.get('reporting'):
            await self.save_report(update, context, text)
        
        # Handle unban payment proof
        elif context.user_data.get('unban_payment'):
            await self.handle_unban_payment(update, context, text)
        
        # Handle broadcast
        elif context.user_data.get('broadcast'):
            if context.user_data.get('broadcast_step') == 'caption':
                await self.broadcast_caption(update, context, text)
            elif context.user_data.get('broadcast_step') == 'buttons':
                await self.broadcast_buttons(update, context, text)
        
        # Handle admin unban by ID
        elif context.user_data.get('admin_unban'):
            await self.admin_unban_by_id(update, context, text)
        
        else:
            await update.message.reply_text(
                "Please use the buttons to navigate.",
                reply_markup=self.get_main_menu(is_admin)
            )

    async def photo_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        is_admin = user_id in Config.ADMIN_IDS
        
        if context.user_data.get('broadcast'):
            await self.broadcast_photo(update, context)
        else:
            await update.message.reply_text(
                "Please use the buttons to navigate.",
                reply_markup=self.get_main_menu(is_admin)
            )

    # ==================== SAVE JOB ====================
    async def save_job(self, update: Update, context: ContextTypes.DEFAULT_TYPE, contact_info):
        user_id = update.effective_user.id
        session = Session()
        
        currency = context.user_data.get('currency', 'USD')
        currency_info = Config.CURRENCIES.get(currency, Config.CURRENCIES['USD'])
        contact_method = context.user_data.get('contact_method', 'telegram')
        
        job = Job(
            poster_id=user_id,
            title=context.user_data['title'],
            description=context.user_data['description'],
            category=context.user_data['category'],
            currency=currency,
            budget_min=context.user_data.get('budget_min', 0),
            budget_max=context.user_data.get('budget_max', 0),
            contact_method=contact_method,
            contact_info=contact_info,
            expires_at=datetime.utcnow() + timedelta(days=30)
        )
        session.add(job)
        session.commit()
        
        min_str = f"{currency_info['symbol']}{job.budget_min:,.2f}"
        max_str = f"{currency_info['symbol']}{job.budget_max:,.2f}" if job.budget_max > 0 else "No max"
        
        await update.message.reply_text(
            f"✅ <b>Job posted successfully!</b>\n\n"
            f"<b>Title:</b> {job.title}\n"
            f"<b>Category:</b> {job.category}\n"
            f"<b>Budget:</b> {min_str} - {max_str} ({currency})\n"
            f"<b>Contact:</b> {job.contact_method}\n\n"
            "Freelancers can now view and apply to this job!",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Browse Jobs", callback_data="browse_jobs")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ])
        )
        
        # Trigger backup after important change
        async_backup(f"new_job_{job.id}")
        
        session.close()
        context.user_data.clear()

    # ==================== SAVE RATING ====================
    async def save_rating(self, update: Update, context: ContextTypes.DEFAULT_TYPE, review):
        if review.lower() == 'skip':
            review = "No review provided."
        
        session = Session()
        rating = Rating(
            reviewer_id=update.effective_user.id,
            reviewee_id=context.user_data['rating_reviewee'],
            job_id=context.user_data['rating_job'],
            rating=context.user_data['rating_score'],
            review=review
        )
        session.add(rating)
        session.commit()
        session.close()
        
        await update.message.reply_text(
            "✅ Thank you for your rating!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Browse Jobs", callback_data="browse_jobs")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ])
        )
        context.user_data.clear()

    # ==================== SAVE REPORT ====================
    async def save_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE, reason):
        reporter_id = update.effective_user.id
        reported_id = context.user_data['reported_id']
        
        session = Session()
        
        report = Report(
            reporter_id=reporter_id,
            reported_id=reported_id,
            job_id=context.user_data.get('report_job'),
            reason=reason
        )
        session.add(report)
        
        reported_user = session.query(User).filter_by(telegram_id=reported_id).first()
        if reported_user:
            reported_user.report_count += 1
            
            warning_message = (
                f"⚠️ <b>Warning!</b>\n\n"
                f"You have received a scam report from another user.\n"
                f"<b>Report #{reported_user.report_count} of {Config.REPORT_THRESHOLD}</b>\n\n"
                f"Reason: {reason[:200]}\n\n"
                f"If you receive {Config.REPORT_THRESHOLD} reports, you will be <b>banned</b> "
                f"and required to pay {Config.UNBAN_FEE} Stars to unban."
            )
            
            try:
                await context.bot.send_message(
                    chat_id=reported_id,
                    text=warning_message,
                    parse_mode='HTML'
                )
                report.warning_sent = True
            except:
                pass
            
            if reported_user.report_count >= Config.REPORT_THRESHOLD:
                reported_user.is_banned = True
                reported_user.ban_reason = f"Multiple scam reports ({reported_user.report_count} reports)"
                
                await context.bot.send_message(
                    chat_id=reported_id,
                    text=(
                        f"🚫 <b>You have been BANNED!</b>\n\n"
                        f"You received {Config.REPORT_THRESHOLD} scam reports.\n"
                        f"To unban, send {Config.UNBAN_FEE} Stars as a gift to:\n"
                        f"<b>@{Config.RECEIVER_USERNAME}</b>\n\n"
                        "Use /start when you're ready to pay."
                    ),
                    parse_mode='HTML'
                )
                
                for admin_id in Config.ADMIN_IDS:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=(
                            f"🚨 <b>User BANNED Automatically</b>\n\n"
                            f"User: {reported_user.full_name} (@{reported_user.username})\n"
                            f"ID: {reported_user.telegram_id}\n"
                            f"Reports: {reported_user.report_count}\n"
                            f"Reason: {reason[:200]}"
                        ),
                        parse_mode='HTML'
                    )
                
                # Trigger backup after ban
                async_backup(f"ban_{reported_id}")
        
        session.commit()
        session.close()
        
        await update.message.reply_text(
            "✅ Report submitted successfully!\n\n"
            "The user has been warned. If they receive more reports, "
            "they will be automatically banned.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Browse Jobs", callback_data="browse_jobs")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ])
        )
        context.user_data.clear()

    # ==================== UNBAN PAYMENT ====================
    async def handle_unban_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE, proof):
        user_id = update.effective_user.id
        
        session = Session()
        user = session.query(User).filter_by(telegram_id=user_id).first()
        
        if not user or not user.is_banned:
            await update.message.reply_text("❌ You're not banned!")
            session.close()
            return
        
        payment = UnbanPayment(
            user_id=user_id,
            amount=Config.UNBAN_FEE,
            status='pending'
        )
        session.add(payment)
        session.commit()
        
        for admin_id in Config.ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"💰 <b>New Unban Payment Request</b>\n\n"
                        f"User: {user.full_name} (@{user.username or 'No username'})\n"
                        f"ID: {user.telegram_id}\n"
                        f"Amount: {Config.UNBAN_FEE} Stars\n"
                        f"Proof: {proof[:500]}"
                    ),
                    parse_mode='HTML'
                )
            except:
                pass
        
        await update.message.reply_text(
            f"✅ <b>Payment proof received!</b>\n\n"
            f"An admin will verify your payment and unban you shortly.\n\n"
            f"💰 Amount: {Config.UNBAN_FEE} Stars\n\n"
            f"⏳ Please wait for admin confirmation.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Check Status", callback_data="check_payment")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ])
        )
        
        async_backup(f"unban_payment_{user_id}")
        session.close()
        context.user_data.clear()

    # ==================== CHECK PAYMENT ====================
    async def check_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        session = Session()
        user = session.query(User).filter_by(telegram_id=user_id).first()
        
        if not user:
            await update.callback_query.edit_message_text(
                "Please use /start first!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
            )
            session.close()
            return
        
        if not user.is_banned:
            await update.callback_query.edit_message_text(
                "✅ You're not banned!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
            )
            session.close()
            return
        
        payment = session.query(UnbanPayment).filter_by(user_id=user_id, status='completed').order_by(UnbanPayment.created_at.desc()).first()
        
        if payment:
            await update.callback_query.edit_message_text(
                f"✅ <b>Payment Status: Completed</b>\n\n"
                f"Amount: {payment.amount} Stars\n"
                f"Date: {payment.completed_at.strftime('%Y-%m-%d %H:%M')}\n\n"
                f"You are now unbanned!",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
            )
        else:
            pending = session.query(UnbanPayment).filter_by(user_id=user_id, status='pending').order_by(UnbanPayment.created_at.desc()).first()
            if pending:
                await update.callback_query.edit_message_text(
                    f"⏳ <b>Payment Status: Pending</b>\n\n"
                    f"Amount: {pending.amount} Stars\n"
                    f"Submitted: {pending.created_at.strftime('%Y-%m-%d %H:%M')}\n\n"
                    f"Please wait for admin confirmation.",
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
                )
            else:
                await update.callback_query.edit_message_text(
                    f"💰 <b>No payment found</b>\n\n"
                    f"To unban, send {Config.UNBAN_FEE} Stars as a gift to:\n"
                    f"<b>@{Config.RECEIVER_USERNAME}</b>\n\n"
                    f"Then click 'I've Sent the Stars' button.",
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"⭐ Send {Config.UNBAN_FEE} Stars", url=f"https://t.me/{Config.RECEIVER_USERNAME}")],
                        [InlineKeyboardButton("✅ I've Sent the Stars", callback_data="pay_unban")],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                    ])
                )
        
        session.close()

    # ==================== BROADCAST ====================
    async def broadcast_start_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['broadcast'] = True
        context.user_data['broadcast_step'] = 'photo'
        await update.callback_query.edit_message_text(
            "📢 <b>Send Broadcast</b>\n\n"
            "Please send a <b>photo</b> for the broadcast (or type 'skip' for text-only):",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_panel")]])
        )

    async def broadcast_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.text and update.message.text.lower() == 'skip':
            context.user_data['broadcast_photo'] = None
            context.user_data['broadcast_step'] = 'caption'
            await update.message.reply_text(
                "Now send the <b>caption</b> for the message:\n"
                "(You can use HTML formatting: &lt;b&gt;bold&lt;/b&gt;, &lt;i&gt;italic&lt;/i&gt;)",
                parse_mode='HTML'
            )
            return
        
        if update.message.photo:
            context.user_data['broadcast_photo'] = update.message.photo[-1].file_id
            context.user_data['broadcast_step'] = 'caption'
            await update.message.reply_text(
                "✅ Photo received!\n\n"
                "Now send the <b>caption</b> for the message:",
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text("Please send a photo or type 'skip'.")

    async def broadcast_caption(self, update: Update, context: ContextTypes.DEFAULT_TYPE, caption):
        context.user_data['broadcast_caption'] = caption
        context.user_data['broadcast_step'] = 'buttons'
        
        await update.message.reply_text(
            "Now send the <b>button configuration</b> (or type 'skip' for no buttons):\n\n"
            "Format: <code>Button Text | URL</code>\n"
            "Example: <code>Join Channel | https://t.me/yourchannel</code>\n"
            "You can send multiple buttons on separate lines.",
            parse_mode='HTML'
        )

    async def broadcast_buttons(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text):
        buttons = []
        if text.lower() != 'skip':
            for line in text.split('\n'):
                if '|' in line:
                    btn_text, url = line.split('|', 1)
                    buttons.append([InlineKeyboardButton(btn_text.strip(), url=url.strip())])
        
        session = Session()
        users = session.query(User).all()
        session.close()
        
        sent = 0
        failed = 0
        
        progress_msg = await update.message.reply_text(f"📤 Sending broadcast to {len(users)} users...")
        
        for user in users:
            try:
                if context.user_data.get('broadcast_photo'):
                    await context.bot.send_photo(
                        chat_id=user.telegram_id,
                        photo=context.user_data['broadcast_photo'],
                        caption=context.user_data['broadcast_caption'],
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
                    )
                else:
                    await context.bot.send_message(
                        chat_id=user.telegram_id,
                        text=context.user_data['broadcast_caption'],
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
                    )
                sent += 1
            except Exception as e:
                failed += 1
                logger.error(f"Failed to send to {user.telegram_id}: {e}")
            
            await asyncio.sleep(0.05)
        
        session = Session()
        broadcast = BroadcastMessage(
            admin_id=update.effective_user.id,
            message_type='photo' if context.user_data.get('broadcast_photo') else 'text',
            caption=context.user_data['broadcast_caption'],
            file_id=context.user_data.get('broadcast_photo'),
            sent_count=sent,
            failed_count=failed
        )
        session.add(broadcast)
        session.commit()
        session.close()
        
        await progress_msg.edit_text(
            f"✅ <b>Broadcast Complete!</b>\n\n"
            f"📤 Sent: {sent}\n"
            f"❌ Failed: {failed}\n"
            f"📊 Total: {len(users)} users",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel")]])
        )
        
        context.user_data.clear()

    # ==================== ADMIN UNBAN BY ID ====================
    async def admin_unban_by_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text):
        try:
            target_id = int(text.strip())
        except:
            await update.message.reply_text(
                "❌ Invalid ID. Please enter a valid Telegram ID (numbers only).",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]])
            )
            context.user_data.clear()
            return
        
        session = Session()
        user = session.query(User).filter_by(telegram_id=target_id).first()
        
        if not user:
            await update.message.reply_text(
                "❌ User not found.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]])
            )
            session.close()
            context.user_data.clear()
            return
        
        if not user.is_banned:
            await update.message.reply_text(
                f"✅ User {user.full_name} is not banned.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]])
            )
            session.close()
            context.user_data.clear()
            return
        
        user.is_banned = False
        user.ban_reason = None
        user.ban_count += 1
        user.report_count = 0
        
        session.commit()
        
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    f"✅ <b>You have been unbanned by an admin!</b>\n\n"
                    f"Welcome back! Please follow the rules to avoid being banned again.\n"
                    f"This was your {user.ban_count} ban."
                ),
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
            )
        except:
            pass
        
        await update.message.reply_text(
            f"✅ <b>User Unbanned Successfully!</b>\n\n"
            f"User: {user.full_name} (@{user.username or 'No username'})\n"
            f"ID: {user.telegram_id}\n"
            f"Ban count: {user.ban_count}",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]])
        )
        
        async_backup(f"admin_unban_{target_id}")
        session.close()
        context.user_data.clear()

    # ==================== ADMIN BACKUP ====================
    async def admin_backup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in Config.ADMIN_IDS:
            await update.callback_query.edit_message_text("❌ You are not an admin.")
            return
        
        await update.callback_query.edit_message_text("🔄 Backing up database to GitHub...")
        
        if not Config.GITHUB_ENABLED:
            await update.callback_query.edit_message_text(
                "❌ GitHub backup is not configured.\n\n"
                "Set these environment variables:\n"
                "- GITHUB_TOKEN\n"
                "- GITHUB_REPO_OWNER\n"
                "- GITHUB_REPO_NAME",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]])
            )
            return
        
        success = github_backup_db(reason=f"manual_admin_{user_id}", force=True)
        if success:
            await update.callback_query.edit_message_text(
                "✅ Database backed up to GitHub successfully!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]])
            )
        else:
            await update.callback_query.edit_message_text(
                "❌ Backup failed. Check logs for details.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]])
            )

    # ==================== ADMIN RESTORE ====================
    async def admin_restore(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in Config.ADMIN_IDS:
            await update.callback_query.edit_message_text("❌ You are not an admin.")
            return
        
        await update.callback_query.edit_message_text(
            "⚠️ <b>RESTORE DATABASE FROM GITHUB</b>\n\n"
            "This will REPLACE the current database with the backup from GitHub.\n"
            "All current data will be lost!\n\n"
            "Are you sure?",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Yes, Restore", callback_data="confirm_restore")],
                [InlineKeyboardButton("❌ Cancel", callback_data="admin_panel")]
            ])
        )

    async def confirm_restore(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in Config.ADMIN_IDS:
            await update.callback_query.edit_message_text("❌ You are not an admin.")
            return
        
        await update.callback_query.edit_message_text("🔄 Restoring database from GitHub...")
        
        if not Config.GITHUB_ENABLED:
            await update.callback_query.edit_message_text(
                "❌ GitHub backup is not configured.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]])
            )
            return
        
        # Close all sessions before restore
        Session.close_all()
        
        success = github_restore_db()
        if success:
            await update.callback_query.edit_message_text(
                "✅ Database restored from GitHub successfully!\n\n"
                "The bot will restart to apply changes.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Restart Bot", callback_data="restart_bot")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                ])
            )
        else:
            await update.callback_query.edit_message_text(
                "❌ Restore failed. Check logs for details.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]])
            )

    # ==================== ADMIN DOWNLOAD DB ====================
    async def admin_download_db(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in Config.ADMIN_IDS:
            await update.callback_query.edit_message_text("❌ You are not an admin.")
            return
        
        if not DATABASE_FILE.exists():
            await update.callback_query.edit_message_text(
                "❌ Database file not found.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]])
            )
            return
        
        await update.callback_query.edit_message_text("📤 Preparing database file for download...")
        
        # Send the database file
        try:
            with open(DATABASE_FILE, 'rb') as f:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=f,
                    filename=f"freelance_bot_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
                    caption=f"💾 Database backup - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                            f"Size: {DATABASE_FILE.stat().st_size / 1024:.1f} KB"
                )
            
            await update.callback_query.edit_message_text(
                "✅ Database file sent successfully!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]])
            )
        except Exception as e:
            await update.callback_query.edit_message_text(
                f"❌ Failed to send database file: {e}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]])
            )

    # ==================== ADMIN STATS ====================
    async def admin_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in Config.ADMIN_IDS:
            await update.callback_query.edit_message_text("❌ You are not an admin.")
            return
        
        session = Session()
        
        total_users = session.query(User).count()
        banned_users = session.query(User).filter_by(is_banned=True).count()
        total_reports = session.query(Report).count()
        pending_reports = session.query(Report).filter_by(status='pending').count()
        total_jobs = session.query(Job).count()
        active_jobs = session.query(Job).filter_by(is_active=True).count()
        total_ratings = session.query(Rating).count()
        total_payments = session.query(UnbanPayment).count()
        pending_payments = session.query(UnbanPayment).filter_by(status='pending').count()
        completed_payments = session.query(UnbanPayment).filter_by(status='completed').count()
        
        session.close()
        
        await update.callback_query.edit_message_text(
            f"📊 <b>Statistics</b>\n\n"
            f"👤 Users: {total_users} (Banned: {banned_users})\n"
            f"📋 Reports: {total_reports} (Pending: {pending_reports})\n"
            f"💼 Jobs: {total_jobs} (Active: {active_jobs})\n"
            f"⭐ Ratings: {total_ratings}\n"
            f"💰 Payments: {total_payments} (Pending: {pending_payments}, Completed: {completed_payments})",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]])
        )

    # ==================== ADMIN REPORTS ====================
    async def admin_reports(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in Config.ADMIN_IDS:
            await update.callback_query.edit_message_text("❌ You are not an admin.")
            return
        
        session = Session()
        pending_reports = session.query(Report).filter_by(status='pending').all()
        
        if not pending_reports:
            await update.callback_query.edit_message_text(
                "✅ No pending reports!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]])
            )
            session.close()
            return
        
        reports_with_users = []
        for report in pending_reports[:10]:
            user = session.query(User).filter_by(telegram_id=report.reported_id).first()
            reports_with_users.append((user, report))
        
        await update.callback_query.edit_message_text(
            f"📋 <b>Pending Reports ({len(pending_reports)})</b>\n\n"
            "Click a report to view details:",
            parse_mode='HTML',
            reply_markup=self.get_reports_menu(reports_with_users)
        )
        session.close()

    # ==================== ADMIN PAYMENTS ====================
    async def admin_payments(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in Config.ADMIN_IDS:
            await update.callback_query.edit_message_text("❌ You are not an admin.")
            return
        
        session = Session()
        pending_payments = session.query(UnbanPayment).filter_by(status='pending').all()
        
        if not pending_payments:
            await update.callback_query.edit_message_text(
                "✅ No pending payments!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]])
            )
            session.close()
            return
        
        payments_with_users = []
        for payment in pending_payments[:10]:
            user = session.query(User).filter_by(telegram_id=payment.user_id).first()
            payments_with_users.append((user, payment))
        
        await update.callback_query.edit_message_text(
            f"💰 <b>Pending Unban Payments ({len(pending_payments)})</b>\n\n"
            "Click a payment to view:",
            parse_mode='HTML',
            reply_markup=self.get_payments_menu(payments_with_users)
        )
        session.close()

    # ==================== ADMIN USERS ====================
    async def admin_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in Config.ADMIN_IDS:
            await update.callback_query.edit_message_text("❌ You are not an admin.")
            return
        
        session = Session()
        total_users = session.query(User).count()
        page = context.user_data.get('users_page', 0)
        per_page = 10
        
        users = session.query(User).order_by(User.created_at.desc()).offset(page * per_page).limit(per_page).all()
        total_pages = (total_users + per_page - 1) // per_page
        
        session.close()
        
        if not users:
            await update.callback_query.edit_message_text(
                "👥 No users found.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]])
            )
            return
        
        await update.callback_query.edit_message_text(
            f"👥 <b>Users</b> (Page {page+1}/{total_pages})\n\n"
            "Click a user to manage:",
            parse_mode='HTML',
            reply_markup=self.get_users_menu(users, page, total_pages, "")
        )

    # ==================== VIEW USER ====================
    async def view_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE, target_id):
        user_id = update.effective_user.id
        if user_id not in Config.ADMIN_IDS:
            await update.callback_query.edit_message_text("❌ You are not an admin.")
            return
        
        session = Session()
        user = session.query(User).filter_by(telegram_id=target_id).first()
        
        if not user:
            await update.callback_query.edit_message_text("❌ User not found.")
            session.close()
            return
        
        avg_rating = self.get_average_rating(target_id)
        
        await update.callback_query.edit_message_text(
            f"👤 <b>User Details</b>\n\n"
            f"Name: {user.full_name}\n"
            f"Username: @{user.username or 'Not set'}\n"
            f"Role: {user.role.title()}\n"
            f"Currency: {user.currency}\n"
            f"⭐ Rating: {avg_rating:.1f}/5.0\n"
            f"📊 Reports: {user.report_count}\n"
            f"🚫 Banned: {'Yes' if user.is_banned else 'No'}\n"
            f"📅 Joined: {user.created_at.strftime('%Y-%m-%d')}",
            parse_mode='HTML',
            reply_markup=self.get_user_actions_menu(target_id)
        )
        session.close()

    # ==================== UNBAN USER ====================
    async def unban_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE, target_id):
        user_id = update.effective_user.id
        if user_id not in Config.ADMIN_IDS:
            await update.callback_query.edit_message_text("❌ You are not an admin.")
            return
        
        session = Session()
        user = session.query(User).filter_by(telegram_id=target_id).first()
        
        if user and user.is_banned:
            user.is_banned = False
            user.ban_reason = None
            user.ban_count += 1
            user.report_count = 0
            session.commit()
            
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=(
                        f"✅ <b>You have been unbanned by an admin!</b>\n\n"
                        f"Welcome back! Please follow the rules."
                    ),
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
                )
            except:
                pass
            
            await update.callback_query.edit_message_text(
                f"✅ User {user.full_name} has been unbanned!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Users", callback_data="admin_users")]])
            )
            async_backup(f"unban_{target_id}")
        else:
            await update.callback_query.edit_message_text("❌ User is not banned or not found.")
        session.close()

    # ==================== BAN USER ====================
    async def ban_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE, target_id):
        user_id = update.effective_user.id
        if user_id not in Config.ADMIN_IDS:
            await update.callback_query.edit_message_text("❌ You are not an admin.")
            return
        
        session = Session()
        user = session.query(User).filter_by(telegram_id=target_id).first()
        
        if user and not user.is_banned:
            user.is_banned = True
            user.ban_reason = "Banned by admin"
            session.commit()
            
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=(
                        f"🚫 <b>You have been banned by an admin!</b>\n\n"
                        f"To unban, contact @{Config.RECEIVER_USERNAME}"
                    ),
                    parse_mode='HTML'
                )
            except:
                pass
            
            await update.callback_query.edit_message_text(
                f"✅ User {user.full_name} has been banned!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Users", callback_data="admin_users")]])
            )
            async_backup(f"ban_admin_{target_id}")
        else:
            await update.callback_query.edit_message_text("❌ User is already banned or not found.")
        session.close()

    # ==================== ADMIN UNBAN (by ID input) ====================
    async def admin_unban_by_id_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in Config.ADMIN_IDS:
            await update.callback_query.edit_message_text("❌ You are not an admin.")
            return
        
        context.user_data['admin_unban'] = True
        
        await update.callback_query.edit_message_text(
            "🔓 <b>Unban User</b>\n\n"
            "Please enter the <b>Telegram ID</b> of the user you want to unban:\n\n"
            "You can find the ID in user profiles or reports.",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_panel")]])
        )

    # ==================== GET AVERAGE RATING ====================
    def get_average_rating(self, user_id):
        session = Session()
        ratings = session.query(Rating).filter_by(reviewee_id=user_id).all()
        session.close()
        if not ratings:
            return 0.0
        avg = sum(r.rating for r in ratings) / len(ratings)
        return round(avg, 1)

    # ==================== CONTACT CLIENT ====================
    async def contact_client(self, job_id, update: Update):
        session = Session()
        job = session.query(Job).filter_by(id=job_id, is_active=True).first()
        
        if not job:
            await update.callback_query.edit_message_text(
                "❌ This job is no longer available.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Browse", callback_data="browse_jobs")]])
            )
            session.close()
            return
        
        poster = session.query(User).filter_by(telegram_id=job.poster_id).first()
        session.close()
        
        await update.callback_query.edit_message_text(
            f"✅ <b>Contact Details</b>\n\n"
            f"<b>Job:</b> {job.title}\n\n"
            f"📞 <b>Contact Method:</b> {job.contact_method}\n"
            f"📱 <b>Contact Info:</b> {job.contact_info}\n\n"
            f"💡 Tip: Mention the job title when contacting!\n"
            f"⚠️ Always verify identities!",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📝 Rate Client", callback_data=f"rate_{job.poster_id}_{job.id}")],
                [InlineKeyboardButton("🚨 Report Scam", callback_data=f"report_{job.poster_id}_{job.id}")],
                [InlineKeyboardButton("🔙 Back to Browse", callback_data="browse_jobs")]
            ])
        )

    # ==================== CALLBACK HANDLER ====================
    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = update.effective_user.id
        is_admin = user_id in Config.ADMIN_IDS
        
        # ===== MAIN MENU =====
        if data == "main_menu":
            await query.edit_message_text(
                "🏠 <b>Main Menu</b>\n\n"
                "Select an option below:",
                parse_mode='HTML',
                reply_markup=self.get_main_menu(is_admin)
            )
            return
        
        # ===== HELP =====
        elif data == "help":
            await query.edit_message_text(
                "🤖 <b>FreelanceHub Bot - Help</b>\n\n"
                "<b>What you can do:</b>\n"
                "• Browse and apply for jobs\n"
                "• Post your own jobs\n"
                "• Rate other users\n"
                "• Report scammers\n"
                "• Manage your profile\n\n"
                "<b>Currencies Supported:</b>\n"
                + "\n".join([f"{data['emoji']} {code} ({data['symbol']})" 
                            for code, data in list(Config.CURRENCIES.items())[:6]]) +
                "\n\n<b>How it works:</b>\n"
                "1. Clients post jobs\n"
                "2. Freelancers browse and apply\n"
                "3. Connect directly\n\n"
                "⚠️ Always verify identities!",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]])
            )
            return
        
        # ===== SETTINGS =====
        elif data == "settings":
            session = Session()
            user = session.query(User).filter_by(telegram_id=user_id).first()
            session.close()
            
            if user:
                await query.edit_message_text(
                    "⚙️ <b>Settings</b>\n\n"
                    "Current settings:",
                    parse_mode='HTML',
                    reply_markup=self.get_settings_menu(user)
                )
            return
        
        elif data == "change_role":
            await query.edit_message_text(
                "Choose your role:",
                reply_markup=self.get_role_keyboard()
            )
            return
        
        elif data == "change_currency":
            session = Session()
            user = session.query(User).filter_by(telegram_id=user_id).first()
            current = user.currency if user else 'USD'
            session.close()
            
            await query.edit_message_text(
                "💰 <b>Select your preferred currency</b>\n\n"
                f"Current: {Config.CURRENCIES[current]['emoji']} {current}",
                parse_mode='HTML',
                reply_markup=self.get_currency_keyboard(current)
            )
            return
        
        # ===== ROLE SELECTION =====
        elif data.startswith('role_'):
            role = data.replace('role_', '')
            session = Session()
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if user:
                user.role = role
                session.commit()
                await query.edit_message_text(
                    f"✅ Role set to: {role.title()}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Settings", callback_data="settings")]])
                )
            session.close()
            return
        
        # ===== CURRENCY SELECTION =====
        elif data.startswith('cur_'):
            currency = data.replace('cur_', '')
            session = Session()
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if user:
                user.currency = currency
                session.commit()
                currency_info = Config.CURRENCIES[currency]
                await query.edit_message_text(
                    f"✅ Currency set to: {currency_info['emoji']} {currency} ({currency_info['symbol']})",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Settings", callback_data="settings")]])
                )
            session.close()
            return
        
        # ===== PROFILE =====
        elif data == "my_profile":
            session = Session()
            user = session.query(User).filter_by(telegram_id=user_id).first()
            
            if not user:
                await query.edit_message_text("Please use /start first!")
                session.close()
                return
            
            avg_rating = self.get_average_rating(user_id)
            ratings_count = session.query(Rating).filter_by(reviewee_id=user_id).count()
            jobs_count = session.query(Job).filter_by(poster_id=user_id, is_active=True).count()
            currency_info = Config.CURRENCIES.get(user.currency, Config.CURRENCIES['USD'])
            
            profile_text = (
                f"👤 <b>Profile</b>\n\n"
                f"Name: {user.full_name}\n"
                f"Username: @{user.username or 'Not set'}\n"
                f"Role: {user.role.title()}\n"
                f"{currency_info['emoji']} Currency: {user.currency}\n"
                f"⭐ Rating: {avg_rating:.1f}/5.0 ({ratings_count} ratings)\n"
                f"📊 Reports: {user.report_count}/{Config.REPORT_THRESHOLD}\n"
                f"🚫 Banned: {'Yes' if user.is_banned else 'No'}\n"
                f"📅 Joined: {user.created_at.strftime('%Y-%m-%d')}\n\n"
                f"📌 {jobs_count} active jobs"
            )
            
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]]
            if user.is_banned:
                keyboard.insert(0, [InlineKeyboardButton(f"💰 Pay {Config.UNBAN_FEE} Stars to Unban", callback_data="pay_unban")])
            
            await query.edit_message_text(
                profile_text,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            session.close()
            return
        
        # ===== POST JOB =====
        elif data == "post_job":
            session = Session()
            user = session.query(User).filter_by(telegram_id=user_id).first()
            
            if not user:
                await query.edit_message_text("Please use /start first!")
                session.close()
                return
            
            if user.is_banned:
                await query.edit_message_text("🚫 You are banned and cannot post jobs!")
                session.close()
                return
                
            if user.role not in ['client', 'both']:
                await query.edit_message_text(
                    "❌ You need to be a <b>Client</b> to post jobs!\n"
                    "Change your role in Settings.",
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Settings", callback_data="settings")]])
                )
                session.close()
                return
            
            context.user_data['posting_job'] = True
            context.user_data['step'] = 'title'
            context.user_data['currency'] = user.currency
            session.close()
            
            await query.edit_message_text(
                "📝 <b>Create Job Listing</b>\n\n"
                "Please enter the <b>job title</b>:",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]])
            )
            return
        
        # ===== CATEGORY SELECTION =====
        elif data.startswith('cat_'):
            category = data.replace('cat_', '')
            context.user_data['category'] = category
            context.user_data['step'] = 'budget_min'
            
            await query.edit_message_text(
                f"✅ Category: {category}\n\n"
                "Now enter the <b>minimum budget</b> (or type '0'):",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]])
            )
            return
        
        # ===== CONTACT METHOD SELECTION =====
        elif data.startswith('contact_method_'):
            method = data.replace('contact_method_', '')
            context.user_data['contact_method'] = method
            context.user_data['step'] = 'contact_info'
            
            await query.edit_message_text(
                f"✅ Contact method: {method}\n\n"
                f"Please enter your <b>{method}</b> contact info:",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]])
            )
            return
        
        # ===== CONTACT CLIENT =====
        elif data.startswith('contact_job_'):
            job_id = int(data.replace('contact_job_', ''))
            await self.contact_client(job_id, update)
            return
        
        # ===== BROWSE JOBS =====
        elif data == "browse_jobs":
            session = Session()
            user = session.query(User).filter_by(telegram_id=user_id).first()
            
            if not user:
                await query.edit_message_text("Please use /start first!")
                session.close()
                return
            
            if user.is_banned:
                await query.edit_message_text("🚫 You are banned and cannot browse jobs!")
                session.close()
                return
                
            if user.role not in ['freelancer', 'both']:
                await query.edit_message_text(
                    "❌ You need to be a <b>Freelancer</b> to browse jobs!\n"
                    "Change your role in Settings.",
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Settings", callback_data="settings")]])
                )
                session.close()
                return
            
            jobs = session.query(Job).filter_by(is_active=True).order_by(Job.created_at.desc()).limit(20).all()
            session.close()
            
            if not jobs:
                await query.edit_message_text(
                    "❌ No jobs available right now.\n\n"
                    "Check back later or post your own job!",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💰 Post a Job", callback_data="post_job")],
                        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
                    ])
                )
                return
            
            for job in jobs[:5]:
                poster = session.query(User).filter_by(telegram_id=job.poster_id).first()
                avg_rating = self.get_average_rating(job.poster_id)
                currency_info = Config.CURRENCIES.get(job.currency, Config.CURRENCIES['USD'])
                min_str = f"{currency_info['symbol']}{job.budget_min:,.2f}"
                max_str = f"{currency_info['symbol']}{job.budget_max:,.2f}" if job.budget_max > 0 else "No max"
                
                await query.message.reply_text(
                    f"📌 <b>{job.title}</b>\n"
                    f"📂 Category: {job.category}\n"
                    f"💰 Budget: {min_str} - {max_str} ({job.currency})\n"
                    f"📝 {job.description[:150]}...\n\n"
                    f"👤 Client: {poster.full_name if poster else 'Unknown'}\n"
                    f"⭐ Rating: {avg_rating:.1f}/5.0\n"
                    f"📅 Posted: {job.created_at.strftime('%Y-%m-%d')}",
                    parse_mode='HTML',
                    reply_markup=self.get_job_actions_keyboard(job.id, job.poster_id)
                )
            
            await query.message.reply_text(
                "📋 <b>Showing latest 5 jobs</b>",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Refresh", callback_data="browse_jobs")],
                    [InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]
                ])
            )
            await query.delete_message()
            return
        
        # ===== RATING =====
        elif data.startswith('rate_'):
            parts = data.split('_')
            reviewee_id = int(parts[1])
            job_id = int(parts[2])
            
            context.user_data['rating'] = True
            context.user_data['rating_reviewee'] = reviewee_id
            context.user_data['rating_job'] = job_id
            context.user_data['step'] = 'score'
            
            keyboard = []
            for i in range(1, 6):
                stars = '⭐' * i
                keyboard.append([InlineKeyboardButton(f"{stars} {i}/5", callback_data=f"score_{i}")])
            keyboard.append([InlineKeyboardButton("🔙 Cancel", callback_data="browse_jobs")])
            
            await query.edit_message_text(
                "How would you rate this user?\n\n"
                "Select a score:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        elif data.startswith('score_'):
            score = int(data.replace('score_', ''))
            context.user_data['rating_score'] = score
            context.user_data['step'] = 'review'
            
            await query.edit_message_text(
                f"Rating: {'⭐' * score} {score}/5\n\n"
                "Please write a brief review (or type 'skip' to skip):",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="browse_jobs")]])
            )
            return
        
        # ===== REPORT =====
        elif data.startswith('report_'):
            parts = data.split('_')
            reported_id = int(parts[1])
            job_id = int(parts[2]) if len(parts) > 2 else None
            
            context.user_data['reporting'] = True
            context.user_data['reported_id'] = reported_id
            context.user_data['report_job'] = job_id
            
            await query.edit_message_text(
                "🚨 <b>Report User for Scam</b>\n\n"
                "Please describe what happened:\n"
                "- What did they do?\n"
                "- Any evidence?\n"
                "- Amount lost?\n\n"
                "Be as detailed as possible.",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="browse_jobs")]])
            )
            return
        
        # ===== MY JOBS =====
        elif data == "my_jobs":
            session = Session()
            jobs = session.query(Job).filter_by(poster_id=user_id, is_active=True).all()
            session.close()
            
            if not jobs:
                await query.edit_message_text(
                    "📋 <b>Your Jobs</b>\n\n"
                    "You haven't posted any jobs yet.",
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💰 Post a Job", callback_data="post_job")],
                        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
                    ])
                )
                return
            
            message = "📋 <b>Your Active Jobs:</b>\n\n"
            for job in jobs:
                currency_info = Config.CURRENCIES.get(job.currency, Config.CURRENCIES['USD'])
                min_str = f"{currency_info['symbol']}{job.budget_min:,.2f}"
                max_str = f"{currency_info['symbol']}{job.budget_max:,.2f}" if job.budget_max > 0 else "No max"
                message += f"🔹 {job.title}\n"
                message += f"   Category: {job.category} | Budget: {min_str} - {max_str}\n"
                message += f"   📅 {job.created_at.strftime('%Y-%m-%d')}\n\n"
            
            keyboard = []
            for job in jobs:
                keyboard.append([InlineKeyboardButton(f"🗑️ Delete: {job.title[:20]}", callback_data=f"delete_{job.id}")])
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
            
            await query.edit_message_text(
                message,
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        # ===== DELETE JOB =====
        elif data.startswith('delete_'):
            job_id = int(data.replace('delete_', ''))
            session = Session()
            job = session.query(Job).filter_by(id=job_id, poster_id=user_id).first()
            
            if not job:
                await query.edit_message_text("❌ Job not found.")
                session.close()
                return
            
            job.is_active = False
            session.commit()
            session.close()
            
            await query.edit_message_text(
                f"✅ Job '{job.title}' has been deleted.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📂 My Jobs", callback_data="my_jobs")]])
            )
            async_backup(f"delete_job_{job_id}")
            return
        
        # ===== UNBAN PAYMENT =====
        elif data == "pay_unban":
            session = Session()
            user = session.query(User).filter_by(telegram_id=user_id).first()
            
            if not user or not user.is_banned:
                await query.edit_message_text("❌ You're not banned!")
                session.close()
                return
            
            context.user_data['unban_payment'] = True
            
            await query.edit_message_text(
                f"💰 <b>Unban Payment Process</b>\n\n"
                f"1. Send <b>{Config.UNBAN_FEE} Stars</b> as a gift to:\n"
                f"   <b>@{Config.RECEIVER_USERNAME}</b>\n\n"
                f"2. After sending, type your <b>gift message</b> or <b>screenshot</b> here\n"
                f"   (Any proof of payment)\n\n"
                f"3. An admin will verify and unban you\n\n"
                f"📝 Type your payment proof below:",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]])
            )
            session.close()
            return
        
        elif data == "check_payment":
            await self.check_payment(update, context)
            return
        
        # ===== ADMIN PANEL =====
        elif data == "admin_panel":
            if not is_admin:
                await query.edit_message_text("❌ You are not an admin.")
                return
            
            await query.edit_message_text(
                "👑 <b>Admin Panel</b>\n\n"
                "Select an option below:",
                parse_mode='HTML',
                reply_markup=self.get_admin_menu()
            )
            return
        
        # ===== ADMIN BACKUP =====
        elif data == "admin_backup":
            await self.admin_backup(update, context)
            return
        
        # ===== ADMIN RESTORE =====
        elif data == "admin_restore":
            await self.admin_restore(update, context)
            return
        
        # ===== CONFIRM RESTORE =====
        elif data == "confirm_restore":
            await self.confirm_restore(update, context)
            return
        
        # ===== ADMIN DOWNLOAD DB =====
        elif data == "admin_download_db":
            await self.admin_download_db(update, context)
            return
        
        # ===== ADMIN STATS =====
        elif data == "admin_stats":
            await self.admin_stats(update, context)
            return
        
        # ===== ADMIN BROADCAST =====
        elif data == "admin_broadcast":
            if not is_admin:
                await query.edit_message_text("❌ You are not an admin.")
                return
            await self.broadcast_start_callback(update, context)
            return
        
        # ===== ADMIN REPORTS =====
        elif data == "admin_reports":
            await self.admin_reports(update, context)
            return
        
        # ===== ADMIN PAYMENTS =====
        elif data == "admin_payments":
            await self.admin_payments(update, context)
            return
        
        # ===== ADMIN USERS =====
        elif data == "admin_users":
            await self.admin_users(update, context)
            return
        
        # ===== ADMIN SEARCH USERS =====
        elif data == "admin_search_users":
            await self.admin_search_users(update, context)
            return
        
        # ===== ADMIN UNBAN (by ID) =====
        elif data == "admin_unban":
            await self.admin_unban_by_id_start(update, context)
            return
        
        # ===== RESTART BOT =====
        elif data == "restart_bot":
            await query.edit_message_text(
                "🔄 Restarting bot...\n\n"
                "The bot will restart automatically.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
            )
            # Trigger a restart (in production, you'd use a process manager)
            os._exit(0)
            return
        
        # ===== VIEW REPORT =====
        elif data.startswith('view_report_'):
            if not is_admin:
                await query.edit_message_text("❌ You are not an admin.")
                return
            
            report_id = int(data.replace('view_report_', ''))
            session = Session()
            report = session.query(Report).filter_by(id=report_id).first()
            
            if not report:
                await query.edit_message_text("❌ Report not found.")
                session.close()
                return
            
            reporter = session.query(User).filter_by(telegram_id=report.reporter_id).first()
            reported = session.query(User).filter_by(telegram_id=report.reported_id).first()
            
            await query.edit_message_text(
                f"📋 <b>Report #{report.id}</b>\n\n"
                f"Reporter: {reporter.full_name} (@{reporter.username or 'No username'})\n"
                f"Reported: {reported.full_name} (@{reported.username or 'No username'})\n"
                f"Status: {report.status}\n"
                f"Date: {report.created_at.strftime('%Y-%m-%d %H:%M')}\n\n"
                f"<b>Reason:</b>\n{report.reason[:500]}",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Resolve", callback_data=f"resolve_report_{report.id}")],
                    [InlineKeyboardButton("❌ Dismiss", callback_data=f"dismiss_report_{report.id}")],
                    [InlineKeyboardButton("🔙 Back to Reports", callback_data="admin_reports")]
                ])
            )
            session.close()
            return
        
        # ===== RESOLVE REPORT =====
        elif data.startswith('resolve_report_'):
            if not is_admin:
                await query.edit_message_text("❌ You are not an admin.")
                return
            
            report_id = int(data.replace('resolve_report_', ''))
            session = Session()
            report = session.query(Report).filter_by(id=report_id).first()
            
            if report:
                report.status = 'resolved'
                report.resolved_at = datetime.utcnow()
                report.resolved_by = user_id
                session.commit()
                await query.edit_message_text(
                    f"✅ Report #{report_id} resolved!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Reports", callback_data="admin_reports")]])
                )
                async_backup(f"resolve_report_{report_id}")
            session.close()
            return
        
        # ===== DISMISS REPORT =====
        elif data.startswith('dismiss_report_'):
            if not is_admin:
                await query.edit_message_text("❌ You are not an admin.")
                return
            
            report_id = int(data.replace('dismiss_report_', ''))
            session = Session()
            report = session.query(Report).filter_by(id=report_id).first()
            
            if report:
                report.status = 'dismissed'
                report.resolved_at = datetime.utcnow()
                report.resolved_by = user_id
                session.commit()
                await query.edit_message_text(
                    f"✅ Report #{report_id} dismissed!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Reports", callback_data="admin_reports")]])
                )
                async_backup(f"dismiss_report_{report_id}")
            session.close()
            return
        
        # ===== VIEW PAYMENT =====
        elif data.startswith('view_payment_'):
            if not is_admin:
                await query.edit_message_text("❌ You are not an admin.")
                return
            
            payment_id = int(data.replace('view_payment_', ''))
            session = Session()
            payment = session.query(UnbanPayment).filter_by(id=payment_id).first()
            
            if not payment:
                await query.edit_message_text("❌ Payment not found.")
                session.close()
                return
            
            user = session.query(User).filter_by(telegram_id=payment.user_id).first()
            
            await query.edit_message_text(
                f"💰 <b>Payment #{payment.id}</b>\n\n"
                f"User: {user.full_name} (@{user.username or 'No username'})\n"
                f"Amount: {payment.amount} Stars\n"
                f"Status: {payment.status}\n"
                f"Date: {payment.created_at.strftime('%Y-%m-%d %H:%M')}",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Confirm & Unban", callback_data=f"confirm_payment_{payment.id}")],
                    [InlineKeyboardButton("🔙 Back to Payments", callback_data="admin_payments")]
                ])
            )
            session.close()
            return
        
        # ===== CONFIRM PAYMENT =====
        elif data.startswith('confirm_payment_'):
            if not is_admin:
                await query.edit_message_text("❌ You are not an admin.")
                return
            
            payment_id = int(data.replace('confirm_payment_', ''))
            session = Session()
            payment = session.query(UnbanPayment).filter_by(id=payment_id).first()
            
            if not payment:
                await query.edit_message_text("❌ Payment not found.")
                session.close()
                return
            
            user = session.query(User).filter_by(telegram_id=payment.user_id).first()
            
            if user and user.is_banned:
                user.is_banned = False
                user.ban_reason = None
                user.ban_count += 1
                user.report_count = 0
                payment.status = 'completed'
                payment.completed_at = datetime.utcnow()
                session.commit()
                
                try:
                    await context.bot.send_message(
                        chat_id=user.telegram_id,
                        text=(
                            f"✅ <b>You have been unbanned!</b>\n\n"
                            f"Welcome back! Please follow the rules.\n"
                            f"This was your {user.ban_count} ban."
                        ),
                        parse_mode='HTML',
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
                    )
                except:
                    pass
                
                await query.edit_message_text(
                    f"✅ Payment confirmed! User unbanned.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Payments", callback_data="admin_payments")]])
                )
                async_backup(f"confirm_payment_{payment_id}")
            else:
                await query.edit_message_text("❌ User is not banned or not found.")
            
            session.close()
            return
        
        # ===== VIEW USER =====
        elif data.startswith('view_user_'):
            target_id = int(data.replace('view_user_', ''))
            await self.view_user(update, context, target_id)
            return
        
        # ===== UNBAN USER =====
        elif data.startswith('unban_user_'):
            target_id = int(data.replace('unban_user_', ''))
            await self.unban_user(update, context, target_id)
            return
        
        # ===== BAN USER =====
        elif data.startswith('ban_user_'):
            target_id = int(data.replace('ban_user_', ''))
            await self.ban_user(update, context, target_id)
            return
        
        # ===== CHECK JOINED =====
        elif data == "check_joined":
            if await self.check_force_join(update, context):
                is_admin = update.effective_user.id in Config.ADMIN_IDS
                await query.edit_message_text(
                    "✅ Thank you for joining!",
                    reply_markup=self.get_main_menu(is_admin)
                )
            return
        
        # ===== NOOP (for pagination placeholder) =====
        elif data == "noop":
            await query.answer()
            return

    # ==================== RUN ====================
    def run(self):
        self.application.run_polling()

if __name__ == '__main__':
    bot = FreelanceBot()
    bot.run()
