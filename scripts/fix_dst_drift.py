"""
One-shot correction for repeating reminders whose stored UTC time drifted by a DST
transition between created_at and the current scheduled_time.

For each ACTIVE/SNOOZED repeating reminder, compares the user-timezone UTC offset
at created_at vs. scheduled_time. If they differ (DST boundary crossed), subtracts
the offset difference from scheduled_time so the local wall-clock time matches the
user's original intent.

Run: python -m scripts.fix_dst_drift            # dry-run (default)
     python -m scripts.fix_dst_drift --apply    # write changes
"""
import argparse
import sys
import pytz

from src.database import SessionLocal
from src.models.reminder import Reminder, ReminderStatus, ReminderType
from src.models.user import User
from src.config import DEFAULT_TIMEZONE


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Write changes (otherwise dry-run)')
    args = parser.parse_args()

    with SessionLocal() as db:
        reminders = db.query(Reminder).filter(
            Reminder.status.in_([ReminderStatus.ACTIVE.value, ReminderStatus.SNOOZED.value]),
            Reminder.reminder_type == ReminderType.REPEATING.value,
        ).order_by(Reminder.id).all()

        print(f'Inspecting {len(reminders)} repeating reminder(s)...\n')
        adjusted = 0
        skipped = 0

        for r in reminders:
            user = db.query(User).filter(User.telegram_user_id == r.user_id).first()
            tz_name = (user.timezone if user else DEFAULT_TIMEZONE)
            if tz_name == 'Europe/Kiev':
                tz_name = 'Europe/Kyiv'
            tz = pytz.timezone(tz_name)

            if not r.created_at or not r.scheduled_time:
                skipped += 1
                continue

            offset_at_created = pytz.UTC.localize(r.created_at).astimezone(tz).utcoffset()
            offset_at_scheduled = pytz.UTC.localize(r.scheduled_time).astimezone(tz).utcoffset()
            drift = offset_at_scheduled - offset_at_created

            if drift.total_seconds() == 0:
                print(f'id={r.id} OK ({tz_name}) — no drift, scheduled={r.scheduled_time} UTC')
                skipped += 1
                continue

            old_utc = r.scheduled_time
            new_utc = old_utc - drift
            old_local = pytz.UTC.localize(old_utc).astimezone(tz)
            new_local = pytz.UTC.localize(new_utc).astimezone(tz)

            print(
                f'id={r.id} DRIFT {drift} ({tz_name})\n'
                f'  msg={r.message_text[:60]!r}\n'
                f'  before: {old_utc} UTC  =  {old_local.strftime("%Y-%m-%d %H:%M %z")}\n'
                f'  after:  {new_utc} UTC  =  {new_local.strftime("%Y-%m-%d %H:%M %z")}'
            )

            if args.apply:
                r.scheduled_time = new_utc
            adjusted += 1

        if args.apply and adjusted > 0:
            db.commit()
            print(f'\nApplied {adjusted} correction(s).')
        elif adjusted > 0:
            print(f'\nDry-run: {adjusted} reminder(s) would be corrected. Re-run with --apply to write changes.')
        else:
            print('\nNo corrections needed.')

        print(f'Skipped (no drift / no created_at): {skipped}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
