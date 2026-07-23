from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from src.database import SessionLocal
from src.services.reminder_service import ReminderService
from src.services.scheduler_service import build_snooze_buttons
from src.services.user_service import UserService
from src.utils.timezone_utils import get_timezone_regions, convert_to_user_timezone


def _resolve_snooze_preset(preset: str, reminder_id: int):
    """Resolve a smart-snooze preset (e.g. 'tomorrow_morning', 'monday_morning') to a UTC naive datetime.

    Returns None if the preset is unknown.
    """
    with SessionLocal() as db:
        reminder_service = ReminderService(db)
        user_service = UserService(db)
        reminder = reminder_service.get_reminder_by_id(reminder_id)
        if not reminder:
            return None
        tz_name = user_service.get_user_timezone(reminder.user_id)

    if tz_name == 'Europe/Kiev':
        tz_name = 'Europe/Kyiv'
    user_tz = pytz.timezone(tz_name)
    now_local = datetime.now(user_tz)

    if preset == 'tomorrow_morning':
        # Before 9am the "morning" the user means is the one coming up today.
        days_ahead = 0 if now_local.hour < 9 else 1
        target = (now_local + timedelta(days=days_ahead)).replace(hour=9, minute=0, second=0, microsecond=0)
    elif preset == 'monday_morning':
        days_ahead = (0 - now_local.weekday()) % 7
        if days_ahead == 0 and now_local.hour >= 9:
            days_ahead = 7
        target = (now_local + timedelta(days=days_ahead)).replace(hour=9, minute=0, second=0, microsecond=0)
    else:
        return None

    return user_tz.localize(target.replace(tzinfo=None), is_dst=False).astimezone(pytz.UTC).replace(tzinfo=None)

def escape_markdown(text: str) -> str:
    """Escape special characters for Markdown parse mode"""
    # Escape only the most critical MarkdownV2 characters that cause parsing issues
    # Parentheses often don't need escaping for regular text content
    special_chars = ['_', '*', '[', ']', '~', '`', '>', '#', '+', '=', '|', '{', '}', '.', '\\']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

