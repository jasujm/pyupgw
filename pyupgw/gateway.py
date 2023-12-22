"""Gateway model"""

import typing

from .models import BaseDevice, DeviceAttributes, Occupant
from .device import Device


class Gateway(BaseDevice):
    """Handle for a gateway"""

    def __init__(
        self,
        attributes: DeviceAttributes,
        occupant: Occupant,
        device_attributes: typing.Iterable[DeviceAttributes],
    ):
        """
        Arguments:
          attributes: gateway attributes
          occupant: occupant of the gateway
          device_attributes: attributes of the managed devices
        """
        super().__init__(attributes)
        self._occupant = occupant
        self._devices = [Device(attrs) for attrs in device_attributes]

    def get_occupant(self) -> Occupant:
        """Get the occupant managing the gateway"""
        return self._occupant

    def get_devices(self) -> list[Device]:
        """Get the devices managed by the gateway"""
        return self._devices
