from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime


@dataclass
class HolderDelta:
    holder: str
    old_shares: int
    new_shares: int

    @property
    def change(self) -> int:
        return self.new_shares - self.old_shares


def compute_holder_deltas(previous: list[dict], current: list[dict]) -> list[HolderDelta]:
    prev_map = {item["holder"]: int(item["shares"]) for item in previous}
    curr_map = {item["holder"]: int(item["shares"]) for item in current}

    all_holders = set(prev_map) | set(curr_map)
    deltas: list[HolderDelta] = []
    for holder in sorted(all_holders):
        old = prev_map.get(holder, 0)
        new = curr_map.get(holder, 0)
        if old != new:
            deltas.append(HolderDelta(holder=holder, old_shares=old, new_shares=new))
    return deltas


def rolling_window_changes(records: list[dict], days: int = 30) -> dict[str, int]:
    if not records:
        return {}

    by_holder: dict[str, list[tuple[datetime, int]]] = defaultdict(list)
    for record in records:
        timestamp = record["observed_at"]
        for item in record.get("holders", []):
            by_holder[item["holder"]].append((timestamp, int(item["shares"])))

    changes: dict[str, int] = {}
    for holder, values in by_holder.items():
        values.sort(key=lambda x: x[0])
        if len(values) < 2:
            continue
        first = values[0][1]
        last = values[-1][1]
        if first != last:
            changes[holder] = last - first

    return changes
