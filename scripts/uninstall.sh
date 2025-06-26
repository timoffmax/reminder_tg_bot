#!/bin/bash
# Uninstall/cleanup script for Telegram Reminder Bot

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
SERVICE_NAME="reminder-bot"

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

main() {
    clear
    print_header "Telegram Reminder Bot - Uninstall/Cleanup"
    
    if [ "$EUID" -ne 0 ]; then 
        print_error "This script must be run as root"
        exit 1
    fi
    
    print_warning "This will remove the Telegram Reminder Bot installation"
    echo "The following will be removed:"
    echo "  - Systemd service: $SERVICE_NAME"
    echo "  - Application directory: $APP_DIR"
    echo "  - System user: $APP_USER"
    echo
    
    if confirm "Do you also want to remove the PostgreSQL database?" "n"; then
        REMOVE_DB=true
        echo "  - PostgreSQL database: $DB_NAME"
        echo "  - PostgreSQL user: $DB_USER"
    else
        REMOVE_DB=false
    fi
    
    echo
    if ! confirm "Are you sure you want to proceed?" "n"; then
        echo "Uninstall cancelled"
        exit 0
    fi
    
    # Backup reminder
    if confirm "Create a backup before uninstalling?" "y"; then
        BACKUP_DIR="/tmp/reminder_bot_final_backup_$(date +%Y%m%d_%H%M%S)"
        mkdir -p "$BACKUP_DIR"
        
        if [ -f "$APP_DIR/.env" ]; then
            cp "$APP_DIR/.env" "$BACKUP_DIR/"
            print_success "Environment file backed up to $BACKUP_DIR"
        fi
        
        if [ "$REMOVE_DB" = true ] && command -v pg_dump &> /dev/null; then
            if sudo -u postgres pg_dump "$DB_NAME" > "$BACKUP_DIR/database_backup.sql" 2>/dev/null; then
                print_success "Database backed up to $BACKUP_DIR/database_backup.sql"
            fi
        fi
    fi
    
    # Stop and disable service
    print_header "Stopping and Removing Service"
    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        systemctl stop "$SERVICE_NAME"
        print_success "Service stopped"
    fi
    
    if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
        systemctl disable "$SERVICE_NAME"
        print_success "Service disabled"
    fi
    
    if [ -f "/etc/systemd/system/$SERVICE_NAME.service" ]; then
        rm "/etc/systemd/system/$SERVICE_NAME.service"
        systemctl daemon-reload
        print_success "Service file removed"
    fi
    
    # Remove cron jobs
    print_header "Removing Scheduled Tasks"
    if crontab -u "$APP_USER" -l &>/dev/null; then
        crontab -u "$APP_USER" -r
        print_success "Cron jobs removed"
    fi
    
    # Remove application directory
    print_header "Removing Application Files"
    if [ -d "$APP_DIR" ]; then
        rm -rf "$APP_DIR"
        print_success "Application directory removed"
    fi
    
    # Remove user
    print_header "Removing System User"
    if id "$APP_USER" &>/dev/null; then
        userdel -r "$APP_USER" 2>/dev/null || userdel "$APP_USER"
        print_success "User $APP_USER removed"
    fi
    
    # Remove database (if requested)
    if [ "$REMOVE_DB" = true ]; then
        print_header "Removing PostgreSQL Database"
        sudo -u postgres psql <<EOF
DROP DATABASE IF EXISTS $DB_NAME;
DROP USER IF EXISTS $DB_USER;
EOF
        print_success "Database and user removed"
    fi
    
    print_header "Uninstall Complete"
    print_success "Telegram Reminder Bot has been removed"
    
    if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
        echo
        print_warning "Backup files saved to: $BACKUP_DIR"
    fi
}

main "$@"