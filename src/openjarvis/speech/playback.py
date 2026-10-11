"""Play an audio file through whatever command-line player the OS provides."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)

# afplay first: it ships with macOS, where unattended digests are played.
_PLAYERS = (
    ["afplay"],
    ["ffplay", "-nodisp", "-autoexit"],
    ["paplay"],
    ["aplay"],
)

# Generous enough for a long digest; stops a wedged player from holding the
# caller's thread forever.
_TIMEOUT_S = 900


def play_audio(path: Union[str, Path]) -> bool:
    """Play *path* to completion with the first player that works.

    Returns ``False`` if the path is unusable, no player is installed, every
    player failed, or playback exceeded the timeout. Never raises.
    """
    # subprocess raises ValueError for NUL bytes in argv; no player could open it.
    if "\x00" in str(path):
        logger.warning("Refusing to play audio path containing a NUL byte")
        return False
    for player in _PLAYERS:
        try:
            subprocess.run(
                [*player, str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=_TIMEOUT_S,
            )
            return True
        except subprocess.TimeoutExpired:
            # Retrying with another player would replay audio already heard.
            logger.warning("Audio playback with %s timed out", player[0])
            return False
        except (OSError, subprocess.CalledProcessError):
            continue
    logger.warning("No audio player could play %s", path)
    return False


__all__ = ["play_audio"]
