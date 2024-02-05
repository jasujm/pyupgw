"""CLI logging"""

import json
import logging
import logging.config

import yaml
from rich.logging import RichHandler

from pyupgw._helpers import LazyEncode

# This is not pretty, but it's just the most foolproof way to ensure
# `LazyEncode` objects always get serialized properly


class _MyJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, LazyEncode):
            return o.encode()
        return super().default(o)


_original_json_dumps = json.dumps


def _new_json_dumps(*args, **kwargs):
    kwargs["cls"] = _MyJSONEncoder
    return _original_json_dumps(*args, **kwargs)


json.dumps = _new_json_dumps


def _setup_logging_basic():
    logging.basicConfig(handlers=[RichHandler()])
    logging.getLogger("pyupgw").setLevel(logging.INFO)


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
