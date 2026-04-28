import re
import pytz
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from dateutil.relativedelta import relativedelta
from src.database import SessionLocal
from src.services.reminder_service import ReminderService
from src.services.user_service import UserService
from src.models.reminder import ReminderType
from src.utils.timezone_utils import parse_time_input, convert_to_user_timezone, parse_recurring_pattern
from datetime import timedelta

def _advance_in_local_tz(scheduled_time_utc: datetime, user_timezone: str, advance) -> datetime:
    """Advance UTC scheduled_time by `advance` in the user's local TZ, preserving wall-clock time across DST."""
    tz_name = 'Europe/Kyiv' if user_timezone == 'Europe/Kiev' else user_timezone
    user_tz = pytz.timezone(tz_name)
    aware_utc = pytz.UTC.localize(scheduled_time_utc)
    local_naive = aware_utc.astimezone(user_tz).replace(tzinfo=None)
    new_local_naive = advance(local_naive)
    new_local_aware = user_tz.localize(new_local_naive, is_dst=False)
    return new_local_aware.astimezone(pytz.UTC).replace(tzinfo=None)

def _calculate_next_occurrence(reminder, user_timezone: str) -> datetime:
    """Calculate the next occurrence for a repeating reminder (DST-safe in user's local TZ)"""
    if reminder.reminder_type != "repeating" or not reminder.repeat_interval:
        return None

    weekly_advance = lambda dt: dt + timedelta(weeks=1)

    if reminder.repeat_interval == "daily":
        return _advance_in_local_tz(reminder.scheduled_time, user_timezone, lambda dt: dt + timedelta(days=1))
    elif reminder.repeat_interval == "weekly":
        return _advance_in_local_tz(reminder.scheduled_time, user_timezone, weekly_advance)
    elif reminder.repeat_interval == "monthly":
        return _advance_in_local_tz(reminder.scheduled_time, user_timezone, lambda dt: dt + relativedelta(months=1))
    elif reminder.repeat_interval.startswith("custom_"):
        parts = reminder.repeat_interval.split('_')
        if len(parts) == 3:
            try:
                number = int(parts[1])
                unit = parts[2]

                if unit == 'days':
                    advance = lambda dt: dt + timedelta(days=number)
                elif unit == 'weeks':
                    advance = lambda dt: dt + timedelta(weeks=number)
                elif unit == 'months':
                    advance = lambda dt: dt + relativedelta(months=number)
                else:
                    advance = weekly_advance
            except ValueError:
                advance = weekly_advance
        else:
            advance = weekly_advance
        return _advance_in_local_tz(reminder.scheduled_time, user_timezone, advance)
    elif reminder.repeat_interval.startswith("multi-day:"):
        days_str = reminder.repeat_interval.replace("multi-day: ", "")
        target_days = [day.strip() for day in days_str.split(",")]

        day_map = {
            'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
            'friday': 4, 'saturday': 5, 'sunday': 6
        }

        target_weekdays = [day_map[day] for day in target_days if day in day_map]

        if target_weekdays:
            tz_name = 'Europe/Kyiv' if user_timezone == 'Europe/Kiev' else user_timezone
            user_tz = pytz.timezone(tz_name)
            current_weekday = pytz.UTC.localize(reminder.scheduled_time).astimezone(user_tz).weekday()
            days_to_add = None
            for days_ahead in range(1, 8):
                future_weekday = (current_weekday + days_ahead) % 7
                if future_weekday in target_weekdays:
                    days_to_add = days_ahead
                    break
            advance = (lambda dt, d=days_to_add: dt + timedelta(days=d)) if days_to_add is not None else weekly_advance
        else:
            advance = weekly_advance
        return _advance_in_local_tz(reminder.scheduled_time, user_timezone, advance)

    return reminder.scheduled_time

def escape_markdown(text: str) -> str:
    """Escape special characters for Markdown parse mode"""
    # Escape only the most critical MarkdownV2 characters that cause parsing issues
    # Parentheses often don't need escaping for regular text content
    special_chars = ['_', '*', '[', ']', '~', '`', '>', '#', '+', '=', '|', '{', '}', '.', '\\']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

def escape_username(username: str) -> str:
    """Escape underscores in usernames to prevent Markdown formatting while preserving @ functionality"""
    return username.replace('_', '\\_')

async def add_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        # Start interactive mode
        from src.handlers.interactive_handlers import start_interactive_reminder, REMINDER_TIME
        await start_interactive_reminder(update, context)
        return REMINDER_TIME
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    chat_title = update.effective_chat.title if update.effective_chat.type in ['group', 'supergroup'] else None
    
    with SessionLocal() as db:
        user_service = UserService(db)
        user_timezone = user_service.get_user_timezone(user_id)
        
        text = " ".join(context.args)
        
        requires_confirmation = "confirm" in text.lower()
        text = re.sub(r'\bconfirm\b', '', text, flags=re.IGNORECASE).strip()
        
        # Parse recurring patterns
        text, repeat_interval = parse_recurring_pattern(text)
        
        reminder_type = ReminderType.REPEATING if repeat_interval else ReminderType.ONE_TIME
        
        parts = text.split(' ', 1)
        if len(parts) < 2:
            await update.message.reply_text("Please provide both time and message.")
            return
        
        time_part, message = parts
        
        scheduled_time = parse_time_input(time_part, user_timezone)
        if not scheduled_time:
            await update.message.reply_text(
                "Invalid time format. Use formats like: 10:30, 2h, 30m, 1d, 1w, 25th at 10AM"
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
            chat_title=chat_title,
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
        keyboard = []
        
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
                
                if reminder.chat_title:
                    response += f"   💬 Group: {escape_markdown(reminder.chat_title)}\n"
                
                if reminder.reminder_type == "repeating" and reminder.repeat_interval:
                    # Format custom periods nicely
                    if reminder.repeat_interval.startswith("custom_"):
                        parts = reminder.repeat_interval.split('_')
                        if len(parts) == 3:
                            response += f"   🔄 Repeats: every {parts[1]} {parts[2]}\n"
                        else:
                            response += f"   🔄 Repeats: {reminder.repeat_interval}\n"
                    else:
                        response += f"   🔄 Repeats: {reminder.repeat_interval}\n"
                    next_occurrence = _calculate_next_occurrence(reminder, user_timezone)
                    if next_occurrence:
                        next_user_time = convert_to_user_timezone(next_occurrence, user_timezone)
                        response += f"   ⏭️ Next: {next_user_time.strftime('%Y-%m-%d %H:%M')}\n"
                
                if reminder.snooze_count > 0:
                    response += f"   😴 Snoozed {reminder.snooze_count} time(s)\n"
                
                if reminder.tagged_users:
                    # Escape underscores in usernames to prevent Markdown formatting
                    response += f"   👥 Tagged: {' '.join([escape_username(user) for user in reminder.tagged_users])}\n"
                
                # Add cancel button for each reminder
                keyboard.append([InlineKeyboardButton(f"❌ Cancel: {reminder.message_text[:20]}{'...' if len(reminder.message_text) > 20 else ''}", callback_data=f"cancel_{reminder.id}")])
                
                response += "\n"
        
        # Add refresh and back buttons
        keyboard.extend([
            [InlineKeyboardButton("🔄 Refresh", callback_data="refresh_reminders")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
        ])
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