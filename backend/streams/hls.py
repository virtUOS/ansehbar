# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Minimal HLS playlist parsing (only the tags ansehBAR needs)."""


def parse_master(text: str) -> list[str]:
    """Return variant URIs of a master playlist, in order of appearance."""
    lines = [line.strip() for line in text.splitlines()]
    uris = []
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF"):
            for nxt in lines[i + 1 :]:
                if nxt and not nxt.startswith("#"):
                    uris.append(nxt)
                    break
    return uris


def parse_media(text: str) -> tuple[int | None, float | None]:
    """Return (media_sequence, target_duration) of a media playlist."""
    sequence = None
    target = None
    for line in text.splitlines():
        line = line.strip()
        try:
            if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
                sequence = int(line.split(":", 1)[1])
            elif line.startswith("#EXT-X-TARGETDURATION:"):
                target = float(line.split(":", 1)[1])
        except ValueError:
            continue
    return sequence, target
