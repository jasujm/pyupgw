"""Command line interface"""

# pylint: disable=wrong-import-position,wrong-import-order

from dotenv import load_dotenv

load_dotenv()

import asyncio
import os
import typing
from collections.abc import Iterable

import rich_click as click
from rich.console import Console
from rich.live import Live
from rich.table import Table

from pyupgw import Device, Gateway, HvacDevice, create_client


def _summary_table(devices: Iterable[tuple[Gateway, HvacDevice]]):
    table = Table(title="Device summary")
    table.add_column("Device")
    table.add_column("State")
    table.add_column("Temperature")
    table.add_column("Current temperature")

    for _, device in devices:
        table.add_row(
            device.get_name(),
            str(
                system_mode.name if (system_mode := device.get_system_mode()) else None
            ),
            str(device.get_temperature()),
            str(device.get_current_temperature()),
        )

    return table


async def _async_main(username: str, password: str):
    queue: asyncio.Queue[tuple[Device, typing.Any]] = asyncio.Queue()

    def enqueue_change(device: Device, changes: typing.Any):
        queue.put_nowait((device, changes))

    async with create_client(username, password) as client:
        await client.refresh_all_devices()
        for _, device in client.get_devices():
            device.subscribe(enqueue_change)
        with Live(_summary_table(client.get_devices())) as live:
            while True:
                changed_device, changes = await queue.get()
                live.console.log(f"{changed_device.get_name()} changed:", changes)
                live.update(_summary_table(client.get_devices()))


@click.command()
@click.option(
    "-u",
    "--username",
    help="Unisenza Plus user. Alternatively can be loaded from the PYUPGW_USERNAME environment variable.",
)
@click.option(
    "-p",
    "--password",
    help="Password for logging into Unisenza Plus. Alternatively can be loaded from the PYUPGW_PASSWORD environment variable.",
)
def cli(username: str | None, password: str | None):
    """Command-line interface for Unisenza Plus

    The author of this tool is not affiliated with Purmo, the vendor of Unisenza
    Plus product line.  The tool is written on a best-effort basis correctness
    is not guaranteed.
    """
    username = username or os.getenv("PYUPGW_USERNAME")
    password = password or os.getenv("PYUPGW_PASSWORD")
    if not username or not password:
        click.echo("Username and password required")
    else:
        asyncio.run(_async_main(username, password))