def _clear_pending_text_flags(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disarm every stateful text-input flow so an armed flag can't hijack unrelated input."""
    for key in (
        'awaiting_edit_message_id',
        'awaiting_reschedule_time',
        'reschedule_reminder_id',
        'awaiting_search_query',
        'awaiting_change_schedule_id',
        'awaiting_repeat_until_id',
        'awaiting_quiet_hours',
    ):
        context.user_data.pop(key, None)

async def _show_manage_view(query, reminder_id: int):
    """Render the per-reminder management view."""
    with SessionLocal() as db:
        reminder_service = ReminderService(db)
        user_service = UserService(db)

        reminder = reminder_service.get_reminder_by_id(reminder_id)
        if not reminder:
            await query.edit_message_text("❌ Reminder not found.")
            return

        user_timezone = user_service.get_user_timezone(reminder.user_id)

    user_time = convert_to_user_timezone(reminder.scheduled_time, user_timezone)

    status_label = ""
    if reminder.status == "paused":
        status_label = "⏸ *PAUSED* — "

    text = f"{status_label}📋 *{escape_markdown(reminder.message_text)}*\n"
    text += f"🕒 {user_time.strftime('%Y-%m-%d %H:%M')} ({escape_markdown(user_timezone)})\n"

    if reminder.repeat_interval:
        if reminder.repeat_interval.startswith("custom_"):
            parts = reminder.repeat_interval.split('_')
            if len(parts) == 3:
                text += f"🔄 Repeats: every {parts[1]} {parts[2]}\n"
            else:
                text += f"🔄 Repeats: {escape_markdown(reminder.repeat_interval)}\n"
        else:
            text += f"🔄 Repeats: {escape_markdown(reminder.repeat_interval)}\n"

    if reminder.repeat_until:
        until_local = convert_to_user_timezone(reminder.repeat_until, user_timezone)
        text += f"🏁 Until: {until_local.strftime('%Y-%m-%d')}\n"

    if reminder.requires_confirmation:
        text += "❓ Requires confirmation\n"

    if reminder.tagged_users:
        tagged = ' '.join(u.replace('_', '\\_') for u in reminder.tagged_users)
        text += f"👥 Tagged: {tagged}\n"

    is_repeating = reminder.reminder_type == "repeating"
    is_paused = reminder.status == "paused"

    keyboard = [[InlineKeyboardButton("✏️ Edit message", callback_data=f"editmsg_{reminder_id}")]]

    if reminder.parent_reminder_id is None:
        keyboard.append([InlineKeyboardButton("🔄 Change schedule", callback_data=f"changesched_{reminder_id}")])

    if is_repeating and not is_paused:
        keyboard.append([InlineKeyboardButton("⏭ Skip next occurrence", callback_data=f"skip_{reminder_id}")])

    if is_repeating:
        if reminder.repeat_until:
            keyboard.append([InlineKeyboardButton("🏁 Clear end date", callback_data=f"clearuntil_{reminder_id}")])
        else:
            keyboard.append([InlineKeyboardButton("🏁 Set end date", callback_data=f"setuntil_{reminder_id}")])

    if reminder.parent_reminder_id is None:
        keyboard.append([InlineKeyboardButton("🔔 Add lead-time alert", callback_data=f"leadtime_{reminder_id}")])

    # Paused reminders can't be rescheduled (resume first), so don't offer it.
    if not is_paused:
        keyboard.append([InlineKeyboardButton("⏰ Reschedule", callback_data=f"reschedule_{reminder_id}")])

    if is_paused:
        keyboard.append([InlineKeyboardButton("▶️ Resume", callback_data=f"resume_{reminder_id}")])
    else:
        keyboard.append([InlineKeyboardButton("⏸ Pause", callback_data=f"pause_{reminder_id}")])

    keyboard.append([InlineKeyboardButton("📝 History", callback_data=f"history_{reminder_id}")])
    keyboard.append([InlineKeyboardButton("❌ Cancel reminder", callback_data=f"cancel_{reminder_id}")])
    keyboard.append([InlineKeyboardButton("🔙 Back to list", callback_data="refresh_reminders")])

    await query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # Handle main menu callbacks
    if data == "menu_my_reminders":
        from src.handlers.reminder_handlers import list_reminders
        await list_reminders(update, context)
        return
    
    elif data == "menu_timezone":
        regions = get_timezone_regions()
        keyboard = []
        
        for region in regions.keys():
            keyboard.append([InlineKeyboardButton(
                f"🌍 {region}", 
                callback_data=f"tzr_{region}"
            )])
        
        keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🌍 *Select your region:*\n\nChoose your geographical region to see available timezones.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    elif data == "menu_help":
        chat_type = update.effective_chat.type
        is_group = chat_type in ['group', 'supergroup']
        
        help_text = """*🤖 Reminder Bot Help*

*Creating Reminders:*
• Use the main menu "➕ New Reminder" button
• Or use `/remind` for interactive creation
• Quick format: `/remind 2h Take a break`

*Time Formats:*
• `10:30` or `10:30 PM` - Specific time
• `2h`, `30m`, `1d` - Relative time
• `tomorrow at 3pm` - Natural language
• `June 26 at 5PM` - Specific date

*Reminder Features:*
• 🔄 Repeating reminders (daily/weekly/monthly)
• ✅ Confirmation required reminders
• 😴 Snooze functionality
• ⏰ Reschedule option"""

        if is_group:
            help_text += """
• 👥 Tag users in groups

*Using in Groups:*
1. Add the bot to your group
2. Use `/start` or `/menu` to see options
3. Click "➕ New Reminder" 
4. Follow the 6-step process:
   - Set time
   - Enter message
   - Tag users (@username @username2) or 'skip'
   - Choose reminder type
   - Set confirmation
   - Set snooze duration
5. Tagged users will be notified when reminder fires"""
        
        help_text += """

*Managing Reminders:*
• View all with "📋 My Reminders"
• Each reminder has action buttons
• Cancel, snooze, or reschedule anytime"""
        
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            help_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return
    
    elif data == "menu_quiet_hours":
        user_id = update.effective_user.id
        with SessionLocal() as db:
            user_service = UserService(db)
            quiet = user_service.get_quiet_hours(user_id)

        if quiet:
            current = f"Currently: {quiet[0]:02d}:00 – {quiet[1]:02d}:00 local time."
        else:
            current = "Currently: disabled."

        _clear_pending_text_flags(context)
        context.user_data['awaiting_quiet_hours'] = True
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
        await query.edit_message_text(
            f"🌙 *Quiet hours*\n\n{current}\n\n"
            "Send a window like `23-8` (start–end, 24h) — reminders inside that window are postponed to the end. "
            "Send `off` to disable.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    elif data == "menu_about":
        about_text = """
*🤖 About Reminder Bot*

Version: 1.0.0

This bot helps you manage your daily tasks and reminders with ease.

*Features:*
• Smart time parsing
• Timezone support
• Interactive creation wizard
• Inline action buttons
• Automatic re-sending for unconfirmed reminders

Made with ❤️ using Python and python-telegram-bot
"""
        
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            about_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return
    
    elif data == "back_to_menu":
        from src.handlers.basic_handlers import get_main_menu_keyboard
        menu_text = """
🤖 *Main Menu*

What would you like to do?
"""
        await query.edit_message_text(
            menu_text,
            parse_mode='Markdown',
            reply_markup=get_main_menu_keyboard()
        )
        return
    
    if data.startswith("tzr_"):
        # Timezone region selected
        region = data[4:]
        regions = get_timezone_regions()
        
        if region in regions:
            timezones = regions[region]
            keyboard = []
            
            # Add back button
            keyboard.append([
                InlineKeyboardButton("⬅️ Back to Regions", callback_data="tzr_back"),
                InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")
            ])
            
            # Add timezone buttons (2 per row for better layout)
            for i in range(0, len(timezones), 2):
                row = [InlineKeyboardButton(
                    timezones[i].replace('_', ' '),
                    callback_data=f"tz_{timezones[i]}"
                )]
                if i + 1 < len(timezones):
                    row.append(InlineKeyboardButton(
                        timezones[i + 1].replace('_', ' '),
                        callback_data=f"tz_{timezones[i + 1]}"
                    ))
                keyboard.append(row)
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"🌍 *{region} Timezones:*\n\nSelect your timezone:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
    
    elif data == "tzr_back":
        # Go back to regions
        regions = get_timezone_regions()
        keyboard = []
        
        for region in regions.keys():
            keyboard.append([InlineKeyboardButton(
                f"🌍 {region}", 
                callback_data=f"tzr_{region}"
            )])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🌍 *Select your region:*\n\nChoose your geographical region to see available timezones.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif data.startswith("tz_"):
        timezone = data[3:]
        user = update.effective_user
        
        with SessionLocal() as db:
            user_service = UserService(db)
            # Ensure user exists first
            user_service.get_or_create_user(
                telegram_user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                language_code=user.language_code
            )
            success = user_service.update_user_timezone(user.id, timezone)
        
        if success:
            await query.edit_message_text(f"✅ Timezone set to {escape_markdown(timezone)}")
        else:
            await query.edit_message_text("❌ Failed to set timezone. Please try again.")
    
    elif data in ["confirm_yes", "confirm_no"]:
        # These are handled by the conversation handler
        pass
    
    elif data.startswith("confirm_"):
        reminder_id = int(data.split("_")[1])

        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            reminder = reminder_service.get_reminder_by_id(reminder_id)

            if not reminder or not reminder.requires_confirmation:
                await query.edit_message_text("❌ Reminder not found or doesn't require confirmation.")
                return

            is_repeating = reminder.reminder_type == "repeating"

            if is_repeating:
                # For repeating reminders, next occurrence is already scheduled when fired;
                # confirming stops the re-sends for the fired occurrence.
                reminder_service.confirm_reminder(reminder_id)
                await query.edit_message_text("✅ Reminder confirmed! Next occurrence is already scheduled.")
            else:
                # For one-time reminders, confirm and complete
                reminder_service.confirm_reminder(reminder_id)
                reminder_service.complete_reminder(reminder_id)
                await query.edit_message_text("✅ Reminder confirmed!")
    
    elif data.startswith("complete_"):
        reminder_id = int(data.split("_")[1])

        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            reminder = reminder_service.get_reminder_by_id(reminder_id)

            if not reminder:
                await query.edit_message_text("❌ Reminder not found.")
                return

            is_repeating = reminder.reminder_type == "repeating"

            if is_repeating:
                # For repeating reminders, next occurrence is already scheduled when fired;
                # acknowledging stops any pending confirmation re-sends.
                if reminder.requires_confirmation:
                    reminder_service.confirm_reminder(reminder_id)
                await query.edit_message_text("✅ Reminder completed! Next occurrence is already scheduled.")
            else:
                # For one-time reminders, mark as completed
                reminder_service.complete_reminder(reminder_id)
                await query.edit_message_text("✅ Reminder completed!")
    
    elif data.startswith("manage_"):
        reminder_id = int(data.split("_")[1])
        # Clear any in-progress text-input expectations before showing the menu
        _clear_pending_text_flags(context)
        await _show_manage_view(query, reminder_id)
        return

    elif data.startswith("skip_"):
        reminder_id = int(data.split("_")[1])
        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            success = reminder_service.skip_next_occurrence(reminder_id)

        if success:
            scheduler_service = context.bot_data.get('scheduler_service')
            if scheduler_service:
                scheduler_service.reschedule_reminder(reminder_id)
            await query.answer("⏭ Skipped — next occurrence scheduled")
        else:
            await query.answer("Cannot skip this reminder")
        await _show_manage_view(query, reminder_id)
        return

    elif data.startswith("pause_"):
        reminder_id = int(data.split("_")[1])
        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            success = reminder_service.pause_reminder(reminder_id)

        if success:
            scheduler_service = context.bot_data.get('scheduler_service')
            if scheduler_service:
                scheduler_service.remove_job(reminder_id)
            await query.answer("⏸ Paused")
        else:
            await query.answer("Cannot pause")
        await _show_manage_view(query, reminder_id)
        return

    elif data.startswith("resume_"):
        reminder_id = int(data.split("_")[1])
        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            success = reminder_service.resume_reminder(reminder_id)

        if success:
            scheduler_service = context.bot_data.get('scheduler_service')
            if scheduler_service:
                scheduler_service.reschedule_reminder(reminder_id)
            await query.answer("▶️ Resumed")
        else:
            await query.answer("Cannot resume")
        await _show_manage_view(query, reminder_id)
        return

    elif data.startswith("snoozeto_"):
        # snoozeto_<id>_<preset>
        parts = data.split("_", 2)
        reminder_id = int(parts[1])
        preset = parts[2]
        new_time_utc = _resolve_snooze_preset(preset, reminder_id)

        if new_time_utc is None:
            await query.answer("❌ Unknown preset")
            return

        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            snoozed = reminder_service.snooze_reminder_until(reminder_id, new_time_utc)
            snoozed_id = snoozed.id if snoozed else None

        if snoozed_id is not None:
            scheduler_service = context.bot_data.get('scheduler_service')
            if scheduler_service:
                scheduler_service.reschedule_reminder(snoozed_id)

            if snoozed_id != reminder_id:
                await query.edit_message_text("✅ Snoozed. The repeating schedule is unchanged.")
            else:
                await query.edit_message_text("✅ Snoozed.")
        else:
            await query.edit_message_text("❌ Failed to snooze.")
        return

    elif data == "search_reminders":
        _clear_pending_text_flags(context)
        context.user_data['awaiting_search_query'] = True
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="refresh_reminders")]]
        await query.edit_message_text(
            "🔍 *Search reminders*\n\nSend the text to search for:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    elif data == "bulk_menu":
        keyboard = [
            [InlineKeyboardButton("⏸ Pause all", callback_data="bulk_pause_all")],
            [InlineKeyboardButton("▶️ Resume all paused", callback_data="bulk_resume_all")],
            [InlineKeyboardButton("❌ Cancel ALL reminders", callback_data="bulk_cancel_confirm")],
            [InlineKeyboardButton("🔙 Back", callback_data="refresh_reminders")],
        ]
        await query.edit_message_text(
            "🛠 *Bulk actions*\n\nThese affect ALL your active reminders.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    elif data == "bulk_pause_all":
        user_id = update.effective_user.id
        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            ids = reminder_service.pause_all_for_user(user_id)
        scheduler_service = context.bot_data.get('scheduler_service')
        if scheduler_service:
            for rid in ids:
                scheduler_service.remove_job(rid)
        await query.edit_message_text(f"⏸ Paused {len(ids)} reminder(s).")
        return

    elif data == "bulk_resume_all":
        user_id = update.effective_user.id
        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            ids = reminder_service.resume_all_for_user(user_id)
        scheduler_service = context.bot_data.get('scheduler_service')
        if scheduler_service:
            for rid in ids:
                scheduler_service.reschedule_reminder(rid)
        await query.edit_message_text(f"▶️ Resumed {len(ids)} reminder(s).")
        return

    elif data == "bulk_cancel_confirm":
        keyboard = [
            [InlineKeyboardButton("✅ Yes, cancel all", callback_data="bulk_cancel_all")],
            [InlineKeyboardButton("🔙 Back", callback_data="bulk_menu")],
        ]
        await query.edit_message_text(
            "⚠️ *Cancel all reminders?*\n\nThis cannot be undone.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    elif data == "bulk_cancel_all":
        user_id = update.effective_user.id
        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            ids = reminder_service.cancel_all_for_user(user_id)
        scheduler_service = context.bot_data.get('scheduler_service')
        if scheduler_service:
            for rid in ids:
                scheduler_service.remove_job(rid)
        await query.edit_message_text(f"❌ Cancelled {len(ids)} reminder(s).")
        return

    elif data.startswith("leadtime_"):
        reminder_id = int(data.split("_")[1])
        keyboard = [
            [
                InlineKeyboardButton("5m", callback_data=f"leadtimeset_{reminder_id}_5"),
                InlineKeyboardButton("15m", callback_data=f"leadtimeset_{reminder_id}_15"),
                InlineKeyboardButton("30m", callback_data=f"leadtimeset_{reminder_id}_30"),
            ],
            [
                InlineKeyboardButton("1h", callback_data=f"leadtimeset_{reminder_id}_60"),
                InlineKeyboardButton("2h", callback_data=f"leadtimeset_{reminder_id}_120"),
                InlineKeyboardButton("1d", callback_data=f"leadtimeset_{reminder_id}_1440"),
            ],
            [InlineKeyboardButton("🔙 Back", callback_data=f"manage_{reminder_id}")],
        ]
        await query.edit_message_text(
            "🔔 *Add a lead-time alert*\n\nHow far in advance should I remind you?",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    elif data.startswith("leadtimeset_"):
        parts = data.split("_")
        parent_id = int(parts[1])
        lead_minutes = int(parts[2])

        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            child = reminder_service.create_lead_time_reminder(parent_id, lead_minutes)

        if child:
            scheduler_service = context.bot_data.get('scheduler_service')
            if scheduler_service:
                scheduler_service.schedule_reminder(child)
            await query.answer(f"🔔 Lead-time alert added ({lead_minutes}m before)")
        else:
            await query.answer("❌ Could not create lead-time alert")
        await _show_manage_view(query, parent_id)
        return

    elif data.startswith("setuntil_"):
        reminder_id = int(data.split("_")[1])
        _clear_pending_text_flags(context)
        context.user_data['awaiting_repeat_until_id'] = reminder_id

        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data=f"manage_{reminder_id}")]]
        await query.edit_message_text(
            "🏁 *Set end date*\n\nSend the last date this reminder should fire on:\n"
            "• `2026-06-01` — ISO date\n"
            "• `June 1` — natural language\n"
            "• `next month` — relative",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    elif data.startswith("clearuntil_"):
        reminder_id = int(data.split("_")[1])
        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            reminder_service.set_repeat_until(reminder_id, None)
        await query.answer("🏁 End date cleared")
        await _show_manage_view(query, reminder_id)
        return

    elif data.startswith("changesched_"):
        reminder_id = int(data.split("_")[1])
        _clear_pending_text_flags(context)
        context.user_data['awaiting_change_schedule_id'] = reminder_id

        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data=f"manage_{reminder_id}")]]
        await query.edit_message_text(
            "🔄 *Change schedule*\n\nSend the new schedule:\n"
            "• `every day at 22:00`\n"
            "• `every monday and thursday at 5PM`\n"
            "• `weekly friday 9AM`\n"
            "• `22:00` — keep the repeat pattern, change only the time",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    elif data.startswith("editmsg_"):
        reminder_id = int(data.split("_")[1])
        _clear_pending_text_flags(context)
        context.user_data['awaiting_edit_message_id'] = reminder_id

        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data=f"manage_{reminder_id}")]]
        await query.edit_message_text(
            "✏️ *Edit reminder message*\n\nSend the new message text:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    elif data == "cancel_interactive":
        # This is handled by the conversation handler, but we need to prevent the error
        pass
    
    elif data.startswith("cancel_"):
        reminder_id = int(data.split("_")[1])

        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            reminder = reminder_service.get_reminder_by_id(reminder_id)

            if not reminder:
                await query.edit_message_text("❌ Reminder not found.")
                return

            reminder_service.cancel_reminder(reminder_id)

        # Remove any pending scheduler job so a repeating reminder doesn't fire again
        scheduler_service = context.bot_data.get('scheduler_service')
        if scheduler_service:
            scheduler_service.remove_job(reminder_id)

        await query.answer("❌ Reminder cancelled!")
        from .reminder_handlers import list_reminders
        await list_reminders(update, context)
    
    elif data.startswith("snooze_"):
        parts = data.split("_")

        # Stale wizard buttons (snooze_5 ... snooze_120) have no reminder id — ignore them.
        if len(parts) != 3:
            return

        reminder_id = int(parts[1])
        snooze_minutes = int(parts[2])

        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            snoozed = reminder_service.snooze_reminder(reminder_id, snooze_minutes)
            snoozed_id = snoozed.id if snoozed else None

        if snoozed_id is not None:
            scheduler_service = context.bot_data.get('scheduler_service')
            if scheduler_service:
                scheduler_service.reschedule_reminder(snoozed_id)

            if snoozed_id != reminder_id:
                await query.edit_message_text(
                    f"😴 Snoozed for {snooze_minutes} minutes. The repeating schedule is unchanged."
                )
            else:
                await query.edit_message_text(f"😴 Reminder snoozed for {snooze_minutes} minutes.")
        else:
            await query.edit_message_text("❌ Reminder not found or cannot be snoozed.")
    
    elif data.startswith("reschedule_custom_"):
        reminder_id = int(data.split("_")[2])

        # Store reminder ID for the conversation
        _clear_pending_text_flags(context)
        context.user_data['reschedule_reminder_id'] = reminder_id
        
        keyboard = [
            [InlineKeyboardButton("❌ Cancel", callback_data=f"back_to_reminder_{reminder_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🔧 *Custom Reschedule Time*\n\n"
            "Enter when you want to reschedule this reminder:\n\n"
            "Examples:\n"
            "• `10:30` or `10:30 PM` - Specific time\n"
            "• `2h`, `30m`, `1d` - Relative time\n"
            "• `tomorrow at 3pm` - Natural language\n"
            "• `June 26 at 5PM` - Specific date\n"
            "• `3 days` - Multiple days from now\n"
            "• `every monday and thursday at 5PM` - Change the repeating schedule",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        # Set conversation state to expect custom time
        context.user_data['awaiting_reschedule_time'] = True
        return
    
    elif data.startswith("reschedule_") and not data.startswith("reschedule_time_") and not data.startswith("reschedule_custom_"):
        reminder_id = int(data.split("_")[1])
        
        keyboard = [
            [InlineKeyboardButton("⏰ 15 minutes", callback_data=f"reschedule_time_{reminder_id}_15")],
            [InlineKeyboardButton("⏰ 30 minutes", callback_data=f"reschedule_time_{reminder_id}_30")],
            [InlineKeyboardButton("⏰ 1 hour", callback_data=f"reschedule_time_{reminder_id}_60")],
            [InlineKeyboardButton("⏰ 2 hours", callback_data=f"reschedule_time_{reminder_id}_120")],
            [InlineKeyboardButton("⏰ Tomorrow", callback_data=f"reschedule_time_{reminder_id}_1440")],
            [InlineKeyboardButton("🔧 Custom Time", callback_data=f"reschedule_custom_{reminder_id}")],
            [InlineKeyboardButton("🔙 Back", callback_data=f"back_to_reminder_{reminder_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "⏰ *Reschedule reminder:*\n\nChoose when to reschedule this reminder:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif data.startswith("reschedule_time_"):
        parts = data.split("_")
        reminder_id = int(parts[2])
        minutes_delay = int(parts[3])

        # Scheduled times are stored as naive UTC; never use server-local time here.
        new_time = datetime.now(pytz.UTC).replace(tzinfo=None) + timedelta(minutes=minutes_delay)

        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            rescheduled = reminder_service.reschedule_reminder(reminder_id, new_time)
            rescheduled_id = rescheduled.id if rescheduled else None

        if rescheduled_id is not None:
            scheduler_service = context.bot_data.get('scheduler_service')
            if scheduler_service:
                scheduler_service.reschedule_reminder(rescheduled_id)

            time_text = "tomorrow" if minutes_delay == 1440 else f"in {minutes_delay} minutes"

            if rescheduled_id != reminder_id:
                await query.edit_message_text(
                    f"⏰ I'll remind you again {time_text}. The repeating schedule is unchanged."
                )
            else:
                await query.edit_message_text(f"⏰ Reminder rescheduled {time_text}.")
        else:
            await query.edit_message_text(
                "❌ Cannot reschedule this reminder — it may be paused (resume it first) or cancelled."
            )
    
    elif data.startswith("back_to_reminder_"):
        reminder_id = int(data.split("_")[3])
        
        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            reminder = reminder_service.get_reminder_by_id(reminder_id)
        
        if not reminder:
            await query.edit_message_text("❌ Reminder not found.")
            return
        
        message = f"🔔 *Reminder:* {escape_markdown(reminder.message_text)}"
        
        keyboard = []
        if reminder.requires_confirmation and not reminder.is_confirmed:
            keyboard.append(
                [InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_{reminder.id}")]
                + build_snooze_buttons(reminder)
            )
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
                InlineKeyboardButton("⏰ Reschedule", callback_data=f"reschedule_{reminder.id}")
            ])
        else:
            # Non-confirmation reminders get only snooze and reschedule
            keyboard.append(
                build_snooze_buttons(reminder)
                + [InlineKeyboardButton("⏰ Reschedule", callback_data=f"reschedule_{reminder.id}")]
            )
        
        keyboard.append([
            InlineKeyboardButton("📝 History", callback_data=f"history_{reminder.id}")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    elif data.startswith("history_"):
        reminder_id = int(data.split("_")[1])
        
        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            history = reminder_service.get_reminder_history(reminder_id)
            reminder = reminder_service.get_reminder_by_id(reminder_id)
        
        if not reminder:
            await query.edit_message_text("❌ Reminder not found.")
            return
        
        response = f"📝 *History for Reminder {reminder_id}:*\n"
        response += f"*Message:* {escape_markdown(reminder.message_text)}\n\n"
        
        if history:
            for entry in history:
                response += f"• {entry.action.title()} - {entry.timestamp.strftime('%Y-%m-%d %H:%M')}\n"
        else:
            response += "No history available."
        
        await query.edit_message_text(response, parse_mode='Markdown')
    
    elif data == "refresh_reminders":
        from src.handlers.reminder_handlers import list_reminders
        try:
            await list_reminders(update, context)
        except Exception as e:
            if "Message is not modified" in str(e):
                await query.answer("✅ Reminders refreshed!")
            else:
                await query.answer("❌ Failed to refresh reminders")
                raise e
    
    # Handle interactive reminder callbacks that don't belong to the conversation
    elif data.startswith(("type_", "repeat_", "back_to_type", "back_to_repeat", "back_to_confirm", "snooze_5", "snooze_10", "snooze_15", "snooze_30", "snooze_60", "snooze_120")) or data == "skip_tagging":
        # These are handled by the conversation handler
        pass
