#!/bin/bash
# Health check script for Telegram Reminder Bot

# Check if service is active
if ! systemctl is-active --quiet reminder-bot; then
    echo "ERROR: reminder-bot service is not running"
    # Optionally send alert or restart
    sudo systemctl restart reminder-bot
    exit 1
fi

# Check database connection
if ! sudo -u reminder_bot /var/www/reminder_tg_bot/venv/bin/python -c "
import os
import psycopg2
from urllib.parse import urlparse
url = urlparse(os.getenv('DATABASE_URL'))
conn = psycopg2.connect(
    database=url.path[1:],
    user=url.username,
    password=url.password,
    host=url.hostname,
    port=url.port
)
conn.close()
" 2>/dev/null; then
    echo "ERROR: Database connection failed"
    exit 1
fi

echo "OK: All health checks passed"
