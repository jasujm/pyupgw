"""CLI logging"""

import logging

from rich.logging import RichHandler


def setup_logging(handlers=None, **kwargs):
    """Setup logging"""
    handlers = [*(handlers or []), RichHandler()]
    logging.basicConfig(handlers=handlers, **kwargs)
