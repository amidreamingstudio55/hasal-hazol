"""Shabbat and Yom Tov rest window for the studio (Moshe's rule, 18/11/2026).

Nothing automatic runs from 60 minutes before sunset on the eve of Shabbat or
Yom Tov until 75 minutes after sunset at its end. Times are calculated for
Jerusalem; the margins cover the 40-minute Jerusalem candle-lighting custom and
a late end of Shabbat. Yom Tov follows the Israeli calendar (one day each,
two for Rosh Hashana). No external libraries.

    python3 scripts/shabbat.py          exit code 0 = working time, 3 = rest
    python3 scripts/shabbat.py --show   print the next rest windows
"""
import datetime, math, sys, zoneinfo

TZ = zoneinfo.ZoneInfo('Asia/Jerusalem')
LAT, LON = 31.778, 35.235            # Jerusalem
BEFORE = datetime.timedelta(minutes=60)
AFTER = datetime.timedelta(minutes=75)


def sunset(day):
    """Sunset in Jerusalem on a civil date, as an aware datetime (NOAA formulas)."""
    n = day.toordinal() - datetime.date(2000, 1, 1).toordinal() - LON / 360
    m = math.radians((357.5291 + 0.98560028 * n) % 360)
    c = 1.9148 * math.sin(m) + 0.02 * math.sin(2 * m) + 0.0003 * math.sin(3 * m)
    lam = math.radians((math.degrees(m) + c + 180 + 102.9372) % 360)
    transit = 2451545.0 + n + 0.0053 * math.sin(m) - 0.0069 * math.sin(2 * lam)
    dec = math.asin(math.sin(lam) * math.sin(math.radians(23.4397)))
    lat = math.radians(LAT)
    cos_h = (math.sin(math.radians(-0.833)) - math.sin(lat) * math.sin(dec)) / (math.cos(lat) * math.cos(dec))
    jd = transit + math.degrees(math.acos(cos_h)) / 360
    utc = datetime.datetime(2000, 1, 1, 12, tzinfo=datetime.timezone.utc) + datetime.timedelta(days=jd - 2451545.0)
    return utc.astimezone(TZ)


def _elapsed(year):
    months = (235 * year - 234) // 19
    parts = 12084 + 13753 * months
    day = months * 29 + parts // 25920
    return day + 1 if (3 * (day + 1)) % 7 < 3 else day


def rosh_hashana(year):
    """Civil date of 1 Tishrei of a Hebrew year."""
    a, b, c = _elapsed(year - 1), _elapsed(year), _elapsed(year + 1)
    b += 2 if c - b == 356 else 1 if b - a == 382 else 0
    return datetime.date.fromordinal(b - 1373427)


def yom_tov(day):
    """True if the civil date is a Yom Tov day in Israel."""
    hy = day.year + 3761
    for y in (hy - 1, hy):
        rh = rosh_hashana(y)
        pesach = rosh_hashana(y + 1) - datetime.timedelta(days=163)
        days = [rh, rh + datetime.timedelta(days=1),            # Rosh Hashana
                rh + datetime.timedelta(days=9),                 # Yom Kippur
                rh + datetime.timedelta(days=14),                # Sukkot
                rh + datetime.timedelta(days=21),                # Shmini Atzeret / Simchat Torah
                pesach, pesach + datetime.timedelta(days=6),     # Pesach, first and seventh day
                pesach + datetime.timedelta(days=50)]            # Shavuot
        if day in days:
            return True
    return False


def rest_day(day):
    return day.weekday() == 5 or yom_tov(day)


def is_rest(now=None):
    """True from 60 minutes before sunset on the eve until 75 minutes after sunset at the end."""
    now = now or datetime.datetime.now(TZ)
    today = now.astimezone(TZ).date()
    for day in (today, today + datetime.timedelta(days=1)):
        if rest_day(day) and sunset(day - datetime.timedelta(days=1)) - BEFORE <= now < sunset(day) + AFTER:
            return True
    return False


def windows(start, count=8):
    """The next rest windows as (begin, end), consecutive days merged."""
    out, day = [], start
    while len(out) < count:
        if rest_day(day):
            begin = sunset(day - datetime.timedelta(days=1)) - BEFORE
            while rest_day(day + datetime.timedelta(days=1)):
                day += datetime.timedelta(days=1)
            out.append((begin, sunset(day) + AFTER))
        day += datetime.timedelta(days=1)
    return out


if __name__ == '__main__':
    if '--show' in sys.argv:
        for b, e in windows(datetime.datetime.now(TZ).date()):
            print(b.strftime('%a %d/%m/%Y %H:%M'), '->', e.strftime('%a %d/%m/%Y %H:%M'))
    else:
        rest = is_rest()
        print('rest: Shabbat or Yom Tov, nothing runs' if rest else 'working time')
        sys.exit(3 if rest else 0)
