# Server Setup Instructions

## Initial Setup

1. **Create deployment config**:
   ```bash
   cp bin/deploy.conf.sample bin/deploy.conf
   nano bin/deploy.conf  # Update with your server details
   ```

## SSH Key Setup

The SSH key is already generated locally. You need to add the public key to the server.

### Option 1: Copy public key to server manually

1. Connect to the server:
   ```bash
   ssh reminder_bot@YOUR_SERVER_IP
   ```

2. Add the public key to authorized_keys:
   ```bash
   mkdir -p ~/.ssh
   echo 'YOUR_PUBLIC_KEY_FROM_setup-ssh' >> ~/.ssh/authorized_keys
   chmod 600 ~/.ssh/authorized_keys
   chmod 700 ~/.ssh
   ```

### Option 2: Use ssh-copy-id (if available)

```bash
ssh-copy-id -i ~/.ssh/reminder_bot_key.pub reminder_bot@YOUR_SERVER_IP
```

## Test SSH Connection

After adding the public key, test the connection:

```bash
./bin/test-ssh
```

This should connect without asking for a password.

## Deploy Usage

Once SSH is working:

```bash
# Deploy code and restart service (requires sudo setup)
./bin/deploy

# Deploy code only (no sudo required)
./bin/deploy-manual

# Just restart service (no code changes)
./bin/deploy --restart-only
```

## Server Directory Structure

Expected server setup:
- Remote directory: `/var/www/reminder_tg_bot`
- Service name: `reminder-bot` 
- User: `reminder_bot`

Make sure the service is configured as a systemd service that can be controlled with:
```bash
sudo systemctl restart reminder-bot
sudo systemctl status reminder-bot
```

## Sudo Configuration

For automatic deployments, the `reminder_bot` user needs passwordless sudo for systemctl commands.

Add this to `/etc/sudoers` (as root):
```bash
# Option 1: Specific commands only (recommended)
reminder_bot ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart reminder-bot, /usr/bin/systemctl status reminder-bot, /usr/bin/systemctl is-active reminder-bot, /usr/bin/journalctl

# Option 2: All systemctl commands
reminder_bot ALL=(ALL) NOPASSWD: /usr/bin/systemctl
```

To edit sudoers safely:
```bash
sudo visudo
```

## Getting Started

1. Copy and edit config: `cp bin/deploy.conf.sample bin/deploy.conf`
2. Setup SSH key: `./bin/setup-ssh`
3. Test connection: `./bin/test-ssh`
4. Deploy: `./bin/deploy` or `./bin/deploy-manual`