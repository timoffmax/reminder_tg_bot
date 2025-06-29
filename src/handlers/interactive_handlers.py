from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CallbackQueryHandler, CommandHandler, filters
from src.database import SessionLocal
from src.services.reminder_service import ReminderService
from src.services.user_service import UserService
from src.models.reminder import ReminderType
from src.utils.timezone_utils import parse_time_input, convert_to_user_timezone, parse_recurring_pattern
import pytz

def escape_markdown(text: str) -> str:
    """Escape special characters for Markdown parse mode"""
    # Only escape characters that actually need escaping in Telegram MarkdownV2
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

def get_step_info(context: ContextTypes.DEFAULT_TYPE) -> tuple[int, int]:
    """Get current step number and total steps"""
    current_step = context.user_data.get('current_step', 1)
    
    # Calculate total steps based on what's been determined so far
    base_steps = 2  # time and message
    if context.user_data.get('is_group'):
        base_steps += 1  # tag users
    
    # Check if we know reminder type to add type selection step
    if not context.user_data.get('reminder_type'):
        base_steps += 1  # type selection
    
    # Check if repeating to add confirmation step
    if context.user_data.get('reminder_type') == ReminderType.REPEATING or not context.user_data.get('reminder_type'):
        base_steps += 1  # confirmation
        
    # Check if confirmation required to add snooze step
    if context.user_data.get('requires_confirmation'):
        base_steps += 1  # snooze duration
    
    return current_step, base_steps

# Conversation states
REMINDER_TIME, REMINDER_MESSAGE, REMINDER_TAG_USERS, REMINDER_TYPE, REMINDER_CONFIRMATION, REMINDER_SNOOZE_DURATION, REMINDER_FINAL, REMINDER_CUSTOM_PERIOD = range(8)

async def start_interactive_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start interactive reminder creation"""
    keyboard = [
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Initialize step tracking
    is_group = update.effective_chat.type in ['group', 'supergroup']
    context.user_data['is_group'] = is_group
    context.user_data['current_step'] = 1
    context.user_data['steps'] = []  # Track which steps we'll use
    
    # Determine which steps we'll show based on context
    base_steps = ['time', 'message']
    if is_group:
        base_steps.append('tag_users')
    
    # We'll add more steps dynamically as we go
    context.user_data['steps'] = base_steps
    
    current_step, total_steps = get_step_info(context)
    
    text = f"""🕒 *Interactive Reminder Creation*

Let's create your reminder step by step!

*Step {current_step}/{total_steps}: When should I remind you?*

Examples:
• `10:30` or `10:30 PM` - At specific time
• `2h` - In 2 hours  
• `30m` - In 30 minutes
• `tomorrow at 3pm` - Natural language
• `June 26 at 5PM` - Specific date & time
• `12.07.2025 14:00` - European format
• `12/7/25 2PM` - US format
• `next monday at 10am` - Day of week"""
    
    # Handle both message and callback query
    if update.message:
        await update.message.reply_text(
            text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    elif update.callback_query:
        # Edit the existing menu message
        await update.callback_query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    return REMINDER_TIME

async def reminder_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process the time input"""
    user_id = update.effective_user.id
    time_input = update.message.text.strip()
    
    with SessionLocal() as db:
        user_service = UserService(db)
        user_timezone = user_service.get_user_timezone(user_id)
        
        # Parse recurring patterns first
        cleaned_time_input, repeat_interval = parse_recurring_pattern(time_input)
        
        scheduled_time = parse_time_input(cleaned_time_input, user_timezone)
        
        if not scheduled_time:
            keyboard = [
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "❌ Invalid time format. Please try again.\n\n"
                "Examples:\n"
                "• `10:30` or `10:30 PM` - At specific time\n"
                "• `2h` - In 2 hours\n"
                "• `tomorrow at 3pm` - Natural language\n"
                "• `June 26 at 5PM` - Specific date & time\n"
                "• `12/7/25 2PM` - US format",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            return REMINDER_TIME
        
        # parse_time_input already returns UTC time, store directly
        context.user_data['scheduled_time'] = scheduled_time
        context.user_data['user_timezone'] = user_timezone
        context.user_data['repeat_interval'] = repeat_interval
        
        # Automatically set reminder type if recurring pattern detected
        if repeat_interval:
            context.user_data['reminder_type'] = ReminderType.REPEATING
        
        # Show user the interpreted time
        user_time = convert_to_user_timezone(scheduled_time, user_timezone)
        
        keyboard = [
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Move to next step
        context.user_data['current_step'] = 2
        current_step, total_steps = get_step_info(context)
        
        # Show appropriate time confirmation message
        time_display = f"✅ Time set: {user_time.strftime('%Y-%m-%d %H:%M')} ({user_timezone})"
        if repeat_interval:
            time_display += f"\n🔄 Schedule: {repeat_interval.replace('multi-day:', 'days:').title()}"
        
        await update.message.reply_text(
            f"{time_display}\n\n"
            f"*Step {current_step}/{total_steps}: What should I remind you about?*\n\n"
            "Enter your reminder message:",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        return REMINDER_MESSAGE

async def reminder_message_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process the reminder message"""
    message = update.message.text.strip()
    
    if len(message) > 500:
        keyboard = [
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "❌ Message too long (max 500 characters). Please shorten it:",
            reply_markup=reply_markup
        )
        return REMINDER_MESSAGE
    
    context.user_data['message'] = message
    
    # Check if we're in a group chat to ask about tagging users
    if update.effective_chat.type in ['group', 'supergroup']:
        keyboard = [
            [InlineKeyboardButton("⏭️ Skip Tagging", callback_data="skip_tagging")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Move to next step
        context.user_data['current_step'] = 3
        current_step, total_steps = get_step_info(context)
        
        await update.message.reply_text(
            f"✅ Message: {escape_markdown(message)}\n\n"
            f"*Step {current_step}/{total_steps}: Tag users (Optional)*\n\n"
            "Would you like to tag specific users for this reminder?\n"
            "Reply with usernames (e.g., @user1 @user2) or click 'Skip Tagging' to continue.",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        return REMINDER_TAG_USERS
    else:
        # Skip tagging step for private chats
        context.user_data['tagged_users'] = []
        
        # If reminder type already determined from time input, skip type selection
        if context.user_data.get('reminder_type'):
            # Go directly to confirmation step
            keyboard = [
                [
                    InlineKeyboardButton("✅ Yes", callback_data="confirm_yes"),
                    InlineKeyboardButton("❌ No", callback_data="confirm_no")
                ],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            repeat_interval = context.user_data.get('repeat_interval')
            type_display = f"Repeating ({repeat_interval})" if repeat_interval else "One-time"
            
            await update.message.reply_text(
                f"✅ Message: {escape_markdown(message)}\n"
                f"🔄 Type: {type_display}\n\n"
                "*Step 3/4: Confirmation required?*\n\n"
                "Do you want this reminder to require confirmation before being marked as done?",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            
            return REMINDER_CONFIRMATION
        
        keyboard = [
            [
                InlineKeyboardButton("⏰ One-time", callback_data="type_one_time"),
                InlineKeyboardButton("🔄 Repeating", callback_data="type_repeating")
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✅ Message: {escape_markdown(message)}\n\n"
            "*Step 3/4: Reminder type*\n\n"
            "Should this be a one-time reminder or repeating?",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        return REMINDER_TYPE

async def skip_tagging(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle skip tagging button"""
    query = update.callback_query
    await query.answer()
    
    context.user_data['tagged_users'] = []
    
    # If reminder type already determined from time input, skip type selection
    if context.user_data.get('reminder_type'):
        # Go directly to confirmation step
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes", callback_data="confirm_yes"),
                InlineKeyboardButton("❌ No", callback_data="confirm_no")
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_tags")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        repeat_interval = context.user_data.get('repeat_interval')
        type_display = f"Repeating ({repeat_interval})" if repeat_interval else "One-time"
        
        await query.edit_message_text(
            f"✅ Message: {escape_markdown(context.user_data['message'])}\n"
            f"🔄 Type: {type_display}\n\n"
            "*Step 4/6: Confirmation required?*\n\n"
            "Do you want this reminder to require confirmation before being marked as done?",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        return REMINDER_CONFIRMATION
    
    keyboard = [
        [
            InlineKeyboardButton("⏰ One-time", callback_data="type_one_time"),
            InlineKeyboardButton("🔄 Repeating", callback_data="type_repeating")
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"✅ Message: {escape_markdown(context.user_data['message'])}\n\n"
        "*Step 4/6: Reminder type*\n\n"
        "Should this be a one-time reminder or repeating?",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    
    return REMINDER_TYPE

async def reminder_tag_users_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process user tagging input"""
    text = update.message.text.strip()
    
    if text.lower() == 'skip':
        context.user_data['tagged_users'] = []
    else:
        # Extract mentions from the message
        tagged_users = []
        entities = update.message.entities or []
        for entity in entities:
            if entity.type == 'mention':
                username = update.message.text[entity.offset:entity.offset + entity.length]
                tagged_users.append(username)
        
        # If no mentions found, try to parse manually (in case of format like @username)
        if not tagged_users:
            import re
            # Find all @username patterns (including underscores and numbers)
            mentions = re.findall(r'@[a-zA-Z0-9_]+', text)
            tagged_users = mentions
        
        context.user_data['tagged_users'] = tagged_users
    
    tagged_list = context.user_data['tagged_users']
    tag_text = f"\n👥 Tagged: {escape_markdown(' '.join(tagged_list))}" if tagged_list else ""
    
    # If reminder type already determined from time input, skip type selection
    if context.user_data.get('reminder_type'):
        # Go directly to confirmation step
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes", callback_data="confirm_yes"),
                InlineKeyboardButton("❌ No", callback_data="confirm_no")
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_tags")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        repeat_interval = context.user_data.get('repeat_interval')
        type_display = f"Repeating ({repeat_interval})" if repeat_interval else "One-time"
        
        await update.message.reply_text(
            f"✅ Message: {escape_markdown(context.user_data['message'])}{tag_text}\n"
            f"🔄 Type: {type_display}\n\n"
            "*Step 5/6: Confirmation required?*\n\n"
            "Do you want this reminder to require confirmation before being marked as done?",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        return REMINDER_CONFIRMATION
    
    keyboard = [
        [
            InlineKeyboardButton("⏰ One-time", callback_data="type_one_time"),
            InlineKeyboardButton("🔄 Repeating", callback_data="type_repeating")
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ Message: {escape_markdown(context.user_data['message'])}{tag_text}\n\n"
        "*Step 4/6: Reminder type*\n\n"
        "Should this be a one-time reminder or repeating?",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    
    return REMINDER_TYPE

async def reminder_type_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process reminder type selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "type_one_time":
        context.user_data['reminder_type'] = ReminderType.ONE_TIME
        context.user_data['repeat_interval'] = None
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes", callback_data="confirm_yes"),
                InlineKeyboardButton("❌ No", callback_data="confirm_no")
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_type")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "✅ Type: One-time reminder\n\n"
            "*Step 5/6: Confirmation required?*\n\n"
            "Do you want this reminder to require confirmation before being marked as done?",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        return REMINDER_CONFIRMATION
        
    elif query.data == "type_repeating":
        keyboard = [
            [
                InlineKeyboardButton("📅 Daily", callback_data="repeat_daily"),
                InlineKeyboardButton("📆 Weekly", callback_data="repeat_weekly"),
                InlineKeyboardButton("🗓 Monthly", callback_data="repeat_monthly")
            ],
            [InlineKeyboardButton("🔧 Custom Period", callback_data="repeat_custom")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_type")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🔄 *Repeating Reminder*\n\n"
            "How often should this reminder repeat?",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

async def reminder_repeat_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process repeat interval selection"""
    query = update.callback_query
    await query.answer()
    
    repeat_map = {
        "repeat_daily": "daily",
        "repeat_weekly": "weekly", 
        "repeat_monthly": "monthly"
    }
    
    if query.data == "repeat_custom":
        keyboard = [
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_repeat_type")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🔧 *Custom Repeat Period*\n\n"
            "Enter your custom repeat period:\n"
            "• `3 days` - every 3 days\n"
            "• `2 weeks` - every 2 weeks\n"
            "• `3 months` - every 3 months\n"
            "• `21 days` - every 21 days\n\n"
            "Format: `<number> <unit>` where unit is days/weeks/months",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        return REMINDER_CUSTOM_PERIOD
    
    elif query.data in repeat_map:
        context.user_data['reminder_type'] = ReminderType.REPEATING
        context.user_data['repeat_interval'] = repeat_map[query.data]
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes", callback_data="confirm_yes"),
                InlineKeyboardButton("❌ No", callback_data="confirm_no")
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_repeat")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"✅ Type: Repeating {repeat_map[query.data]}\n\n"
            "*Step 5/6: Confirmation required?*\n\n"
            "Do you want this reminder to require confirmation before being marked as done?",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        return REMINDER_CONFIRMATION

async def reminder_custom_period_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process custom repeat period input"""
    import re
    
    text = update.message.text.strip().lower()
    
    # Parse pattern like "3 days", "2 weeks", "3 months"
    pattern = r'^(\d+)\s*(day|days|week|weeks|month|months)$'
    match = re.match(pattern, text)
    
    if not match:
        keyboard = [
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_repeat_type")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "❌ Invalid format. Please use format like:\n"
            "• `3 days`\n"
            "• `2 weeks`\n"
            "• `3 months`",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        return REMINDER_CUSTOM_PERIOD
    
    number = int(match.group(1))
    unit = match.group(2)
    
    # Normalize unit names
    if unit.startswith('day'):
        unit = 'days'
    elif unit.startswith('week'):
        unit = 'weeks'
    elif unit.startswith('month'):
        unit = 'months'
    
    # Store custom period
    custom_period = f"custom_{number}_{unit}"
    context.user_data['reminder_type'] = ReminderType.REPEATING
    context.user_data['repeat_interval'] = custom_period
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes", callback_data="confirm_yes"),
            InlineKeyboardButton("❌ No", callback_data="confirm_no")
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_repeat_type")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ Type: Repeating every {number} {unit}\n\n"
        "*Step 5/6: Confirmation required?*\n\n"
        "Do you want this reminder to require confirmation before being marked as done?",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    
    return REMINDER_CONFIRMATION

async def reminder_confirmation_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process confirmation requirement"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "confirm_yes":
        context.user_data['requires_confirmation'] = True
        
        keyboard = [
            [
                InlineKeyboardButton("😴 5 min", callback_data="snooze_5"),
                InlineKeyboardButton("😴 10 min", callback_data="snooze_10"),
                InlineKeyboardButton("😴 15 min", callback_data="snooze_15")
            ],
            [
                InlineKeyboardButton("😴 30 min", callback_data="snooze_30"),
                InlineKeyboardButton("😴 1 hour", callback_data="snooze_60"),
                InlineKeyboardButton("😴 2 hours", callback_data="snooze_120")
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_confirm")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "✅ Confirmation: Required\n\n"
            "*Step 6/6: Default snooze duration*\n\n"
            "If no action is taken, how long should the reminder wait before re-sending?",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        return REMINDER_SNOOZE_DURATION
        
    elif query.data == "confirm_no":
        context.user_data['requires_confirmation'] = False
        context.user_data['default_snooze_minutes'] = 10  # Default for non-confirmation reminders
        return await create_reminder_final(update, context)
    else:
        return REMINDER_CONFIRMATION

async def reminder_snooze_duration_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process snooze duration selection and create reminder"""
    query = update.callback_query
    await query.answer()
    
    snooze_map = {
        "snooze_5": 5,
        "snooze_10": 10,
        "snooze_15": 15,
        "snooze_30": 30,
        "snooze_60": 60,
        "snooze_120": 120
    }
    
    if query.data in snooze_map:
        context.user_data['default_snooze_minutes'] = snooze_map[query.data]
        return await create_reminder_final(update, context)
    else:
        return REMINDER_SNOOZE_DURATION

async def create_reminder_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create the final reminder with all settings"""
    # Create the reminder
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    chat_title = update.effective_chat.title if update.effective_chat.type in ['group', 'supergroup'] else None
    
    scheduled_time = context.user_data['scheduled_time']
    message = context.user_data['message']
    reminder_type = context.user_data['reminder_type']
    repeat_interval = context.user_data.get('repeat_interval')
    user_timezone = context.user_data['user_timezone']
    requires_confirmation = context.user_data['requires_confirmation']
    default_snooze_minutes = context.user_data['default_snooze_minutes']
    tagged_users = context.user_data.get('tagged_users', [])
    
    with SessionLocal() as db:
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
        
        # Schedule the reminder
        scheduler_service = context.bot_data.get('scheduler_service')
        if scheduler_service:
            scheduler_service.schedule_reminder(reminder)
    
    # Build summary message
    user_time = convert_to_user_timezone(scheduled_time, user_timezone)
    summary = f"🎉 *Reminder Created Successfully!*\n\n"
    if chat_title:
        summary += f"💬 *Group:* {escape_markdown(chat_title)}\n"
    summary += f"📝 *Message:* {escape_markdown(message)}\n"
    summary += f"🕒 *Time:* {user_time.strftime('%Y-%m-%d %H:%M')} ({escape_markdown(user_timezone)})\n"
    summary += f"🔄 *Type:* {escape_markdown(reminder_type.value.title())}"
    
    if repeat_interval:
        # Format custom periods nicely
        if repeat_interval.startswith("custom_"):
            parts = repeat_interval.split('_')
            if len(parts) == 3:
                summary += f" (every {parts[1]} {parts[2]})"
            else:
                summary += f" ({escape_markdown(repeat_interval)})"
        else:
            summary += f" ({escape_markdown(repeat_interval)})"
    
    if requires_confirmation:
        summary += f"\n❓ *Confirmation:* Required (re-send after {default_snooze_minutes} min)"
    
    if tagged_users:
        # Don't escape @ mentions - they need to work in Telegram
        summary += f"\n👥 *Tagged:* {' '.join(tagged_users)}"
    
    keyboard = [
        [InlineKeyboardButton("📋 My Reminders", callback_data="refresh_reminders")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            summary,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            summary,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    # Clear user data
    context.user_data.clear()
    
    return ConversationHandler.END

async def cancel_interactive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel interactive reminder creation"""
    from src.handlers.basic_handlers import get_main_menu_keyboard
    
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            "❌ Reminder creation cancelled.\n\n🤖 *Main Menu*\n\nWhat would you like to do?",
            parse_mode='Markdown',
            reply_markup=get_main_menu_keyboard()
        )
    else:
        await update.message.reply_text(
            "❌ Reminder creation cancelled.\n\n🤖 *Main Menu*\n\nWhat would you like to do?",
            parse_mode='Markdown',
            reply_markup=get_main_menu_keyboard()
        )
    
    # Clear user data
    context.user_data.clear()
    
    return ConversationHandler.END

async def back_to_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to reminder type selection"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [
            InlineKeyboardButton("⏰ One-time", callback_data="type_one_time"),
            InlineKeyboardButton("🔄 Repeating", callback_data="type_repeating")
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = context.user_data.get('message', 'Your message')
    
    await query.edit_message_text(
        f"✅ Message: {escape_markdown(message)}\n\n"
        "*Step 3/4: Reminder type*\n\n"
        "Should this be a one-time reminder or repeating?",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    
    return REMINDER_TYPE

async def back_to_repeat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to repeat interval selection"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [
            InlineKeyboardButton("📅 Daily", callback_data="repeat_daily"),
            InlineKeyboardButton("📆 Weekly", callback_data="repeat_weekly"),
            InlineKeyboardButton("🗓 Monthly", callback_data="repeat_monthly")
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_type")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🔄 *Repeating Reminder*\n\n"
        "How often should this reminder repeat?",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def back_to_repeat_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to repeat type selection"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [
            InlineKeyboardButton("📅 Daily", callback_data="repeat_daily"),
            InlineKeyboardButton("📆 Weekly", callback_data="repeat_weekly"),
            InlineKeyboardButton("🗓 Monthly", callback_data="repeat_monthly")
        ],
        [InlineKeyboardButton("🔧 Custom Period", callback_data="repeat_custom")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_type")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🔄 *Repeating Reminder*\n\n"
        "How often should this reminder repeat?",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    
    return REMINDER_TYPE

async def back_to_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to confirmation requirement selection"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Yes", callback_data="confirm_yes"),
            InlineKeyboardButton("❌ No", callback_data="confirm_no")
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_type")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_interactive")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    reminder_type = context.user_data.get('reminder_type', ReminderType.ONE_TIME)
    repeat_interval = context.user_data.get('repeat_interval')
    
    type_text = reminder_type.value.title()
    if repeat_interval:
        type_text += f" ({repeat_interval})"
    
    await query.edit_message_text(
        f"✅ Type: {type_text}\n\n"
        "*Step 5/6: Confirmation required?*\n\n"
        "Do you want this reminder to require confirmation before being marked as done?",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    
    return REMINDER_CONFIRMATION

async def start_interactive_reminder_from_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start interactive reminder creation from callback query"""
    return await start_interactive_reminder(update, context)

def get_interactive_reminder_handler():
    """Create and return the conversation handler for interactive reminders"""
    from src.handlers.reminder_handlers import add_reminder
    return ConversationHandler(
        entry_points=[
            CommandHandler("remind", add_reminder),
            CallbackQueryHandler(start_interactive_reminder_from_callback, pattern=r"^menu_new_reminder$")
        ],
        states={
            REMINDER_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, reminder_time_received)
            ],
            REMINDER_MESSAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, reminder_message_received)
            ],
            REMINDER_TAG_USERS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, reminder_tag_users_received),
                CallbackQueryHandler(skip_tagging, pattern=r"^skip_tagging$")
            ],
            REMINDER_TYPE: [
                CallbackQueryHandler(reminder_type_received, pattern=r"^type_"),
                CallbackQueryHandler(reminder_repeat_received, pattern=r"^repeat_"),
                CallbackQueryHandler(back_to_type, pattern=r"^back_to_type$")
            ],
            REMINDER_CONFIRMATION: [
                CallbackQueryHandler(reminder_confirmation_received, pattern=r"^confirm_"),
                CallbackQueryHandler(back_to_type, pattern=r"^back_to_type$"),
                CallbackQueryHandler(back_to_repeat, pattern=r"^back_to_repeat$"),
                CallbackQueryHandler(back_to_repeat_type, pattern=r"^back_to_repeat_type$")
            ],
            REMINDER_SNOOZE_DURATION: [
                CallbackQueryHandler(reminder_snooze_duration_received, pattern=r"^snooze_"),
                CallbackQueryHandler(back_to_confirm, pattern=r"^back_to_confirm$")
            ],
            REMINDER_CUSTOM_PERIOD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, reminder_custom_period_received),
                CallbackQueryHandler(back_to_repeat_type, pattern=r"^back_to_repeat_type$")
            ]
        },
        fallbacks=[
            CallbackQueryHandler(cancel_interactive, pattern=r"^cancel_interactive$"),
            CommandHandler('cancel', cancel_interactive)
        ]
    )