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
