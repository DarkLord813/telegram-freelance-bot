#!/usr/bin/env python3

import logging
import os
from datetime import datetime, timedelta
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

load_dotenv()

class Config:
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///freelance_bot.db')
    ADMIN_IDS = [int(id.strip()) for id in os.getenv('ADMIN_IDS', '').split(',') if id.strip()]
    REPORT_THRESHOLD = 5
    UNBAN_FEE = 50
    RECEIVER_USERNAME = os.getenv('RECEIVER_USERNAME', 'YourMainAccount')
    RECEIVER_TELEGRAM_ID = int(os.getenv('RECEIVER_TELEGRAM_ID', '123456789'))
    
    FORCE_JOIN_CHANNELS = [
        'https://t.me/PulseProfit012',
        'https://t.me/moneyplugngx',
        'https://t.me/aidropupdatesx',
        'https://t.me/PulseProfitWithdrawals'
    ]
    CHANNEL_USERNAMES = ['PulseProfit012', 'moneyplugngx', 'aidropupdatesx', 'PulseProfitWithdrawals']
    
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

Base = declarative_base()
engine = create_engine(Config.DATABASE_URL)
Session = sessionmaker(bind=engine)

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
    is_admin = Column(Boolean, default=False)

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

Base.metadata.create_all(engine)

