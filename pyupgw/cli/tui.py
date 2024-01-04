"""Interactive text-user interface"""

import asyncio
import typing
from collections.abc import Iterable

from rich.live import Live
from rich.table import Table

from pyupgw import Client, Device, Gateway, HvacDevice


def _summary_table(devices: Iterable[tuple[Gateway, HvacDevice]]):
    table = Table(title="Device summary")
    table.add_column("Device")
    table.add_column("Gateway")
    table.add_column("State")
    table.add_column("Temperature")
    table.add_column("Current temperature")

    for gateway, device in devices:
        table.add_row(
            device.get_name(),
            gateway.get_name(),
            str(
                system_mode.name if (system_mode := device.get_system_mode()) else None
            ),
            str(device.get_temperature()),
            str(device.get_current_temperature()),
        )

    return table


async def tui(client: Client):
    """Text-user interface"""

    queue: asyncio.Queue[tuple[Device, typing.Any]] = asyncio.Queue()

    def enqueue_change(device: Device, changes: typing.Any):
        queue.put_nowait((device, changes))

    await client.refresh_all_devices()
    for _, device in client.get_devices():
        device.subscribe(enqueue_change)
    with Live(_summary_table(client.get_devices())) as live:
        while True:
            changed_device, changes = await queue.get()
            live.console.log(f"{changed_device.get_name()} changed:", changes)
            live.update(_summary_table(client.get_devices()))
