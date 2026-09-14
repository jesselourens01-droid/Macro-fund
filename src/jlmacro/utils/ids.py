"""Unique ID generation for signals, models, trades, orders, portfolio snapshots."""

from __future__ import annotations

import uuid


def new_id(prefix: str = "") -> str:
    value = str(uuid.uuid4())
    return f"{prefix}{value}" if prefix else value
