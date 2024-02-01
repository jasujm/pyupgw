"""CLI logging"""

import logging

from rich.console import Console
from rich.logging import RichHandler

_LOGGING_HANDLER = RichHandler()


def setup_logging(handlers=None, **kwargs):
    """Setup logging"""
    handlers = [*(handlers or []), _LOGGING_HANDLER]
    logging.basicConfig(handlers=handlers, **kwargs)


def set_logging_console(console: Console):
    """Set new logging console"""
    _LOGGING_HANDLER.console = console
