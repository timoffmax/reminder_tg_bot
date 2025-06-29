import asyncio
from datetime import datetime, timedelta
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from src.database import SessionLocal
from src.services.reminder_service import ReminderService
from src.services.user_service import UserService
from src.models.reminder import Reminder
from src.utils.timezone_utils import convert_to_user_timezone

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

class SchedulerService:
    def __init__(self, scheduler: AsyncIOScheduler, bot: Bot):
        self.scheduler = scheduler
        self.bot = bot
        self._schedule_existing_reminders()
        self._schedule_reminder_check()
    
    def _schedule_existing_reminders(self):
        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            # Get all active reminders to reschedule after restart
            from src.models.reminder import ReminderStatus
            active_reminders = db.query(Reminder).filter(
                Reminder.status == ReminderStatus.ACTIVE.value
            ).all()
            
            for reminder in active_reminders:
                self.schedule_reminder(reminder)
    
    def schedule_reminder(self, reminder: Reminder):
        job_id = f"reminder_{reminder.id}"
        
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
        
        # Ensure the scheduled time is timezone-aware (UTC)
        scheduled_time = reminder.scheduled_time
        if scheduled_time.tzinfo is None:
            scheduled_time = pytz.UTC.localize(scheduled_time)
        
        now_utc = datetime.now(pytz.UTC)
        
        # If reminder is in the past, schedule it to run immediately
        if scheduled_time <= now_utc:
            scheduled_time = now_utc + timedelta(seconds=1)
        
        self.scheduler.add_job(
            func=self._send_reminder,
            trigger="date",
            run_date=scheduled_time,
            args=[reminder.id],
            id=job_id,
            replace_existing=True,
            timezone=pytz.UTC
        )
    
    async def _send_reminder(self, reminder_id: int):
        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            user_service = UserService(db)
            
            reminder = reminder_service.get_reminder_by_id(reminder_id)
            if not reminder:
                return
            
            user_timezone = user_service.get_user_timezone(reminder.user_id)
            
            message = f"🔔 *Reminder:* {escape_markdown(reminder.message_text)}"
            
            if reminder.tagged_users:
                # Escape underscores in usernames to prevent Markdown formatting
                tagged_mentions = " ".join([escape_username(user) for user in reminder.tagged_users])
                message += f"\n👥 {tagged_mentions}"
            
            keyboard = []
            
            if reminder.requires_confirmation and not reminder.is_confirmed:
                keyboard.append([
                    InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_{reminder.id}"),
                    InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{reminder.id}")
                ])
                keyboard.append([
                    InlineKeyboardButton("😴 Snooze 10m", callback_data=f"snooze_{reminder.id}_10"),
                    InlineKeyboardButton("⏰ Reschedule", callback_data=f"reschedule_{reminder.id}")
                ])
            elif reminder.requires_confirmation and reminder.is_confirmed:
                # Confirmed reminders get a Done button
                keyboard.append([
                    InlineKeyboardButton("✅ Done", callback_data=f"complete_{reminder.id}"),
                    InlineKeyboardButton("😴 Snooze 10m", callback_data=f"snooze_{reminder.id}_10"),
                    InlineKeyboardButton("😴 Snooze 1h", callback_data=f"snooze_{reminder.id}_60")
                ])
                keyboard.append([
                    InlineKeyboardButton("⏰ Reschedule", callback_data=f"reschedule_{reminder.id}")
                ])
            else:
                # Non-confirmation reminders get only snooze and reschedule
                keyboard.append([
                    InlineKeyboardButton("😴 Snooze 10m", callback_data=f"snooze_{reminder.id}_10"),
                    InlineKeyboardButton("😴 Snooze 1h", callback_data=f"snooze_{reminder.id}_60"),
                    InlineKeyboardButton("⏰ Reschedule", callback_data=f"reschedule_{reminder.id}")
                ])
            
            keyboard.append([
                InlineKeyboardButton("📝 View History", callback_data=f"history_{reminder.id}")
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await self.bot.send_message(
                    chat_id=reminder.chat_id,
                    text=message,
                    parse_mode='Markdown',
                    reply_markup=reply_markup
                )
                
                if reminder.requires_confirmation and not reminder.is_confirmed:
                    pass
                else:
                    reminder_service.complete_reminder(reminder.id)
                    
                    if reminder.reminder_type == "repeating":
                        updated_reminder = reminder_service.get_reminder_by_id(reminder.id)
                        if updated_reminder:
                            self.schedule_reminder(updated_reminder)
                            
            except Exception as e:
                print(f"Error sending reminder {reminder_id}: {e}")
    
    def reschedule_reminder(self, reminder_id: int):
        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            reminder = reminder_service.get_reminder_by_id(reminder_id)
            
            if reminder:
                self.schedule_reminder(reminder)
    
    def _schedule_reminder_check(self):
        self.scheduler.add_job(
            func=self._check_unconfirmed_reminders,
            trigger="interval",
            minutes=5,
            id="check_unconfirmed_reminders",
            replace_existing=True
        )
    
    async def _check_unconfirmed_reminders(self):
        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            user_service = UserService(db)
            
            overdue_reminders = reminder_service.get_unconfirmed_overdue_reminders()
            
            for reminder in overdue_reminders:
                user_timezone = user_service.get_user_timezone(reminder.user_id)
                
                message = f"⚠️ *Unconfirmed Reminder:* {escape_markdown(reminder.message_text)}\n\n"
                message += "This reminder requires your confirmation. Please confirm or take action:"
                
                if reminder.tagged_users:
                    # Escape underscores in usernames to prevent Markdown formatting
                    tagged_mentions = " ".join([escape_username(user) for user in reminder.tagged_users])
                    message += f"\n👥 {tagged_mentions}"
                
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_{reminder.id}"),
                        InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{reminder.id}")
                    ],
                    [
                        InlineKeyboardButton("😴 Snooze 10m", callback_data=f"snooze_{reminder.id}_10"),
                        InlineKeyboardButton("⏰ Reschedule", callback_data=f"reschedule_{reminder.id}")
                    ],
                    [
                        InlineKeyboardButton("📝 View History", callback_data=f"history_{reminder.id}")
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                try:
                    await self.bot.send_message(
                        chat_id=reminder.chat_id,
                        text=message,
                        parse_mode='Markdown',
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    print(f"Error re-sending unconfirmed reminder {reminder.id}: {e}")