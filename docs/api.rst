.. _api:

.. module:: pyupgw

API reference
=============

Client
------

The usual entry point to the library is the :func:`create_client()` function
that creates and sets up a :class:`Client` instance.

.. autoclass:: Client
   :members:

.. autofunction:: create_client

Models
------

.. autoclass:: Device
   :members:

.. autoclass:: DeviceAttributes
   :members:
   :undoc-members:

.. autoclass:: DeviceType
   :members:
   :undoc-members:

.. autoclass:: GatewayAttributes
   :members:
   :undoc-members:

.. autoclass:: Occupant
   :members:
   :undoc-members:

.. autoclass:: SystemMode
   :members:
   :undoc-members:

.. autoclass:: ThermostatAttributes
   :members:
   :undoc-members:
