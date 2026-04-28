from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from src.database import SessionLocal
from src.services.user_service import UserService
from src.services.reminder_service import ReminderService
from src.utils.timezone_utils import get_timezone_regions, parse_time_input
from datetime import datetime

def get_main_menu_keyboard():
    """Get the main menu keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("➕ New Reminder", callback_data="menu_new_reminder"),
            InlineKeyboardButton("📋 My Reminders", callback_data="menu_my_reminders")
        ],
        [
            InlineKeyboardButton("⏰ Set Timezone", callback_data="menu_timezone"),
            InlineKeyboardButton("❓ Help", callback_data="menu_help")
        ],
        [
            InlineKeyboardButton("ℹ️ About", callback_data="menu_about")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    with SessionLocal() as db:
        user_service = UserService(db)
        user_service.get_or_create_user(
            telegram_user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code
        )
    
    welcome_text = f"""
🤖 *Welcome {user.first_name}!*

I'm your personal reminder assistant. I can help you:

• 📝 Create one-time or repeating reminders
• 👥 Tag users in group chats  
• 😴 Snooze, reschedule or cancel reminders
• ✅ Set reminders that require confirmation
• 📋 Manage your reminder list

Choose an option below to get started:
"""
    
    await update.message.reply_text(
        welcome_text, 
        parse_mode='Markdown',
        reply_markup=get_main_menu_keyboard()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
*Available Commands:*

*Basic:*
/start - Start the bot
/help - Show this help message
/timezone - Set your timezone

*Reminder Creation:*
/remind - Interactive mode (no arguments) OR quick mode (with arguments)

*Reminder Management:*
/reminders - Show your active reminders
/snooze <id> [minutes] - Snooze a reminder
/cancel <id> - Cancel a reminder
/confirm <id> - Confirm a reminder

*Quick Mode Examples:*
• `/remind 10:30 Meeting with John`
• `/remind 2h Take a break`
• `/remind 1d daily Pay bills`
• `/remind 15m confirm Call mom`

*Interactive Mode:*
Use `/remind` (without arguments) for guided step-by-step creation:
• ✅ Visual time selection with validation
• ✅ Message input with character limits
• ✅ Type selection (one-time/repeating)
• ✅ Confirmation settings
• ✅ Back/cancel buttons at each step

*Time formats:*
• `10:30` or `10:30 PM` - At specific time
• `2h`, `30m`, `1d`, `1w` - Relative time
• `tomorrow at 3pm` - Natural language
• `June 26 at 5PM` - Specific date & time
• `12.07.2025 14:00` - European format
• `12/7/25 2PM` - US format
• `next monday at 10am` - Day of week
• Add `daily`, `weekly`, `monthly` for repeating
• Add `confirm` for confirmation required
"""
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def set_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        # Show regions first
        regions = get_timezone_regions()
        keyboard = []
        
        for region in regions.keys():
            keyboard.append([InlineKeyboardButton(
                f"🌍 {region}", 
                callback_data=f"tzr_{region}"
            )])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🌍 *Select your region:*\n\nChoose your geographical region to see available timezones.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    timezone = context.args[0]
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
        await update.message.reply_text(f"✅ Timezone set to {timezone}")
    else:
        await update.message.reply_text("❌ Failed to set timezone. Please try again.")

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the main menu"""
    menu_text = """
🤖 *Main Menu*

What would you like to do?
"""
    
    await update.message.reply_text(
        menu_text,
        parse_mode='Markdown',
        reply_markup=get_main_menu_keyboard()
    )

async def handle_edit_message_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new text input for an in-progress 'Edit message' action."""
    reminder_id = context.user_data.get('awaiting_edit_message_id')
    if not reminder_id:
        return False

    new_text = update.message.text.strip()

    if len(new_text) > 500:
        await update.message.reply_text("❌ Message too long (max 500 characters). Please try again:")
        return True

    if len(new_text) == 0:
        await update.message.reply_text("❌ Message cannot be empty. Please try again:")
        return True

    context.user_data.pop('awaiting_edit_message_id', None)

    with SessionLocal() as db:
        reminder_service = ReminderService(db)
        success = reminder_service.update_message_text(reminder_id, new_text)

    if success:
        await update.message.reply_text("✅ Reminder message updated.")
    else:
        await update.message.reply_text("❌ Failed to update reminder.")
    return True

async def handle_custom_reschedule_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle custom reschedule time input"""
    # Check if we're expecting a reschedule time
    if not context.user_data.get('awaiting_reschedule_time'):
        return False
    
    reminder_id = context.user_data.get('reschedule_reminder_id')
    if not reminder_id:
        return False
    
    # Clear the flags
    context.user_data['awaiting_reschedule_time'] = False
    
    user_id = update.effective_user.id
    time_input = update.message.text.strip()
    
    with SessionLocal() as db:
        user_service = UserService(db)
        user_timezone = user_service.get_user_timezone(user_id)
        
        # Parse the time input
        new_time = parse_time_input(time_input, user_timezone)
        
        if not new_time:
            await update.message.reply_text(
                "❌ Invalid time format. Please try again or click Cancel.\n\n"
                "Examples:\n"
                "• `10:30` or `10:30 PM`\n"
                "• `2h`, `30m`, `1d`\n"
                "• `tomorrow at 3pm`\n"
                "• `3 days`",
                parse_mode='Markdown'
            )
            context.user_data['awaiting_reschedule_time'] = True
            return True
        
        # Reschedule the reminder
        reminder_service = ReminderService(db)
        success = reminder_service.reschedule_reminder(reminder_id, new_time)
        
        if success:
            # Update scheduler
            scheduler_service = context.bot_data.get('scheduler_service')
            if scheduler_service:
                scheduler_service.reschedule_reminder(reminder_id)
            
            # Format the new time for display
            from src.utils.timezone_utils import convert_to_user_timezone
            user_time = convert_to_user_timezone(new_time, user_timezone)
            
            await update.message.reply_text(
                f"✅ Reminder rescheduled to {user_time.strftime('%Y-%m-%d %H:%M')} ({user_timezone})"
            )
        else:
            await update.message.reply_text("❌ Failed to reschedule reminder.")
    
    # Clear context data
    context.user_data.pop('reschedule_reminder_id', None)
    return True