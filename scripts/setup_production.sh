#!/bin/bash
# Interactive production setup script for Telegram Reminder Bot

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
APP_DIR="/var/www/reminder_bot"
APP_USER="reminder_bot"
DB_NAME="reminder_bot"
DB_USER="reminder_bot"
PYTHON_VERSION="python3.11"

# Functions
print_header() {
    echo -e "\n${BLUE}======================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}======================================${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

check_root() {
    if [ "$EUID" -ne 0 ]; then 
        print_error "This script must be run as root"
        exit 1
    fi
}

check_os() {
    if ! command -v apt &> /dev/null; then
        print_error "This script is designed for Debian/Ubuntu systems"
        exit 1
    fi
}

confirm() {
    local prompt="$1"
    local default="${2:-n}"
    local REPLY
    
    if [ "$default" = "y" ]; then
        prompt="$prompt [Y/n]: "
    else
        prompt="$prompt [y/N]: "
    fi
    
    read -p "$prompt" REPLY
    REPLY=${REPLY:-$default}
    
    case "$REPLY" in
        [yY][eE][sS]|[yY]) return 0 ;;
        *) return 1 ;;
    esac
}

# Main setup process
main() {
    clear
    print_header "Telegram Reminder Bot - Production Setup"
    
    # Pre-flight checks
    check_root
    check_os
    
    # Get configuration
    echo "Let's configure your bot deployment..."
    echo
    
    # Bot token
    while true; do
        read -p "Enter your Telegram Bot Token: " BOT_TOKEN
        if [ -n "$BOT_TOKEN" ]; then
            break
        fi
        print_error "Bot token cannot be empty"
    done
    
    # Database password
    while true; do
        read -s -p "Enter database password for user '$DB_USER': " DB_PASSWORD
        echo
        read -s -p "Confirm database password: " DB_PASSWORD_CONFIRM
        echo
        if [ "$DB_PASSWORD" = "$DB_PASSWORD_CONFIRM" ] && [ -n "$DB_PASSWORD" ]; then
            break
        fi
        print_error "Passwords don't match or are empty"
    done
    
    # Timezone
    read -p "Enter default timezone (default: UTC): " TIMEZONE
    TIMEZONE=${TIMEZONE:-UTC}
    
    # Repository URL
    read -p "Enter your git repository URL (or press Enter to skip): " REPO_URL
    
    # Summary
    print_header "Configuration Summary"
    echo "Installation directory: $APP_DIR"
    echo "System user: $APP_USER"
    echo "Database name: $DB_NAME"
    echo "Database user: $DB_USER"
    echo "Default timezone: $TIMEZONE"
    echo "Repository: ${REPO_URL:-Manual upload required}"
    echo
    
    if ! confirm "Proceed with installation?"; then
        echo "Installation cancelled"
        exit 0
    fi
    
    # Step 1: System dependencies
    print_header "Step 1: Installing System Dependencies"
    
    # Fix potential repository issues
    apt-get update --allow-releaseinfo-change 2>/dev/null || apt update
    
    # Check Python version availability
    if ! apt-cache show $PYTHON_VERSION &>/dev/null; then
        print_warning "$PYTHON_VERSION not available, using python3"
        PYTHON_VERSION="python3"
    fi
    
    apt install -y \
        $PYTHON_VERSION \
        ${PYTHON_VERSION}-venv \
        python3-pip \
        postgresql \
        postgresql-contrib \
        git
    print_success "System dependencies installed"
    
    # Step 2: Create user
    print_header "Step 2: Creating System User"
    if id "$APP_USER" &>/dev/null; then
        print_warning "User $APP_USER already exists"
    else
        useradd -r -m -d "$APP_DIR" -s /bin/bash "$APP_USER"
        print_success "User $APP_USER created"
    fi
    
    # Step 3: PostgreSQL setup
    print_header "Step 3: Setting up PostgreSQL Database"
    sudo -u postgres psql <<EOF
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_user WHERE usename = '$DB_USER') THEN
        CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
    ELSE
        ALTER USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
    END IF;
END
\$\$;

SELECT 'CREATE DATABASE $DB_NAME OWNER $DB_USER'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB_NAME')\\gexec

GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;
EOF
    print_success "PostgreSQL database configured"
    
    # Step 4: Application setup
    print_header "Step 4: Setting up Application"
    
    # Clone or create directory
    if [ -n "$REPO_URL" ]; then
        if [ -d "$APP_DIR/.git" ]; then
            print_warning "Repository already exists, pulling latest changes"
            sudo -u "$APP_USER" bash -c "cd $APP_DIR && git pull"
        else
            print_warning "Cloning repository..."
            rm -rf "$APP_DIR"
            sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"
        fi
    else
        if [ ! -d "$APP_DIR" ]; then
            mkdir -p "$APP_DIR"
            chown "$APP_USER:$APP_USER" "$APP_DIR"
            print_warning "Created $APP_DIR - please upload your code manually"
        fi
    fi
    
    # Check if source code exists
    if [ ! -f "$APP_DIR/requirements.txt" ]; then
        print_error "No requirements.txt found in $APP_DIR"
        print_warning "Please upload your code to $APP_DIR and run this script again"
        exit 1
    fi
    
    # Setup Python environment
    print_header "Step 5: Setting up Python Environment"
    sudo -u "$APP_USER" bash -c "cd $APP_DIR && $PYTHON_VERSION -m venv venv"
    sudo -u "$APP_USER" bash -c "cd $APP_DIR && ./venv/bin/pip install --upgrade pip"
    sudo -u "$APP_USER" bash -c "cd $APP_DIR && ./venv/bin/pip install -r requirements.txt"
    print_success "Python environment configured"
    
    # Step 6: Environment configuration
    print_header "Step 6: Configuring Environment"
    DATABASE_URL="postgresql://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME"
    
    sudo -u "$APP_USER" bash -c "cat > $APP_DIR/.env << EOF
