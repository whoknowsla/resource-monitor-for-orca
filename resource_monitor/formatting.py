"""Number, size, duration, and temperature formatting."""

from __future__ import annotations

from .i18n import _, ngettext

# Binary multiples with the familiar decimal names, as most desktops show them.
# This matches the "alternative" style of the NVDA add-on.
_SIZE_UNITS: tuple[tuple[float, str], ...] = (
    (1024.0**10, " QB"),
    (1024.0**9, " RB"),
    (1024.0**8, " YB"),
    (1024.0**7, " ZB"),
    (1024.0**6, " EB"),
    (1024.0**5, " PB"),
    (1024.0**4, " TB"),
    (1024.0**3, " GB"),
    (1024.0**2, " MB"),
    (1024.0, " KB"),
)

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400

CELSIUS = "celsius"
FAHRENHEIT = "fahrenheit"


def trim_number(value: float) -> int | float:
    """Returns value without a trailing .0, so 5.0 becomes 5."""

    if value == int(value):
        return int(value)
    return value


def format_percent(value: float) -> str:
    """Returns a percentage rounded to one decimal place, without a trailing .0."""

    return str(trim_number(round(value, 1)))


def percent_of(part: float, whole: float) -> float:
    """Returns part as a percentage of whole, or 0 when whole is not positive."""

    if whole <= 0:
        return 0.0
    return part / whole * 100.0


def format_size(num_bytes: float) -> str:
    """Returns a human readable size such as 15.40 GB."""

    for factor, suffix in _SIZE_UNITS:
        if num_bytes >= factor:
            return f"{num_bytes / factor:.2f}{suffix}"
    count = int(num_bytes)
    # Translators: A size smaller than one kilobyte.
    return ngettext("{count} byte", "{count} bytes", count).format(count=count)


def format_duration(total_seconds: float) -> str:
    """Returns a duration as days, hours, minutes, and seconds."""

    seconds_left = max(0, int(total_seconds))
    days, seconds_left = divmod(seconds_left, SECONDS_PER_DAY)
    hours, seconds_left = divmod(seconds_left, SECONDS_PER_HOUR)
    minutes, seconds = divmod(seconds_left, SECONDS_PER_MINUTE)
    parts = (
        # Translators: system uptime in days.
        ngettext("{days:d} day", "{days:d} days", days).format(days=days),
        # Translators: system uptime in hours.
        ngettext("{hours:d} hour", "{hours:d} hours", hours).format(hours=hours),
        # Translators: system uptime in minutes.
        ngettext("{minutes:d} minute", "{minutes:d} minutes", minutes).format(minutes=minutes),
        # Translators: system uptime in seconds.
        ngettext("{seconds:d} second", "{seconds:d} seconds", seconds).format(seconds=seconds),
    )
    return ", ".join(parts)


def format_time_remaining(total_seconds: float) -> str:
    """Returns a rough duration in hours and minutes, for a battery estimate.

    Deliberately not format_duration: that always names days, hours, minutes,
    and seconds, which is right for an uptime read once and wrong for a
    battery estimate read often. A battery estimate is also not accurate to
    the second, so reading seconds aloud would claim a precision it does not
    have.
    """

    minutes_left = max(0, int(total_seconds) // SECONDS_PER_MINUTE)
    hours, minutes = divmod(minutes_left, 60)
    if hours and minutes:
        # Translators: A duration in hours and minutes (example: 2 hours, 15 minutes).
        return _("{hours}, {minutes}").format(
            hours=ngettext("{hours:d} hour", "{hours:d} hours", hours).format(hours=hours),
            minutes=ngettext(
                "{minutes:d} minute", "{minutes:d} minutes", minutes
            ).format(minutes=minutes),
        )
    if hours:
        return ngettext("{hours:d} hour", "{hours:d} hours", hours).format(hours=hours)
    # Translators: A duration of under an hour, in minutes.
    return ngettext("{minutes:d} minute", "{minutes:d} minutes", minutes).format(
        minutes=minutes
    )


def format_temperature(celsius: float, unit: str) -> str:
    """Returns a temperature given in Celsius, in the requested unit."""

    if unit == FAHRENHEIT:
        value = celsius * 9.0 / 5.0 + 32.0
        # Translators: Fahrenheit temperature unit appended to a GPU temperature value.
        symbol = _("degrees Fahrenheit")
    else:
        value = celsius
        # Translators: Celsius temperature unit appended to a GPU temperature value.
        symbol = _("degrees Celsius")
    return f"{trim_number(round(value, 1))} {symbol}"
