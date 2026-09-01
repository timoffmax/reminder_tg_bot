# Reminder Bot CI/CD Deployment Setup

## How Deployment Works

Production deployment is handled by [`.github/workflows/deploy.yml`](workflows/deploy.yml). It runs on a **self-hosted GitHub Actions runner** installed on the production server itself, so no SSH secrets are required — the workflow operates on the production directory on that same host.

- **Trigger**: push to `master` (only for changes under `src/`, `requirements.txt`, `pyproject.toml`, `docker-compose.yml`, `Dockerfile`, `setup_db.py`), or manually via *Actions → Deploy Reminder Bot to Production → Run workflow* (with an optional `restart_only` input)
- **Service**: the bot runs as a systemd service (default name: `reminder-bot`)
- **Steps**: stop service → backup current version → `git reset --hard origin/master` → update dependencies → run `setup_db.py` → fix permissions → start and enable service → verify

> **Before first use, edit the workflow to match your server.** `deploy.yml` hardcodes `PROJECT_PATH="/var/www/reminder_tg_bot"` and the OS user `reminder_bot` (used for `pip`, `setup_db.py` and `chown`); `scripts/reminder-bot.service` hardcodes the same path. Change all of them together, or use the paths below consistently.

An alternative push-based deploy over SSH (no runner required) is available via the scripts in `bin/` — see [bin/setup-server.md](../bin/setup-server.md).

> **Security note for public forks**: self-hosted runners should never be exposed to workflows triggered by untrusted contributors. Keep *Settings → Actions → General* configured to require approval for outside collaborators, and restrict which workflows may run on the self-hosted runner.

## Server Setup

### Step 1: Prepare the Server

```bash
# Create project directory (adjust to taste)
sudo mkdir -p /opt/reminder_tg_bot
cd /opt/reminder_tg_bot

# Clone the repository
git clone https://github.com/timoffmax/reminder_tg_bot.git .

# Create a virtual environment and install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env: set BOT_TOKEN and DATABASE_URL

# Create the schema, then mark it as up to date for Alembic
python setup_db.py
alembic stamp head
```

The `alembic stamp head` step is required: the initial migration is empty, so an
unstamped database breaks the first `alembic upgrade head` that `bin/deploy` runs.

### Step 2: Create the systemd Service

Use `scripts/reminder-bot.service` as a template, adjust paths and user, then:

```bash
sudo cp scripts/reminder-bot.service /etc/systemd/system/reminder-bot.service
sudo systemctl daemon-reload
sudo systemctl enable reminder-bot
sudo systemctl start reminder-bot
```

### Step 3: Install the Self-hosted Runner (optional)

Follow GitHub's instructions under *Settings → Actions → Runners → New self-hosted runner*. The runner user needs passwordless sudo for the specific `systemctl` commands used by the workflow (see the sudoers example in [bin/setup-server.md](../bin/setup-server.md)) — grant the narrowest set of commands possible, not blanket `systemctl` access.

## Service Management

```bash
sudo systemctl start reminder-bot     # Start the bot
sudo systemctl stop reminder-bot      # Stop the bot
sudo systemctl restart reminder-bot   # Restart the bot
sudo systemctl status reminder-bot    # Check status
sudo journalctl -u reminder-bot -f    # View live logs
```

## Troubleshooting

**Deployment failed**

1. Check GitHub Actions logs: *Actions* tab in the repository
2. SSH into the server and diagnose:
   ```bash
   cd /path/to/your/project

   # Check git status
   git status
   git log --oneline -5

   # Check bot service
   sudo systemctl status reminder-bot
   sudo journalctl -u reminder-bot -n 50

   # Test the bot manually
   source venv/bin/activate
   python -m src.bot
   ```

**Common fixes**

```bash
# Reload systemd after unit changes
sudo systemctl daemon-reload
sudo systemctl enable reminder-bot

# Reset git state
git reset --hard HEAD
git clean -fd

# Reinstall dependencies
pip install -r requirements.txt --force-reinstall

# Re-run database setup, then migrations.
# On a database created by setup_db.py that was never stamped, run
# `alembic stamp head` instead of `upgrade head` (see Server Setup).
python setup_db.py
alembic upgrade head
```

**Environment configuration**

```bash
# Check that .env exists and BOT_TOKEN is set
ls -la .env
grep -c BOT_TOKEN .env
```
