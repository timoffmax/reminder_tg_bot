#!/bin/bash
# Fix Debian repository issues for older systems

set -e

echo "Fixing Debian repository configuration..."

# Backup original sources
cp /etc/apt/sources.list /etc/apt/sources.list.backup.$(date +%Y%m%d)

# Remove problematic backports line
if [ -f /etc/apt/sources.list.d/buster-backports.list ]; then
    echo "Removing problematic backports configuration..."
    rm -f /etc/apt/sources.list.d/buster-backports.list
fi

# Fix duplicate entries
if [ -f /etc/apt/sources.list.d/hetzner-mirror.list ]; then
    echo "Removing duplicate mirror entries..."
    sed -i '/buster-backports/d' /etc/apt/sources.list.d/hetzner-mirror.list
fi

# Update package lists
echo "Updating package lists..."
apt-get update --allow-releaseinfo-change || apt-get update

echo "Repository issues fixed!"