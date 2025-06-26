from sqlalchemy import create_engine, MetaData
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from src.config import DATABASE_URL
from src.utils.db_utils import create_database_if_not_exists_psycopg2
import logging

logger = logging.getLogger(__name__)

# Create database if it doesn't exist
create_database_if_not_exists_psycopg2(DATABASE_URL)

# Convert postgresql:// to postgresql+psycopg:// for psycopg3
if DATABASE_URL.startswith('postgresql://'):
    sqlalchemy_url = DATABASE_URL.replace('postgresql://', 'postgresql+psycopg://', 1)
else:
    sqlalchemy_url = DATABASE_URL

engine = create_engine(sqlalchemy_url, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Initialize database and create all tables"""
    try:
        # Import all models to ensure they're registered with Base
        from src.models.user import User
        from src.models.reminder import Reminder, ReminderHistory
        
        logger.info("Creating database tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully!")
        
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise