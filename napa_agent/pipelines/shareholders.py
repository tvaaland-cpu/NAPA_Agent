from __future__ import annotations

from datetime import datetime
from email.utils import format_datetime
from zoneinfo import ZoneInfo

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apscheduler.schedulers.base import BaseScheduler
    from napa_agent.config import Settings
else:
    BaseScheduler = Any
from napa_agent.db import (
    fetch_latest_shareholder_snapshot,
    fetch_shareholder_snapshot,
    fetch_snapshot_nearest_to,
    insert_shareholder_run,
    insert_shareholder_snapshot,
)
from napa_agent.notify.emailer import send_email
from napa_agent.sources.napatech_shareinfo import fetch_shareholders

OSLO_TZ = ZoneInfo("Europe/Oslo")
MONDAY_ATTEMPTS = (13, 14, 15, 16)
ROLLING_MONTH_WINDOWS = (1, 3, 6, 9, 12)


def run_shareholders_pipeline(engine, settings: Settings) -> list[str]:
    snapshot = fetch_shareholders(settings.napatech_shareinfo_url)
    if not snapshot.rows:
        return []

    changed, snapshot_id = insert_shareholder_snapshot(engine, snapshot, attempt_hour=snapshot.fetched_at.hour)
    if not changed:
        return ["Shareholder snapshot unchanged"]
    return [f"Stored shareholder snapshot #{snapshot_id} with {len(snapshot.rows)} rows"]


def shareholders_check(
    engine,
    settings: Settings,
    *,
    attempt: int | None = None,
    scheduler: BaseScheduler | None = None,
    force: bool = False,
) -> list[str]:
    now_oslo = datetime.now(OSLO_TZ)
    attempt_hour = attempt or now_oslo.hour
    is_monday = now_oslo.weekday() == 0
    
    # Check gating: only run on Monday or if forced
    if not force and not is_monday:
        insert_shareholder_run(
            engine,
            attempt_hour=attempt_hour,
            updated_changed_bool=False,
            notes="skipped: not Monday",
        )
        return ["Skipped: not Monday"]

    # For scheduled (non-force) Monday runs at 13:00, schedule retries
    monday_key = now_oslo.strftime("%Y%m%d")
    if attempt_hour == 13 and not force and scheduler is not None:
        _schedule_retry_attempts(scheduler, now_oslo, monday_key, engine, settings)

    # Fetch and process
    try:
        previous_snapshot = fetch_latest_shareholder_snapshot(engine)
        snapshot = fetch_shareholders(settings.napatech_shareinfo_url)
        
        # insert_shareholder_snapshot will insert a run row with proper updated_changed_bool
        changed, snapshot_id = insert_shareholder_snapshot(
            engine,
            snapshot,
            attempt_hour=attempt_hour,
            notes="ok",
        )

        # Email on: (1) change detected, (2) force run, or (3) final attempt on Monday
        should_email = changed or force or (is_monday and attempt_hour >= 16)
        
        if should_email:
            if changed and snapshot_id is not None:
                current_snapshot = fetch_shareholder_snapshot(engine, snapshot_id)
                if current_snapshot is None:
                    return ["Snapshot inserted but unavailable for reporting"]

                report = _build_update_report(engine, previous_snapshot, current_snapshot)
                subject = "NAPA Monday Top-20 update"
                body = f"Monday Top-20 update detected at {attempt_hour:02d}:00 Europe/Oslo.\n\n{report}"
            else:
                # No change but emailing (force or final attempt)
                report = _build_unchanged_report(previous_snapshot)
                subject = (
                    "NAPA Manual Top-20 Check" if force
                    else "NAPA Monday Top-20 unchanged"
                )
                body = (
                    f"Manual force run completed.\n\n{report}"
                    if force
                    else f"Monday Top-20 unchanged by 16:00 Europe/Oslo.\nFinal decision: assumed unchanged for this Monday.\n\n{report}"
                )
            
            send_email(settings, subject, body)

        # Cancel remaining retry jobs if we found a change (and not a force run)
        if changed and not force and is_monday and scheduler is not None:
            _cancel_remaining_attempts(scheduler, monday_key, attempt_hour)

        if changed:
            return [f"Top-20 updated at {attempt_hour:02d}:00; sent summary email"]
        elif force:
            return [f"Manual force run completed; no changes detected"]
        elif attempt_hour >= 16:
            return [f"No update by 16:00; assumed unchanged for this Monday"]
        else:
            return [f"No Top-20 update at {attempt_hour:02d}:00; retry remains scheduled"]

    except Exception as exc:
        # Always record the error, then re-raise for scheduler/CLI failure visibility.
        insert_shareholder_run(
            engine,
            attempt_hour=attempt_hour,
            updated_changed_bool=False,
            notes=f"error: {str(exc)}",
        )
        raise


def _schedule_retry_attempts(
    scheduler: BaseScheduler | None,
    now_oslo: datetime,
    monday_key: str,
    engine,
    settings: Settings,
) -> None:
    if scheduler is None:
        return
    for hour in MONDAY_ATTEMPTS[1:]:
        job_id = f"monday_top20_{hour:02d}_{monday_key}"
        if scheduler.get_job(job_id) is not None:
            continue
        run_time = now_oslo.replace(hour=hour, minute=0, second=0, microsecond=0)
        scheduler.add_job(
            shareholders_check,
            trigger="date",
            run_date=run_time,
            args=[engine, settings],
            kwargs={"attempt": hour, "scheduler": scheduler},
            id=job_id,
            replace_existing=True,
        )


