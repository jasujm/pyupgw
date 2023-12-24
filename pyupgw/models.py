"""Models and data structures used by the library"""

import enum
import typing
import uuid
from collections.abc import Callable, Iterable

from attrs import define, evolve, field


class DeviceType(enum.Enum):
    """Device type"""

    DEVICE = "device"
    GATEWAY = "gateway"


class SystemMode(enum.Enum):
    """HVAC system mode"""

    OFF = 0
    HEAT = 4


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
class IotDeviceAttributes(DeviceAttributes):
    """Attributes of an IoT device managed by gateway"""

    type: typing.Literal[DeviceType.DEVICE]


@define
class ThermostatAttributes(IotDeviceAttributes):
    """Attributes of a smart thermostat"""

    system_mode: SystemMode | None = field(default=None)
    temperature: float | None = field(default=None)
    current_temperature: float | None = field(default=None)
    min_temp: float | None = field(default=None)
    max_temp: float | None = field(default=None)


DeviceChangeSubscriber = Callable[["Device", dict[str, typing.Any]], None]


class Device:
    """Handle for a managed device"""

    def __init__(self, attributes: DeviceAttributes, children: Iterable["Device"] = ()):
        self._attributes = attributes
        self._children = list(children)
        self._subscribers: list[DeviceChangeSubscriber] = []

    def get_attributes(self) -> DeviceAttributes:
        """Get the attributes associated with the device"""
        return self._attributes

    def update_attributes(self, changes: dict[str, typing.Any]):
        """Update attributes associated with the device

        Note that this function only changes the attributes in-memory, and the
        changes are not dispatched to the cloud service.

        Parameters:
          changes: dictionary containing the changes
        """
        self._attributes = evolve(self._attributes, **changes)
        for subscriber in self._subscribers:
            subscriber(self, changes)

    def subscribe_device_changes(self, callback: DeviceChangeSubscriber):
        """Register a callback to be notified when the state of a device changes

        Parameters:
          callback: the callback that will be called with the updated device and
                    dictionary of the changed attributes
        """
        self._subscribers.append(callback)

    def unsubscribe_device_changes(self, callback: DeviceChangeSubscriber):
        """Remove a callback previously registered with :func:`subscribe_device_changes()`

        Parameters:
          callback: the callback to be removed from subscribers
        """
        self._subscribers.remove(callback)

    def get_device_code(self) -> str:
        """Get device code"""
        return self._attributes.device_code

    def get_children(self) -> list["Device"]:
        """Get the children of this device"""
        return self._children
