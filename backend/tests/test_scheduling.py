"""Unit tests for the pure slot-generation logic."""

from datetime import date, datetime, time, timedelta

from app.models import Weekday, WorkingHours
from app.scheduling import free_slots

DAY = date(2030, 1, 7)
PAST = datetime(2000, 1, 1)


def hours(**overrides: object) -> WorkingHours:
    defaults: dict[str, object] = {
        "barber_id": 1,
        "weekday": Weekday.MONDAY,
        "start_time": time(9, 0),
        "end_time": time(17, 0),
    }
    defaults.update(overrides)
    return WorkingHours(**defaults)  # type: ignore[arg-type]


def booking(hour: int, minute: int, minutes: int) -> tuple[datetime, datetime]:
    start = datetime(2030, 1, 7, hour, minute)
    return (start, start + timedelta(minutes=minutes))


def test_full_day_has_16_half_hour_slots():
    slots = free_slots(hours(), DAY, [], PAST, 30, 30)
    assert slots[0] == datetime(2030, 1, 7, 9, 0)
    assert slots[-1] == datetime(2030, 1, 7, 16, 30)
    assert len(slots) == 16


def test_the_grid_step_is_independent_of_service_length():
    # Every service starts on the same fixed grid (here 15 min), whatever its
    # own length — so a 60-minute and a 15-minute service share start times.
    hourly = free_slots(hours(), DAY, [], PAST, 60, 15)
    assert hourly[:2] == [datetime(2030, 1, 7, 9, 0), datetime(2030, 1, 7, 9, 15)]
    assert hourly[-1] == datetime(2030, 1, 7, 16, 0)
    quarter = free_slots(hours(), DAY, [], PAST, 15, 15)
    assert quarter[:2] == [datetime(2030, 1, 7, 9, 0), datetime(2030, 1, 7, 9, 15)]
    assert len(quarter) == 32


def test_a_longer_service_needs_room_to_finish():
    # A 90-minute service can't start once too little of the day remains.
    slots = free_slots(hours(), DAY, [], PAST, 90, 30)
    assert slots[-1] == datetime(2030, 1, 7, 15, 30)


def test_lunch_break_is_excluded():
    slots = free_slots(
        hours(break_start=time(12, 0), break_end=time(13, 0)), DAY, [], PAST, 30, 30
    )
    assert datetime(2030, 1, 7, 12, 0) not in slots
    assert datetime(2030, 1, 7, 12, 30) not in slots
    assert len(slots) == 14


def test_booked_slots_are_excluded():
    slots = free_slots(hours(), DAY, [booking(9, 0, 30)], PAST, 30, 30)
    assert datetime(2030, 1, 7, 9, 0) not in slots
    assert len(slots) == 15


def test_a_partial_overlap_blocks_the_slot():
    # A 15-minute booking at 09:15 still spoils the 09:00 half-hour window.
    slots = free_slots(hours(), DAY, [booking(9, 15, 15)], PAST, 30, 15)
    assert datetime(2030, 1, 7, 9, 0) not in slots
    assert datetime(2030, 1, 7, 9, 30) in slots


def test_slots_pack_against_an_earlier_booking():
    # A 15-minute booking ending at 09:15 lets a 30-minute service start at
    # 09:15 *and* 09:30 — the fixed 15-min grid never skips 09:30.
    slots = free_slots(hours(), DAY, [booking(9, 0, 15)], PAST, 30, 15)
    assert slots[0] == datetime(2030, 1, 7, 9, 15)
    assert slots[1] == datetime(2030, 1, 7, 9, 30)


def test_past_slots_are_excluded():
    now = datetime(2030, 1, 7, 12, 0)
    slots = free_slots(hours(), DAY, [], now, 30, 30)
    assert all(slot >= now for slot in slots)
    assert slots[0] == now