TITLE, DESCRIPTION, CATEGORY, CURRENCY, BUDGET_MIN, BUDGET_MAX, CONTACT_METHOD, CONTACT_INFO = range(8)
RATING_SCORE, RATING_REVIEW = range(2)
REPORT_REASON = range(1)
BROADCAST_PHOTO, BROADCAST_CAPTION, BROADCAST_BUTTONS = range(3)
UNBAN_PAYMENT = range(1)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class FreelanceBot:
    def __init__(self):
        self.application = Application.builder().token(Config.BOT_TOKEN).build()
        self.setup_handlers()
        logger.info("Bot initialized successfully!")
        
    def setup_handlers(self):
        # ONLY /start command - everything else is inline buttons
        self.application.add_handler(CommandHandler('start', self.start))
        
        # All functionality via callback queries
        self.application.add_handler(CallbackQueryHandler(self.callback_handler))
        
        # Message handlers for conversations
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.text_handler))
        self.application.add_handler(MessageHandler(filters.PHOTO, self.photo_handler))

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
            [InlineKeyboardButton("🏠 Back to Main Menu", callback_data="main_menu")]
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

    def get_users_menu(self, users):
        keyboard = []
        for user in users[:10]:
            status = "🚫" if user.is_banned else "✅"
            keyboard.append([
                InlineKeyboardButton(
                    f"{status} {user.full_name[:20]} (@{user.username or 'No username'})", 
                    callback_data=f"view_user_{user.telegram_id}"
                )
            ])
        keyboard.append([InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")])
        return InlineKeyboardMarkup(keyboard)

    def get_user_actions_menu(self, user_id):
        keyboard = [
            [InlineKeyboardButton("🔓 Unban User", callback_data=f"unban_user_{user_id}")],
            [InlineKeyboardButton("🚫 Ban User", callback_data=f"ban_user_{user_id}")],
            [InlineKeyboardButton("👑 Make Admin", callback_data=f"make_admin_{user_id}")],
            [InlineKeyboardButton("🔙 Back to Users", callback_data="admin_users")]
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
            [InlineKeyboardButton("📱 Telegram", callback_data="contact_telegram")],
            [InlineKeyboardButton("📧 Email", callback_data="contact_email")],
            [InlineKeyboardButton("📞 Phone", callback_data="contact_phone")],
            [InlineKeyboardButton("💬 Other", callback_data="contact_other")],
            [InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    def get_job_actions_keyboard(self, job_id, poster_id):
        keyboard = [
            [InlineKeyboardButton("📞 Contact Client", callback_data=f"contact_{job_id}")],
            [InlineKeyboardButton("📝 Rate Client", callback_data=f"rate_{poster_id}_{job_id}")],
            [InlineKeyboardButton("🚨 Report Scam", callback_data=f"report_{poster_id}_{job_id}")],
            [InlineKeyboardButton("🔙 Back to Browse", callback_data="browse_jobs")]
        ]
        return InlineKeyboardMarkup(keyboard)

    # ==================== FORCE JOIN ====================
    async def check_force_join(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        for channel in Config.CHANNEL_USERNAMES:
            try:
                member = await context.bot.get_chat_member(f"@{channel}", user_id)
                if member.status not in ['member', 'administrator', 'creator']:
                    keyboard = []
                    for ch in Config.FORCE_JOIN_CHANNELS:
                        keyboard.append([InlineKeyboardButton(f"📢 Join Channel", url=ch)])
                    keyboard.append([InlineKeyboardButton("✅ I've Joined", callback_data="check_joined")])
                    
                    if update.message:
                        await update.message.reply_text(
                            "⚠️ **Please join our channels first!**\n\n"
                            "You need to join all channels to use this bot.\n"
                            "Click the buttons below to join:",
                            parse_mode='Markdown',
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                    else:
                        await update.callback_query.edit_message_text(
                            "⚠️ **Please join our channels first!**\n\n"
                            "You need to join all channels to use this bot.\n"
                            "Click the buttons below to join:",
                            parse_mode='Markdown',
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                    return False
            except:
                pass
        
        return True

    # ==================== START ====================
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        
        if not await self.check_force_join(update, context):
            return
        
        session = Session()
        
        db_user = session.query(User).filter_by(telegram_id=user.id).first()
        
        # Check if user is admin
        is_admin = user.id in Config.ADMIN_IDS
        
        if db_user and db_user.is_banned:
            await update.message.reply_text(
                f"🚫 **You are BANNED from this bot!**\n\n"
                f"Reason: {db_user.ban_reason or 'Multiple scam reports'}\n"
                f"This is your {db_user.ban_count + 1} ban.\n\n"
                f"💰 **To unban, send {Config.UNBAN_FEE} Stars as a gift to:**\n"
                f"**@{Config.RECEIVER_USERNAME}**\n\n"
                f"📝 **Instructions:**\n"
                f"1. Click the button below to send Stars\n"
                f"2. Send exactly {Config.UNBAN_FEE} Stars\n"
                f"3. Click 'I've Sent the Stars' button after sending\n\n"
                f"⚠️ You'll be unbanned after admin confirmation.",
                parse_mode='Markdown',
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
                f"👋 Welcome to FreelanceHub, {user.full_name}!\n\n"
                f"Use the buttons below to navigate:",
                reply_markup=self.get_main_menu(is_admin)
            )
        else:
            currency_info = Config.CURRENCIES.get(db_user.currency, Config.CURRENCIES['USD'])
            role_emoji = "💼" if db_user.role == "client" else "💻" if db_user.role == "freelancer" else "🔀"
            await update.message.reply_text(
                f"👋 Welcome back, {user.full_name}!\n\n"
                f"{role_emoji} Role: {db_user.role.title()}\n"
                f"{currency_info['emoji']} Currency: {db_user.currency} ({currency_info['symbol']})\n"
                f"⭐ Rating: {self.get_average_rating(user.id):.1f}/5.0\n"
                f"📊 Reports: {db_user.report_count}/{Config.REPORT_THRESHOLD}\n\n"
                f"Select an option below:",
                reply_markup=self.get_main_menu(is_admin)
            )
        session.close()

    # ==================== TEXT HANDLER ====================
    async def text_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        
        # Handle job posting
        if context.user_data.get('posting_job'):
            step = context.user_data.get('step')
            
            if step == 'title':
                context.user_data['title'] = text
                context.user_data['step'] = 'description'
                await update.message.reply_text(
                    "Great! Now enter a **description** of the job:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]])
                )
            
            elif step == 'description':
                context.user_data['description'] = text
                context.user_data['step'] = 'category'
                await update.message.reply_text(
                    "Choose a **category**:",
                    reply_markup=self.get_categories_keyboard()
                )
            
            elif step == 'budget_min':
                try:
                    context.user_data['budget_min'] = float(text)
                except:
                    context.user_data['budget_min'] = 0
                context.user_data['step'] = 'budget_max'
                await update.message.reply_text(
                    "Enter the **maximum budget** (or type '0'):",
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
        
        # Handle broadcast caption
        elif context.user_data.get('broadcast'):
            await self.broadcast_caption(update, context, text)
        
        else:
            is_admin = update.effective_user.id in Config.ADMIN_IDS
            await update.message.reply_text(
                "Please use the buttons to navigate.",
                reply_markup=self.get_main_menu(is_admin)
            )

    async def photo_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if context.user_data.get('broadcast'):
            await self.broadcast_photo(update, context)
        else:
            is_admin = update.effective_user.id in Config.ADMIN_IDS
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
        
        job = Job(
            poster_id=user_id,
            title=context.user_data['title'],
            description=context.user_data['description'],
            category=context.user_data['category'],
            currency=currency,
            budget_min=context.user_data.get('budget_min', 0),
            budget_max=context.user_data.get('budget_max', 0),
            contact_method=context.user_data['contact_method'],
            contact_info=contact_info,
            expires_at=datetime.utcnow() + timedelta(days=30)
        )
        session.add(job)
        session.commit()
        
        min_str = f"{currency_info['symbol']}{job.budget_min:,.2f}"
        max_str = f"{currency_info['symbol']}{job.budget_max:,.2f}" if job.budget_max > 0 else "No max"
        
        await update.message.reply_text(
            f"✅ **Job posted successfully!**\n\n"
            f"📌 **Title:** {job.title}\n"
            f"📂 **Category:** {job.category}\n"
            f"💰 **Budget:** {min_str} - {max_str} ({currency})\n"
            f"📞 **Contact:** {job.contact_method}\n\n"
            f"Freelancers can now view and apply to this job!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Browse Jobs", callback_data="browse_jobs")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ])
        )
        
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
                f"⚠️ **Warning!**\n\n"
                f"You have received a scam report from another user.\n"
                f"**Report #{reported_user.report_count} of {Config.REPORT_THRESHOLD}**\n\n"
                f"Reason: {reason[:200]}\n\n"
                f"If you receive {Config.REPORT_THRESHOLD} reports, you will be **banned** "
                f"and required to pay {Config.UNBAN_FEE} Stars to unban."
            )
            
            try:
                await context.bot.send_message(
                    chat_id=reported_id,
                    text=warning_message,
                    parse_mode='Markdown'
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
                        f"🚫 **You have been BANNED!**\n\n"
                        f"You received {Config.REPORT_THRESHOLD} scam reports.\n"
                        f"To unban, send {Config.UNBAN_FEE} Stars as a gift to:\n"
                        f"**@{Config.RECEIVER_USERNAME}**\n\n"
                        f"Use /start when you're ready to pay."
                    ),
                    parse_mode='Markdown'
                )
                
                for admin_id in Config.ADMIN_IDS:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=(
                            f"🚨 **User BANNED Automatically**\n\n"
                            f"User: {reported_user.full_name} (@{reported_user.username})\n"
                            f"ID: {reported_user.telegram_id}\n"
                            f"Reports: {reported_user.report_count}\n"
                            f"Reason: {reason[:200]}"
                        ),
                        parse_mode='Markdown'
                    )
        
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
                        f"💰 **New Unban Payment Request**\n\n"
                        f"User: {user.full_name} (@{user.username or 'No username'})\n"
                        f"ID: {user.telegram_id}\n"
                        f"Amount: {Config.UNBAN_FEE} Stars\n"
                        f"Proof: {proof[:500]}"
                    ),
                    parse_mode='Markdown'
                )
            except:
                pass
        
        await update.message.reply_text(
            f"✅ **Payment proof received!**\n\n"
            f"An admin will verify your payment and unban you shortly.\n\n"
            f"💰 Amount: {Config.UNBAN_FEE} Stars\n\n"
            f"⏳ Please wait for admin confirmation.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Check Status", callback_data="check_payment")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ])
        )
        
        session.close()
        context.user_data.clear()

    # ==================== BROADCAST ====================
    async def broadcast_start_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['broadcast'] = True
        await update.callback_query.edit_message_text(
            "📢 **Send Broadcast**\n\n"
            "Please send a **photo** for the broadcast (or type 'skip' for text-only):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_panel")]])
        )

    async def broadcast_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.text and update.message.text.lower() == 'skip':
            context.user_data['broadcast_photo'] = None
            await update.message.reply_text(
                "Now send the **caption** for the message:\n"
                "(You can use HTML formatting: <b>bold</b>, <i>italic</i>)"
            )
            return
        
        if update.message.photo:
            context.user_data['broadcast_photo'] = update.message.photo[-1].file_id
            await update.message.reply_text(
                "✅ Photo received!\n\n"
                "Now send the **caption** for the message:"
            )
        else:
            await update.message.reply_text("Please send a photo or type 'skip'.")

    async def broadcast_caption(self, update: Update, context: ContextTypes.DEFAULT_TYPE, caption):
        context.user_data['broadcast_caption'] = caption
        context.user_data['broadcast_step'] = 'buttons'
        
        await update.message.reply_text(
            "Now send the **button configuration** (or type 'skip' for no buttons):\n\n"
            "Format: `Button Text | URL`\n"
            "Example: `Join Channel | https://t.me/yourchannel`\n"
            "You can send multiple buttons on separate lines."
        )

    async def broadcast_buttons(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text):
        buttons = []
        if text.lower() != 'skip':
            for line in text.split('\n'):
                if '|' in line:
                    btn_text, url = line.split('|', 1)
                    buttons.append([InlineKeyboardButton(btn_text.strip(), url=url.strip())])
        
        # Send broadcast
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
        
        # Save broadcast record
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
            f"✅ **Broadcast Complete!**\n\n"
            f"📤 Sent: {sent}\n"
            f"❌ Failed: {failed}\n"
            f"📊 Total: {len(users)} users",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👑 Admin Panel", callback_data="admin_panel")]])
        )
        
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
                f"✅ **Payment Status: Completed**\n\n"
                f"Amount: {payment.amount} Stars\n"
                f"Date: {payment.completed_at.strftime('%Y-%m-%d %H:%M')}\n\n"
                f"You are now unbanned!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
            )
        else:
            pending = session.query(UnbanPayment).filter_by(user_id=user_id, status='pending').order_by(UnbanPayment.created_at.desc()).first()
            if pending:
                await update.callback_query.edit_message_text(
                    f"⏳ **Payment Status: Pending**\n\n"
                    f"Amount: {pending.amount} Stars\n"
                    f"Submitted: {pending.created_at.strftime('%Y-%m-%d %H:%M')}\n\n"
                    f"Please wait for admin confirmation.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
                )
            else:
                await update.callback_query.edit_message_text(
                    f"💰 **No payment found**\n\n"
                    f"To unban, send {Config.UNBAN_FEE} Stars as a gift to:\n"
                    f"**@{Config.RECEIVER_USERNAME}**\n\n"
                    f"Then click 'I've Sent the Stars' button.",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(f"⭐ Send {Config.UNBAN_FEE} Stars", url=f"https://t.me/{Config.RECEIVER_USERNAME}")],
                        [InlineKeyboardButton("✅ I've Sent the Stars", callback_data="pay_unban")],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                    ])
                )
        
        session.close()

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
                "🏠 **Main Menu**\n\n"
                "Select an option below:",
                parse_mode='Markdown',
                reply_markup=self.get_main_menu(is_admin)
            )
            return
        
        # ===== HELP =====
        elif data == "help":
            await query.edit_message_text(
                "🤖 **FreelanceHub Bot - Help**\n\n"
                "📌 **What you can do:**\n"
                "• Browse and apply for jobs\n"
                "• Post your own jobs\n"
                "• Rate other users\n"
                "• Report scammers\n"
                "• Manage your profile\n\n"
                "💰 **Currencies Supported:**\n"
                + "\n".join([f"{data['emoji']} {code} ({data['symbol']})" 
                            for code, data in list(Config.CURRENCIES.items())[:6]]) +
                "\n\n📌 **How it works:**\n"
                "1. Clients post jobs\n"
                "2. Freelancers browse and apply\n"
                "3. Connect directly\n\n"
                "⚠️ Always verify identities!",
                parse_mode='Markdown',
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
                    "⚙️ **Settings**\n\n"
                    f"Current settings:",
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
                "💰 **Select your preferred currency**\n\n"
                f"Current: {Config.CURRENCIES[current]['emoji']} {current}",
                parse_mode='Markdown',
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
                f"👤 **Profile**\n\n"
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
                parse_mode='Markdown',
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
                    "❌ You need to be a **Client** to post jobs!\n"
                    "Change your role in Settings.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Settings", callback_data="settings")]])
                )
                session.close()
                return
            
            context.user_data['posting_job'] = True
            context.user_data['step'] = 'title'
            context.user_data['currency'] = user.currency
            session.close()
            
            await query.edit_message_text(
                "📝 **Create Job Listing**\n\n"
                "Please enter the **job title**:",
                parse_mode='Markdown',
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
                "Now enter the **minimum budget** (or type '0'):",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]])
            )
            return
        
        # ===== CONTACT METHOD =====
        elif data.startswith('contact_'):
            method = data.replace('contact_', '')
            context.user_data['contact_method'] = method
            context.user_data['step'] = 'contact_info'
            
            await query.edit_message_text(
                f"✅ Contact method: {method}\n\n"
                f"Please enter your **{method}** contact info:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]])
            )
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
                    "❌ You need to be a **Freelancer** to browse jobs!\n"
                    "Change your role in Settings.",
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
                    f"📌 **{job.title}**\n"
                    f"📂 Category: {job.category}\n"
                    f"💰 Budget: {min_str} - {max_str} ({job.currency})\n"
                    f"📝 {job.description[:150]}...\n\n"
                    f"👤 Client: {poster.full_name if poster else 'Unknown'}\n"
                    f"⭐ Rating: {avg_rating:.1f}/5.0\n"
                    f"📅 Posted: {job.created_at.strftime('%Y-%m-%d')}",
                    parse_mode='Markdown',
                    reply_markup=self.get_job_actions_keyboard(job.id, job.poster_id)
                )
            
            await query.message.reply_text(
                "📋 **Showing latest 5 jobs**",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Refresh", callback_data="browse_jobs")],
                    [InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]
                ])
            )
            await query.delete_message()
            return
        
        # ===== CONTACT CLIENT =====
        elif data.startswith('contact_'):
            job_id = int(data.replace('contact_', ''))
            session = Session()
            job = session.query(Job).filter_by(id=job_id, is_active=True).first()
            
            if not job:
                await query.edit_message_text("❌ This job is no longer available.")
                session.close()
                return
            
            poster = session.query(User).filter_by(telegram_id=job.poster_id).first()
            session.close()
            
            await query.edit_message_text(
                f"✅ **Contact Details**\n\n"
                f"Job: {job.title}\n\n"
                f"📞 **Contact Method:** {poster.contact_method}\n"
                f"📱 **Contact Info:** {poster.contact_info}\n\n"
                f"💡 Tip: Mention the job title when contacting!\n"
                f"⚠️ Always verify identities!",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📝 Rate Client", callback_data=f"rate_{job.poster_id}_{job.id}")],
                    [InlineKeyboardButton("🚨 Report Scam", callback_data=f"report_{job.poster_id}_{job.id}")],
                    [InlineKeyboardButton("🔙 Back to Browse", callback_data="browse_jobs")]
                ])
            )
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
                "🚨 **Report User for Scam**\n\n"
                "Please describe what happened:\n"
                "- What did they do?\n"
                "- Any evidence?\n"
                "- Amount lost?\n\n"
                "Be as detailed as possible.",
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
                    "📋 **Your Jobs**\n\n"
                    "You haven't posted any jobs yet.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💰 Post a Job", callback_data="post_job")],
                        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
                    ])
                )
                return
            
            message = "📋 **Your Active Jobs:**\n\n"
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
                parse_mode='Markdown',
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
                f"💰 **Unban Payment Process**\n\n"
                f"1. Send **{Config.UNBAN_FEE} Stars** as a gift to:\n"
                f"   **@{Config.RECEIVER_USERNAME}**\n\n"
                f"2. After sending, type your **gift message** or **screenshot** here\n"
                f"   (Any proof of payment)\n\n"
                f"3. An admin will verify and unban you\n\n"
                f"📝 Type your payment proof below:",
                parse_mode='Markdown',
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
                "👑 **Admin Panel**\n\n"
                "Select an option below:",
                parse_mode='Markdown',
                reply_markup=self.get_admin_menu()
            )
            return
        
        # ===== ADMIN STATS =====
        elif data == "admin_stats":
            if not is_admin:
                await query.edit_message_text("❌ You are not an admin.")
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
            
            await query.edit_message_text(
                f"📊 **Statistics**\n\n"
                f"👤 Users: {total_users} (Banned: {banned_users})\n"
                f"📋 Reports: {total_reports} (Pending: {pending_reports})\n"
                f"💼 Jobs: {total_jobs} (Active: {active_jobs})\n"
                f"⭐ Ratings: {total_ratings}\n"
                f"💰 Payments: {total_payments} (Pending: {pending_payments}, Completed: {completed_payments})",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]])
            )
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
            if not is_admin:
                await query.edit_message_text("❌ You are not an admin.")
                return
            
            session = Session()
            pending_reports = session.query(Report).filter_by(status='pending').all()
            
            if not pending_reports:
                await query.edit_message_text(
                    "✅ No pending reports!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]])
                )
                session.close()
                return
            
            reports_with_users = []
            for report in pending_reports[:10]:
                user = session.query(User).filter_by(telegram_id=report.reported_id).first()
                reports_with_users.append((user, report))
            
            await query.edit_message_text(
                f"📋 **Pending Reports ({len(pending_reports)})**\n\n"
                "Click a report to view details:",
                reply_markup=self.get_reports_menu(reports_with_users)
            )
            session.close()
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
                f"📋 **Report #{report.id}**\n\n"
                f"Reporter: {reporter.full_name} (@{reporter.username or 'No username'})\n"
                f"Reported: {reported.full_name} (@{reported.username or 'No username'})\n"
                f"Status: {report.status}\n"
                f"Date: {report.created_at.strftime('%Y-%m-%d %H:%M')}\n\n"
                f"**Reason:**\n{report.reason[:500]}",
                parse_mode='Markdown',
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
            session.close()
            return
        
        # ===== ADMIN PAYMENTS =====
        elif data == "admin_payments":
            if not is_admin:
                await query.edit_message_text("❌ You are not an admin.")
                return
            
            session = Session()
            pending_payments = session.query(UnbanPayment).filter_by(status='pending').all()
            
            if not pending_payments:
                await query.edit_message_text(
                    "✅ No pending payments!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]])
                )
                session.close()
                return
            
            payments_with_users = []
            for payment in pending_payments[:10]:
                user = session.query(User).filter_by(telegram_id=payment.user_id).first()
                payments_with_users.append((user, payment))
            
            await query.edit_message_text(
                f"💰 **Pending Unban Payments ({len(pending_payments)})**\n\n"
                "Click a payment to view:",
                reply_markup=self.get_payments_menu(payments_with_users)
            )
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
                f"💰 **Payment #{payment.id}**\n\n"
                f"User: {user.full_name} (@{user.username or 'No username'})\n"
                f"Amount: {payment.amount} Stars\n"
                f"Status: {payment.status}\n"
                f"Date: {payment.created_at.strftime('%Y-%m-%d %H:%M')}",
                parse_mode='Markdown',
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
                            f"✅ **You have been unbanned!**\n\n"
                            f"Welcome back! Please follow the rules.\n"
                            f"This was your {user.ban_count} ban."
                        ),
                        parse_mode='Markdown',
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
                    )
                except:
                    pass
                
                await query.edit_message_text(
                    f"✅ Payment confirmed! User unbanned.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Payments", callback_data="admin_payments")]])
                )
            else:
                await query.edit_message_text("❌ User is not banned or not found.")
            
            session.close()
            return
        
        # ===== ADMIN USERS =====
        elif data == "admin_users":
            if not is_admin:
                await query.edit_message_text("❌ You are not an admin.")
                return
            
            session = Session()
            users = session.query(User).order_by(User.created_at.desc()).limit(20).all()
            session.close()
            
            if not users:
                await query.edit_message_text(
                    "No users found.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel")]])
                )
                return
            
            await query.edit_message_text(
                "👥 **Recent Users**\n\n"
                "Click a user to manage:",
                reply_markup=self.get_users_menu(users)
            )
            return
        
        # ===== VIEW USER =====
        elif data.startswith('view_user_'):
            if not is_admin:
                await query.edit_message_text("❌ You are not an admin.")
                return
            
            target_id = int(data.replace('view_user_', ''))
            session = Session()
            user = session.query(User).filter_by(telegram_id=target_id).first()
            
            if not user:
                await query.edit_message_text("❌ User not found.")
                session.close()
                return
            
            avg_rating = self.get_average_rating(target_id)
            
            await query.edit_message_text(
                f"👤 **User Details**\n\n"
                f"Name: {user.full_name}\n"
                f"Username: @{user.username or 'Not set'}\n"
                f"Role: {user.role.title()}\n"
                f"Currency: {user.currency}\n"
                f"⭐ Rating: {avg_rating:.1f}/5.0\n"
                f"📊 Reports: {user.report_count}\n"
                f"🚫 Banned: {'Yes' if user.is_banned else 'No'}\n"
                f"📅 Joined: {user.created_at.strftime('%Y-%m-%d')}",
                parse_mode='Markdown',
                reply_markup=self.get_user_actions_menu(target_id)
            )
            session.close()
            return
        
        # ===== UNBAN USER =====
        elif data.startswith('unban_user_'):
            if not is_admin:
                await query.edit_message_text("❌ You are not an admin.")
                return
            
            target_id = int(data.replace('unban_user_', ''))
            session = Session()
            user = session.query(User).filter_by(telegram_id=target_id).first()
            
            if user and user.is_banned:
                user.is_banned = False
                user.ban_reason = None
                session.commit()
                
                try:
                    await context.bot.send_message(
                        chat_id=target_id,
                        text="✅ You have been unbanned by an admin!",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
                    )
                except:
                    pass
                
                await query.edit_message_text(
                    f"✅ User {user.full_name} has been unbanned!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Users", callback_data="admin_users")]])
                )
            else:
                await query.edit_message_text("❌ User is not banned or not found.")
            session.close()
            return
        
        # ===== BAN USER =====
        elif data.startswith('ban_user_'):
            if not is_admin:
                await query.edit_message_text("❌ You are not an admin.")
                return
            
            target_id = int(data.replace('ban_user_', ''))
            session = Session()
            user = session.query(User).filter_by(telegram_id=target_id).first()
            
            if user and not user.is_banned:
                user.is_banned = True
                user.ban_reason = "Banned by admin"
                session.commit()
                
                try:
                    await context.bot.send_message(
                        chat_id=target_id,
                        text="🚫 You have been banned by an admin!",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
                    )
                except:
                    pass
                
                await query.edit_message_text(
                    f"✅ User {user.full_name} has been banned!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Users", callback_data="admin_users")]])
                )
            else:
                await query.edit_message_text("❌ User is already banned or not found.")
            session.close()
            return
        
        # ===== MAKE ADMIN =====
        elif data.startswith('make_admin_'):
            if not is_admin:
                await query.edit_message_text("❌ You are not an admin.")
                return
            
            target_id = int(data.replace('make_admin_', ''))
            session = Session()
            user = session.query(User).filter_by(telegram_id=target_id).first()
            
            if user:
                if target_id in Config.ADMIN_IDS:
                    await query.edit_message_text("This user is already an admin!")
                else:
                    Config.ADMIN_IDS.append(target_id)
                    session.commit()
                    await query.edit_message_text(
                        f"✅ User {user.full_name} is now an admin!",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Users", callback_data="admin_users")]])
                    )
            else:
                await query.edit_message_text("❌ User not found.")
            session.close()
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

    # ==================== GET AVERAGE RATING ====================
    def get_average_rating(self, user_id):
        session = Session()
        ratings = session.query(Rating).filter_by(reviewee_id=user_id).all()
        session.close()
        if not ratings:
            return 0.0
        avg = sum(r.rating for r in ratings) / len(ratings)
        return round(avg, 1)

    # ==================== RUN ====================
    def run(self):
        self.application.run_polling()

if __name__ == '__main__':
    bot = FreelanceBot()
    bot.run()