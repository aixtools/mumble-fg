from __future__ import annotations

import logging
import sys
from typing import Iterable

from django.conf import settings


DEFAULT_LOG_FILE = "/var/tmp/monitor.log"


def configure_logging(fg: bool = False) -> None:
    """
    Configure app logging.

    When fg=True, log to stdout regardless of settings.
    Otherwise log to LOG_FILE if set, or
    DEFAULT_LOG_FILE (/var/tmp/monitor.log).
    """
    log_level = getattr(
        settings, "LOG_LEVEL", "INFO"
    ).upper()

    handlers: Iterable[logging.Handler]
    if fg:
        handlers = [logging.StreamHandler(sys.stdout)]
    else:
        log_file = getattr(
            settings, "LOG_FILE", None
        ) or DEFAULT_LOG_FILE
        handlers = [logging.FileHandler(log_file)]

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=list(handlers),
    )
