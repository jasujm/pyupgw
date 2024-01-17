"""Non-interactive commands"""

import sys
import typing

from rich import print
from rich.console import Group
from rich.pretty import Pretty
from rich.tree import Tree

from pyupgw import Client, Device, DeviceType, SystemMode


def _find_device_by_str(client: Client, needle: str):
    for _, device in client.get_devices():
        if needle in [
            device.get_name(),
            device.get_device_code(),
            str(device.get_id()),
        ]:
            return device
    return None


def _pretty_print_device(device: Device):
    if device.get_type() == DeviceType.GATEWAY:
        header = f":globe_with_meridians: [bold]Gateway: {device.get_name()}"
    else:
        header = f"Device: {device.get_name()}"
    return Group(header, Pretty(device.get_attributes()))


async def update(
    client: Client,
    device_needle: str,
    temperature: float | None,
    system_mode: SystemMode | None,
):
    """Update the state of a device"""

    device = _find_device_by_str(client, device_needle)
    if not device:
        print("[b red]Device not found", file=sys.stderr)
        sys.exit(1)

    changes: dict[str, typing.Any] = {}
    if temperature is not None:
        changes["target_temperature"] = temperature
    if system_mode is not None:
        changes["system_mode"] = system_mode
    await device.update(changes)


async def get(client: Client, device_needle: str):
    """Print details of a single device"""

    device = _find_device_by_str(client, device_needle)
    if not device:
        print("[b red]Device not found", file=sys.stderr)
        sys.exit(1)

    await device.refresh()
    print(_pretty_print_device(device))


async def list_devices(client: Client):
    """Print detailed view of managed gateways and devices"""
    await client.refresh_all_devices()
    tree = Tree("Device details", hide_root=True)
    for gateway in client.get_gateways():
        branch = tree.add(_pretty_print_device(gateway))
        for device in gateway.get_children():
            branch.add(_pretty_print_device(device))
    print(tree)
