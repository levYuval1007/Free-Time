import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import hours

ISRAEL = 180  # UTC+3 in minutes


def period(open_day, open_time, close_day, close_time):
    return {
        "open": {"day": open_day, "hour": open_time[0], "minute": open_time[1]},
        "close": {"day": close_day, "hour": close_time[0], "minute": close_time[1]},
    }


def local(year, month, day, hour, minute=0, offset=ISRAEL):
    """A local wall-clock time at the given UTC offset, as an aware UTC datetime."""
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc) - timedelta(minutes=offset)


# 2026-09-20 is a Sunday
SUN, MON, TUE, FRI, SAT = 20, 21, 22, 25, 26
WEEKDAYS_10_TO_18 = [period(d, (10, 0), d, (18, 0)) for d in (1, 2, 3, 4)]


def check(periods, start, end, offset=ISRAEL):
    return hours.is_open_during(periods, offset, start, end)


class RegularHoursTests(unittest.TestCase):
    def test_visit_inside_opening_hours(self):
        self.assertTrue(check(WEEKDAYS_10_TO_18, local(2026, 9, MON, 12), local(2026, 9, MON, 13)))

    def test_visit_ending_exactly_at_closing_is_open(self):
        self.assertTrue(check(WEEKDAYS_10_TO_18, local(2026, 9, MON, 17), local(2026, 9, MON, 18)))

    def test_visit_running_past_closing_is_closed(self):
        self.assertFalse(check(WEEKDAYS_10_TO_18, local(2026, 9, MON, 17, 30), local(2026, 9, MON, 18, 30)))

    def test_visit_before_opening_is_closed(self):
        self.assertFalse(check(WEEKDAYS_10_TO_18, local(2026, 9, MON, 9), local(2026, 9, MON, 10, 30)))

    def test_closed_day(self):
        self.assertFalse(check(WEEKDAYS_10_TO_18, local(2026, 9, SUN, 12), local(2026, 9, SUN, 13)))

    def test_saturday_closed_friday_short(self):
        friday = [period(5, (9, 0), 5, (14, 0))]
        self.assertTrue(check(friday, local(2026, 9, FRI, 12), local(2026, 9, FRI, 13)))
        self.assertFalse(check(friday, local(2026, 9, FRI, 15), local(2026, 9, FRI, 16)))
        self.assertFalse(check(friday, local(2026, 9, SAT, 10), local(2026, 9, SAT, 11)))


class TimeZoneTests(unittest.TestCase):
    def test_utc_times_are_converted_with_the_places_offset(self):
        utc_start = datetime(2026, 9, MON, 9, 0, tzinfo=timezone.utc)  # 12:00 in Israel
        self.assertTrue(check(WEEKDAYS_10_TO_18, utc_start, utc_start + timedelta(hours=1)))
        self.assertFalse(check(WEEKDAYS_10_TO_18, utc_start, utc_start + timedelta(hours=1), offset=0))

    def test_negative_offset(self):
        start = local(2026, 9, MON, 12, offset=-240)
        self.assertTrue(check(WEEKDAYS_10_TO_18, start, start + timedelta(hours=1), offset=-240))


class SpecialHoursTests(unittest.TestCase):
    def test_open_all_the_time(self):
        always = [{"open": {"day": 0, "hour": 0, "minute": 0}}]
        self.assertTrue(check(always, local(2026, 9, SAT, 3), local(2026, 9, SAT, 5)))

    def test_overnight_period_covers_after_midnight(self):
        night = [period(5, (20, 0), 6, (2, 0))]
        self.assertTrue(check(night, local(2026, 9, FRI, 23), local(2026, 9, FRI, 23, 45)))
        self.assertTrue(check(night, local(2026, 9, SAT, 1), local(2026, 9, SAT, 1, 30)))
        self.assertFalse(check(night, local(2026, 9, SAT, 1, 45), local(2026, 9, SAT, 2, 15)))

    def test_visit_can_span_midnight_when_days_are_contiguous(self):
        two_days = [period(0, (0, 0), 1, (0, 0)), period(1, (0, 0), 2, (0, 0))]
        self.assertTrue(check(two_days, local(2026, 9, SUN, 23, 30), local(2026, 9, MON, 0, 30)))

    def test_period_wrapping_around_the_week(self):
        weekend_night = [period(6, (22, 0), 0, (2, 0))]
        self.assertTrue(check(weekend_night, local(2026, 9, SAT, 23), local(2026, 9, SAT, 23, 30)))
        self.assertTrue(check(weekend_night, local(2026, 9, SUN, 1), local(2026, 9, SUN, 1, 30)))
        self.assertFalse(check(weekend_night, local(2026, 9, SUN, 3), local(2026, 9, SUN, 3, 30)))

    def test_seconds_do_not_flip_the_result(self):
        start = local(2026, 9, MON, 12) + timedelta(seconds=40)
        self.assertTrue(check(WEEKDAYS_10_TO_18, start, start + timedelta(hours=1)))


class UnknownHoursTests(unittest.TestCase):
    def test_missing_periods_are_unknown(self):
        self.assertIsNone(check(None, local(2026, 9, MON, 12), local(2026, 9, MON, 13)))
        self.assertIsNone(check([], local(2026, 9, MON, 12), local(2026, 9, MON, 13)))

    def test_missing_offset_is_unknown(self):
        self.assertIsNone(
            hours.is_open_during(WEEKDAYS_10_TO_18, None, local(2026, 9, MON, 12), local(2026, 9, MON, 13))
        )


if __name__ == "__main__":
    unittest.main()
