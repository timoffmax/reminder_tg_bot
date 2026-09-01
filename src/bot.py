import logging
from uuid import uuid4
from telegram import Update, BotCommand, MenuButtonCommands, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
    InlineQueryHandler,
    ChosenInlineResultHandler,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.config import BOT_TOKEN
from src.database import init_db, SessionLocal
from src.services.user_service import UserService
from src.services.reminder_service import ReminderService
from src.models.reminder import ReminderType
from src.utils.timezone_utils import parse_time_input, parse_recurring_pattern, convert_to_user_timezone
from src.handlers.basic_handlers import (
    start,
    help_command,
    set_timezone,
    menu,
    handle_custom_reschedule_time,
    handle_edit_message_text,
    handle_search_query,
    handle_quiet_hours_input,
    handle_repeat_until_input,
    handle_change_schedule_input,
)
from src.handlers.reminder_handlers import (
    add_reminder, list_reminders, snooze_reminder, 
    cancel_reminder, confirm_reminder
)
from src.handlers.callback_handlers import handle_callback
from src.handlers.interactive_handlers import get_interactive_reminder_handler
from src.services.scheduler_service import SchedulerService

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    # Handle common Telegram errors gracefully
    if "Message is not modified" in str(context.error):
        if hasattr(update, 'callback_query') and update.callback_query:
            try:
                await update.callback_query.answer("✅ No changes to update!")
            except:
                pass
    elif "Bad Request" in str(context.error):
        if hasattr(update, 'callback_query') and update.callback_query:
            try:
                await update.callback_query.answer("❌ Invalid request")
            except:
                pass

INLINE_CREATE_ID = "create-reminder"

def _parse_inline_query(text: str, user_timezone: str):
    """Parse an inline query into (scheduled_time, message, repeat_interval).

    Returns None when the query is incomplete or the time cannot be parsed.
    The time is the first word only, matching quick-mode /remind.
    """
    result = None
    parts = text.split(' ', 1)

    if len(parts) == 2:
        time_part, message = parts
        cleaned, repeat_interval = parse_recurring_pattern(time_part)
        scheduled_time = parse_time_input(cleaned, user_timezone)

        if (scheduled_time and message.strip()):
            result = (scheduled_time, message.strip(), repeat_interval)

    return result

async def handle_inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inline-mode entry point: preview the reminder that '<time> <message>' would create.

    This only renders a preview. Telegram fires an inline query on every keystroke,
    so the reminder itself is created in handle_chosen_inline_result once the user
    actually picks the result.
    """
    query = update.inline_query
    if not query:
        return

    user_id = query.from_user.id
    text = (query.query or "").strip()

    results = []

    if not text:
        results.append(
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="Type: <time> <message>",
                description="e.g. 5pm Buy milk, 2h call mom, 09:00 Standup",
                input_message_content=InputTextMessageContent("Open the bot and use /remind to create a reminder."),
            )
        )
        await query.answer(results, cache_time=1, is_personal=True)
        return

    with SessionLocal() as db:
        user_timezone = UserService(db).get_user_timezone(user_id)

    parsed = _parse_inline_query(text, user_timezone)

    if parsed is None:
        results.append(
            InlineQueryResultArticle(
                id=str(uuid4()),
                title="❌ Need a time followed by a message",
                description="The time must be one word, e.g. 5pm Buy milk",
                input_message_content=InputTextMessageContent(
                    "Couldn't parse that. Use a one-word time then the message, e.g. `5pm Buy milk`."
                ),
            )
        )
        await query.answer(results, cache_time=1, is_personal=True)
        return

    scheduled_time, message, _ = parsed
    user_time = convert_to_user_timezone(scheduled_time, user_timezone)
    confirmation = f"✅ Reminder scheduled for {user_time.strftime('%Y-%m-%d %H:%M')} ({user_timezone}): {message}"

    results.append(
        InlineQueryResultArticle(
            id=INLINE_CREATE_ID,
            title=f"⏰ {message}",
            description=f"{user_time.strftime('%Y-%m-%d %H:%M')} ({user_timezone})",
            input_message_content=InputTextMessageContent(confirmation),
        )
    )

    await query.answer(results, cache_time=0, is_personal=True)

async def handle_chosen_inline_result(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Create the reminder once the user actually picks the inline result."""
    chosen = update.chosen_inline_result

    if ((not chosen) or (chosen.result_id != INLINE_CREATE_ID)):
        return

    user_id = chosen.from_user.id
    text = (chosen.query or "").strip()

    with SessionLocal() as db:
        user_timezone = UserService(db).get_user_timezone(user_id)
        parsed = _parse_inline_query(text, user_timezone)

        if parsed is None:
            return

        scheduled_time, message, repeat_interval = parsed
        reminder_service = ReminderService(db)
        reminder = reminder_service.create_reminder(
            user_id=user_id,
            chat_id=user_id,  # private chat with the user
            chat_title=None,
            message_text=message,
            scheduled_time=scheduled_time,
            reminder_type=ReminderType.REPEATING if repeat_interval else ReminderType.ONE_TIME,
            requires_confirmation=False,
            tagged_users=[],
            repeat_interval=repeat_interval,
        )

        scheduler_service = context.bot_data.get('scheduler_service')

        if scheduler_service:
            scheduler_service.schedule_reminder(reminder)

        reminder_id = reminder.id

    logger.info(f"Inline reminder {reminder_id} created for user {user_id}")


async def setup_bot_menu(bot):
    """Set up bot commands and menu button"""
    commands = [
        BotCommand("start", "Start the bot and get welcome message"),
        BotCommand("menu", "Show main menu"),
        BotCommand("remind", "Create a new reminder"),
        BotCommand("reminders", "List all your reminders"),
        BotCommand("timezone", "Set your timezone"),
        BotCommand("help", "Show help information"),
    ]
    
    await bot.set_my_commands(commands)
    
    # Set menu button that opens the commands menu
    menu_button = MenuButtonCommands()
    await bot.set_chat_menu_button(menu_button=menu_button)
    
    logger.info("Bot menu and commands configured")

async def post_init(application: Application) -> None:
    """Initialize scheduler after the application starts"""
    scheduler = AsyncIOScheduler()
    scheduler_service = SchedulerService(scheduler, application.bot)
    application.bot_data['scheduler_service'] = scheduler_service
    
    # Start the scheduler
    scheduler.start()
    logger.info("Scheduler started")
    
    # Set up bot commands and menu button
    await setup_bot_menu(application.bot)

def main():
    init_db()
    
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    # Basic commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("timezone", set_timezone))
    application.add_handler(CommandHandler("menu", menu))
    
    # Interactive reminder handler with /remind as entry point
    interactive_handler = get_interactive_reminder_handler()
    application.add_handler(interactive_handler)
    application.add_handler(CommandHandler("reminders", list_reminders))
    application.add_handler(CommandHandler("snooze", snooze_reminder))
    application.add_handler(CommandHandler("cancel", cancel_reminder))
    application.add_handler(CommandHandler("confirm", confirm_reminder))
    
    # Callback handlers
    application.add_handler(CallbackQueryHandler(handle_callback))

    # Inline query handler — quick-create reminders from any chat: @bot 5pm meeting.
    # The query handler only previews; ChosenInlineResultHandler does the creating.
    application.add_handler(InlineQueryHandler(handle_inline_query))
    application.add_handler(ChosenInlineResultHandler(handle_chosen_inline_result))
    
    # Message handler for stateful flows awaiting text input
    async def dispatch_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Route text messages to whichever action is awaiting input."""
        if await handle_custom_reschedule_time(update, context):
            return
        if await handle_edit_message_text(update, context):
            return
        if await handle_search_query(update, context):
            return
        if await handle_quiet_hours_input(update, context):
            return
        if await handle_repeat_until_input(update, context):
            return
        if await handle_change_schedule_input(update, context):
            return

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, dispatch_text_input))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    logger.info("Bot started")
    application.run_polling()

if __name__ == '__main__':
    main()
