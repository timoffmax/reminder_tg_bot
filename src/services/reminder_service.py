from datetime import datetime, timedelta
from typing import Callable, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_ as sa_and, or_ as sa_or
from sqlalchemy import func as sa_func_lower_module
from dateutil.relativedelta import relativedelta
import pytz
from src.models.reminder import Reminder, ReminderHistory, ReminderType, ReminderStatus
from src.models.user import User
from src.config import DEFAULT_TIMEZONE
from src.database import get_db

sa_func_lower = sa_func_lower_module.lower

class ReminderService:
    # Fallback snooze/re-send interval for reminders created without an explicit choice.
    DEFAULT_SNOOZE_MINUTES = 10

    # Day names as stored in "multi-day: ..." repeat intervals -> Python weekday numbers (Monday=0).
    WEEKDAY_MAP = {
        'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
        'friday': 4, 'saturday': 5, 'sunday': 6,
    }

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
        chat_title: Optional[str] = None,
        repeat_until: Optional[datetime] = None,
        parent_reminder_id: Optional[int] = None,
        default_snooze_minutes: Optional[int] = None,
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
            repeat_interval=repeat_interval,
            repeat_until=repeat_until,
            parent_reminder_id=parent_reminder_id,
            default_snooze_minutes=default_snooze_minutes,
        )

        self.db.add(reminder)
        self.db.commit()
        self.db.refresh(reminder)

        self._log_action(reminder.id, "created")
        return reminder

    def get_active_reminders(self, user_id: int) -> List[Reminder]:
        return self.db.query(Reminder).filter(
            Reminder.user_id == user_id,
            Reminder.status.in_([
                ReminderStatus.ACTIVE.value,
                ReminderStatus.SNOOZED.value,
                ReminderStatus.PAUSED.value,
            ])
        ).order_by(Reminder.scheduled_time).all()

    def search_reminders(self, user_id: int, query: str) -> List[Reminder]:
        like_query = f"%{query.lower()}%"
        return self.db.query(Reminder).filter(
            Reminder.user_id == user_id,
            Reminder.status.in_([
                ReminderStatus.ACTIVE.value,
                ReminderStatus.SNOOZED.value,
                ReminderStatus.PAUSED.value,
            ]),
            sa_func_lower(Reminder.message_text).like(like_query),
        ).order_by(Reminder.scheduled_time).all()
    
    def get_reminder_by_id(self, reminder_id: int) -> Optional[Reminder]:
        return self.db.query(Reminder).filter(Reminder.id == reminder_id).first()
    
    def get_due_reminders(self) -> List[Reminder]:
        now = datetime.now(pytz.UTC).replace(tzinfo=None)
        return self.db.query(Reminder).filter(
            Reminder.scheduled_time <= now,
            Reminder.status == ReminderStatus.ACTIVE.value
        ).all()
    
    def snooze_reminder(self, reminder_id: int, snooze_minutes: int = 10) -> Optional[Reminder]:
        """Snooze a reminder for `snooze_minutes` counted from now (or from its scheduled time if still in the future).

        For repeating reminders a one-off follow-up is created instead, so the
        series schedule is never shifted. Returns the reminder that should be
        (re)scheduled, or None if snoozing is not possible.
        """
        reminder = self.get_reminder_by_id(reminder_id)
        if reminder is None:
            return None

        now = datetime.now(pytz.UTC).replace(tzinfo=None)

        if reminder.reminder_type == ReminderType.REPEATING.value:
            # Snoozing a repeating reminder targets the just-fired occurrence.
            anchor = now
        elif reminder.status in (ReminderStatus.ACTIVE.value, ReminderStatus.SNOOZED.value):
            # Snoozing a not-yet-fired reminder must push it later, not pull it earlier.
            anchor = max(now, reminder.scheduled_time)
        else:
            # Reviving a completed reminder counts from the moment of the click.
            anchor = now

        new_time = anchor + timedelta(minutes=snooze_minutes)
        return self._snooze_to_time(reminder, new_time, {"snooze_minutes": snooze_minutes})

    def snooze_reminder_until(self, reminder_id: int, new_time: datetime) -> Optional[Reminder]:
        """Snooze a reminder to an absolute UTC time (smart-snooze presets).

        Same semantics as snooze_reminder: repeating series are never re-anchored;
        a one-off follow-up is created for them instead.
        """
        reminder = self.get_reminder_by_id(reminder_id)
        if reminder is None:
            return None

        return self._snooze_to_time(reminder, new_time, {"snoozed_until": new_time.isoformat()})

    def _snooze_to_time(self, reminder: Reminder, new_time: datetime, log_details: dict) -> Optional[Reminder]:
        # CANCELLED stays dead (stale buttons must not resurrect it) and PAUSED requires
        # an explicit resume. COMPLETED is allowed: one-time reminders are auto-completed
        # right after delivery, yet their just-sent message legitimately offers snoozing.
        if reminder.status in (ReminderStatus.CANCELLED.value, ReminderStatus.PAUSED.value):
            return None

        if reminder.reminder_type == ReminderType.REPEATING.value:
            follow_up = self._create_snooze_follow_up(reminder, new_time)
            self._log_action(reminder.id, "snoozed", {**log_details, "follow_up_id": follow_up.id})
            return follow_up

        reminder.scheduled_time = new_time
        reminder.status = ReminderStatus.SNOOZED.value
        reminder.snooze_count += 1
        # Snoozing means "not done yet": drop any earlier confirmation so the
        # reminder nags again after it re-fires, and stop re-sends until then.
        reminder.is_confirmed = False
        reminder.last_confirmation_request_at = None

        self.db.commit()
        self._log_action(reminder.id, "snoozed", log_details)
        return reminder

    def _create_snooze_follow_up(self, parent: Reminder, new_time: datetime) -> Reminder:
        """Create (or retarget) a one-off copy of a repeating reminder so a snooze doesn't shift the series."""
        parent.snooze_count += 1
        parent.last_confirmation_request_at = None

        # Repeated snooze clicks (old message + nag message both carry buttons) must
        # retarget the existing pending follow-up instead of stacking duplicates.
        # Lead-time children mirror the parent's repeating type, so a ONE_TIME child
        # of a repeating parent can only be a snooze follow-up.
        follow_up = self.db.query(Reminder).filter(
            Reminder.parent_reminder_id == parent.id,
            Reminder.reminder_type == ReminderType.ONE_TIME.value,
            Reminder.status.in_([ReminderStatus.ACTIVE.value, ReminderStatus.SNOOZED.value]),
        ).first()

        if follow_up is not None:
            follow_up.scheduled_time = new_time
            follow_up.status = ReminderStatus.SNOOZED.value
            follow_up.snooze_count += 1
            follow_up.last_confirmation_request_at = None
            self.db.commit()
            return follow_up

        follow_up = Reminder(
            user_id=parent.user_id,
            chat_id=parent.chat_id,
            chat_title=parent.chat_title,
            message_text=parent.message_text,
            scheduled_time=new_time,
            reminder_type=ReminderType.ONE_TIME.value,
            status=ReminderStatus.SNOOZED.value,
            requires_confirmation=parent.requires_confirmation,
            tagged_users=parent.tagged_users or [],
            default_snooze_minutes=parent.default_snooze_minutes,
            parent_reminder_id=parent.id,
            snooze_count=1,
        )
        self.db.add(follow_up)
        self.db.commit()
        self.db.refresh(follow_up)
        return follow_up

    def complete_reminder(self, reminder_id: int) -> bool:
        reminder = self.get_reminder_by_id(reminder_id)
        if not reminder:
            return False

        reminder.last_confirmation_request_at = None

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

        cancelled_follow_up_ids = []

        # Repeating reminders keep is_confirmed=False so the next occurrence
        # renders the Confirm keyboard again; clearing the request timestamp
        # is what stops the re-sends for the acknowledged occurrence.
        if reminder.reminder_type != ReminderType.REPEATING.value:
            reminder.is_confirmed = True
        else:
            # Confirming the occurrence also retires its pending snooze follow-up.
            follow_ups = self.db.query(Reminder).filter(
                Reminder.parent_reminder_id == reminder_id,
                Reminder.reminder_type == ReminderType.ONE_TIME.value,
                Reminder.status.in_([ReminderStatus.ACTIVE.value, ReminderStatus.SNOOZED.value]),
            ).all()

            for follow_up in follow_ups:
                follow_up.status = ReminderStatus.CANCELLED.value
                follow_up.last_confirmation_request_at = None
                cancelled_follow_up_ids.append(follow_up.id)

        reminder.last_confirmation_request_at = None
        self.db.commit()
        self._log_action(reminder_id, "confirmed")

        for follow_up_id in cancelled_follow_up_ids:
            self._log_action(follow_up_id, "cancelled", {"confirmed_parent": reminder_id})
        return True

    def cancel_reminder(self, reminder_id: int) -> bool:
        reminder = self.get_reminder_by_id(reminder_id)
        if not reminder:
            return False

        reminder.status = ReminderStatus.CANCELLED.value
        reminder.last_confirmation_request_at = None

        # Cascade to pending descendants (snooze follow-ups, lead-time alerts and
        # their own follow-ups) so nothing keeps firing for a cancelled series.
        # Their stale jobs are harmless: _send_reminder skips CANCELLED reminders.
        pending_statuses = [
            ReminderStatus.ACTIVE.value,
            ReminderStatus.SNOOZED.value,
            ReminderStatus.PAUSED.value,
        ]
        cancelled_child_ids = []
        parent_ids = [reminder_id]

        while parent_ids:
            children = self.db.query(Reminder).filter(
                Reminder.parent_reminder_id.in_(parent_ids),
                Reminder.status.in_(pending_statuses),
            ).all()
            parent_ids = []

            for child in children:
                child.status = ReminderStatus.CANCELLED.value
                child.last_confirmation_request_at = None
                cancelled_child_ids.append(child.id)
                parent_ids.append(child.id)

        self.db.commit()
        self._log_action(reminder_id, "cancelled")

        for child_id in cancelled_child_ids:
            self._log_action(child_id, "cancelled", {"cascaded_from": reminder_id})
        return True

    def pause_reminder(self, reminder_id: int) -> bool:
        reminder = self.get_reminder_by_id(reminder_id)
        if not reminder:
            return False

        if reminder.status not in (ReminderStatus.ACTIVE.value, ReminderStatus.SNOOZED.value):
            return False

        reminder.status = ReminderStatus.PAUSED.value
        reminder.last_confirmation_request_at = None
        self.db.commit()
        self._log_action(reminder_id, "paused")
        return True

    def resume_reminder(self, reminder_id: int) -> bool:
        reminder = self.get_reminder_by_id(reminder_id)
        if not reminder or reminder.status != ReminderStatus.PAUSED.value:
            return False

        # If the scheduled time has passed while paused, advance to the next future occurrence.
        now = datetime.now(pytz.UTC).replace(tzinfo=None)
        if reminder.scheduled_time <= now and reminder.reminder_type == ReminderType.REPEATING.value:
            self._reschedule_repeating_reminder(reminder)
        else:
            reminder.status = ReminderStatus.ACTIVE.value

        self.db.commit()
        self._log_action(reminder_id, "resumed")
        return True

    def skip_next_occurrence(self, reminder_id: int) -> bool:
        """For repeating reminders: advance to the occurrence AFTER the next one (skipping it)."""
        reminder = self.get_reminder_by_id(reminder_id)
        if not reminder or reminder.reminder_type != ReminderType.REPEATING.value:
            return False

        self._reschedule_repeating_reminder(reminder)
        self.db.commit()
        self._log_action(reminder_id, "skipped")
        return True

    def cancel_all_for_user(self, user_id: int) -> List[int]:
        active = self.db.query(Reminder).filter(
            Reminder.user_id == user_id,
            Reminder.status.in_([
                ReminderStatus.ACTIVE.value,
                ReminderStatus.SNOOZED.value,
                ReminderStatus.PAUSED.value,
            ]),
        ).all()
        cancelled_ids = []
        for r in active:
            r.status = ReminderStatus.CANCELLED.value
            r.last_confirmation_request_at = None
            cancelled_ids.append(r.id)
        self.db.commit()
        for rid in cancelled_ids:
            self._log_action(rid, "cancelled", {"bulk": True})
        return cancelled_ids

    def pause_all_for_user(self, user_id: int) -> List[int]:
        targets = self.db.query(Reminder).filter(
            Reminder.user_id == user_id,
            Reminder.status.in_([ReminderStatus.ACTIVE.value, ReminderStatus.SNOOZED.value]),
        ).all()
        paused_ids = []
        for r in targets:
            r.status = ReminderStatus.PAUSED.value
            r.last_confirmation_request_at = None
            paused_ids.append(r.id)
        self.db.commit()
        for rid in paused_ids:
            self._log_action(rid, "paused", {"bulk": True})
        return paused_ids

    def resume_all_for_user(self, user_id: int) -> List[int]:
        targets = self.db.query(Reminder).filter(
            Reminder.user_id == user_id,
            Reminder.status == ReminderStatus.PAUSED.value,
        ).all()
        now = datetime.now(pytz.UTC).replace(tzinfo=None)
        resumed_ids = []
        for r in targets:
            if r.scheduled_time <= now and r.reminder_type == ReminderType.REPEATING.value:
                self._reschedule_repeating_reminder(r)
            else:
                r.status = ReminderStatus.ACTIVE.value
            resumed_ids.append(r.id)
        self.db.commit()
        for rid in resumed_ids:
            self._log_action(rid, "resumed", {"bulk": True})
        return resumed_ids

    def create_lead_time_reminder(self, parent_id: int, lead_minutes: int) -> Optional[Reminder]:
        """Create a child reminder that fires `lead_minutes` before the parent.

        For repeating parents, the child mirrors the parent's repeat pattern so it follows the cadence.
        Cascade to status changes is best-effort; users can manage the child via /reminders.
        """
        parent = self.get_reminder_by_id(parent_id)
        if not parent or parent.parent_reminder_id is not None:
            return None

        child_text = f"⏳ {lead_minutes}m before: {parent.message_text}"
        child_time = parent.scheduled_time - timedelta(minutes=lead_minutes)

        child = Reminder(
            user_id=parent.user_id,
            chat_id=parent.chat_id,
            chat_title=parent.chat_title,
            message_text=child_text,
            scheduled_time=child_time,
            reminder_type=parent.reminder_type,
            requires_confirmation=False,
            tagged_users=parent.tagged_users or [],
            repeat_interval=parent.repeat_interval,
            repeat_until=parent.repeat_until,
            parent_reminder_id=parent.id,
        )
        self.db.add(child)
        self.db.commit()
        self.db.refresh(child)
        self._log_action(child.id, "created", {"lead_minutes": lead_minutes, "parent_id": parent.id})
        return child

    def set_repeat_until(self, reminder_id: int, repeat_until: Optional[datetime]) -> bool:
        reminder = self.get_reminder_by_id(reminder_id)
        if not reminder:
            return False

        reminder.repeat_until = repeat_until
        self.db.commit()
        self._log_action(
            reminder_id,
            "set_repeat_until",
            {"value": repeat_until.isoformat() if repeat_until else None},
        )
        return True

    def update_message_text(self, reminder_id: int, message_text: str) -> bool:
        reminder = self.get_reminder_by_id(reminder_id)
        if not reminder:
            return False

        old_text = reminder.message_text
        reminder.message_text = message_text
        self.db.commit()
        self._log_action(reminder_id, "edited", {"old_text": old_text, "new_text": message_text})
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

        reminder.last_confirmation_request_at = None

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

        # If the next occurrence is past the user-defined end date, complete the series.
        if reminder.repeat_until is not None and reminder.scheduled_time > reminder.repeat_until:
            reminder.status = ReminderStatus.COMPLETED.value
            reminder.is_confirmed = False
            return

        reminder.status = ReminderStatus.ACTIVE.value
        reminder.is_confirmed = False
    
    def _reschedule_multi_day_reminder(self, reminder: Reminder, now: datetime, user_tz: pytz.BaseTzInfo):
        """Schedule next occurrence for multi-day reminders"""
        # Extract days from repeat_interval (e.g., "multi-day: saturday, sunday")
        days_str = reminder.repeat_interval.replace("multi-day: ", "")
        target_days = [day.strip() for day in days_str.split(",")]

        target_weekdays = [self.WEEKDAY_MAP[day] for day in target_days if day in self.WEEKDAY_MAP]
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
    
    def reschedule_reminder(self, reminder_id: int, new_time: datetime) -> Optional[Reminder]:
        """Reschedule a reminder to an absolute UTC time.

        For repeating reminders a one-off follow-up is created/retargeted instead,
        so the series anchor (its wall-clock time-of-day) is never shifted.
        Returns the reminder that should be (re)scheduled, or None if
        rescheduling is not possible.
        """
        reminder = self.get_reminder_by_id(reminder_id)
        if reminder is None:
            return None

        # Same contract as snoozing: CANCELLED stays dead (stale buttons must
        # not resurrect it) and PAUSED requires an explicit resume.
        if reminder.status in (ReminderStatus.CANCELLED.value, ReminderStatus.PAUSED.value):
            return None

        if reminder.reminder_type == ReminderType.REPEATING.value:
            follow_up = self._create_snooze_follow_up(reminder, new_time)
            self._log_action(reminder.id, "rescheduled", {
                "new_time": new_time.isoformat(),
                "follow_up_id": follow_up.id,
            })
            return follow_up

        old_time = reminder.scheduled_time
        reminder.scheduled_time = new_time
        reminder.status = ReminderStatus.ACTIVE.value
        reminder.last_confirmation_request_at = None

        self.db.commit()
        self._log_action(reminder_id, "rescheduled", {
            "old_time": old_time.isoformat(),
            "new_time": new_time.isoformat()
        })
        return reminder

    def change_repeat_schedule(
        self,
        reminder_id: int,
        repeat_interval: str,
        anchor_time: Optional[datetime] = None,
    ) -> Optional[Reminder]:
        """Change a reminder's recurrence pattern and, optionally, its anchor time.

        The reminder becomes (or stays) REPEATING. When no anchor is given, the
        current wall-clock time-of-day is kept and only advanced to the next
        occurrence matching the new pattern. This is the deliberate way to
        re-anchor a series — unlike snooze/reschedule, which never touch it.
        Returns the updated reminder, or None if the change is not possible.
        """
        reminder = self.get_reminder_by_id(reminder_id)
        if reminder is None or reminder.status == ReminderStatus.CANCELLED.value:
            return None

        # Children (snooze follow-ups, lead-time alerts) must not become their own
        # series: the follow-up retarget lookup relies on ONE_TIME children of a
        # repeating parent being snooze follow-ups.
        if reminder.parent_reminder_id is not None:
            return None

        old_interval = reminder.repeat_interval
        old_time = reminder.scheduled_time
        user_tz = self._get_user_tz(reminder.user_id)

        reminder.reminder_type = ReminderType.REPEATING.value
        reminder.repeat_interval = repeat_interval

        if anchor_time is not None:
            reminder.scheduled_time = anchor_time

        reminder.scheduled_time = self._align_to_pattern(reminder.scheduled_time, repeat_interval, user_tz)

        # A paused series stays paused; everything else becomes schedulable again.
        if reminder.status != ReminderStatus.PAUSED.value:
            reminder.status = ReminderStatus.ACTIVE.value

        reminder.is_confirmed = False
        reminder.last_confirmation_request_at = None

        self.db.commit()
        self._log_action(reminder_id, "schedule_changed", {
            "old_interval": old_interval,
            "new_interval": repeat_interval,
            "old_time": old_time.isoformat(),
            "new_time": reminder.scheduled_time.isoformat(),
        })
        return reminder

    def _align_to_pattern(
        self,
        scheduled_time_utc: datetime,
        repeat_interval: str,
        user_tz: pytz.BaseTzInfo,
    ) -> datetime:
        """Advance a UTC anchor (wall-clock preserving) until it is in the future and matches the pattern's weekdays."""
        result = scheduled_time_utc
        now = datetime.now(pytz.UTC).replace(tzinfo=None)
        target_weekdays = None
        advance = lambda dt: dt + timedelta(days=1)

        if repeat_interval.startswith("multi-day:"):
            days_str = repeat_interval.replace("multi-day: ", "")
            target_weekdays = [
                self.WEEKDAY_MAP[day.strip()]
                for day in days_str.split(",")
                if day.strip() in self.WEEKDAY_MAP
            ] or None
        elif repeat_interval == "weekly":
            advance = lambda dt: dt + timedelta(weeks=1)
        elif repeat_interval == "monthly":
            advance = lambda dt: dt + relativedelta(months=1)
        elif repeat_interval.startswith("custom_"):
            parts = repeat_interval.split('_')

            if len(parts) == 3:
                try:
                    number = int(parts[1])

                    if parts[2] == 'days':
                        advance = lambda dt: dt + timedelta(days=number)
                    elif parts[2] == 'weeks':
                        advance = lambda dt: dt + timedelta(weeks=number)
                    elif parts[2] == 'months':
                        advance = lambda dt: dt + relativedelta(months=number)
                except ValueError:
                    pass

        # 400 daily steps cover any weekday/month combination; guards against loops.
        for _ in range(400):
            local_weekday = pytz.UTC.localize(result).astimezone(user_tz).weekday()
            day_matches = (target_weekdays is None) or (local_weekday in target_weekdays)

            if result > now and day_matches:
                break

            result = self._advance_in_local_tz(result, user_tz, advance)

        return result
    
    def get_unconfirmed_overdue_reminders(self) -> List[Reminder]:
        """Reminders with a pending confirmation request older than their own re-send interval.

        ACTIVE reminders with no request timestamp fall back to scheduled_time as the
        anchor, so a reminder whose initial delivery failed is still retried. COMPLETED
        repeating series are included for their final unconfirmed occurrence.
        """
        now = datetime.now(pytz.UTC).replace(tzinfo=None)
        candidates = self.db.query(Reminder).filter(
            Reminder.requires_confirmation == True,
            Reminder.is_confirmed == False,
            sa_or(
                Reminder.status == ReminderStatus.ACTIVE.value,
                sa_and(
                    Reminder.status == ReminderStatus.COMPLETED.value,
                    Reminder.reminder_type == ReminderType.REPEATING.value,
                    Reminder.last_confirmation_request_at.isnot(None),
                ),
            ),
        ).all()

        result = []
        for reminder in candidates:
            resend_after = timedelta(minutes=reminder.default_snooze_minutes or self.DEFAULT_SNOOZE_MINUTES)
            anchor = reminder.last_confirmation_request_at or reminder.scheduled_time
            if anchor <= now - resend_after:
                result.append(reminder)
        return result

    def mark_confirmation_requested(self, reminder_id: int) -> None:
        """Record that a confirmation request was just sent for this reminder.

        Snoozed reminders are returned to ACTIVE so they stay eligible for re-sends.
        COMPLETED repeating series stay markable so the final occurrence of a
        repeat_until-bounded series keeps nagging until confirmed.
        """
        reminder = self.get_reminder_by_id(reminder_id)
        if not reminder or reminder.status in (ReminderStatus.CANCELLED.value, ReminderStatus.PAUSED.value):
            return

        is_completed = reminder.status == ReminderStatus.COMPLETED.value

        if is_completed and reminder.reminder_type != ReminderType.REPEATING.value:
            return

        if reminder.status == ReminderStatus.SNOOZED.value:
            reminder.status = ReminderStatus.ACTIVE.value

        reminder.last_confirmation_request_at = datetime.now(pytz.UTC).replace(tzinfo=None)
        self.db.commit()
    
    def _log_action(self, reminder_id: int, action: str, details: dict = None):
        history = ReminderHistory(
            reminder_id=reminder_id,
            action=action,
            details=details or {}
        )
        self.db.add(history)
        self.db.commit()
