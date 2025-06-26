#!/bin/bash
# Deployment script for Telegram Reminder Bot

set -e

echo "Starting deployment..."

# Pull latest changes
sudo -u reminder_bot git pull origin master

# Update dependencies
sudo -u reminder_bot /var/www/reminder_bot/venv/bin/pip install -r requirements.txt

# Run database migrations
sudo -u reminder_bot /var/www/reminder_bot/venv/bin/python setup_db.py

# Restart service
sudo systemctl restart reminder-bot

# Check service status
sudo systemctl status reminder-bot

echo "Deployment completed!"