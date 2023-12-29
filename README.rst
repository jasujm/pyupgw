Python client for Unisenza Plus
===============================

Unisenza Plus is a product line that connects smart thermostats and other
devices manufactured by `Purmo <https://global.purmo.com/>`_ to a cloud service
via the Unisenza Plus Gateway. ``pyupgw`` is a python client for that cloud
service.

Currently only the smart thermostats are supported.

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

            # Refresh device attributes from the server
            await client.refresh_all_devices()
            await asyncio.sleep(10)

            print("Gateways:")
            for gateway in client.get_gateways():
                print(f"- {gateway.get_name()}")

            print("Devices:")
            for gateway, device in client.get_devices():
                print(
                    f"- {device.get_name()},",
                    f"setpoint temperature: {device.get_temperature()},",
                    f"current temperature: {device.get_current_temperature()}",
                )

            device = client.get_gateways()[0].get_children()[0]
            device.subscribe(report_changes)

            print(f"Updating setpoint temperature for {device.get_name()}")
            await device.update_temperature(20.0)

            await asyncio.sleep(10)

    if __name__ == "__main__":
        asyncio.run(main())

Please note that the underlying API is MQTT based. Compared to REST APIs this
makes it totally asynchronous. While the functions for refreshing and updating
the device state are coroutines, they complete as soon as the server
acknowledges the message (but before it actually responds with a message of its
own). The server may not even report some updates, for instance when setting
temperature to the same value it already has.

The sample program naively uses ``asyncio.sleep()`` calls to synchronize to the
actual updates. A real program would do something more elegant, like update GUI
elements or dispatch messages to event loop in response to the callbacks.

Goals
-----

The main reason for this project is to (eventually) develop `Home Assistant
<https://www.home-assistant.io/>`_ integration for the Unisenza Plus.

The client library is intended to give a robust and simplified interface to the
most important attributes and functionality of the smart thermostats. By hiding
complexity it trades off some degree of control.

The library only supports a subset of features of the devices. New features may
be added on case-by-case basis.

Non-goals
---------

The author of the library is in no way affiliated with the company Purmo, and
not working using official API documentation. Hence, the scope of the library
will likely never cover all the possible features of the products.

The Unisenza Plus service is based on the `UleEco <https://www.uleeco.com/>`_
IoT platform. As such, this package *might* work with some modifications with
other product lines based on the platform. However, since the author does not
have official documentation, this is not guaranteed and a universal UleEco
client is not in the scope of this project for the time being.

The intended usage of the library is developing scripts and other automations
for the Purmo thermostats. The underlying API contains data specifically
intended to be consumed by the official Unisenza Plus app (related to
presentation and notifications, for instance). There is no intention to support
those features in this library.

Contributing
------------

This project is still in early stages. Please open an issue or PR in the `Github
<https://github.com/jasujm/pyupgw>`_ repository if you want to get in touch with
questions or contributions.
