# Telegram Reminder Bot

A feature-rich Telegram bot for managing reminders with support for personal and group chat reminders, timezone handling, confirmations, and recurring reminders.

## Features

- **Personal and Group Reminders**: Set reminders in private chats or group chats with user tagging
- **One-time and Repeating Reminders**: Support for daily, weekly, and monthly recurring reminders
- **Timezone Support**: Each user can set their own timezone for accurate scheduling
- **Snooze Functionality**: Snooze reminders for custom durations
- **Confirmation Required**: Set reminders that require user confirmation before completion
- **Reminder Management**: List, cancel, and view history of reminders
- **PostgreSQL Database**: Robust data storage with full history tracking
- **Automatic Database Setup**: Creates database and tables automatically if they don't exist

## Installation

### Prerequisites

- Python 3.10+
- PostgreSQL database
- Telegram Bot Token (from @BotFather)

### Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd reminder_tg_bot
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your BOT_TOKEN and DATABASE_URL
```

5. Set up database (automatic):
```bash
# The bot will automatically create the database if it doesn't exist
# Or run manually:
python setup_db.py
```

6. Run the bot:
```bash
python -m src.bot
```

### Docker Setup

#### Option 1: Using Existing Local PostgreSQL
1. Create `.env` file with your local PostgreSQL settings:
```bash
cp .env.example .env
# Edit .env with your BOT_TOKEN and local DATABASE_URL
```

2. Run with Docker Compose:
```bash
docker-compose up -d
```

#### Option 2: Using Standalone PostgreSQL Container
If you prefer to run PostgreSQL in Docker on a different port:
```bash
docker-compose -f docker-compose.standalone.yml up -d
# This uses port 5433 to avoid conflicts with your local PostgreSQL
```

## Usage

### Basic Commands

- `/start` - Initialize the bot and create user profile
- `/help` - Show help message with all commands
- `/timezone` - Set your timezone

### Reminder Commands

- `/remind <time> <message>` - Create a basic reminder
- `/remind <time> daily <message>` - Create daily recurring reminder
- `/remind <time> weekly <message>` - Create weekly recurring reminder
- `/remind <time> monthly <message>` - Create monthly recurring reminder
- `/remind <time> confirm <message>` - Create reminder requiring confirmation

### Management Commands

- `/reminders` - List all active reminders
- `/snooze <id> [minutes]` - Snooze a reminder (default: 10 minutes)
- `/cancel <id>` - Cancel a reminder
- `/confirm <id>` - Confirm a reminder that requires confirmation

### Time Formats

- **Specific time**: `10:30`, `14:00`
- **Relative time**: `30m`, `2h`, `1d`, `1w`
- **Combined**: Any of the above with `daily`, `weekly`, `monthly`, `confirm`

### Examples

```
/remind 09:00 daily Take vitamins
/remind 2h Take a break
/remind 10:30 confirm Call dentist
/remind 1d weekly Team meeting
/remind 15m @john @jane Project review
```

## Database Schema

### Users Table
- Stores user information and timezone preferences
- Links Telegram user ID to bot settings

### Reminders Table
- Main reminder data with scheduling information
- Supports one-time and repeating reminders
- Tracks confirmation status and snooze count

### Reminder History Table
- Complete audit trail of all reminder actions
- Tracks creation, completion, snoozing, confirmation, etc.

## Architecture

- **Bot Core**: `src/bot.py` - Main application and handler registration
- **Handlers**: Command and callback handlers for user interactions
- **Services**: Business logic for reminders, users, and scheduling
- **Models**: Database models using SQLAlchemy
- **Utils**: Timezone handling and time parsing utilities

## Configuration

Environment variables:

- `BOT_TOKEN`: Your Telegram bot token
- `DATABASE_URL`: PostgreSQL connection string
- `DEFAULT_TIMEZONE`: Default timezone for new users (default: UTC)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License.