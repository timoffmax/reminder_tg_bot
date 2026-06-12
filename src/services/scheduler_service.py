import asyncio
from datetime import datetime, timedelta
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from src.database import SessionLocal
from src.services.reminder_service import ReminderService
from src.services.user_service import UserService
from src.models.reminder import Reminder, ReminderStatus
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

def format_snooze_label(minutes: int) -> str:
    """Render a snooze duration as a compact button label (45 -> '45m', 120 -> '2h')."""
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"

def build_snooze_buttons(reminder: Reminder) -> list:
    """Snooze buttons honoring the reminder's own default snooze duration.

    Always offers two distinct options: the reminder's default plus 1h
    (or 10m/1h when the default is 1h itself).
    """
    default_minutes = reminder.default_snooze_minutes or ReminderService.DEFAULT_SNOOZE_MINUTES
    if default_minutes == 60:
        options = [10, 60]
    else:
        options = sorted({default_minutes, 60})
    return [
        InlineKeyboardButton(f"😴 {format_snooze_label(minutes)}", callback_data=f"snooze_{reminder.id}_{minutes}")
        for minutes in options
    ]

class SchedulerService:
    def __init__(self, scheduler: AsyncIOScheduler, bot: Bot):
        self.scheduler = scheduler
        self.bot = bot
        self._schedule_existing_reminders()
        self._schedule_reminder_check()
    
    def _schedule_existing_reminders(self):
        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            # Get all active and snoozed reminders to reschedule after restart
            # SNOOZED reminders must also be included as they have pending scheduled times
            from src.models.reminder import ReminderStatus
            pending_reminders = db.query(Reminder).filter(
                Reminder.status.in_([ReminderStatus.ACTIVE.value, ReminderStatus.SNOOZED.value])
            ).all()

            for reminder in pending_reminders:
                self.schedule_reminder(reminder)
    
    def schedule_reminder(self, reminder: Reminder):
        # Paused/cancelled/completed reminders should never be scheduled.
        if reminder.status in (
            ReminderStatus.PAUSED.value,
            ReminderStatus.CANCELLED.value,
            ReminderStatus.COMPLETED.value,
        ):
            self.remove_job(reminder.id)
            return

        job_id = f"reminder_{reminder.id}"

        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        # Ensure the scheduled time is timezone-aware (UTC)
        scheduled_time = reminder.scheduled_time
        if scheduled_time.tzinfo is None:
            scheduled_time = pytz.UTC.localize(scheduled_time)

        # Apply the user's quiet-hours preference: shift firing into the next active window.
        scheduled_time = self._apply_quiet_hours(reminder.user_id, scheduled_time)

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
            timezone=pytz.UTC,
            # A late reminder must still be delivered; the default 1s grace
            # silently drops jobs whenever the event loop is briefly busy.
            misfire_grace_time=None
        )

    def _apply_quiet_hours(self, telegram_user_id: int, scheduled_time_aware: datetime) -> datetime:
        """If the scheduled time falls inside the user's quiet hours, shift it to the end of the quiet window."""
        with SessionLocal() as db:
            user_service = UserService(db)
            quiet = user_service.get_quiet_hours(telegram_user_id)
            tz_name = user_service.get_user_timezone(telegram_user_id)

        if not quiet:
            return scheduled_time_aware

        start_h, end_h = quiet
        if start_h == end_h:
            return scheduled_time_aware

        if tz_name == 'Europe/Kiev':
            tz_name = 'Europe/Kyiv'
        user_tz = pytz.timezone(tz_name)
        local = scheduled_time_aware.astimezone(user_tz)
        hour = local.hour

        # quiet window may wrap midnight (e.g. 23 -> 8)
        in_quiet = (start_h < end_h and start_h <= hour < end_h) or (
            start_h > end_h and (hour >= start_h or hour < end_h)
        )
        if not in_quiet:
            return scheduled_time_aware

        target = local.replace(hour=end_h, minute=0, second=0, microsecond=0)
        if start_h > end_h and hour >= start_h:
            # wrapped past midnight: end_h is on the next day
            target = target + timedelta(days=1)

        return user_tz.localize(target.replace(tzinfo=None), is_dst=False).astimezone(pytz.UTC)
    
    def remove_job(self, reminder_id: int) -> bool:
        """Safely remove a pending scheduler job for the given reminder."""
        job_id = f"reminder_{reminder_id}"
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            return True
        return False

    async def _send_reminder(self, reminder_id: int):
        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            user_service = UserService(db)

            reminder = reminder_service.get_reminder_by_id(reminder_id)
            if not reminder:
                return

            # Don't deliver reminders the user has cancelled, completed, or paused —
            # protects against stale scheduler jobs that weren't removed.
            if reminder.status in (
                ReminderStatus.CANCELLED.value,
                ReminderStatus.COMPLETED.value,
                ReminderStatus.PAUSED.value,
            ):
                return
            
            user_timezone = user_service.get_user_timezone(reminder.user_id)
            
            message = f"🔔 *Reminder:* {escape_markdown(reminder.message_text)}"
            
            if reminder.tagged_users:
                # Escape underscores in usernames to prevent Markdown formatting
                tagged_mentions = " ".join([escape_username(user) for user in reminder.tagged_users])
                message += f"\n👥 {tagged_mentions}"
            
            keyboard = []

            if reminder.requires_confirmation and not reminder.is_confirmed:
                keyboard.append(
                    [InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_{reminder.id}")]
                    + build_snooze_buttons(reminder)
                )
                keyboard.append([
                    InlineKeyboardButton("🌅 Tomorrow 9am", callback_data=f"snoozeto_{reminder.id}_tomorrow_morning"),
                    InlineKeyboardButton("📅 Mon 9am", callback_data=f"snoozeto_{reminder.id}_monday_morning"),
                ])
                keyboard.append([
                    InlineKeyboardButton("⏰ Reschedule", callback_data=f"reschedule_{reminder.id}")
                ])
            elif reminder.requires_confirmation and reminder.is_confirmed:
                # Confirmed reminders get a Done button
                keyboard.append(
                    [InlineKeyboardButton("✅ Done", callback_data=f"complete_{reminder.id}")]
                    + build_snooze_buttons(reminder)
                )
                keyboard.append([
                    InlineKeyboardButton("🌅 Tomorrow 9am", callback_data=f"snoozeto_{reminder.id}_tomorrow_morning"),
                    InlineKeyboardButton("⏰ Reschedule", callback_data=f"reschedule_{reminder.id}"),
                ])
            else:
                # Non-confirmation reminders get only snooze and reschedule
                keyboard.append(build_snooze_buttons(reminder))
                keyboard.append([
                    InlineKeyboardButton("🌅 Tomorrow 9am", callback_data=f"snoozeto_{reminder.id}_tomorrow_morning"),
                    InlineKeyboardButton("📅 Mon 9am", callback_data=f"snoozeto_{reminder.id}_monday_morning"),
                ])
                keyboard.append([
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

                # For repeating reminders, always schedule the next occurrence
                # Confirmation status should not block the schedule
                if reminder.reminder_type == "repeating":
                    requires_confirmation = reminder.requires_confirmation
                    reminder_service.complete_reminder(reminder.id)

                    # Advancing the series must not lose the pending confirmation:
                    # re-sends are tracked via last_confirmation_request_at, not scheduled_time.
                    if requires_confirmation:
                        reminder_service.mark_confirmation_requested(reminder.id)

                    updated_reminder = reminder_service.get_reminder_by_id(reminder.id)
                    if updated_reminder and updated_reminder.status == "active":
                        self.schedule_reminder(updated_reminder)
                elif not reminder.requires_confirmation:
                    # Complete non-confirmation one-time reminders
                    reminder_service.complete_reminder(reminder.id)
                else:
                    # One-time confirmation reminders stay pending until the user
                    # confirms; this also reactivates previously snoozed ones so
                    # they keep receiving re-sends.
                    reminder_service.mark_confirmation_requested(reminder.id)

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
            replace_existing=True,
            # Never skip a check cycle just because the loop was busy at the tick;
            # coalesce collapses any backlog into a single run.
            misfire_grace_time=None,
            coalesce=True
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
                    [InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_{reminder.id}")]
                    + build_snooze_buttons(reminder),
                    [
                        InlineKeyboardButton("🌅 Tomorrow 9am", callback_data=f"snoozeto_{reminder.id}_tomorrow_morning"),
                        InlineKeyboardButton("⏰ Reschedule", callback_data=f"reschedule_{reminder.id}"),
                    ],
                    [
                        InlineKeyboardButton("📝 View History", callback_data=f"history_{reminder.id}")
                    ],
                ]

                reply_markup = InlineKeyboardMarkup(keyboard)

                try:
                    await self.bot.send_message(
                        chat_id=reminder.chat_id,
                        text=message,
                        parse_mode='Markdown',
                        reply_markup=reply_markup
                    )

                    # Restart the per-reminder re-send countdown.
                    reminder_service.mark_confirmation_requested(reminder.id)
                except Exception as e:
                    print(f"Error re-sending unconfirmed reminder {reminder.id}: {e}")
