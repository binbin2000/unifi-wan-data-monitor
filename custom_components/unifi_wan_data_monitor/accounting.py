"""Persistent, conservative counter accounting independent of Home Assistant."""

from calendar import monthrange
from copy import deepcopy
from datetime import datetime

from .models import Snapshot


def cycle_start(now: datetime, day: int) -> str:
    """Billing cycle starts at local midnight; 29–31 clamp to month's end."""
    year, month = now.year, now.month
    if now.day < min(day, monthrange(year, month)[1]):
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return f"{year:04d}-{month:02d}-{min(day, monthrange(year, month)[1]):02d}"


class Accounting:
    """Only observed positive deltas are billed; uncertain intervals are flagged."""

    def __init__(self, saved: dict | None = None):
        self.state = (
            deepcopy(saved)
            if saved
            else {
                "last": None,
                "cycle": None,
                "billing_day": None,
                "month_rx": 0,
                "month_tx": 0,
                "month_offset": 0,
                "total_rx": 0,
                "total_tx": 0,
                "resets": 0,
                "coverage": "partial",
                "note": "first_sample",
            }
        )

    def update(
        self,
        snap: Snapshot,
        now: datetime,
        day: int,
        poll_interval: int,
        initial_used_gb: float = 0,
    ) -> dict:
        state = self.state
        cycle = cycle_start(now, day)
        previous = state["last"]
        if previous and now.timestamp() <= previous["time"]:
            return state  # Never move baselines backwards after clock changes.
        if (
            previous
            and snap.reported_at is not None
            and previous.get("reported_at") is not None
            and snap.reported_at < previous["reported_at"]
        ):
            state.update(coverage="partial", note="stale_sample")
            return state
        changed_day = state["billing_day"] not in (None, day)
        new_cycle = state["cycle"] != cycle or changed_day
        if new_cycle:
            state.update(
                cycle=cycle,
                billing_day=day,
                month_rx=0,
                month_tx=0,
                month_offset=round(initial_used_gb * 1_000_000_000) if previous is None else 0,
                coverage="partial",
                note="billing_day_changed" if changed_day else "cycle_boundary",
            )
        source = f"{snap.mac}/{snap.interface}/{snap.counter_source}"
        if previous is None:
            state["note"] = "first_sample"
        elif previous["source"] != source:
            state.update(coverage="partial", note="source_changed")
        else:
            reset = (
                snap.uptime is not None
                and previous["uptime"] is not None
                and snap.uptime < previous["uptime"]
            )
            dx, dt = snap.rx - previous["rx"], snap.tx - previous["tx"]
            if reset and not (
                snap.reported_at is not None
                and previous.get("reported_at") is not None
                and snap.reported_at > previous["reported_at"]
            ):
                state.update(coverage="partial", note="unconfirmed_restart")
                return state
            if reset:
                # Re-baseline BOTH directions. A reset/wrap/stale sample is ambiguous:
                # counting the new value as a delta can create false multi-GB charges.
                state["resets"] += 1
                state.update(coverage="partial", note="counter_reset")
            elif dx < 0 or dt < 0:
                # Without a confirmed reboot, retain the high-water mark. A stale
                # lower sample followed by a current sample must not be double billed.
                if state["note"] != "counter_decrease":
                    state["resets"] += 1
                state.update(coverage="partial", note="counter_decrease")
                return state
            else:
                state["total_rx"] += dx
                state["total_tx"] += dt
                if (
                    not new_cycle
                    and previous.get("cycle", cycle) == cycle
                    and previous.get("billing_day", day) == day
                ):
                    state["month_rx"] += dx
                    state["month_tx"] += dt
                # A delta crossing midnight cannot be attributed exactly. Lifetime
                # receives it, monthly drops it rather than charging the wrong cycle.
                if now.timestamp() - previous["time"] > poll_interval * 2.5:
                    state.update(coverage="partial", note="polling_gap")
        state["last"] = {
            "rx": snap.rx,
            "tx": snap.tx,
            "uptime": snap.uptime,
            "source": source,
            "time": now.timestamp(),
            "reported_at": snap.reported_at,
            "cycle": cycle,
            "billing_day": day,
        }
        return state
