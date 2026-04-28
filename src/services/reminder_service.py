from datetime import datetime, timedelta
from typing import Callable, List, Optional
from sqlalchemy.orm import Session
from dateutil.relativedelta import relativedelta
import pytz
from src.models.reminder import Reminder, ReminderHistory, ReminderType, ReminderStatus
from src.models.user import User
from src.config import DEFAULT_TIMEZONE
from src.database import get_db

class ReminderService:
    def __init__(self, db: Session):
        self.db = db
    
    def create_reminder(
        self,
        user_id: int,
        chat_id: int,
        message_text: str,
        scheduled_time: datetime,
        reminder_type: ReminderType = ReminderType.ONE_TIME,
        requires_confirmation: bool = False,
        tagged_users: List[int] = None,
        repeat_interval: Optional[str] = None,
        chat_title: Optional[str] = None
    ) -> Reminder:
        reminder = Reminder(
            user_id=user_id,
            chat_id=chat_id,
            chat_title=chat_title,
            message_text=message_text,
            scheduled_time=scheduled_time,
            reminder_type=reminder_type.value,
            requires_confirmation=requires_confirmation,
            tagged_users=tagged_users or [],
            repeat_interval=repeat_interval
        )
        
        self.db.add(reminder)
        self.db.commit()
        self.db.refresh(reminder)
        
        self._log_action(reminder.id, "created")
        return reminder
    
    def get_active_reminders(self, user_id: int) -> List[Reminder]:
        return self.db.query(Reminder).filter(
            Reminder.user_id == user_id,
            Reminder.status == ReminderStatus.ACTIVE.value
        ).order_by(Reminder.scheduled_time).all()
    
    def get_reminder_by_id(self, reminder_id: int) -> Optional[Reminder]:
        return self.db.query(Reminder).filter(Reminder.id == reminder_id).first()
    
    def get_due_reminders(self) -> List[Reminder]:
        now = datetime.now(pytz.UTC).replace(tzinfo=None)
        return self.db.query(Reminder).filter(
            Reminder.scheduled_time <= now,
            Reminder.status == ReminderStatus.ACTIVE.value
        ).all()
    
    def snooze_reminder(self, reminder_id: int, snooze_minutes: int = 10) -> bool:
        reminder = self.get_reminder_by_id(reminder_id)
        if not reminder:
            return False
        
        reminder.scheduled_time += timedelta(minutes=snooze_minutes)
        reminder.status = ReminderStatus.SNOOZED.value
        reminder.snooze_count += 1
        
        self.db.commit()
        self._log_action(reminder_id, "snoozed", {"snooze_minutes": snooze_minutes})
        return True
    
    def complete_reminder(self, reminder_id: int) -> bool:
        reminder = self.get_reminder_by_id(reminder_id)
        if not reminder:
            return False
        
        if reminder.reminder_type == ReminderType.REPEATING.value:
            self._reschedule_repeating_reminder(reminder)
        else:
            reminder.status = ReminderStatus.COMPLETED.value
        
        self.db.commit()
        self._log_action(reminder_id, "completed")
        return True
    
    def confirm_reminder(self, reminder_id: int) -> bool:
        reminder = self.get_reminder_by_id(reminder_id)
        if not reminder or not reminder.requires_confirmation:
            return False
        
        reminder.is_confirmed = True
        self.db.commit()
        self._log_action(reminder_id, "confirmed")
        return True
    
    def cancel_reminder(self, reminder_id: int) -> bool:
        reminder = self.get_reminder_by_id(reminder_id)
        if not reminder:
            return False
        
        reminder.status = ReminderStatus.CANCELLED.value
        self.db.commit()
        self._log_action(reminder_id, "cancelled")
        return True
    
    def get_reminder_history(self, reminder_id: int) -> List[ReminderHistory]:
        return self.db.query(ReminderHistory).filter(
            ReminderHistory.reminder_id == reminder_id
        ).order_by(ReminderHistory.timestamp.desc()).all()
    
    def _get_user_tz(self, telegram_user_id: int) -> pytz.BaseTzInfo:
        user = self.db.query(User).filter(User.telegram_user_id == telegram_user_id).first()
        tz_name = user.timezone if user else DEFAULT_TIMEZONE
        if tz_name == 'Europe/Kiev':
            tz_name = 'Europe/Kyiv'
        return pytz.timezone(tz_name)

    def _advance_in_local_tz(
        self,
        scheduled_time_utc: datetime,
        user_tz: pytz.BaseTzInfo,
        advance: Callable[[datetime], datetime],
    ) -> datetime:
        """Apply `advance` to the scheduled time in the user's local timezone, preserving wall-clock time across DST."""
        aware_utc = pytz.UTC.localize(scheduled_time_utc)
        local_naive = aware_utc.astimezone(user_tz).replace(tzinfo=None)
        new_local_naive = advance(local_naive)
        new_local_aware = user_tz.localize(new_local_naive, is_dst=False)
        return new_local_aware.astimezone(pytz.UTC).replace(tzinfo=None)

    def _reschedule_repeating_reminder(self, reminder: Reminder):
        now = datetime.now(pytz.UTC).replace(tzinfo=None)
        user_tz = self._get_user_tz(reminder.user_id)

        if reminder.repeat_interval == "daily":
            advance = lambda dt: dt + timedelta(days=1)
            reminder.scheduled_time = self._advance_in_local_tz(reminder.scheduled_time, user_tz, advance)
            # Keep advancing until we're in the future
            while reminder.scheduled_time <= now:
                reminder.scheduled_time = self._advance_in_local_tz(reminder.scheduled_time, user_tz, advance)
        elif reminder.repeat_interval == "weekly":
            advance = lambda dt: dt + timedelta(weeks=1)
            reminder.scheduled_time = self._advance_in_local_tz(reminder.scheduled_time, user_tz, advance)
            while reminder.scheduled_time <= now:
                reminder.scheduled_time = self._advance_in_local_tz(reminder.scheduled_time, user_tz, advance)
        elif reminder.repeat_interval == "monthly":
            advance = lambda dt: dt + relativedelta(months=1)
            reminder.scheduled_time = self._advance_in_local_tz(reminder.scheduled_time, user_tz, advance)
            while reminder.scheduled_time <= now:
                reminder.scheduled_time = self._advance_in_local_tz(reminder.scheduled_time, user_tz, advance)
        elif reminder.repeat_interval and reminder.repeat_interval.startswith("multi-day:"):
            # Handle multi-day scheduling (e.g., "multi-day: saturday, sunday")
            self._reschedule_multi_day_reminder(reminder, now, user_tz)
        elif reminder.repeat_interval and reminder.repeat_interval.startswith("custom_"):
            # Handle custom periods like "custom_3_days", "custom_2_weeks", "custom_3_months"
            self._reschedule_custom_period_reminder(reminder, now, user_tz)

        reminder.status = ReminderStatus.ACTIVE.value
        reminder.is_confirmed = False
    
    def _reschedule_multi_day_reminder(self, reminder: Reminder, now: datetime, user_tz: pytz.BaseTzInfo):
        """Schedule next occurrence for multi-day reminders"""
        # Extract days from repeat_interval (e.g., "multi-day: saturday, sunday")
        days_str = reminder.repeat_interval.replace("multi-day: ", "")
        target_days = [day.strip() for day in days_str.split(",")]

        # Map day names to weekday numbers (Monday=0, Sunday=6)
        day_map = {
            'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
            'friday': 4, 'saturday': 5, 'sunday': 6
        }

        target_weekdays = [day_map[day] for day in target_days if day in day_map]
        weekly_advance = lambda dt: dt + timedelta(weeks=1)

        if not target_weekdays:
            # Fallback to weekly if parsing fails
            reminder.scheduled_time = self._advance_in_local_tz(reminder.scheduled_time, user_tz, weekly_advance)
            while reminder.scheduled_time <= now:
                reminder.scheduled_time = self._advance_in_local_tz(reminder.scheduled_time, user_tz, weekly_advance)
            return

        # Keep advancing until we find a future occurrence (weekday is local-tz aware)
        while True:
            local_aware = pytz.UTC.localize(reminder.scheduled_time).astimezone(user_tz)
            current_weekday = local_aware.weekday()
            days_to_add = None

            # Find the next target day from current scheduled_time
            for days_ahead in range(1, 8):  # Check next 7 days
                future_weekday = (current_weekday + days_ahead) % 7
                if future_weekday in target_weekdays:
                    days_to_add = days_ahead
                    break

            if days_to_add is not None:
                advance = lambda dt, d=days_to_add: dt + timedelta(days=d)
                reminder.scheduled_time = self._advance_in_local_tz(reminder.scheduled_time, user_tz, advance)
            else:
                # Fallback - schedule for next week
                reminder.scheduled_time = self._advance_in_local_tz(reminder.scheduled_time, user_tz, weekly_advance)

            # Exit loop when scheduled_time is in the future
            if reminder.scheduled_time > now:
                break

    def _reschedule_custom_period_reminder(self, reminder: Reminder, now: datetime, user_tz: pytz.BaseTzInfo):
        """Schedule next occurrence for custom period reminders"""
        weekly_advance = lambda dt: dt + timedelta(weeks=1)

        # Parse custom period format: "custom_3_days", "custom_2_weeks", etc.
        parts = reminder.repeat_interval.split('_')
        if len(parts) != 3 or parts[0] != 'custom':
            # Fallback to weekly if parsing fails
            reminder.scheduled_time = self._advance_in_local_tz(reminder.scheduled_time, user_tz, weekly_advance)
            while reminder.scheduled_time <= now:
                reminder.scheduled_time = self._advance_in_local_tz(reminder.scheduled_time, user_tz, weekly_advance)
            return

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

            reminder.scheduled_time = self._advance_in_local_tz(reminder.scheduled_time, user_tz, advance)
            while reminder.scheduled_time <= now:
                reminder.scheduled_time = self._advance_in_local_tz(reminder.scheduled_time, user_tz, advance)
        except (ValueError, IndexError):
            # Fallback to weekly if parsing fails
            reminder.scheduled_time = self._advance_in_local_tz(reminder.scheduled_time, user_tz, weekly_advance)
            while reminder.scheduled_time <= now:
                reminder.scheduled_time = self._advance_in_local_tz(reminder.scheduled_time, user_tz, weekly_advance)
    
    def reschedule_reminder(self, reminder_id: int, new_time: datetime) -> bool:
        reminder = self.get_reminder_by_id(reminder_id)
        if not reminder:
            return False
        
        old_time = reminder.scheduled_time
        reminder.scheduled_time = new_time
        reminder.status = ReminderStatus.ACTIVE.value
        
        self.db.commit()
        self._log_action(reminder_id, "rescheduled", {
            "old_time": old_time.isoformat(),
            "new_time": new_time.isoformat()
        })
        return True
    
    def get_unconfirmed_overdue_reminders(self, minutes_overdue: int = 5) -> List[Reminder]:
        cutoff_time = datetime.now(pytz.UTC).replace(tzinfo=None) - timedelta(minutes=minutes_overdue)
        return self.db.query(Reminder).filter(
            Reminder.requires_confirmation == True,
            Reminder.is_confirmed == False,
            Reminder.scheduled_time <= cutoff_time,
            Reminder.status == ReminderStatus.ACTIVE.value
        ).all()
    
    def _log_action(self, reminder_id: int, action: str, details: dict = None):
        history = ReminderHistory(
            reminder_id=reminder_id,
            action=action,
            details=details or {}
        )
        self.db.add(history)
        self.db.commit()