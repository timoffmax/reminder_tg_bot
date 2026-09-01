# Telegram Reminder Bot

A feature-rich Telegram bot for managing reminders with support for personal and group chat reminders, timezone handling, confirmations, and recurring schedules.

## Features

- **Personal and Group Reminders**: Set reminders in private chats or group chats with user tagging
- **One-time and Repeating Reminders**: Daily, weekly, monthly, and custom repeat intervals with optional end dates
- **Interactive Creation**: Guided step-by-step reminder creation via `/remind` or the inline menu
- **Inline Mode**: Quick-create reminders from any chat: `@your_bot 5pm Buy milk`
- **Timezone Support**: Each user can set their own timezone for accurate scheduling
- **Natural Time Parsing**: `10:30`, `2h`, `tomorrow at 3pm`, `next monday at 10am`, `June 26 at 5PM`, and more
- **Snooze and Reschedule**: Smart snooze options and full rescheduling, including editing the schedule of a repeating series
- **Pause / Resume / Skip**: Pause a repeating series, resume it later, or skip a single occurrence
- **Confirmations**: Reminders can require explicit confirmation and re-send until confirmed
- **Quiet Hours**: Suppress notifications during configured hours
- **Lead-time Alerts**: Get an advance notification before the reminder fires
- **Search and Bulk Actions**: Find reminders by text and manage them in bulk
- **History Tracking**: Complete audit trail of reminder actions in PostgreSQL

## Installation

### Prerequisites

- Python 3.10+
- PostgreSQL database
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))

### Setup

1. Clone the repository:
```bash
git clone https://github.com/timoffmax/reminder_tg_bot.git
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

5. Set up the database:
```bash
# Creates the database (if missing) and all tables
python setup_db.py

# Stamp the schema so future migrations apply cleanly
alembic stamp head
```

6. Run the bot:
```bash
python -m src.bot
```

### Database Migrations

Schema *changes* are managed with Alembic, but the initial revision is empty, so
Alembic cannot build the schema from scratch. Step 5 above is therefore
mandatory: `setup_db.py` creates the tables and `alembic stamp head` records
that they are already up to date. Running `alembic upgrade head` on an
unstamped database fails with a duplicate-column error.

After pulling new code:

```bash
alembic upgrade head
```

To create a new migration after changing the models:

```bash
alembic revision --autogenerate -m "description"
```

Migrations run from a host checkout — the Docker image ships only `src/` and
`setup_db.py`, so `alembic` is not available inside the container.

### Docker Setup

A `Makefile` wraps the common Docker commands: `make start`, `make stop`, `make restart`, `make logs`, `make shell`, `make status`.

#### Option 1: Using Existing Local PostgreSQL
1. Create `.env` file with your local PostgreSQL settings:
```bash
cp .env.example .env
# Edit .env with your BOT_TOKEN and local DATABASE_URL
```

2. Run with Docker Compose:
```bash
docker-compose up -d   # or: make start
```

#### Option 2: Using Standalone PostgreSQL Container
If you prefer to run PostgreSQL in Docker on a different port:
```bash
# Set POSTGRES_PASSWORD in .env first
docker-compose -f docker-compose.standalone.yml up -d
# PostgreSQL listens on 127.0.0.1:5433 to avoid conflicts with a local instance
```

## Usage

### Commands

- `/start` - Initialize the bot and create your user profile
- `/menu` - Show the main menu (new reminder, list, timezone, quiet hours)
- `/remind` - Create a reminder: interactive mode without arguments, quick mode with arguments
- `/reminders` - List your active reminders with management buttons
- `/timezone` - Set your timezone
- `/snooze <id> [minutes]` - Snooze a reminder (default: 10 minutes)
- `/cancel <id>` - Cancel a reminder
- `/confirm <id>` - Confirm a reminder that requires confirmation
- `/help` - Show help message

### Quick Mode

```
/remind <time> [daily|weekly|monthly] [confirm] <message>
```

In quick mode the time must be a **single word** — everything after that first
word becomes the reminder text. Use interactive mode for multi-word times.

```
/remind 09:00 daily Take vitamins
/remind 2h Take a break
/remind 5pm Buy milk
/remind 10:30 confirm Call dentist
/remind 15m @john @jane Project review
```

### Interactive Mode

Send `/remind` with no arguments for guided step-by-step creation. Here the time
is entered on its own, so the full range of formats below is available.

### Managing Reminders

When a reminder fires, its message carries buttons to confirm, snooze (including
smart options like *Tomorrow 9am* and *Mon 9am*), reschedule, and view history.

The full management view — edit the message text, change the schedule,
pause/resume, skip the next occurrence, set an end date, and configure
lead-time alerts — is reached from `/reminders` by picking a reminder.

### Time Formats

Accepted anywhere a time is entered on its own (interactive mode, reschedule,
change schedule):

- **Specific time**: `10:30`, `10:30 PM`
- **Relative time**: `30m`, `2h`, `1d`, `1w`
- **Natural language**: `tomorrow at 3pm`, `next monday at 10am`
- **Dates**: `June 26 at 5PM`, `12.07.2025 14:00` (European), `12/7/25 2PM` (US)

In quick mode (`/remind <time> <message>`) only the single-word forms work:
`10:30`, `5pm`, `2h`, `30m`, `1d`, `1w`.

Add `daily`, `weekly` or `monthly` for a repeating reminder, and `confirm` to
require explicit confirmation.

## Architecture

- **Bot Core**: `src/bot.py` - Application entry point, handler registration, inline mode
- **Handlers**: `src/handlers/` - Command, callback, and interactive conversation handlers
- **Services**: `src/services/` - Business logic for reminders, users, and APScheduler-based scheduling
- **Models**: `src/models/` - SQLAlchemy models (User, Reminder, ReminderHistory)
- **Utils**: `src/utils/` - Timezone conversion and time parsing

All times are stored in UTC; the user's timezone is applied for display only. On startup the scheduler restores jobs for all active and snoozed reminders from the database.

## Configuration

Environment variables (see `.env.example`):

- `BOT_TOKEN`: Your Telegram bot token (required)
- `DATABASE_URL`: PostgreSQL connection string
- `DEFAULT_TIMEZONE`: Default timezone for new users (default: UTC)

## Deployment

See [.github/DEPLOYMENT.md](.github/DEPLOYMENT.md) for CI/CD notes and [bin/setup-server.md](bin/setup-server.md) for the SSH-based deploy scripts in `bin/`.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
