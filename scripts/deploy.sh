#!/bin/bash
# Deployment script for Telegram Reminder Bot

set -e

echo "Starting deployment..."

# Get the current directory (should be the app directory)
APP_DIR=$(pwd)

# Pull latest changes as the user who owns the repository
git pull origin master

# Update dependencies as reminder_bot user
sudo -u reminder_bot $APP_DIR/venv/bin/pip install -r requirements.txt

# Run database migrations as reminder_bot user
echo "[INFO] Running database migrations..."
if sudo -u reminder_bot $APP_DIR/venv/bin/alembic upgrade head 2>/dev/null; then
    echo "[SUCCESS] Database migrations completed"
else
    echo "[INFO] Setting up Alembic for existing database..."
    if sudo -u reminder_bot $APP_DIR/venv/bin/python $APP_DIR/scripts/setup_alembic.py; then
        echo "[SUCCESS] Alembic setup completed"
    else
        echo "[WARNING] Alembic setup failed, falling back to manual setup"
        # Fallback to setup_db.py for initial setup
        sudo -u reminder_bot $APP_DIR/venv/bin/python setup_db.py
    fi
fi

# Fix permissions
sudo chown -R reminder_bot:reminder_bot $APP_DIR

# Restart service
sudo systemctl restart reminder-bot

# Check service status
sudo systemctl status reminder-bot

echo "Deployment completed!"