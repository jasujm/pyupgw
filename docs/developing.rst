Developing ``pyupgw``
=====================

This section gives an overview of developing support for new devices compatible
with Unisenza Plus, or supporting new features for the existing devices.

Logging messages
----------------

The easiest way to inspect messages that the client exchanges with the cloud
service is logging. The command-line interface supports YAML configurations in
`Python logging configuration schema
<https://docs.python.org/3/library/logging.config.html#logging-config-dictschema>`_.
The following sample configuration produces both nicely formatted output into
the console, and structured logs in `JSON lines <https://jsonlines.org/>`_ into
a file.

.. code-block:: yaml

   version: 1
   formatters:
     file:
       class: jsonformatter.JsonFormatter
       format:
         asctime: asctime
         levelname: levelname
         name: name
         message: message
         request: request
         response: response
   handlers:
     console:
       class: rich.logging.RichHandler
     file:
       class: logging.FileHandler
       formatter: file
       filename: pyupgw.log
   loggers:
     pyupgw:
       handlers:
         - console
         - file
       level: DEBUG

The CLI can then be run with the configuration file provided as an option:

.. code-block:: console

   $ pyupgw --logging-config=my-config.yaml

The requests and responses to and from the server are logged:

- As ``repr()`` of the object in the log message
- As base64 encoded pickled object in the ``request`` and ``response`` fields,
  respectively

The latter format is useful for offline inspection the objects with Python
scripts.
