"""Interactive text-user interface"""

import asyncio
import contextlib
import curses
import logging
import signal
import sys
import typing

from blessed import Terminal
from rich import print
from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from pyupgw import Client, Device, HvacDevice, SystemMode, create_client

logger = logging.getLogger(__name__)

HELP_PANEL = Panel(
    "(:arrow_up::arrow_down:) Select device, (O)ff, (H)eat, (+-) Adjust temperature, (Enter) Confirm"
)


# pylint: disable=too-many-instance-attributes
class Application(contextlib.AbstractAsyncContextManager):
    """Application state"""

    def __init__(self, client: Client, term: Terminal):
        self._client = client
        self._term = term
        self._queue: asyncio.Queue[tuple[Device, typing.Any]] = asyncio.Queue()
        self._exit_event = asyncio.Event()
        self._device_index = 0
        self._inkey_task = self._create_inkey_task()
        self._get_change_task = self._create_get_key_task()
        self._exit_task = self._create_exit_task()
        self._tasks: list[asyncio.Task] = [
            self._inkey_task,
            self._get_change_task,
            self._exit_task,
        ]
        self._devices: list[HvacDevice] = []
        self._pending_temperature: float | None = None

    def _enqueue_change(self, device: Device, changes: typing.Any):
        self._queue.put_nowait((device, changes))

    async def __aenter__(self):
        await self._client.refresh_all_devices()
        for _, device in self._client.get_devices():
            device.subscribe(self._enqueue_change)
        self._devices = list(device for _, device in self._client.get_devices())
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, self._exit_event.set)
        loop.add_signal_handler(signal.SIGTERM, self._exit_event.set)
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        for task in self._tasks:
            task.cancel()

    async def tick(self):
        """Handle application events"""
        done, pending = await asyncio.wait(
            self._tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
        self._tasks = list(pending)
        if self._inkey_task in done:
            self._handle_inkey_task()
        if self._get_change_task in done:
            self._handle_get_change_task()
        for task in done:
            if ex := task.exception():
                logger.error("Failed executing task: %r", task, exc_info=ex)

    def get_renderable(self):
        """Get application renderable"""
        table = Table(title="Devices", expand=True)
        table.add_column("Device")
        table.add_column("Gateway")
        table.add_column("Mode")
        table.add_column("Action")
        table.add_column("Target temperature")
        table.add_column("Current temperature")

        for current, (gateway, device) in enumerate(self._client.get_devices()):
            table.add_row(
                f"{':arrow_forward:' if self._device_index == current else ' '} {device.get_name()}",
                gateway.get_name(),
                str(
                    system_mode.name
                    if (system_mode := device.get_system_mode())
                    else None
                ),
                str(
                    running_state.name
                    if (running_state := device.get_running_state())
                    else None
                ),
                self._temperature_renderable(current, device),
                str(device.get_current_temperature()),
            )

        return Group(table, HELP_PANEL)

    def done(self):
        """Return True if done, False otherwise"""
        return self._exit_event.is_set()

    def _temperature_renderable(self, current: int, device: HvacDevice):
        if current == self._device_index and self._pending_temperature is not None:
            return f"[blink]{self._pending_temperature}"
        return str(device.get_target_temperature())

    def _create_inkey_task(self):
        return asyncio.create_task(asyncio.to_thread(self._term.inkey))

    def _create_get_key_task(self):
        return asyncio.create_task(self._queue.get())

    def _create_exit_task(self):
        return asyncio.create_task(self._exit_event.wait())

    def _current_device(self):
        return self._devices[self._device_index]

    def _handle_inkey_task(self):
        assert self._inkey_task.done()
        key = self._inkey_task.result()
        if key.code == curses.KEY_UP:
            self._pending_temperature = None
            self._device_index = max(self._device_index - 1, 0)
        elif key.code == curses.KEY_DOWN:
            self._pending_temperature = None
            self._device_index = min(self._device_index + 1, len(self._devices) - 1)
        elif key.upper() == "O" and self._devices:
            self._pending_temperature = None
            self._tasks.append(
                asyncio.create_task(
                    self._current_device().update_system_mode(SystemMode.OFF),
                )
            )
        elif key.upper() == "H" and self._devices:
            self._pending_temperature = None
            self._tasks.append(
                asyncio.create_task(
                    self._current_device().update_system_mode(SystemMode.HEAT),
                )
            )
        elif key.code == curses.KEY_ENTER and self._pending_temperature is not None:
            self._tasks.append(
                asyncio.create_task(
                    self._current_device().update_target_temperature(
                        self._pending_temperature
                    )
                )
            )
            self._pending_temperature = None
        elif key == "+":
            current_device = self._current_device()
            if self._pending_temperature is None:
                self._pending_temperature = current_device.get_target_temperature()
            self._pending_temperature = min(
                self._pending_temperature + 0.5, current_device.get_max_temp()
            )
        elif key == "-":
            current_device = self._current_device()
            if self._pending_temperature is None:
                self._pending_temperature = current_device.get_target_temperature()
            self._pending_temperature = max(
                self._pending_temperature - 0.5, current_device.get_min_temp()
            )
        self._inkey_task = self._create_inkey_task()
        self._tasks.append(self._inkey_task)

    def _handle_get_change_task(self):
        assert self._get_change_task.done()
        changed_device, changes = self._get_change_task.result()
        logger.info(f"{changed_device.get_name()} changed: %r", changes)
        self._get_change_task = self._create_get_key_task()
        self._tasks.append(self._get_change_task)


async def _tui_main(term: Terminal, username: str, password: str):
    async with create_client(username, password) as client:
        async with Application(client, term) as app:
            with Live(app.get_renderable()) as live:
                while not app.done():
                    await app.tick()
                    live.update(app.get_renderable(), refresh=True)


def tui(username: str, password: str):
    """Text-user interface"""

    term = Terminal()
    if not term.is_a_tty:
        print("[b red]Interactive mode supported only in TTY", file=sys.stderr)
        sys.exit(1)

    with term.fullscreen(), term.cbreak():
        asyncio.run(_tui_main(term, username, password))
