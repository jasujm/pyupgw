Version 0.13
------------

Date
  2025-03-09

Added
 * Parse EUID from devices
 * Support for python 3.13

Changed
 * Update paho-mqtt to version 2

Fixed
 * Do not allow NaN for float values in hypothesis unit tests

Version 0.12
------------

Date
  2024-03-01

Added
 * More unit test coverage

Changed
 * Replace existing linters with ``ruff``

Fixed
 * Retrieve and log error for failing to refresh device state after reconnect
 * Correct typo in function name ``Gateway.get_ip_address()``

Version 0.11.1
--------------

Date
  2024-02-18

Fixed
 * Subscribe to AWS IoT shadow topics one device at a time to avoid server
   disconnecting

Version 0.11
------------

Date
  2024-02-17

Added
 * Add ``firmware_version``, ``mac_address`` and ``ip_address`` fields to the
   gateway model
 * Device availability information

Changed
 * Make model attributes keyword only
 * ``Client.get_devices()`` now also includes gateways

Fixed
 * Do not initialize multiple MQTT connections for a gateway

Version 0.10
------------

Date
  2024-02-15

Changed
 * Reauthenticate to cloud service with password if the refresh token is no
   longer valid

Fixed
 * Fix handling of background tasks in MQTT client

Version 0.9
-----------

Date
  2024-02-14

Changed
 * Migrate MQTT implementation from ``awsiotsdk`` to ``paho.mqtt``

Version 0.8.1
-------------

Date
  2024-02-05

Changed
 * Only log INFO level messages by ``pyupgw`` package in CLI application

Version 0.8
-----------

Date
  2024-02-05

Added
 * More flexible logging configuration
 * Timeout for publishing and receiving MQTT replies

Changed
 * Increase timeouts for reinitializing MQTT connection
 * Logging in TUI application

Version 0.7
-----------

Date
  2024-02-03

Added
 * Nicer logging in CLI

Changed
 * Refresh device states when MQTT connection is resumed
 * Try to recreate MQTT clients after connection is lost. This is an additional
   measure on top of AWS SDK trying to resume connection.
 * Convert errors in client operation into ``ClientError``

Version 0.6
-----------

Date
  2024-01-28

Added
 * More concurrency

Fixed
 * Fix several external API calls blocking event loop by delegating to worker
   thread
 * Only throw ``AuthenticationError`` if the underlying cause for the error is
   authentication issue

Removed
 * Support for python 3.10

Version 0.5
-----------

Date
  2024-01-26

Added
 * ``manufacturer``, ``serial_number`` and ``firmware_version`` attributes to
   HVAC devices

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
