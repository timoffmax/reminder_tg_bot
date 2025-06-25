import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://user:password@localhost/reminder_bot')
DEFAULT_TIMEZONE = os.getenv('DEFAULT_TIMEZONE', 'UTC')

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")