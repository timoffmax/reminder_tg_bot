#!/usr/bin/env python3
"""
Setup Alembic for existing database
This script initializes Alembic for an existing database by marking the current state as the baseline.
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config import DATABASE_URL
import subprocess
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_command(cmd, cwd=None):
    """Run a command and return success status"""
    try:
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True, cwd=cwd)
        logger.info(f"Command succeeded: {cmd}")
        if result.stdout:
            logger.info(f"Output: {result.stdout}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {cmd}")
        logger.error(f"Error: {e.stderr}")
        return False

def main():
    """Setup Alembic for existing database"""
    
    # Get the project root directory
    project_root = Path(__file__).parent.parent
    logger.info(f"Project root: {project_root}")
    
    # Change to project directory
    os.chdir(project_root)
    
    # Check if alembic is already configured
    alembic_versions_dir = project_root / "alembic" / "versions"
    if not alembic_versions_dir.exists():
        logger.error("Alembic not initialized. Run 'alembic init alembic' first.")
        return False
    
    # Check if there are any migration files
    migration_files = list(alembic_versions_dir.glob("*.py"))
    if not migration_files:
        logger.error("No migration files found. Create initial migration first.")
        return False
    
    # Get the latest migration revision
    latest_migration = max(migration_files, key=lambda f: f.stat().st_mtime)
    revision = latest_migration.stem.split('_')[0]
    logger.info(f"Latest migration revision: {revision}")
    
    # Check if alembic_version table exists
    check_table_cmd = f"""python -c "
import sys
sys.path.insert(0, 'src')
from src.database import engine
from sqlalchemy import text
with engine.connect() as conn:
    result = conn.execute(text(\\\"SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'alembic_version')\\\"))
    exists = result.fetchone()[0]
    print('EXISTS' if exists else 'NOT_EXISTS')
"
"""
    
    result = subprocess.run(check_table_cmd, shell=True, capture_output=True, text=True)
    table_exists = "EXISTS" in result.stdout
    
    if table_exists:
        logger.info("Alembic version table already exists")
        # Check current revision
        check_revision_cmd = f"""python -c "
import sys
sys.path.insert(0, 'src')
from src.database import engine
from sqlalchemy import text
with engine.connect() as conn:
    result = conn.execute(text('SELECT version_num FROM alembic_version'))
    row = result.fetchone()
    print(row[0] if row else 'NONE')
"
"""
        result = subprocess.run(check_revision_cmd, shell=True, capture_output=True, text=True)
        current_revision = result.stdout.strip()
        logger.info(f"Current database revision: {current_revision}")
        
        if current_revision == "NONE":
            # Stamp with the first migration (initial state)
            initial_revision = "cf19f441a84c"  # The initial migration revision
            logger.info(f"Stamping database with initial revision: {initial_revision}")
            if not run_command(f"alembic stamp {initial_revision}"):
                return False
        
    else:
        logger.info("Alembic version table does not exist. Stamping with initial revision.")
        initial_revision = "cf19f441a84c"  # The initial migration revision
        if not run_command(f"alembic stamp {initial_revision}"):
            return False
    
    # Now run any pending migrations
    logger.info("Running pending migrations...")
    if not run_command("alembic upgrade head"):
        logger.warning("Migration upgrade failed, but this might be expected")
        return False
    
    logger.info("Alembic setup completed successfully")
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)