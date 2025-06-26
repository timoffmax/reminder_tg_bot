# 🤖 Reminder Bot CI/CD Deployment Setup

## Required GitHub Secrets

### Production Environment
Go to your GitHub repository → Settings → Secrets and variables → Actions → New repository secret

Add these secrets for **production** deployment:

| Secret Name | Description | Example |
|-------------|-------------|---------|
| `SSH_PRIVATE_KEY` | Private SSH key for server access | `-----BEGIN OPENSSH PRIVATE KEY-----\n...` |
| `SERVER_HOST` | Production server hostname/IP | `your-server.com` or `123.456.789.012` |
| `SERVER_USER` | SSH username for production server | `ubuntu`, `root`, or your username |
| `PROJECT_PATH` | Full path to project on production server | `/home/ubuntu/reminder_tg_bot` |

### Development Environment (Optional)
For development server deployment, add these additional secrets:

| Secret Name | Description | Example |
|-------------|-------------|---------|
| `DEV_SSH_PRIVATE_KEY` | Private SSH key for dev server | `-----BEGIN OPENSSH PRIVATE KEY-----\n...` |
| `DEV_SERVER_HOST` | Development server hostname/IP | `dev-server.com` |
| `DEV_SERVER_USER` | SSH username for dev server | `ubuntu` |
| `DEV_PROJECT_PATH` | Full path to project on dev server | `/home/ubuntu/reminder_tg_bot-dev` |

## 🔧 Server Setup Instructions

### Step 1: Generate SSH Keys
On your local machine:
```bash
# Generate SSH key pair for deployment
ssh-keygen -t ed25519 -C "github-actions-deployment" -f ~/.ssh/github_deploy_key

# Copy public key to server
ssh-copy-id -i ~/.ssh/github_deploy_key.pub user@your-server.com

# Copy private key content for GitHub secret
cat ~/.ssh/github_deploy_key
```

### Step 2: Prepare Production Server
SSH into your production server and run:
```bash
# Create project directory
mkdir -p /path/to/your/reminder_tg_bot
cd /path/to/your/reminder_tg_bot

# Clone your repository
git clone https://github.com/yourusername/reminder_tg_bot.git .

# Set up git configuration
git config user.name "Production Server"
git config user.email "server@yourdomain.com"

# Install Python dependencies
pip3 install -r requirements.txt

# Make sure Docker is installed (if using docker-compose)
docker --version
docker-compose --version
```

### Step 3: Configure GitHub Environments
1. Go to your repo → Settings → Environments
2. Create environments:
   - **production** (with protection rules)
   - **development** (optional)
3. Add environment-specific secrets to each environment

## 🚦 Deployment Triggers

### Automatic Deployments
- **Production**: Triggers on push to `main` branch
- **Development**: Triggers on push to `develop` or `dev` branch
- **Pull Requests**: Runs dev deployment for testing

### Manual Deployments
You can trigger deployments manually:
1. Go to Actions tab in your GitHub repository
2. Choose "Deploy to Production" or "Deploy to Development"
3. Click "Run workflow"
4. Optionally check "Force deployment" to deploy even without changes

## 📁 What Gets Deployed

The deployment includes:
- 🤖 **Bot Source Code**: Complete `src/` directory with all handlers, services, and models
- 🗄️ **Database Setup**: Automatic database initialization and migrations
- 📦 **Dependencies**: Python packages from `requirements.txt`
- ⚙️ **Configuration**: Environment variables and settings
- 🔧 **Service Management**: Systemd service creation and management
- 🛠️ **Development Tools**: Commit tools (`bin/` and `tools/` directories)

## 🔍 Deployment Process

1. **🛑 Stop Service**: Gracefully stops the running bot service
2. **💾 Backup**: Creates backup of current version for rollback
3. **📥 Pull Code**: Fetches latest code from repository
4. **📦 Dependencies**: Updates Python packages and virtual environment
5. **🗄️ Database**: Runs database setup/migrations if needed
6. **🚀 Start Service**: Starts the bot as a systemd service
7. **✅ Verify**: Tests bot service status and database connectivity
8. **📝 Logs**: Provides service logs for monitoring

## 🎯 Service Management

The bot runs as a systemd service called `reminder-tg-bot`:

```bash
# Service commands on your server
sudo systemctl start reminder-tg-bot     # Start the bot
sudo systemctl stop reminder-tg-bot      # Stop the bot
sudo systemctl restart reminder-tg-bot   # Restart the bot
sudo systemctl status reminder-tg-bot    # Check status
sudo journalctl -u reminder-tg-bot -f    # View live logs
```

## 🛠️ Troubleshooting

### Common Issues:

**SSH Connection Failed**
```bash
# Test SSH connection manually
ssh -i ~/.ssh/github_deploy_key user@your-server.com

# Check if key is added to server
ssh user@your-server.com "cat ~/.ssh/authorized_keys"
```

**Permission Denied**
```bash
# On server, check project directory permissions
ls -la /path/to/your/project
sudo chown -R $USER:$USER /path/to/your/project
```

**Docker Issues**
```bash
# On server, check Docker status
sudo systemctl status docker
docker-compose ps
```

**Git Issues**
```bash
# On server, reset git state
cd /path/to/your/project
git status
git reset --hard HEAD
```

## 📞 Support

If deployment fails:

1. **Check GitHub Actions logs**: Go to Actions tab in your repository

2. **SSH into server and diagnose**:
   ```bash
   cd /path/to/your/project
   
   # Check git status
   git status
   git log --oneline -5
   
   # Check bot service
   sudo systemctl status reminder-tg-bot
   sudo journalctl -u reminder-tg-bot -n 50
   
   # Check bot configuration
   cat .env  # (make sure BOT_TOKEN is set)
   
   # Test bot manually
   source venv/bin/activate  # if using venv
   python src/bot.py
   ```

3. **Common fixes**:
   ```bash
   # Fix service permissions
   sudo systemctl daemon-reload
   sudo systemctl enable reminder-tg-bot
   
   # Reset git state
   git reset --hard HEAD
   git clean -fd
   
   # Reinstall dependencies
   pip install -r requirements.txt --force-reinstall
   
   # Check database
   python setup_db.py
   ```

4. **Environment Configuration**: Ensure `.env` file has correct values:
   ```bash
   # Check if .env exists and has BOT_TOKEN
   ls -la .env
   grep BOT_TOKEN .env
   ```

5. **Manual Service Recovery**:
   ```bash
   # Stop and restart service
   sudo systemctl stop reminder-tg-bot
   sudo systemctl start reminder-tg-bot
   
   # Check logs in real-time
   sudo journalctl -u reminder-tg-bot -f
   ```