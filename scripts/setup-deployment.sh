#!/bin/bash

# 🚀 Production Server Setup Script
# This script prepares your server for GitHub Actions deployment

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
DEFAULT_PROJECT_PATH="/home/$USER/reminder_tg_bot"
DEFAULT_GIT_REPO="https://github.com/yourusername/reminder_tg_bot.git"

print_header() {
    echo -e "${BLUE}"
    echo "=================================="
    echo "🤖 Reminder Bot Deployment Setup"
    echo "=================================="
    echo -e "${NC}"
}

print_step() {
    echo -e "${YELLOW}📋 $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Check if running as root
check_user() {
    if [ "$EUID" -eq 0 ]; then
        print_error "Please don't run this script as root. Use a regular user with sudo privileges."
        exit 1
    fi
}

# Install required packages
install_dependencies() {
    print_step "Installing required dependencies..."
    
    # Update package list
    sudo apt update
    
    # Install essential packages
    sudo apt install -y \
        git \
        python3 \
        python3-pip \
        python3-venv \
        curl \
        wget \
        unzip \
        htop \
        nano
    
    # Install Docker and Docker Compose
    if ! command -v docker &> /dev/null; then
        print_step "Installing Docker..."
        curl -fsSL https://get.docker.com -o get-docker.sh
        sudo sh get-docker.sh
        sudo usermod -aG docker $USER
        rm get-docker.sh
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        print_step "Installing Docker Compose..."
        sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
        sudo chmod +x /usr/local/bin/docker-compose
    fi
    
    print_success "Dependencies installed successfully"
}

# Setup project directory
setup_project() {
    print_step "Setting up project directory..."
    
    # Get project path from user
    echo -n "Enter project path [${DEFAULT_PROJECT_PATH}]: "
    read -r PROJECT_PATH
    PROJECT_PATH=${PROJECT_PATH:-$DEFAULT_PROJECT_PATH}
    
    # Get repository URL
    echo -n "Enter GitHub repository URL [${DEFAULT_GIT_REPO}]: "
    read -r GIT_REPO
    GIT_REPO=${GIT_REPO:-$DEFAULT_GIT_REPO}
    
    # Create and setup project directory
    mkdir -p "$PROJECT_PATH"
    cd "$PROJECT_PATH"
    
    # Clone repository if not already cloned
    if [ ! -d ".git" ]; then
        print_step "Cloning repository..."
        git clone "$GIT_REPO" .
    else
        print_info "Git repository already exists, pulling latest changes..."
        git pull origin main
    fi
    
    # Set up git configuration
    print_step "Configuring Git..."
    git config user.name "Production Server"
    git config user.email "server@$(hostname)"
    
    print_success "Project directory setup completed"
}

# Setup Python environment
setup_python() {
    print_step "Setting up Python environment..."
    
    cd "$PROJECT_PATH"
    
    # Create virtual environment if it doesn't exist
    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi
    
    # Activate virtual environment and install dependencies
    source venv/bin/activate
    
    if [ -f "requirements.txt" ]; then
        pip install --upgrade pip
        pip install -r requirements.txt
        print_success "Python dependencies installed"
    else
        print_info "No requirements.txt found, skipping Python dependencies"
    fi
    
    deactivate
}

# Setup commit tools
setup_commit_tools() {
    print_step "Setting up commit tools..."
    
    cd "$PROJECT_PATH"
    
    # Make commit tools executable
    if [ -f "bin/commit" ]; then
        chmod +x bin/commit
        print_success "bin/commit is now executable"
    else
        print_info "bin/commit not found yet - will be set up during deployment"
    fi
    
    if [ -f "tools/git/commit" ]; then
        chmod +x tools/git/commit
        print_success "tools/git/commit is now executable"
    else
        print_info "tools/git/commit not found yet - will be set up during deployment"
    fi
}

# Setup SSH keys for GitHub Actions
setup_ssh_keys() {
    print_step "Setting up SSH keys for GitHub Actions..."
    
    echo -e "${YELLOW}To complete the setup, you need to:"
    echo "1. Generate SSH keys for GitHub Actions deployment"
    echo "2. Add the public key to this server"
    echo "3. Add the private key to GitHub Secrets${NC}"
    echo
    
    echo -n "Do you want to generate SSH keys now? (y/N): "
    read -r GENERATE_KEYS
    
    if [[ $GENERATE_KEYS =~ ^[Yy]$ ]]; then
        SSH_KEY_PATH="$HOME/.ssh/github_deploy_key"
        
        # Generate SSH key pair
        ssh-keygen -t ed25519 -C "github-actions-deployment-$(hostname)" -f "$SSH_KEY_PATH" -N ""
        
        # Add public key to authorized_keys
        cat "${SSH_KEY_PATH}.pub" >> "$HOME/.ssh/authorized_keys"
        chmod 600 "$HOME/.ssh/authorized_keys"
        
        print_success "SSH keys generated!"
        print_info "Public key added to authorized_keys"
        
        echo
        print_step "Next steps:"
        echo "1. Copy this PRIVATE key to GitHub Secrets (SSH_PRIVATE_KEY):"
        echo -e "${BLUE}$(cat $SSH_KEY_PATH)${NC}"
        echo
        echo "2. Add these GitHub Secrets:"
        echo "   - SSH_PRIVATE_KEY: (the private key above)"
        echo "   - SERVER_HOST: $(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
        echo "   - SERVER_USER: $USER"
        echo "   - PROJECT_PATH: $PROJECT_PATH"
        echo
    else
        print_info "Skipping SSH key generation"
        echo "You'll need to set up SSH keys manually for GitHub Actions"
    fi
}

# Create systemd service for the bot
setup_service() {
    print_step "Setting up systemd service for the bot..."
    
    echo -n "Do you want to create a systemd service for the bot? (Y/n): "
    read -r CREATE_SERVICE
    CREATE_SERVICE=${CREATE_SERVICE:-Y}
    
    if [[ $CREATE_SERVICE =~ ^[Yy]$ ]]; then
        SERVICE_NAME="reminder-tg-bot"
        SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
        TEMPLATE_FILE="$PROJECT_PATH/scripts/reminder-tg-bot.service"
        
        # Determine Python path
        if [ -d "$PROJECT_PATH/venv" ]; then
            PYTHON_PATH="$PROJECT_PATH/venv/bin/python"
        else
            PYTHON_PATH="/usr/bin/python3"
        fi
        
        # Create service file from template if it exists
        if [ -f "$TEMPLATE_FILE" ]; then
            print_step "Creating service from template..."
            # Replace placeholders in template
            sudo sed -e "s|%REPLACE_USER%|$USER|g" \
                     -e "s|%REPLACE_PROJECT_PATH%|$PROJECT_PATH|g" \
                     -e "s|%REPLACE_PYTHON_PATH%|$PYTHON_PATH|g" \
                     "$TEMPLATE_FILE" > /tmp/reminder-tg-bot.service
            sudo mv /tmp/reminder-tg-bot.service "$SERVICE_FILE"
        else
            # Create basic service file
            print_step "Creating basic service file..."
            sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=Reminder Telegram Bot
After=network.target
Wants=network.target

[Service]
Type=simple
User=$USER
Group=$USER
WorkingDirectory=$PROJECT_PATH
Environment=PATH=$PROJECT_PATH/venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONPATH=$PROJECT_PATH/src
Environment=PYTHONUNBUFFERED=1
ExecStart=$PYTHON_PATH $PROJECT_PATH/src/bot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=reminder-tg-bot

# Security settings
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$PROJECT_PATH

# Environment file for configuration
EnvironmentFile=-$PROJECT_PATH/.env

[Install]
WantedBy=multi-user.target
EOF
        fi
        
        # Set proper permissions
        sudo chmod 644 "$SERVICE_FILE"
        
        # Reload systemd and enable service
        sudo systemctl daemon-reload
        sudo systemctl enable "$SERVICE_NAME"
        
        print_success "Systemd service created and enabled: $SERVICE_NAME"
        print_info "Service file: $SERVICE_FILE"
        
        # Ask if user wants to start the service now
        echo -n "Do you want to start the bot service now? (y/N): "
        read -r START_NOW
        
        if [[ $START_NOW =~ ^[Yy]$ ]]; then
            # Check if .env file exists
            if [ ! -f "$PROJECT_PATH/.env" ]; then
                print_info "Creating example .env file..."
                create_env_file
            fi
            
            sudo systemctl start "$SERVICE_NAME"
            sleep 2
            
            if systemctl is-active --quiet "$SERVICE_NAME"; then
                print_success "Bot service started successfully!"
                print_info "Check status: sudo systemctl status $SERVICE_NAME"
                print_info "View logs: sudo journalctl -u $SERVICE_NAME -f"
            else
                print_error "Failed to start bot service"
                print_info "Check logs: sudo journalctl -u $SERVICE_NAME -n 20"
            fi
        else
            print_info "Service created but not started"
            print_info "To start: sudo systemctl start $SERVICE_NAME"
        fi
        
        print_info "Service management commands:"
        echo "  Start:   sudo systemctl start $SERVICE_NAME"
        echo "  Stop:    sudo systemctl stop $SERVICE_NAME"
        echo "  Restart: sudo systemctl restart $SERVICE_NAME"
        echo "  Status:  sudo systemctl status $SERVICE_NAME"
        echo "  Logs:    sudo journalctl -u $SERVICE_NAME -f"
        
    else
        print_info "Skipping systemd service creation"
    fi
}

# Create example environment file
create_env_file() {
    ENV_FILE="$PROJECT_PATH/.env"
    
    if [ ! -f "$ENV_FILE" ]; then
        print_step "Creating example .env file..."
        
        cat > "$ENV_FILE" << 'EOF'
# Telegram Bot Configuration
BOT_TOKEN=your_bot_token_here

# Database Configuration (if using PostgreSQL)
# DATABASE_URL=postgresql://user:password@localhost:5432/reminder_bot
# DB_HOST=localhost
# DB_PORT=5432
# DB_NAME=reminder_bot
# DB_USER=your_db_user
# DB_PASSWORD=your_db_password

# SQLite Database (default)
DATABASE_URL=sqlite:///reminder_bot.db

# Logging Configuration
LOG_LEVEL=INFO

# Application Settings
TIMEZONE=UTC
EOF
        
        # Set secure permissions
        chmod 600 "$ENV_FILE"
        
        print_success "Example .env file created: $ENV_FILE"
        print_info "⚠️  Please edit the .env file with your actual configuration!"
        print_info "⚠️  Especially set your BOT_TOKEN from @BotFather"
    fi
}

# Main execution
main() {
    print_header
    
    check_user
    install_dependencies
    setup_project
    setup_python
    setup_commit_tools
    setup_ssh_keys
    setup_service
    
    echo
    print_success "🎉 Server setup completed!"
    print_info "Your server is now ready for GitHub Actions deployment"
    
    echo
    print_step "Final checklist:"
    echo "✅ Dependencies installed"
    echo "✅ Project directory set up"
    echo "✅ Python environment configured"
    echo "✅ Commit tools permissions set"
    echo "📋 SSH keys generated (add to GitHub Secrets)"
    echo "📋 Configure GitHub Secrets in your repository"
    
    echo
    print_info "Project location: $PROJECT_PATH"
    print_info "Test deployment by pushing to your main branch!"
}

# Run main function
main "$@"