def _cancel_remaining_attempts(scheduler: BaseScheduler | None, monday_key: str, attempt_hour: int) -> None:
    if scheduler is None:
        return
    for hour in MONDAY_ATTEMPTS:
        if hour <= attempt_hour:
            continue
        job_id = f"monday_top20_{hour:02d}_{monday_key}"
        if scheduler.get_job(job_id) is not None:
            scheduler.remove_job(job_id)


def _build_update_report(engine, previous: dict | None, current: dict) -> str:
    prev_rows = previous["rows"] if previous else []
    curr_rows = current["rows"]

    prev_map = {row["holder_name"]: row for row in prev_rows}
    curr_map = {row["holder_name"]: row for row in curr_rows}

    entrants = sorted(name for name in curr_map if name not in prev_map)
    exits = sorted(name for name in prev_map if name not in curr_map)

    rank_changes: list[tuple[str, int, int]] = []
    share_changes: list[tuple[str, int]] = []
    for holder, row in curr_map.items():
        old = prev_map.get(holder)
        if old is None:
            continue
        if old["rank"] != row["rank"]:
            rank_changes.append((holder, old["rank"], row["rank"]))
        delta = int(row["shares"]) - int(old["shares"])
        if delta != 0:
            share_changes.append((holder, delta))

    share_changes.sort(key=lambda item: abs(item[1]), reverse=True)

    lines = [
        "Week-over-week Top-20 delta",
        f"- Entrants: {_format_name_list(entrants)}",
        f"- Exits: {_format_name_list(exits)}",
        "- Rank changes: " + (_format_rank_changes(rank_changes) if rank_changes else "none"),
        "- Biggest share changes: " + (_format_share_changes(share_changes[:5]) if share_changes else "none"),
        _totals_section(prev_rows, curr_rows),
        _rolling_window_section(engine, current),
        "",
        _current_top20_section(curr_rows),
    ]
    return "\n".join(lines)


def _build_unchanged_report(previous: dict | None) -> str:
    if previous is None:
        return "No historical Top-20 snapshot exists yet."

    snapshot_dt = previous["snapshot_dt"].astimezone(OSLO_TZ)
    lines = [
        "No changes detected from previous snapshot: "
        f"#{previous['snapshot_id']} from {format_datetime(snapshot_dt)}",
        "",
        _current_top20_section(previous.get("rows", [])),
    ]
    return "\n".join(lines)


def _totals_section(prev_rows: list[dict], curr_rows: list[dict]) -> str:
    prev_shares = sum(int(row["shares"]) for row in prev_rows)
    curr_shares = sum(int(row["shares"]) for row in curr_rows)
    prev_pct = sum(float(row.get("pct") or 0.0) for row in prev_rows)
    curr_pct = sum(float(row.get("pct") or 0.0) for row in curr_rows)

    return (
        "- Top-20 totals: "
        f"shares {curr_shares:,} ({curr_shares - prev_shares:+,} WoW), "
        f"pct {curr_pct:.2f}% ({curr_pct - prev_pct:+.2f} pp WoW)"
    )


def _current_top20_section(rows: list[dict]) -> str:
    """Format current Top-20 shareholders as a readable list."""
    if not rows:
        return "Current Top-20: (no data)"
    
    lines = ["Current Top-20 shareholders:"]
    total_shares = 0
    total_pct = 0.0
    
    for row in rows[:20]:
        rank = row.get("rank", "?")
        name = row.get("holder_name", "?")
        shares = int(row.get("shares") or 0)
        pct = float(row.get("pct") or 0.0)
        holder_type = row.get("holder_type") or ""
        
        total_shares += shares
        total_pct += pct
        
        type_str = f" ({holder_type})" if holder_type else ""
        lines.append(f"  {rank:2}. {name:<45} {shares:>10,} shares {pct:>6.2f}%{type_str}")
    
    lines.append(f"  ---")
    lines.append(f"  Total: {total_shares:>45,} shares {total_pct:>6.2f}%")
    
    return "\n".join(lines)


def _rolling_window_section(engine, current: dict) -> str:
    current_rows = {row["holder_name"]: int(row["shares"]) for row in current["rows"]}
    current_dt = current["snapshot_dt"]

    summaries: list[str] = []
    for months in ROLLING_MONTH_WINDOWS:
        target_dt = _shift_months(current_dt, months)
        nearest = fetch_snapshot_nearest_to(engine, target_dt)
        if nearest is None:
            summaries.append(f"{months}m: n/a")
            continue

        nearest_rows = {row["holder_name"]: int(row["shares"]) for row in nearest["rows"]}
        delta = sum(
            current_rows.get(holder, 0) - nearest_rows.get(holder, 0)
            for holder in set(current_rows) | set(nearest_rows)
        )
        summaries.append(f"{months}m vs #{nearest['snapshot_id']}: {delta:+,} shares")

    return "- Rolling windows: " + "; ".join(summaries)


def _shift_months(dt: datetime, months: int) -> datetime:
    year = dt.year
    month = dt.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(dt.day, 28)
    return dt.replace(year=year, month=month, day=day)


def _format_name_list(names: list[str]) -> str:
    return ", ".join(names) if names else "none"


def _format_rank_changes(changes: list[tuple[str, int, int]]) -> str:
    ordered = sorted(changes, key=lambda item: abs(item[1] - item[2]), reverse=True)
    return "; ".join(f"{name} {old}->{new}" for name, old, new in ordered[:8])


def _format_share_changes(changes: list[tuple[str, int]]) -> str:
    return "; ".join(f"{name} {delta:+,}" for name, delta in changes)
