Python client for Unisenza Plus
===============================

Unisenza Plus is an IoT family that connects smart thermostats and other devices
manufactured by `Purmo <https://global.purmo.com/>`_ to a cloud service via the
Unisenza Plus Gateway. ``pyupgw`` is a python client for that cloud service.

Currently, only the smart thermostats are supported.

.. note::

    The author of this library is not affiliated with Purmo, the vendor of
    Unisenza Plus, in any way.  The library and its conformance to the Unisenza
    Plus API is implemented on a best-effort basis.  No warranty of any kind is
    provided.

Installation
------------

Install the library using ``pip`` or your favorite package management tool:

.. code-block:: console

   $ pip install pyupgw

Usage
-----

The following sample program illustrates how to use the client

.. code-block:: python

   import asyncio
   from pyupgw import create_client, Client, Device

   def report_changes(device: Device, changes: dict):
       print(f"{device.get_name()} has new changes:")
       for key, value in changes.items():
           print(f"- {key}: {value}")

    async def main():
        async with create_client("username", "password") as client:

            # Refresh the device state from the server.
            # The coroutine completes when the new state is available.
            await client.refresh_all_devices()

            print("Gateways:")
            for gateway in client.get_gateways():
                print(f"- {gateway.get_name()}")

            print("Devices:")
            for gateway, device in client.get_devices():
                print(
                    f"- {device.get_name()},",
                    f"target temperature: {device.get_target_temperature()},",
                    f"current temperature: {device.get_current_temperature()}",
                )

            device = client.get_gateways()[0].get_children()[0]

            # Send the updated temperature to the server.
            # The coroutine completes when the server accepts the change,
            # but hasn't necessarily applied it yet.
            # You can subscribe to get notified when the change is eventually applied.
            device.subscribe(report_changes)
            await device.update_target_temperature(20.0)
            await asyncio.sleep(10)

    if __name__ == "__main__":
        asyncio.run(main())

The underlying API is based on MQTT and totally asynchronous. The library
automatically synchronizes when fetching fresh state for the devices, but the
same is not true for the ``update_X()`` calls. The server may not even report
some updates, for instance when setting the target temperature to the same value
it already has.

The sample program naively uses ``asyncio.sleep()`` to ensure it has time to
receive the notification about the newly applied temperature value. An actual
program would do something more efficient, like update GUI elements or dispatch
messages to an event loop in response to the callbacks.

Command-line interface
----------------------

The package contains a command-line interface. To install the dependencies,
include the ``cli`` extras:

.. code-block:: console

   $ pip install pyupgw[cli]
   $ pyupgw --help

Goals
-----

The main reason for this project is to (eventually) develop `Home Assistant
<https://www.home-assistant.io/>`_ integration for the Unisenza Plus.

The client library is intended to give a robust and simplified interface to the
most important functionality of the smart thermostats. By hiding complexity it
trades off some degree of control.

The library only supports a subset of features of the devices. New features may
be added on a case-by-case basis.

Non-goals
---------

The author of the library is in no way affiliated with the company Purmo, and
not working using official API documentation. The code is based on
experimentation with the equipment at hand, and will likely never cover all the
possible features of the products.

The Unisenza Plus service is based on the `UleEco <https://www.uleeco.com/>`_
IoT platform. Hence, the package *might* work with some modifications with other
solutions based on the platform. However, since the author does not have
official documentation, this is not guaranteed and a universal UleEco client is
not in the scope of this project for the time being.

The intended use of the library is developing scripts and other automation for
the Purmo thermostats. The underlying API contains data specifically intended to
be consumed by the official Unisenza Plus app (related to presentation and
notifications, for instance). There is no intention to support those features in
this library.

Contributing
------------

This project is still in its early stages. Please open an issue or PR in the
`Github <https://github.com/jasujm/pyupgw>`_ repository if you want to get in
touch with questions or contributions.
