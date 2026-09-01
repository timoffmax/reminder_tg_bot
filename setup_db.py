#!/usr/bin/env python3
"""
Database setup script for Reminder Bot
Run this script to create the database and tables if they don't exist.
"""

import sys
import os
import logging
import re

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.config import DATABASE_URL
from src.utils.db_utils import create_database_if_not_exists_psycopg2
from src.database import init_db

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

def main():
    """Setup database and tables"""
    try:
        logger.info("Starting database setup...")
        safe_url = re.sub(r'//([^:/@]+):[^@]+@', r'//\1:***@', DATABASE_URL)
        logger.info(f"Database URL: {safe_url}")
        
        # Create database if it doesn't exist
        logger.info("Step 1: Creating database if it doesn't exist...")
        create_database_if_not_exists_psycopg2(DATABASE_URL)
        
        # Initialize database tables
        logger.info("Step 2: Creating database tables...")
        init_db()
        
        logger.info("✅ Database setup completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Database setup failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()