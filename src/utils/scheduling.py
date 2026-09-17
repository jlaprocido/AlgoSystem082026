import os
import datetime as dt
from zoneinfo import ZoneInfo

# All target run times in this project are specified in the user's own local time, not market
# time -- America/Chicago handles CDT/CST automatically via real IANA tz data, so there's no
# twice-a-year manual UTC cron adjustment needed (the mistake that caused the last two rounds
# of wrong-time bugs: a fixed UTC cron is only correct for one of the two DST states, permanently).
LOCAL_TZ = ZoneInfo("America/Chicago")


def is_scheduled_trigger() -> bool:
    # GITHUB_EVENT_NAME is set automatically by GitHub Actions (schedule, workflow_dispatch,
    # etc.) and is simply unset when running locally -- treated as "not a schedule" either way,
    # so local/manual runs always proceed instead of silently no-oping on the clock
    return os.environ.get("GITHUB_EVENT_NAME") == "schedule"


def in_time_window(target_hour: int, target_minute: int = 0, window_minutes: int = 15,
                    now: dt.datetime | None = None) -> bool:
    """True if the current America/Chicago time is within `window_minutes` at/after the target
    time. A manual trigger (workflow_dispatch, or running locally) always returns True -- a
    human running this by hand wants it to actually do something, not silently no-op because
    of the clock. The underlying GitHub Actions cron fires more often than this window (see the
    workflow YAML), so this is what actually pins down the precise, DST-proof local time.
    `now` is for tests only -- omit it in real use, it defaults to the real current time."""
    if not is_scheduled_trigger():
        return True

    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(LOCAL_TZ)
    target_today = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
    return target_today <= now < target_today + dt.timedelta(minutes=window_minutes)


def in_hourly_window(start_hour: int, end_hour: int, window_minutes: int = 15,
                      now: dt.datetime | None = None) -> bool:
    """True once per hour, during the first `window_minutes` of each hour from start_hour
    through end_hour inclusive (America/Chicago, DST-proof). Manual triggers always return True.
    `now` is for tests only -- omit it in real use, it defaults to the real current time."""
    if not is_scheduled_trigger():
        return True

    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(LOCAL_TZ)
    return start_hour <= now.hour <= end_hour and now.minute < window_minutes
