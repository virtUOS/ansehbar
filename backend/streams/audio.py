# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Audio level measurement with ffmpeg. Plain Python, no Django imports."""

import re
import shutil
import subprocess
from dataclasses import dataclass

PROTOCOL_WHITELIST = "http,https,tls,tcp,crypto,hls"
_MEAN_VOLUME = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?|-inf)\s*dB")
_NO_AUDIO = "matches no streams"


@dataclass(frozen=True)
class AudioMeasurement:
    ok: bool  # False: ffmpeg failed (network, timeout, no samples, missing)
    level_db: float | None  # mean dBFS; None with ok=True = no audio track
    detail: str = ""


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def ffmpeg_command(url: str, seconds: int) -> list[str]:
    """Argument list (never a shell string); the URL is passed through as is."""
    return [
        "ffmpeg", "-nostdin", "-hide_banner", "-nostats",
        "-loglevel", "info",
        "-rw_timeout", "10000000",
        "-protocol_whitelist", PROTOCOL_WHITELIST,
        "-i", url,
        "-map", "0:a:0",
        "-t", str(seconds),
        "-af", "volumedetect",
        "-f", "null", "-",
    ]


def parse_volumedetect(stderr: str) -> float | None:
    match = _MEAN_VOLUME.search(stderr or "")
    if not match:
        return None
    value = float(match.group(1))  # "-inf" parses to -inf (digital silence)
    return value


def measure_audio(
    url: str, seconds: int = 10, runner=subprocess.run
) -> AudioMeasurement:
    try:
        proc = runner(
            ffmpeg_command(url, seconds),
            capture_output=True,
            text=True,
            timeout=seconds + 30,
        )
    except subprocess.TimeoutExpired:
        return AudioMeasurement(False, None, "ffmpeg timed out")
    except OSError as exc:  # FileNotFoundError: ffmpeg missing
        return AudioMeasurement(False, None, f"{type(exc).__name__}: {exc}"[:200])
    stderr = proc.stderr or ""
    level = parse_volumedetect(stderr)
    if level is not None:  # a level counts before the return code
        return AudioMeasurement(True, level)
    if _NO_AUDIO in stderr:
        return AudioMeasurement(True, None, "no audio track")
    tail = stderr.strip().splitlines()[-1:] or [f"ffmpeg exit {proc.returncode}"]
    return AudioMeasurement(False, None, tail[0][:200])
