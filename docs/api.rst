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

.. autofunction:: create_api

.. autofunction:: create_client

Models
------

.. autoclass:: Device
   :members:
   :show-inheritance:

.. autoclass:: DeviceAttributes
   :members:
   :undoc-members:

.. autoclass:: DeviceType
   :members:
   :undoc-members:

.. autoclass:: Gateway
   :show-inheritance:
   :members:

.. autoclass:: GatewayAttributes
   :show-inheritance:
   :members:
   :undoc-members:

.. autoclass:: HvacAttributes
   :show-inheritance:
   :members:
   :undoc-members:

.. autoclass:: HvacDevice
   :show-inheritance:
   :members:

.. autoclass:: Occupant
   :members:
   :undoc-members:

.. autoclass:: RunningState
   :members:
   :undoc-members:

.. autoclass:: SystemMode
   :members:
   :undoc-members:

Exceptions
----------

.. autoexception:: ClientError

.. autoexception:: AuthenticationError
