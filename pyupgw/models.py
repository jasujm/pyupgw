"""Models and data structures used by the library"""

import uuid
import enum

from attrs import define


class DeviceType(enum.Enum):
    """Device type"""

    GATEWAY = "gateway"


@define
class Device:
    """Device managed by the gateway"""

    id: uuid.UUID
    type: DeviceType
    device_code: str
    model: str
    name: str
