import pytz
from datetime import datetime
from typing import Optional
import re
from dateutil import parser
from dateutil.relativedelta import relativedelta

def convert_to_user_timezone(dt: datetime, user_timezone: str) -> datetime:
    # Database stores naive datetime in UTC, so we need to add UTC timezone info
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)
    
    # Handle timezone name changes (Kiev -> Kyiv) but preserve Europe/Kiev for display
    display_timezone = user_timezone
    if user_timezone == 'Europe/Kiev':
        user_timezone = 'Europe/Kyiv'
    
    user_tz = pytz.timezone(user_timezone)
    return dt.astimezone(user_tz).replace(tzinfo=None)

def convert_to_utc(dt: datetime, user_timezone: str = None) -> datetime:
    if dt.tzinfo is None:
        if user_timezone is None:
            raise ValueError("user_timezone must be provided for naive datetime")
        # Handle timezone name changes (Kiev -> Kyiv)
        if user_timezone == 'Europe/Kiev':
            user_timezone = 'Europe/Kyiv'
        user_tz = pytz.timezone(user_timezone)
        dt = user_tz.localize(dt)
    
    return dt.astimezone(pytz.UTC).replace(tzinfo=None)

def parse_time_input(time_str: str, user_timezone: str) -> Optional[datetime]:
    """
    Parse various time input formats including:
    - Exact time: "10:30", "10:30 PM", "22:30"
    - Relative time: "2h", "30m", "1d", "1w"
    - Natural language: "tomorrow at 3pm", "next monday at 10am"
    - Date formats: "12.07.2025 14:00", "12/7/25 2PM", "July 12 at 2:30 PM"
    - ISO format: "2025-07-12T14:00:00"
    """
    from datetime import datetime, timedelta
    
    # Handle timezone name changes (Kiev -> Kyiv)
    if user_timezone == 'Europe/Kiev':
        user_timezone = 'Europe/Kyiv'
    
    now = datetime.now(pytz.timezone(user_timezone))
    time_str = time_str.strip()
    
    # Try simple time format (HH:MM)
    if re.match(r'^\d{1,2}:\d{2}$', time_str):
        hour, minute = map(int, time_str.split(':'))
        target_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        
        if target_time <= now:
            target_time += timedelta(days=1)
        
        return convert_to_utc(target_time)
    
    # Try relative time patterns (2h, 30m, etc.)
    time_patterns = {
        r'(\d+)\s*(?:minute|min|m)s?': lambda m: now + timedelta(minutes=int(m.group(1))),
        r'(\d+)\s*(?:hour|hr|h)s?': lambda m: now + timedelta(hours=int(m.group(1))),
        r'(\d+)\s*(?:day|d)s?': lambda m: now + timedelta(days=int(m.group(1))),
        r'(\d+)\s*(?:week|w)s?': lambda m: now + timedelta(weeks=int(m.group(1))),
    }
    
    for pattern, calc_func in time_patterns.items():
        match = re.search(pattern, time_str.lower())
        if match:
            target_time = calc_func(match)
            return convert_to_utc(target_time)
    
    # Try natural language and various date formats using dateutil
    try:
        # Handle "tomorrow", "next week", etc.
        time_str_lower = time_str.lower()
        
        # Replace common natural language terms
        replacements = {
            'tomorrow': (now + timedelta(days=1)).strftime('%Y-%m-%d'),
            'today': now.strftime('%Y-%m-%d'),
            'next week': (now + timedelta(weeks=1)).strftime('%Y-%m-%d'),
            'next month': (now + relativedelta(months=1)).strftime('%Y-%m-%d'),
        }
        
        for term, replacement in replacements.items():
            if term in time_str_lower:
                time_str = time_str_lower.replace(term, replacement)
                break
        
        # Parse the datetime
        naive_default = now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        parsed_dt = parser.parse(time_str, fuzzy=True, default=naive_default)
        
        # Convert parsed datetime to user timezone  
        user_tz = pytz.timezone(user_timezone)
        if parsed_dt.tzinfo is None:
            parsed_dt = user_tz.localize(parsed_dt)
        
        # If only time was specified (no date), adjust the date
        if parsed_dt.date() == now.date() and parsed_dt.time() < now.time():
            # If time is in the past today, assume tomorrow
            parsed_dt += timedelta(days=1)
        
        # Ensure the datetime is in the future
        if parsed_dt <= now:
            # If the parsed date is in the past, try to interpret it as next occurrence
            if 'monday' in time_str_lower:
                days_ahead = 0 - now.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                parsed_dt = now + timedelta(days=days_ahead)
                parsed_dt = parsed_dt.replace(hour=parsed_dt.hour, minute=parsed_dt.minute)
            elif 'tuesday' in time_str_lower:
                days_ahead = 1 - now.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                parsed_dt = now + timedelta(days=days_ahead)
                parsed_dt = parsed_dt.replace(hour=parsed_dt.hour, minute=parsed_dt.minute)
            elif 'wednesday' in time_str_lower:
                days_ahead = 2 - now.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                parsed_dt = now + timedelta(days=days_ahead)
                parsed_dt = parsed_dt.replace(hour=parsed_dt.hour, minute=parsed_dt.minute)
            elif 'thursday' in time_str_lower:
                days_ahead = 3 - now.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                parsed_dt = now + timedelta(days=days_ahead)
                parsed_dt = parsed_dt.replace(hour=parsed_dt.hour, minute=parsed_dt.minute)
            elif 'friday' in time_str_lower:
                days_ahead = 4 - now.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                parsed_dt = now + timedelta(days=days_ahead)
                parsed_dt = parsed_dt.replace(hour=parsed_dt.hour, minute=parsed_dt.minute)
            elif 'saturday' in time_str_lower:
                days_ahead = 5 - now.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                parsed_dt = now + timedelta(days=days_ahead)
                parsed_dt = parsed_dt.replace(hour=parsed_dt.hour, minute=parsed_dt.minute)
            elif 'sunday' in time_str_lower:
                days_ahead = 6 - now.weekday()
                if days_ahead <= 0:
                    days_ahead += 7
                parsed_dt = now + timedelta(days=days_ahead)
                parsed_dt = parsed_dt.replace(hour=parsed_dt.hour, minute=parsed_dt.minute)
        
        return convert_to_utc(parsed_dt)
        
    except (ValueError, parser.ParserError):
        # If all parsing attempts fail
        return None

