from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from src.database import SessionLocal
from src.services.user_service import UserService
from src.utils.timezone_utils import get_timezone_regions

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