BOT_TOKEN=$BOT_TOKEN
DATABASE_URL=$DATABASE_URL
DEFAULT_TIMEZONE=$TIMEZONE
EOF"
    chmod 600 "$APP_DIR/.env"
    print_success "Environment configured"
    
    # Step 7: Initialize database
    print_header "Step 7: Initializing Database"
    if [ -f "$APP_DIR/setup_db.py" ]; then
        sudo -u "$APP_USER" bash -c "cd $APP_DIR && ./venv/bin/python setup_db.py"
        print_success "Database initialized"
    else
        print_warning "No setup_db.py found, skipping database initialization"
    fi
    
    # Step 8: Systemd service
    print_header "Step 8: Setting up Systemd Service"
    
    # Copy service file if exists, otherwise create it
    if [ -f "$APP_DIR/scripts/reminder-bot.service" ]; then
        cp "$APP_DIR/scripts/reminder-bot.service" /etc/systemd/system/
    else
        cat > /etc/systemd/system/reminder-bot.service << EOF
[Unit]
Description=Telegram Reminder Bot
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$APP_DIR
Environment="PYTHONPATH=$APP_DIR"
Environment="PATH=$APP_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStartPre=$APP_DIR/venv/bin/python $APP_DIR/setup_db.py
ExecStart=$APP_DIR/venv/bin/python -m src.bot
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=reminder-bot

# Security settings
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP_DIR

[Install]
WantedBy=multi-user.target
EOF
    fi
    
    systemctl daemon-reload
    systemctl enable reminder-bot
    systemctl start reminder-bot
    print_success "Systemd service configured and started"
    
    # Step 9: Setup scripts
    print_header "Step 9: Setting up Management Scripts"
    
    # Ensure scripts directory exists
    mkdir -p "$APP_DIR/scripts"
    chown -R "$APP_USER:$APP_USER" "$APP_DIR/scripts"
    
    # Copy or create scripts
    if [ -f "$APP_DIR/scripts/deploy.sh" ]; then
        chmod +x "$APP_DIR/scripts/deploy.sh"
    fi
    
    if [ -f "$APP_DIR/scripts/backup.sh" ]; then
        chmod +x "$APP_DIR/scripts/backup.sh"
    fi
    
    if [ -f "$APP_DIR/scripts/health_check.sh" ]; then
        chmod +x "$APP_DIR/scripts/health_check.sh"
    fi
    
    # Step 10: Cron jobs
    print_header "Step 10: Setting up Scheduled Tasks"
    
    if confirm "Set up automatic backups?" "y"; then
        (crontab -u "$APP_USER" -l 2>/dev/null || echo "") | \
        grep -v "$APP_DIR/scripts/backup.sh" | \
        { cat; echo "0 2 * * * $APP_DIR/scripts/backup.sh"; } | \
        crontab -u "$APP_USER" -
        print_success "Backup cron job configured"
    fi
    
    if confirm "Set up health checks?" "y"; then
        (crontab -u "$APP_USER" -l 2>/dev/null || echo "") | \
        grep -v "$APP_DIR/scripts/health_check.sh" | \
        { cat; echo "*/30 * * * * $APP_DIR/scripts/health_check.sh"; } | \
        crontab -u "$APP_USER" -
        print_success "Health check cron job configured"
    fi
    
    # Step 11: Firewall
    print_header "Step 11: Configuring Firewall"
    if command -v ufw &> /dev/null; then
        if confirm "Configure UFW firewall?" "y"; then
            ufw allow ssh
            ufw --force enable
            print_success "Firewall configured"
        fi
    fi
    
    # Final permissions
    chown -R "$APP_USER:$APP_USER" "$APP_DIR"
    chmod 700 "$APP_DIR"
    chmod 600 "$APP_DIR/.env"
    
    # Installation complete
    print_header "Installation Complete!"
    echo
    print_success "Bot is running as systemd service 'reminder-bot'"
    echo
    echo "Useful commands:"
    echo "  - Check status: sudo systemctl status reminder-bot"
    echo "  - View logs: sudo journalctl -u reminder-bot -f"
    echo "  - Restart bot: sudo systemctl restart reminder-bot"
    echo "  - Deploy updates: cd $APP_DIR && sudo ./scripts/deploy.sh"
    echo
    
    # Check service status
    if systemctl is-active --quiet reminder-bot; then
        print_success "Bot is running successfully!"
    else
        print_error "Bot service is not running. Check logs with: sudo journalctl -u reminder-bot -n 50"
    fi
}

# Run main function
main "$@"