def get_available_timezones() -> list:
    """Get a comprehensive list of common timezones organized by region"""
    timezones = [
        # UTC
        'UTC',
        
        # Americas
        'America/New_York',
        'America/Chicago', 
        'America/Denver',
        'America/Los_Angeles',
        'America/Toronto',
        'America/Vancouver',
        'America/Mexico_City',
        'America/Sao_Paulo',
        'America/Buenos_Aires',
        'America/Lima',
        'America/Bogota',
        'America/Caracas',
        
        # Europe
        'Europe/London',
        'Europe/Paris',
        'Europe/Berlin',
        'Europe/Rome',
        'Europe/Madrid',
        'Europe/Amsterdam',
        'Europe/Brussels',
        'Europe/Vienna',
        'Europe/Prague',
        'Europe/Warsaw',
        'Europe/Stockholm',
        'Europe/Helsinki',
        'Europe/Moscow',
        'Europe/Kyiv',
        'Europe/Athens',
        'Europe/Istanbul',
        
        # Asia
        'Asia/Tokyo',
        'Asia/Seoul',
        'Asia/Shanghai',
        'Asia/Hong_Kong',
        'Asia/Singapore',
        'Asia/Bangkok',
        'Asia/Jakarta',
        'Asia/Manila',
        'Asia/Kuala_Lumpur',
        'Asia/Kolkata',
        'Asia/Karachi',
        'Asia/Dubai',
        'Asia/Tehran',
        'Asia/Jerusalem',
        'Asia/Riyadh',
        
        # Africa
        'Africa/Cairo',
        'Africa/Lagos',
        'Africa/Nairobi',
        'Africa/Johannesburg',
        'Africa/Casablanca',
        'Africa/Tunis',
        
        # Australia/Oceania
        'Australia/Sydney',
        'Australia/Melbourne',
        'Australia/Perth',
        'Australia/Brisbane',
        'Australia/Adelaide',
        'Pacific/Auckland',
        'Pacific/Fiji',
        'Pacific/Honolulu',
    ]
    return timezones

def get_timezone_regions() -> dict:
    """Get timezones organized by regions for better UI"""
    return {
        'UTC': ['UTC'],
        'Americas': [
            'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles',
            'America/Toronto', 'America/Vancouver', 'America/Mexico_City', 'America/Sao_Paulo',
            'America/Buenos_Aires', 'America/Lima', 'America/Bogota', 'America/Caracas'
        ],
        'Europe': [
            'Europe/London', 'Europe/Paris', 'Europe/Berlin', 'Europe/Rome',
            'Europe/Madrid', 'Europe/Amsterdam', 'Europe/Brussels', 'Europe/Vienna',
            'Europe/Prague', 'Europe/Warsaw', 'Europe/Stockholm', 'Europe/Helsinki',
            'Europe/Moscow', 'Europe/Kyiv', 'Europe/Athens', 'Europe/Istanbul'
        ],
        'Asia': [
            'Asia/Tokyo', 'Asia/Seoul', 'Asia/Shanghai', 'Asia/Hong_Kong',
            'Asia/Singapore', 'Asia/Bangkok', 'Asia/Jakarta', 'Asia/Manila',
            'Asia/Kuala_Lumpur', 'Asia/Kolkata', 'Asia/Karachi', 'Asia/Dubai',
            'Asia/Tehran', 'Asia/Jerusalem', 'Asia/Riyadh'
        ],
        'Africa': [
            'Africa/Cairo', 'Africa/Lagos', 'Africa/Nairobi', 'Africa/Johannesburg',
            'Africa/Casablanca', 'Africa/Tunis'
        ],
        'Australia/Oceania': [
            'Australia/Sydney', 'Australia/Melbourne', 'Australia/Perth',
            'Australia/Brisbane', 'Australia/Adelaide', 'Pacific/Auckland',
            'Pacific/Fiji', 'Pacific/Honolulu'
        ]
    }