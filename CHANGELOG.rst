Version 0.4
-----------

Date
  2024-01-21

Added
 * ``create_api()`` function for bootstrapping client
 * ``running_state`` attribute to HVAC devices

Changed
 * Rename ``temperature`` attribute to ``target_temperature`` (the former was
   ambiguous)

Fixed
 * ``Client`` now subscribes to updates in ``__init__()`` and not ``__aenter__()``

Version 0.3
-----------

Date
  2024-01-09

Added
 * Error handling to several places where none previously existed
 * Improved text user interface
 * ``tox`` for test automation
 * Documentation hosted at `Read the Docs <https://pyupgw.readthedocs.io/>`_

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
