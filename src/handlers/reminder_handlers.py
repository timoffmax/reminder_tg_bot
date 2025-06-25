import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from src.database import SessionLocal
from src.services.reminder_service import ReminderService
from src.services.user_service import UserService
from src.models.reminder import ReminderType
from src.utils.timezone_utils import parse_time_input, convert_to_user_timezone

def escape_markdown(text: str) -> str:
    """Escape special characters for Markdown parse mode"""
    # Only escape characters that actually need escaping in Telegram MarkdownV2
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

async def add_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        # Start interactive mode
        from src.handlers.interactive_handlers import start_interactive_reminder, REMINDER_TIME
        await start_interactive_reminder(update, context)
        return REMINDER_TIME
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    with SessionLocal() as db:
        user_service = UserService(db)
        user_timezone = user_service.get_user_timezone(user_id)
        
        text = " ".join(context.args)
        
        requires_confirmation = "confirm" in text.lower()
        text = re.sub(r'\bconfirm\b', '', text, flags=re.IGNORECASE).strip()
        
        reminder_type = ReminderType.ONE_TIME
        repeat_interval = None
        
        if "daily" in text.lower():
            reminder_type = ReminderType.REPEATING
            repeat_interval = "daily"
            text = re.sub(r'\bdaily\b', '', text, flags=re.IGNORECASE).strip()
        elif "weekly" in text.lower():
            reminder_type = ReminderType.REPEATING
            repeat_interval = "weekly"
            text = re.sub(r'\bweekly\b', '', text, flags=re.IGNORECASE).strip()
        elif "monthly" in text.lower():
            reminder_type = ReminderType.REPEATING
            repeat_interval = "monthly"
            text = re.sub(r'\bmonthly\b', '', text, flags=re.IGNORECASE).strip()
        
        parts = text.split(' ', 1)
        if len(parts) < 2:
            await update.message.reply_text("Please provide both time and message.")
            return
        
        time_part, message = parts
        
        scheduled_time = parse_time_input(time_part, user_timezone)
        if not scheduled_time:
            await update.message.reply_text(
                "Invalid time format. Use formats like: 10:30, 2h, 30m, 1d, 1w"
            )
            return
        
        tagged_users = []
        if update.effective_chat.type != 'private':
            entities = update.message.entities or []
            for entity in entities:
                if entity.type == 'mention':
                    username = update.message.text[entity.offset:entity.offset + entity.length]
                    tagged_users.append(username)
            
            # If no mentions found with entities, try manual parsing
            if not tagged_users:
                import re
                # Find all @username patterns (including underscores and numbers)
                mentions = re.findall(r'@[a-zA-Z0-9_]+', update.message.text)
                tagged_users = mentions
        
        reminder_service = ReminderService(db)
        reminder = reminder_service.create_reminder(
            user_id=user_id,
            chat_id=chat_id,
            message_text=message,
            scheduled_time=scheduled_time,
            reminder_type=reminder_type,
            requires_confirmation=requires_confirmation,
            tagged_users=tagged_users,
            repeat_interval=repeat_interval
        )
        
        scheduler_service = context.bot_data.get('scheduler_service')
        if scheduler_service:
            scheduler_service.schedule_reminder(reminder)
        
        user_time = convert_to_user_timezone(scheduled_time, user_timezone)
        response = f"✅ Reminder set for {user_time.strftime('%Y-%m-%d %H:%M')} ({user_timezone})"
        
        if reminder_type == ReminderType.REPEATING:
            response += f" (repeating {repeat_interval})"
        if requires_confirmation:
            response += " (requires confirmation)"
        
        await update.message.reply_text(response)

async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    with SessionLocal() as db:
        reminder_service = ReminderService(db)
        user_service = UserService(db)
        
        reminders = reminder_service.get_active_reminders(user_id)
        user_timezone = user_service.get_user_timezone(user_id)
        
        response = "*Your Active Reminders:*\n\n"
        
        if not reminders:
            response = "You have no active reminders."
        else:
            for reminder in reminders:
                user_time = convert_to_user_timezone(reminder.scheduled_time, user_timezone)
                status_emoji = "🔄" if reminder.reminder_type == "repeating" else "⏰"
                if reminder.requires_confirmation:
                    status_emoji += "❓" if not reminder.is_confirmed else "✅"
                
                response += (
                    f"{status_emoji} {escape_markdown(reminder.message_text)}\n"
                    f"   📅 {user_time.strftime('%Y-%m-%d %H:%M')} ({escape_markdown(user_timezone)})\n"
                )
                
                if reminder.snooze_count > 0:
                    response += f"   😴 Snoozed {reminder.snooze_count} time(s)\n"
                
                if reminder.tagged_users:
                    response += f"   👥 Tagged: {escape_markdown(' '.join(reminder.tagged_users))}\n"
                
                response += "\n"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_reminders")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Handle both message and callback query
        if update.message:
            await update.message.reply_text(
                response, 
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        elif update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    response,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
            except Exception as e:
                # If message is the same, just answer the callback
                if "Message is not modified" in str(e):
                    await update.callback_query.answer("✅ Reminders refreshed!")
                else:
                    # For other errors, send a new message
                    await update.callback_query.message.reply_text(
                        response,
                        parse_mode='Markdown',
                        reply_markup=reply_markup
                    )

async def snooze_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /snooze <reminder_id> [minutes]")
        return
    
    try:
        reminder_id = int(context.args[0])
        snooze_minutes = int(context.args[1]) if len(context.args) > 1 else 10
    except ValueError:
        await update.message.reply_text("Invalid reminder ID or snooze duration.")
        return
    
    with SessionLocal() as db:
        reminder_service = ReminderService(db)
        success = reminder_service.snooze_reminder(reminder_id, snooze_minutes)
    
    if success:
        await update.message.reply_text(f"⏰ Reminder {reminder_id} snoozed for {snooze_minutes} minutes.")
    else:
        await update.message.reply_text("Reminder not found or cannot be snoozed.")

async def cancel_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /cancel <reminder_id>")
        return
    
    try:
        reminder_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid reminder ID.")
        return
    
    with SessionLocal() as db:
        reminder_service = ReminderService(db)
        success = reminder_service.cancel_reminder(reminder_id)
    
    if success:
        await update.message.reply_text(f"❌ Reminder {reminder_id} cancelled.")
    else:
        await update.message.reply_text("Reminder not found.")

async def confirm_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /confirm <reminder_id>")
        return
    
    try:
        reminder_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid reminder ID.")
        return
    
    with SessionLocal() as db:
        reminder_service = ReminderService(db)
        success = reminder_service.confirm_reminder(reminder_id)
    
    if success:
        await update.message.reply_text(f"✅ Reminder {reminder_id} confirmed.")
    else:
        await update.message.reply_text("Reminder not found or doesn't require confirmation.")