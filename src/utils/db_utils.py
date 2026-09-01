import psycopg
from psycopg import IsolationLevel
from sqlalchemy import create_engine, text
from urllib.parse import urlparse
import logging

logger = logging.getLogger(__name__)

def create_database_if_not_exists(database_url: str):
    """Create database if it doesn't exist"""
    try:
        parsed_url = urlparse(database_url)
        
        db_name = parsed_url.path[1:]  # Remove leading slash
        
        # Create connection URL without database name
        admin_url = f"{parsed_url.scheme}://{parsed_url.netloc}/postgres"
        
        # Connect to PostgreSQL server (default 'postgres' database)
        logger.info(f"Checking if database '{db_name}' exists...")
        
        admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        
        with admin_engine.connect() as conn:
            # Check if database exists
            result = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :db_name"),
                {"db_name": db_name}
            )
            
            if not result.fetchone():
                logger.info(f"Database '{db_name}' does not exist. Creating...")
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
                logger.info(f"Database '{db_name}' created successfully!")
            else:
                logger.info(f"Database '{db_name}' already exists.")
        
        admin_engine.dispose()
        
    except Exception as e:
        logger.error(f"Error creating database: {e}")
        # If we can't create the database, try using the original URL anyway
        # in case it exists but we don't have permission to check
        pass

def create_database_if_not_exists_psycopg2(database_url: str):
    """Alternative method using psycopg directly"""
    try:
        parsed_url = urlparse(database_url)
        
        db_name = parsed_url.path[1:]  # Remove leading slash
        host = parsed_url.hostname
        port = parsed_url.port or 5432
        user = parsed_url.username
        password = parsed_url.password
        
        logger.info(f"Attempting to create database '{db_name}' if it doesn't exist...")
        
        # Connect to PostgreSQL server (default 'postgres' database)
        with psycopg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname='postgres',  # Connect to default database
            autocommit=True
        ) as conn:
            with conn.cursor() as cursor:
                # Check if database exists
                cursor.execute(
                    "SELECT 1 FROM pg_database WHERE datname = %s",
                    (db_name,)
                )
                
                if not cursor.fetchone():
                    logger.info(f"Database '{db_name}' does not exist. Creating...")
                    cursor.execute(f'CREATE DATABASE "{db_name}"')
                    logger.info(f"Database '{db_name}' created successfully!")
                else:
                    logger.info(f"Database '{db_name}' already exists.")
        
    except Exception as e:
        logger.error(f"Error creating database with psycopg: {e}")
        # Fallback to SQLAlchemy method
        create_database_if_not_exists(database_url)
