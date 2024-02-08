"""CLI logging"""

import logging
import logging.config

import yaml
from rich.logging import RichHandler


def _setup_logging_basic():
    logging.basicConfig(handlers=[RichHandler()])
    logging.getLogger("pyupgw.cli").setLevel(logging.INFO)


def _setup_logging_file(config_file: str):
    with open(config_file, encoding="utf-8") as f:
        config = yaml.load(f, Loader=yaml.Loader)
    logging.config.dictConfig(config)


def setup_logging(config_file: str | None = None):
    """Setup logging"""
    if config_file:
        _setup_logging_file(config_file)
    else:
        _setup_logging_basic()
