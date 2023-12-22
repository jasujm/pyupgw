"""Models and data structures used by the library"""

import uuid
import enum

from attrs import define


class DeviceType(enum.Enum):
    """Device type"""

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
    email: str
    first_name: str
    last_name: str
    identity_id: str


class BaseDevice:
    """Handle for a managed device"""

    def __init__(self, attributes: DeviceAttributes):
        self._attributes = attributes

    def get_attributes(self) -> DeviceAttributes:
        """Get the attributes associated with the device"""
        return self._attributes
