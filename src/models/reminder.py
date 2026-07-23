from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, BigInteger, JSON, ForeignKey
from sqlalchemy.sql import func
from src.database import Base
from datetime import datetime
from enum import Enum
from typing import Optional, List

class ReminderType(Enum):
    ONE_TIME = "one_time"
    REPEATING = "repeating"

class ReminderStatus(Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    SNOOZED = "snoozed"
    CANCELLED = "cancelled"
    PAUSED = "paused"

class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    chat_id = Column(BigInteger, nullable=False, index=True)
    chat_title = Column(String(255), nullable=True)
    message_text = Column(Text, nullable=False)
    scheduled_time = Column(DateTime, nullable=False)
    reminder_type = Column(String(20), nullable=False, default=ReminderType.ONE_TIME.value)
    status = Column(String(20), nullable=False, default=ReminderStatus.ACTIVE.value)
    requires_confirmation = Column(Boolean, default=False)
    is_confirmed = Column(Boolean, default=False)
    # When the last confirmation request was sent; None means no confirmation is pending.
    last_confirmation_request_at = Column(DateTime, nullable=True)
    # User-chosen snooze/re-send interval in minutes; None falls back to the global default.
    default_snooze_minutes = Column(Integer, nullable=True)
    tagged_users = Column(JSON, default=list)
    repeat_interval = Column(String(100), nullable=True)
    repeat_until = Column(DateTime, nullable=True)
    parent_reminder_id = Column(Integer, ForeignKey('reminders.id', ondelete='CASCADE'), nullable=True, index=True)
    snooze_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<Reminder(id={self.id}, message='{self.message_text[:50]}...', scheduled_time={self.scheduled_time})>"

class ReminderHistory(Base):
    __tablename__ = "reminder_history"
    
    id = Column(Integer, primary_key=True, index=True)
    reminder_id = Column(Integer, nullable=False, index=True)
    action = Column(String(50), nullable=False)
    timestamp = Column(DateTime, default=func.now())
    details = Column(JSON, default=dict)
    
    def __repr__(self):
        return f"<ReminderHistory(id={self.id}, reminder_id={self.reminder_id}, action='{self.action}')>"
