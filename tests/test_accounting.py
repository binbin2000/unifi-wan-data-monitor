from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from custom_components.unifi_wan_data_monitor.accounting import Accounting, cycle_start
from custom_components.unifi_wan_data_monitor.models import parse_snapshot

NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)


def test_first_sample_baseline_no_historic_charge(payload):
    a = Accounting()
    a.update(parse_snapshot(payload), NOW, 1, 60)
    assert a.state["month_rx"] == a.state["month_tx"] == 0
    assert a.state["coverage"] == "partial"


def test_positive_deltas_and_ha_restart(payload):
    s = parse_snapshot(payload)
    a = Accounting()
    a.update(s, NOW, 1, 60, 20)
    restored = Accounting(json.loads(json.dumps(a.state)))
    restored.update(
        replace(s, rx=s.rx + 100, tx=s.tx + 50, uptime=s.uptime + 60),
        NOW + timedelta(seconds=60),
        1,
        60,
        20,
    )
    assert restored.state["month_rx"] == 100
    assert restored.state["month_tx"] == 50
    assert restored.state["month_offset"] == 20_000_000_000
    assert restored.state["total_rx"] == 100


def test_reboot_resets_both_directions_without_spike(payload):
    s = parse_snapshot(payload)
    a = Accounting()
    a.update(s, NOW, 1, 60)
    a.update(
        replace(s, rx=500, tx=50, uptime=10, reported_at=s.reported_at + 60),
        NOW + timedelta(seconds=60),
        1,
        60,
    )
    a.update(
        replace(s, rx=600, tx=60, uptime=70, reported_at=s.reported_at + 120),
        NOW + timedelta(seconds=120),
        1,
        60,
    )
    assert a.state["total_rx"] == 100
    assert a.state["month_tx"] == 10
    assert a.state["resets"] == 1


def test_reboot_even_when_new_counters_are_larger(payload):
    s = parse_snapshot(payload)
    a = Accounting()
    a.update(s, NOW, 1, 60)
    a.update(
        replace(s, rx=s.rx + 999, uptime=10, reported_at=s.reported_at + 60),
        NOW + timedelta(seconds=60),
        1,
        60,
    )
    assert a.state["month_rx"] == 0


def test_uptime_drop_without_newer_report_does_not_double_bill(payload):
    s = parse_snapshot(payload)
    a = Accounting()
    a.update(s, NOW, 1, 60)
    a.update(replace(s, rx=10, tx=5, uptime=10), NOW + timedelta(seconds=60), 1, 60)
    assert a.state["note"] == "unconfirmed_restart"
    a.update(replace(s, rx=s.rx + 10, tx=s.tx + 5), NOW + timedelta(seconds=120), 1, 60)
    assert a.state["month_rx"] == 10
    assert a.state["month_tx"] == 5


def test_stale_lower_sample_cannot_double_count(payload):
    s = parse_snapshot(payload)
    a = Accounting()
    a.update(s, NOW, 1, 60)
    a.update(replace(s, rx=100, tx=10), NOW + timedelta(seconds=60), 1, 60)
    a.update(replace(s, rx=s.rx + 10, tx=s.tx + 5), NOW + timedelta(seconds=120), 1, 60)
    assert a.state["total_rx"] == 10
    assert a.state["month_tx"] == 5


def test_older_reported_timestamp_is_ignored(payload):
    s = parse_snapshot(payload)
    a = Accounting()
    a.update(s, NOW, 1, 60)
    a.update(
        replace(s, rx=10, uptime=5, reported_at=s.reported_at - 60),
        NOW + timedelta(seconds=60),
        1,
        60,
    )
    assert a.state["last"]["rx"] == s.rx
    assert a.state["note"] == "stale_sample"


def test_poll_gap_is_counted_but_marked_partial(payload):
    s = parse_snapshot(payload)
    a = Accounting()
    a.update(s, NOW, 1, 60)
    a.update(replace(s, rx=s.rx + 30), NOW + timedelta(hours=2), 1, 60)
    assert a.state["month_rx"] == 30
    assert a.state["note"] == "polling_gap"


def test_cycle_boundary_drops_ambiguous_delta_and_initial_offset(payload):
    s = parse_snapshot(payload)
    a = Accounting()
    a.update(s, datetime(2026, 11, 30, 23, 59, 30, tzinfo=timezone.utc), 1, 60, 50)
    a.update(replace(s, rx=s.rx + 100), datetime(2026, 12, 1, tzinfo=timezone.utc), 1, 60, 50)
    assert a.state["month_rx"] == a.state["month_offset"] == 0
    assert a.state["total_rx"] == 100


def test_decrease_at_cycle_boundary_cannot_later_charge_old_cycle(payload):
    s = parse_snapshot(payload)
    a = Accounting()
    before = datetime(2026, 11, 30, 23, 59, 30, tzinfo=timezone.utc)
    after = datetime(2026, 12, 1, tzinfo=timezone.utc)
    a.update(s, before, 1, 60)
    a.update(replace(s, rx=1, tx=1), after, 1, 60)
    a.update(replace(s, rx=s.rx + 10, tx=s.tx + 5), after + timedelta(seconds=60), 1, 60)
    assert a.state["month_rx"] == a.state["month_tx"] == 0
    assert a.state["total_rx"] == 10


@pytest.mark.parametrize(
    "date,day,expected",
    [
        ("2026-11-02", 15, "2026-10-15"),
        ("2026-11-15", 15, "2026-11-15"),
        ("2026-03-01", 31, "2026-02-28"),
        ("2028-02-29", 31, "2028-02-29"),
        ("2027-01-01", 2, "2026-12-02"),
        ("2026-04-30", 31, "2026-04-30"),
    ],
)
def test_billing_dates(date, day, expected):
    assert cycle_start(datetime.fromisoformat(date), day) == expected


def test_timezone_uses_local_calendar():
    local = datetime(2026, 12, 1, 0, 1, tzinfo=timezone(timedelta(hours=1)))
    assert cycle_start(local, 1) == "2026-12-01"


def test_backwards_clock_and_source_change(payload):
    s = parse_snapshot(payload)
    a = Accounting()
    a.update(s, NOW, 1, 60)
    a.update(replace(s, rx=s.rx + 100), NOW - timedelta(seconds=1), 1, 60)
    assert a.state["last"]["rx"] == s.rx
    a.update(
        replace(s, mac="02:00:00:00:00:02", rx=900000000000), NOW + timedelta(seconds=60), 1, 60
    )
    assert a.state["month_rx"] == 0
    assert a.state["note"] == "source_changed"
