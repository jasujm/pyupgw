"""Command line interface"""

# pylint: disable=wrong-import-position,wrong-import-order,redefined-builtin

from dotenv import load_dotenv

load_dotenv()

import asyncio
import functools
import os
import sys
import typing
from collections.abc import Iterable

import rich_click as click
from rich.console import Console
from rich.live import Live
from rich.table import Table

from pyupgw import Client, Device, Gateway, HvacDevice, SystemMode, create_client

from ._logging import setup_logging
from .commands import get as get_impl
from .commands import list_devices as list_impl
from .commands import update as update_impl
from .tui import tui


@click.group(invoke_without_command=True)
@click.option(
    "-u",
    "--username",
    help="Unisenza Plus user. Alternatively can be loaded from the PYUPGW_USERNAME environment variable.",
)
@click.option(
    "-p",
    "--password",
    help="Password for the user. Alternatively can be loaded from the PYUPGW_PASSWORD environment variable.",
)
@click.option(
    "--logging-config", help="YAML file containing logging config for the application"
)
@click.pass_context
def cli(
    ctx: click.Context,
    username: str | None,
    password: str | None,
    logging_config: str | None,
):
    """Command-line interface for Unisenza Plus

    When invoked without subcommand, starts the client in interactive mode.

    The author of this tool is not affiliated with Purmo, the vendor of Unisenza
    Plus, in any way.  The tool and its conformance to the Unisenza Plus API is
    implemented on a best-effort basis.  No warranty of any kind is provided.
    """

    setup_logging(logging_config)

    username = username or os.getenv("PYUPGW_USERNAME")
    password = password or os.getenv("PYUPGW_PASSWORD")

    if not username or not password:
        click.echo("Username and password required")
        sys.exit(0)

    ctx.obj = {
        "username": username,
        "password": password,
    }

    if ctx.invoked_subcommand is None:
        tui(username, password)


def with_client(func):
    """Decorate for a command that gets client as first argument"""

    @functools.wraps(func)
    @click.pass_context
    def inner(ctx: click.Context, *args, **kwargs):
        async def _inner_async(*args, **kwargs):
            async with create_client(**ctx.obj) as client:
                return await func(client, *args, **kwargs)

        return asyncio.run(_inner_async(*args, **kwargs))

    return inner


@cli.command()
@with_client
async def list(client: Client):
    """Print list of gateways and devices with details"""

    return await list_impl(client)


@cli.command()
@click.argument("device", required=True)
@with_client
async def get(client: Client, device: str):
    """Print details of a single device

    The DEVICE can be identified either by id, name or device code."""

    return await get_impl(client, device)


@cli.command()
@click.argument("device", required=True)
@click.option("--temperature", "-t", type=float, help="New target temperature")
@click.option(
    "--system-mode",
    "-s",
    type=click.Choice([sm.name for sm in SystemMode]),
    help="New system mode",
)
@with_client
async def update(
    client: Client, device: str, temperature: float | None, system_mode: str | None
):
    """Update the state of a device

    The DEVICE can be identified either by id, name or device code."""

    system_mode_enum = SystemMode[system_mode] if system_mode is not None else None

    return await update_impl(client, device, temperature, system_mode_enum)
