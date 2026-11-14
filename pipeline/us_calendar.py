"""NYSE trading calendar (regular sessions 09:30-16:00 America/New_York, full-day holidays, 13:00 early closes), computed from the exchange's
standing rules so no download is needed. Special one-off closures can be added in data/us_special_sessions.json:
  {"2026-12-24": {"open": "09:30", "close": "13:00", "name": "Early close"}}   (an entry with "closed": true marks a one-off holiday)
All times are New York wall-clock times."""
import datetime as dt
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANUAL = ROOT / "data" / "us_special_sessions.json"
TZ = "America/New_York"
REGULAR = ((9, 30), (16, 0))
EARLY = ((9, 30), (13, 0))


def _nth_weekday(year, month, weekday, n):
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(weekday - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def _last_weekday(year, month, weekday):
    d = dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1)
    return d - dt.timedelta(days=(d.weekday() - weekday) % 7)


def _easter(year):
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


def _observed(d):
    """A holiday on Saturday is observed on the Friday before, on Sunday on the Monday after."""
    return d - dt.timedelta(days=1) if d.weekday() == 5 else d + dt.timedelta(days=1) if d.weekday() == 6 else d


def holidays(year):
    h = {}
    ny = dt.date(year, 1, 1)
    if ny.weekday() != 5:                                   # New Year's Day on a Saturday is not observed on the Friday
        h[_observed(ny)] = "New Year's Day"
    h[_nth_weekday(year, 1, 0, 3)] = "Martin Luther King Jr. Day"
    h[_nth_weekday(year, 2, 0, 3)] = "Washington's Birthday"
    h[_easter(year) - dt.timedelta(days=2)] = "Good Friday"
    h[_last_weekday(year, 5, 0)] = "Memorial Day"
    h[_observed(dt.date(year, 6, 19))] = "Juneteenth"
    h[_observed(dt.date(year, 7, 4))] = "Independence Day"
    h[_nth_weekday(year, 9, 0, 1)] = "Labor Day"
    h[_nth_weekday(year, 11, 3, 4)] = "Thanksgiving Day"
    h[_observed(dt.date(year, 12, 25))] = "Christmas Day"
    return h


def early_closes(year):
    out = {}
    tg = _nth_weekday(year, 11, 3, 4)
    out[tg + dt.timedelta(days=1)] = "Day after Thanksgiving"
    hol = holidays(year)
    d = dt.date(year, 7, 3)                                  # the day before Independence Day, when it is a weekday and not itself a holiday
    if d.weekday() < 5 and d not in hol and dt.date(year, 7, 4).weekday() < 5:
        out[d] = "Day before Independence Day"
    d = dt.date(year, 12, 24)
    if d.weekday() < 5 and d not in hol:
        out[d] = "Christmas Eve"
    return out


def _manual():
    try:
        return json.loads(MANUAL.read_text(encoding="utf-8"))
    except Exception:
        return {}


def sessions(day):
    """The trading sessions of a date as [((h, m), (h, m))]; empty on a holiday or weekend."""
    key = day.isoformat()
    man = _manual().get(key)
    if man:
        if man.get("closed"):
            return []
        a, b = man["open"].split(":"), man["close"].split(":")
        return [((int(a[0]), int(a[1])), (int(b[0]), int(b[1])))]
    if day.weekday() >= 5 or day in holidays(day.year):
        return []
    return [EARLY] if day in early_closes(day.year) else [REGULAR]


def is_trading_day(day):
    return bool(sessions(day))


def is_regular(day):
    ss = sessions(day)
    return bool(ss) and ss[0] == REGULAR


def prev_trading_day(day):
    d = day - dt.timedelta(days=1)
    while not is_trading_day(d):
        d -= dt.timedelta(days=1)
    return d


def next_trading_day(day):
    d = day + dt.timedelta(days=1)
    while not is_trading_day(d):
        d += dt.timedelta(days=1)
    return d


def close_minute(day):
    """Minute of the day (0-1439) the session closes, or None on a non-trading day."""
    ss = sessions(day)
    return ss[-1][1][0] * 60 + ss[-1][1][1] if ss else None


def in_session(t, lead=5, tail=10):
    """True from `lead` minutes before the open to `tail` minutes after the close (t: tz-aware pandas Timestamp, New York time)."""
    mins = t.hour * 60 + t.minute
    return any(o[0] * 60 + o[1] - lead <= mins < c[0] * 60 + c[1] + tail for o, c in sessions(t.date()))


def to_json():
    """For the page's countdown: holidays for the current and next year, and early-close days as special sessions."""
    y = dt.date.today().year
    hol, special = {}, {}
    for yy in (y, y + 1):
        hol.update({d.isoformat(): n for d, n in holidays(yy).items()})
        special.update({d.isoformat(): {"open": "09:30", "close": "13:00", "name": "Early close (" + n + ")"} for d, n in early_closes(yy).items()})
    for k, v in _manual().items():
        if v.get("closed"):
            hol[k] = v.get("name", "Closed")
        else:
            special[k] = v
    return {"holidays": hol, "special": special, "pending": {}}
