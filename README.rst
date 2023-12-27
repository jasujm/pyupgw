Python client for Unisenza Plus Gateway
=======================================

Unisenza Plus Gateway is a product that connects smart thermostats manufactured
by `Purmo <https://global.purmo.com/>`_ to the Unisenza Plus cloud
service. ``pyupgw`` is a python client for that cloud service.

Goals
-----

The main reason for this project is to develop `Home Assistant
<https://www.home-assistant.io/>`_ integration for the Unisenza Plus Gateway.

The client library is intended to give a robust and simplified interface to the
most important attributes and functionality of the smart thermostats. By hiding
complexity it trades off some degree of control.

While the library only supports a subset of features of the devices, new
features may be added on case-by-case basis.

Non-goals
---------

Most importantly, the author of the library is in no way affiliated with the
company Purmo, and not working using official API documentation. Hence, the
scope of the library will likely never cover all the possible features of the
products.

The Unisenza Plus service is based on the `UleEco <https://www.uleeco.com/>`_ IoT
platform. As such, this package *might* work with some modifications with other
product lines based on the platform. However, since the author does not have
official documentation, this is not guaranteed and a universal UleEco client is
not in the scope of this project for the time being.

The intended usage of the library is developing scripts and other automations
for the Purmo thermostats. The underlying API contains data specifically
intended to be consumed by the official Unisenza Plus app (related to
presentation and notifications, for instance). There is no intention to support
those features in this library.

Contributing
------------

This project is still in early stages. Please open an issue or PR in the `Github
<https://github.com/jasujm/pyupgq>`_ repository if you want to get in touch with
questions or contributions.
