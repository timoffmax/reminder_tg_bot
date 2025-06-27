from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from src.database import SessionLocal
from src.services.reminder_service import ReminderService
from src.services.user_service import UserService
from src.utils.timezone_utils import get_timezone_regions

def escape_markdown(text: str) -> str:
    """Escape special characters for Markdown parse mode"""
    # Escape only the most critical MarkdownV2 characters that cause parsing issues
    # Parentheses often don't need escaping for regular text content
    special_chars = ['_', '*', '[', ']', '~', '`', '>', '#', '+', '=', '|', '{', '}', '.', '\\']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

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
            success = reminder_service.confirm_reminder(reminder_id)
        
        if success:
            await query.edit_message_text("✅ Reminder confirmed!")
        else:
            await query.edit_message_text("❌ Reminder not found or already confirmed.")
    
    elif data.startswith("complete_"):
        reminder_id = int(data.split("_")[1])
        
        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            success = reminder_service.complete_reminder(reminder_id)
        
        if success:
            await query.edit_message_text("✅ Reminder completed!")
        else:
            await query.edit_message_text("❌ Reminder not found.")
    
    elif data == "cancel_interactive":
        # This is handled by the conversation handler, but we need to prevent the error
        pass
    
    elif data.startswith("cancel_"):
        reminder_id = int(data.split("_")[1])
        
        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            success = reminder_service.cancel_reminder(reminder_id)
        
        if success:
            # Show updated reminder list after cancellation
            await query.answer("❌ Reminder cancelled!")
            # Import the function dynamically to avoid circular import
            from .reminder_handlers import list_reminders
            await list_reminders(update, context)
        else:
            await query.edit_message_text("❌ Reminder not found.")
    
    elif data.startswith("snooze_"):
        parts = data.split("_")
        reminder_id = int(parts[1])
        snooze_minutes = int(parts[2])
        
        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            success = reminder_service.snooze_reminder(reminder_id, snooze_minutes)
        
        if success:
            scheduler_service = context.bot_data.get('scheduler_service')
            if scheduler_service:
                scheduler_service.reschedule_reminder(reminder_id)
            
            await query.edit_message_text(f"😴 Reminder snoozed for {snooze_minutes} minutes.")
        else:
            await query.edit_message_text("❌ Reminder not found or cannot be snoozed.")
    
    elif data.startswith("reschedule_"):
        reminder_id = int(data.split("_")[1])
        
        keyboard = [
            [InlineKeyboardButton("⏰ 15 minutes", callback_data=f"reschedule_time_{reminder_id}_15")],
            [InlineKeyboardButton("⏰ 30 minutes", callback_data=f"reschedule_time_{reminder_id}_30")],
            [InlineKeyboardButton("⏰ 1 hour", callback_data=f"reschedule_time_{reminder_id}_60")],
            [InlineKeyboardButton("⏰ 2 hours", callback_data=f"reschedule_time_{reminder_id}_120")],
            [InlineKeyboardButton("⏰ Tomorrow", callback_data=f"reschedule_time_{reminder_id}_1440")],
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
        
        from datetime import datetime, timedelta
        new_time = datetime.now() + timedelta(minutes=minutes_delay)
        
        with SessionLocal() as db:
            reminder_service = ReminderService(db)
            success = reminder_service.reschedule_reminder(reminder_id, new_time)
        
        if success:
            scheduler_service = context.bot_data.get('scheduler_service')
            if scheduler_service:
                scheduler_service.reschedule_reminder(reminder_id)
            
            time_text = "tomorrow" if minutes_delay == 1440 else f"{minutes_delay} minutes"
            await query.edit_message_text(f"⏰ Reminder rescheduled for {time_text} from now.")
        else:
            await query.edit_message_text("❌ Failed to reschedule reminder.")
    
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