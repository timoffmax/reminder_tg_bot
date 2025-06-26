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
sudo -u reminder_bot $APP_DIR/venv/bin/python setup_db.py

# Fix permissions
sudo chown -R reminder_bot:reminder_bot $APP_DIR

# Restart service
sudo systemctl restart reminder-bot

# Check service status
sudo systemctl status reminder-bot

echo "Deployment completed!"