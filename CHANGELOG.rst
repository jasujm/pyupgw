Unreleased
----------

Added
 * Error handling to several places where none previously existed
 * Improved text user interface
 * ``tox`` for test automation

Version 0.2
-----------

Date
  2024-01-05

Added
 * Command-line interface

Changed
 * Refreshing and updating the state of the devices is now synchronized to the
   reply from the server
 * Tokens and WebSocket connections are automatically refreshed

Fixed
 * Include ``aiohttp`` in ``pyproject.toml``

Version 0.1.1
-------------

Date
  2023-12-29

Added
 * Debug logging for service API responses

Changed
 * Rename ``ThermostatDevice`` and ``ThermostatAttributes`` into ``HvacDevice``
   and ``HvacAttributes``, respectively. This is in anticipation that there are
   other HVAC products with similar API.
 * Rename ``DeviceType.DEVICE`` into ``DeviceType.HVAC`` to be more descriptive
   and not reserve the most general name for just one kind of device.

Version 0.1
-----------

Date
  2023-12-29

Initial version
