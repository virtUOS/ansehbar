# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""The "stream is missing right now" rule, shared by the API and the monitor."""
from datetime import datetime, timedelta

from recorders.models import RecorderStatus


def missing_since(
    active: bool,
    state: str,
    offline_since: datetime | None,
    current_event,
    now: datetime,
    grace: timedelta,
) -> datetime | None:
    """Since when the stream is missing during the current event, else None.

    Missing = active recorder, an event running now, status offline and the
    grace period after the event start over. Unknown is never missing.
    """
    if not active or state != RecorderStatus.OFFLINE or current_event is None:
        return None
    threshold = current_event.start + grace
    if now < threshold:
        return None
    return max(threshold, offline_since) if offline_since else threshold
