"""Slot generation — a barber's open time windows for a day."""

from datetime import date, datetime, timedelta

from app.models import WorkingHours

# A busy stretch of the day: [start, end). Appointments, breaks and closures all
# reduce to these, so a candidate slot is free when it overlaps none of them.
Interval = tuple[datetime, datetime]


def free_slots(
    hours: WorkingHours,
    day: date,
    busy: list[Interval],
    now: datetime,
    duration_minutes: int,
    step_minutes: int,
) -> list[datetime]:
    """Open start-times (naive, shop-local) for a service of a given length.

    Start times fall on a fixed grid stepped by ``step_minutes`` from the day's
    work start — 09:00, 09:15, 09:30, … The step is the barber's finest common
    service length (see ``available_slots``), so every service shares one grid
    and none can leave an unusable sliver behind. A slot is kept when its whole
    window fits inside the working day, sits clear of the lunch break and of
    everything already booked, and isn't in the past. So a 15-minute booking at
    09:00 lets a 30-minute cut start at 09:15 *and* 09:30, never only 09:15.
    """
    duration = timedelta(minutes=duration_minutes)
    step = timedelta(minutes=step_minutes)
    work_start = datetime.combine(day, hours.start_time)
    work_end = datetime.combine(day, hours.end_time)

    blocks = list(busy)
    if hours.break_start is not None and hours.break_end is not None:
        blocks.append(
            (
                datetime.combine(day, hours.break_start),
                datetime.combine(day, hours.break_end),
            )
        )

    slots: list[datetime] = []
    slot = work_start
    while slot + duration <= work_end:
        end = slot + duration
        clear = all(end <= b_start or slot >= b_end for b_start, b_end in blocks)
        if slot >= now and clear:
            slots.append(slot)
        slot += step
    return slots
