"""Gateway model"""

from .models import BaseDevice, DeviceAttributes, Occupant


class Gateway(BaseDevice):
    """Handle for a gateway"""

    def __init__(self, attributes: DeviceAttributes, occupant: Occupant):
        """
        Arguments:
          attributes: device attributes
          occupant: occupant managing the gateway
        """
        super().__init__(attributes)
        self._occupant = occupant

    def get_occupant(self) -> Occupant:
        """Get the occupant managing the gateway"""
        return self._occupant
