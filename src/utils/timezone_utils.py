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
    - Monthly patterns: "25th at 10AM", "15th 14:00"
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
    
    # Try time format with AM/PM (HH:MM AM/PM)
    am_pm_match = re.match(r'^(?:at\s+)?(\d{1,2}):(\d{2})\s*(am|pm)$', time_str.lower())
    if am_pm_match:
        hour = int(am_pm_match.group(1))
        minute = int(am_pm_match.group(2))
        am_pm = am_pm_match.group(3)
        
        # Convert to 24-hour format
        if am_pm == 'pm' and hour != 12:
            hour += 12
        elif am_pm == 'am' and hour == 12:
            hour = 0
        
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
    
    # Try monthly patterns like "25th at 10AM" or "15th 14:00"
    # Improved pattern to avoid matching regular time strings
    monthly_pattern = r'(\d{1,2})(?:st|nd|rd|th)\s*(?:at\s*)?(\d{1,2}):?(\d{2})?\s*(am|pm)?'
    monthly_match = re.search(monthly_pattern, time_str.lower())
    if monthly_match:
        day = int(monthly_match.group(1))
        hour = int(monthly_match.group(2))
        minute = int(monthly_match.group(3) or 0)
        am_pm = monthly_match.group(4)
        
        # Convert to 24-hour format if needed
        if am_pm:
            if am_pm.lower() == 'pm' and hour != 12:
                hour += 12
            elif am_pm.lower() == 'am' and hour == 12:
                hour = 0
        
        # Validate day and time
        if 1 <= day <= 31 and 0 <= hour <= 23 and 0 <= minute <= 59:
            try:
                # Try current month first
                target_time = now.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
                
                # If the date has already passed this month, use next month
                if target_time <= now:
                    target_time = target_time + relativedelta(months=1)
                
                return convert_to_utc(target_time)
            except ValueError:
                # Invalid day for current month, try next month
                try:
                    next_month = now + relativedelta(months=1)
                    target_time = next_month.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
                    return convert_to_utc(target_time)
                except ValueError:
                    # Invalid day for next month too, skip this parsing
                    pass
    
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
        
        weekday_names = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        requested_weekday = next(
            (index for index, name in enumerate(weekday_names) if name in time_str_lower), None
        )

        # If only time was specified (no date), adjust the date. An explicitly
        # requested weekday is handled below instead, so "monday at 5pm" typed
        # on a Monday evening doesn't drift to Tuesday.
        if requested_weekday is None and parsed_dt.date() == now.date() and parsed_dt.time() < now.time():
            # If time is in the past today, assume tomorrow
            parsed_dt += timedelta(days=1)

        # An explicitly requested weekday must be honored even when today's
        # instance already passed: move to the next one, keeping the parsed time-of-day.
        if requested_weekday is not None and parsed_dt <= now:
            days_ahead = requested_weekday - now.weekday()

            if days_ahead <= 0:
                days_ahead += 7

            parsed_dt = (now + timedelta(days=days_ahead)).replace(
                hour=parsed_dt.hour, minute=parsed_dt.minute, second=0, microsecond=0
            )

        return convert_to_utc(parsed_dt)
        
    except (ValueError, parser.ParserError):
        # If all parsing attempts fail
        return None

def parse_recurring_pattern(text: str) -> tuple[str, Optional[str]]:
    """
    Parse text for recurring patterns and return (cleaned_text, repeat_interval)
    
    Detects patterns like:
    - "every month 25th at 10AM" -> ("25th at 10AM", "monthly")
    - "every day 9AM" -> ("9AM", "daily") 
    - "every week monday 10AM" -> ("monday 10AM", "weekly")
    - "every saturday and sunday 11AM" -> ("11AM", "multi-day: saturday, sunday")
    - "everyday at 10:20 AM" -> ("at 10:20 AM", "daily")
    """
    text_lower = text.lower()
    original_text = text
    
    # Handle compound words like "everyday" first
    if "everyday" in text_lower:
        cleaned_text = re.sub(r'\beveryday\b', '', text, flags=re.IGNORECASE).strip()
        return (cleaned_text, "daily")
    
    # Check for "every" keyword
    if "every" in text_lower:
        # Remove "every" from text
        cleaned_text = re.sub(r'\bevery\b', '', text, flags=re.IGNORECASE).strip()

        # Numeric periods like "3 days", "2 weeks", "3 months" -> custom_N_unit;
        # must run before the generic month/day/week checks so the number isn't dropped.
        period_match = re.search(r'\b(\d+)\s*(day|week|month)s?\b', cleaned_text.lower())
        if period_match:
            number = int(period_match.group(1))
            unit = period_match.group(2)
            cleaned_text = re.sub(
                rf'\b{number}\s*{unit}s?\b', '', cleaned_text, count=1, flags=re.IGNORECASE
            ).strip()

            if number == 1:
                return (cleaned_text, {'day': 'daily', 'week': 'weekly', 'month': 'monthly'}[unit])

            return (cleaned_text, f"custom_{number}_{unit}s")

        # Check for monthly patterns
        if "month" in text_lower:
            cleaned_text = re.sub(r'\bmonth\b', '', cleaned_text, flags=re.IGNORECASE).strip()
            return (cleaned_text, "monthly")
        
        # Check for multi-day patterns like "saturday and sunday"
        weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        found_days = [day for day in weekdays if day in text_lower]
        
        if len(found_days) > 1:
            repeat_interval = "multi-day: " + ", ".join(found_days)
            # Remove all day names from text
            for day in found_days:
                cleaned_text = re.sub(rf'\b{day}\b', '', cleaned_text, flags=re.IGNORECASE)
            cleaned_text = re.sub(r'\band\b', '', cleaned_text, flags=re.IGNORECASE).strip()
            return (cleaned_text, repeat_interval)
        elif len(found_days) == 1:
            return (cleaned_text, "weekly")
        
        # Check for explicit daily/weekly/monthly
        if "day" in text_lower:
            cleaned_text = re.sub(r'\bday\b', '', cleaned_text, flags=re.IGNORECASE).strip()
            return (cleaned_text, "daily")
        elif "week" in text_lower:
            cleaned_text = re.sub(r'\bweek\b', '', cleaned_text, flags=re.IGNORECASE).strip()
            return (cleaned_text, "weekly")
        
        # Default to daily if no specific pattern found
        return (cleaned_text, "daily")
    
    # Check for standalone keywords
    if "daily" in text_lower:
        cleaned_text = re.sub(r'\bdaily\b', '', text, flags=re.IGNORECASE).strip()
        return (cleaned_text, "daily")
    elif "weekly" in text_lower:
        cleaned_text = re.sub(r'\bweekly\b', '', text, flags=re.IGNORECASE).strip()
        return (cleaned_text, "weekly")
    elif "monthly" in text_lower:
        cleaned_text = re.sub(r'\bmonthly\b', '', text, flags=re.IGNORECASE).strip()
        return (cleaned_text, "monthly")
    
    return (text, None)

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
