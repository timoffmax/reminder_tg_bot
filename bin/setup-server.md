# Server Setup Instructions

## Initial Setup

1. **Create deployment config**:
   ```bash
   cp bin/deploy.conf.sample bin/deploy.conf
   nano bin/deploy.conf  # Update with your server details
   ```

## SSH Key Setup

Generate a dedicated deploy key and add its public part to the server.

1. Generate a key pair locally:
   ```bash
   ssh-keygen -t ed25519 -C "reminder-bot-deploy" -f ~/.ssh/your_deploy_key
   ```

2. Copy the public key to the server:
   ```bash
   ssh-copy-id -i ~/.ssh/your_deploy_key.pub your_deploy_user@YOUR_SERVER_IP
   ```

   Or manually on the server:
   ```bash
   mkdir -p ~/.ssh
   echo 'YOUR_PUBLIC_KEY' >> ~/.ssh/authorized_keys
   chmod 600 ~/.ssh/authorized_keys
   chmod 700 ~/.ssh
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

Expected server setup (all configurable in `bin/deploy.conf`):
- Remote directory: e.g. `/opt/reminder_tg_bot`
- Service name: `reminder-bot`
- A dedicated deploy user

Make sure the service is configured as a systemd service that can be controlled with:
```bash
sudo systemctl restart reminder-bot
sudo systemctl status reminder-bot
```

## Sudo Configuration

For automatic deployments, the deploy user needs passwordless sudo for the specific systemctl commands.

Add this to `/etc/sudoers` (as root), replacing `your_deploy_user`:
```bash
your_deploy_user ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart reminder-bot, /usr/bin/systemctl status reminder-bot, /usr/bin/systemctl is-active reminder-bot
```

Grant only the exact commands needed — a blanket `NOPASSWD: /usr/bin/systemctl` is effectively root access.

To edit sudoers safely:
```bash
sudo visudo
```

## Getting Started

1. Copy and edit config: `cp bin/deploy.conf.sample bin/deploy.conf`
2. Set up the SSH key (see above)
3. Test connection: `./bin/test-ssh`
4. Deploy: `./bin/deploy` or `./bin/deploy-manual`
