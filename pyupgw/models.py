"""Models and data structures used by the library"""

import enum
import typing
import uuid
from collections.abc import Iterable

from attrs import define


class DeviceType(enum.Enum):
    """Device type"""

    DEVICE = "device"
    GATEWAY = "gateway"


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


class Device:
    """Handle for a managed device"""

    def __init__(self, attributes: DeviceAttributes, children: Iterable["Device"] = ()):
        self._attributes = attributes
        self._children = list(children)

    def get_attributes(self) -> DeviceAttributes:
        """Get the attributes associated with the device"""
        return self._attributes

    def get_device_code(self) -> str:
        """Get device code"""
        return self._attributes.device_code

    def get_children(self) -> list["Device"]:
        """Get the children of this device"""
        return self._children
