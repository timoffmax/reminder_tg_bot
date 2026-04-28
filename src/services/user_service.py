from typing import Optional
from sqlalchemy.orm import Session
from src.models.user import User
from src.config import DEFAULT_TIMEZONE

class UserService:
    def __init__(self, db: Session):
        self.db = db
    
    def get_or_create_user(
        self,
        telegram_user_id: int,
        username: str = None,
        first_name: str = None,
        last_name: str = None,
        language_code: str = None
    ) -> User:
        user = self.db.query(User).filter(
            User.telegram_user_id == telegram_user_id
        ).first()
        
        if not user:
            user = User(
                telegram_user_id=telegram_user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                timezone=DEFAULT_TIMEZONE,
                language_code=language_code
            )
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)
        else:
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
            user.language_code = language_code
            self.db.commit()
        
        return user
    
    def get_user_by_telegram_id(self, telegram_user_id: int) -> Optional[User]:
        return self.db.query(User).filter(
            User.telegram_user_id == telegram_user_id
        ).first()
    
    def update_user_timezone(self, telegram_user_id: int, timezone: str) -> bool:
        user = self.get_user_by_telegram_id(telegram_user_id)
        if not user:
            return False
        
        user.timezone = timezone
        self.db.commit()
        return True
    
    def get_user_timezone(self, telegram_user_id: int) -> str:
        user = self.get_user_by_telegram_id(telegram_user_id)
        return user.timezone if user else DEFAULT_TIMEZONE

    def set_quiet_hours(self, telegram_user_id: int, start_hour: Optional[int], end_hour: Optional[int]) -> bool:
        user = self.get_user_by_telegram_id(telegram_user_id)
        if not user:
            return False

        user.quiet_start_hour = start_hour
        user.quiet_end_hour = end_hour
        self.db.commit()
        return True

    def get_quiet_hours(self, telegram_user_id: int) -> Optional[tuple]:
        user = self.get_user_by_telegram_id(telegram_user_id)
        if not user or user.quiet_start_hour is None or user.quiet_end_hour is None:
            return None
        return (user.quiet_start_hour, user.quiet_end_hour)