import logging
from telegram import Update, BotCommand, MenuButtonCommands
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.config import BOT_TOKEN
from src.database import init_db
from src.handlers.basic_handlers import start, help_command, set_timezone, menu, handle_custom_reschedule_time, handle_edit_message_text
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
    
    # Message handler for stateful flows awaiting text input
    async def dispatch_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Route text messages to whichever action is awaiting input."""
        if await handle_custom_reschedule_time(update, context):
            return
        if await handle_edit_message_text(update, context):
            return

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, dispatch_text_input))
    
    # Error handler
    application.add_error_handler(error_handler)
    
    logger.info("Bot started")
    application.run_polling()

if __name__ == '__main__':
    main()