"""Models and data structures used by the library"""

# pylint: disable=too-many-instance-attributes

import enum
import functools
import logging
import typing
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping

from attrs import define, evolve, field

logger = logging.getLogger(__name__)


class DeviceType(enum.Enum):
    """Enumeration indicating the type of the device"""

    GATEWAY = "gateway"
    HVAC = "hvac"


class SystemMode(enum.Enum):
    """HVAC system mode"""

    OFF = 0
    HEAT = 4


class RunningState(enum.Enum):
    """HVAC running state"""

    IDLE = 0
    HEATING = 1


@define
class DeviceAttributes:
    """Common device attributes"""

    id: uuid.UUID
    type: DeviceType
    device_code: str
    model: str
    name: str


@define
class Occupant:
    """Occupant of a managed device"""

    id: uuid.UUID
    identity_id: str


@define
class GatewayAttributes(DeviceAttributes):
    """Gateway attributes"""

    type: typing.Literal[DeviceType.GATEWAY]
    occupant: Occupant


@define
class HvacAttributes(DeviceAttributes):
    """Attributes of a HVAC device"""

    type: typing.Literal[DeviceType.HVAC]

    manufacturer: str | None = field(default=None)
    """Device manufacturer"""

    serial_number: str | None = field(default=None)
    """Serial number"""

    firmware_version: str | None = field(default=None)
    """Firmware version"""

    system_mode: SystemMode | None = field(default=None)
    """The system mode (state) of the device"""

    running_state: RunningState | None = field(default=None)
    """The running state (action) of the device"""

    target_temperature: float | None = field(default=None)
    """The setpoint temperature"""

    current_temperature: float | None = field(default=None)
    """The current temperature as measured by the device"""

    min_temp: float | None = field(default=None)
    """Minimum setpoint temperature"""

    max_temp: float | None = field(default=None)
    """Maximum setpoint temperature"""


DeviceChangeSubscriber = Callable[["Device", Mapping[str, typing.Any]], None]


AttributesType = typing.TypeVar(  # pylint: disable=invalid-name
    "AttributesType", bound=DeviceAttributes
)
"""Type variable"""


class Device(typing.Generic[AttributesType]):
    """A managed device

    A device object is a dynamic handle for the device data managed by a client.
    It responds to direct and indirect state changes both from the client and
    other sources.  The instantaneous state of the device can be retrieved using
    the :meth:`get_attributes()` method.

    Arguments:
      attributes: the initial attributes
      dispatch_refresh: dispatch request to refresh the state of this device
      dispatch_update: dispatch request to update the state of this device
    """

    def __init__(
        self,
        attributes: AttributesType,
        dispatch_refresh: Callable[["Device"], Awaitable[None]],
        dispatch_update: Callable[
            ["Device", Mapping[str, typing.Any]], Awaitable[None]
        ],
    ):
        self._attributes = attributes
        self._dispatch_refresh = dispatch_refresh
        self._dispatch_update = dispatch_update
        self._subscribers: list[DeviceChangeSubscriber] = []

    def get_attributes(self) -> AttributesType:
        """Get the attributes associated with the device"""
        return self._attributes

    def get_id(self) -> uuid.UUID:
        """Get device id"""
        return self._attributes.id

    def get_type(self) -> DeviceType:
        """Get device type"""
        return self._attributes.type

    def get_device_code(self) -> str:
        """Get device code"""
        return self._attributes.device_code

    def get_model(self) -> str:
        """Get device code"""
        return self._attributes.model

    def get_name(self) -> str:
        """Get device code"""
        return self._attributes.name

    def set_attributes(self, changes: Mapping[str, typing.Any]):
        """Set new value for attributes

        Note that this method only changes the attributes in-memory, and the
        changes are not dispatched to the cloud service.

        Arguments:
          changes: dictionary containing new values for the attributes
        """
        if changes:
            self._attributes = evolve(self._attributes, **changes)
            for subscriber in self._subscribers:
                try:
                    subscriber(self, changes)
                except Exception:  # pylint: disable=broad-exception-caught
                    logger.exception(
                        "Failed to invoke subscriber callback for device %r",
                        self.get_attributes(),
                    )

    async def refresh(self):
        """Refresh the state of the device

        This call will delegate to :meth:`Client.refresh_device_state()`
        """
        await self._dispatch_refresh(self)

    async def update(self, changes: Mapping[str, typing.Any]):
        """Update the state of the device

        This call will delegate to :meth:`Client.update_device_state()`
        """
        await self._dispatch_update(self, changes)

    def subscribe(self, callback: DeviceChangeSubscriber):
        """Register a callback to be notified when the state of a device changes

        Arguments:
          callback: the callback that will be called with the updated device and
                    dictionary of the changed attributes
        """
        self._subscribers.append(callback)

    def unsubscribe(self, callback: DeviceChangeSubscriber):
        """Remove a callback previously registered with :meth:`subscribe()`

        Arguments:
          callback: the callback to be removed from subscribers
        """
        self._subscribers.remove(callback)


class HvacDevice(Device[HvacAttributes]):
    """A HVAC device (smart thermostat)"""

    def get_serial_number(self) -> str | None:
        """Get serial number"""
        return self._attributes.serial_number

    def get_manufacturer(self) -> str | None:
        """Get serial number"""
        return self._attributes.manufacturer

    def get_firmware_version(self) -> str | None:
        """Get serial number"""
        return self._attributes.firmware_version

    def get_system_mode(self) -> SystemMode | None:
        """Get mode of the device"""
        return self._attributes.system_mode

    def get_running_state(self) -> RunningState | None:
        """Get action the device is performing"""
        return self._attributes.running_state

    def get_target_temperature(self) -> float | None:
        """Get the setpoint temperature"""
        return self._attributes.target_temperature

    def get_current_temperature(self) -> float | None:
        """Get the current temperature as measured by the device"""
        return self._attributes.current_temperature

    def get_min_temp(self) -> float | None:
        """Get the minimum setpoint temperature"""
        return self._attributes.min_temp

    def get_max_temp(self) -> float | None:
        """Get the maximum setpoint temperature"""
        return self._attributes.max_temp

    async def update_system_mode(self, system_mode: SystemMode):
        """Update the system mode"""
        await self.update({"system_mode": system_mode})

    async def update_target_temperature(self, target_temperature: float):
        """Update the setpoint temperature"""
        await self.update({"target_temperature": target_temperature})


class Gateway(Device[GatewayAttributes]):
    """A gateway acting between Unisenza IoT devices and the cloud service

    Arguments:
      attributes: the gateway attributes
      children: initial attributes of the children managed by the gateway
      dispatch_refresh: dispatch request to refresh the state of this device
      dispatch_update: dispatch request to update the state of this device
    """

    def __init__(
        self,
        attributes: GatewayAttributes,
        children: Iterable[HvacAttributes],
        dispatch_refresh: Callable[["Gateway", Device], Awaitable[None]],
        dispatch_update: Callable[
            ["Gateway", Device, Mapping[str, typing.Any]], Awaitable[None]
        ],
    ):
        bound_dispatch_refresh = functools.partial(dispatch_refresh, self)
        bound_dispatch_update = functools.partial(dispatch_update, self)
        super().__init__(attributes, bound_dispatch_refresh, bound_dispatch_update)
        self._children = [
            HvacDevice(child, bound_dispatch_refresh, bound_dispatch_update)
            for child in children
        ]

    def get_children(self) -> list[HvacDevice]:
        """Get the children of this device"""
        return self._children

    def get_occupant(self) -> Occupant:
        """Get the occupant of the gateway"""
        return self._attributes.occupant
