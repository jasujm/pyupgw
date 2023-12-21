"""Main client code"""

import uuid
import contextlib

import aiohttp

from ._api import AwsApi, ServiceApi
from .models import DeviceType, Device


def _parse_device(data):
    gateway_data = data["gateway"]
    return Device(
        id=uuid.UUID(data["id"]),
        type=DeviceType(data["type"]),
        device_code=str(gateway_data["device_code"]),
        model=str(gateway_data["model"]),
        name=str(gateway_data["name"]),
    )


def _create_aws_api(username: str):
    return AwsApi(username)


def _create_service_api():
    return ServiceApi()


class Client:
    """Unisenza Plus Gateway client

    Clients for accessing gateways and devices accessible for an authenticated
    user.

    The recommended way to start a client session is with
    :func:`create_client()` context manager.
    """

    def __init__(self, devices: list[Device]):
        """
        Parameters:
          devices: list of managed devices
        """
        self._devices: list[Device] = devices

    def get_devices(self):
        """Get the managed devices"""
        return self._devices


@contextlib.asynccontextmanager
async def create_client(username: str, password: str):
    """Create Unisenza Plus Gateway client

    This function is used as a context manager that initializes and manages
    resources for a :class:`Client` instance.

    .. code-block:: python

        async with create_client("user@example.com", "password") as client:
           print(client.get_devices())
    """

    aws = _create_aws_api(username)
    id_token, access_token = await aws.authenticate(password)
    service_api = _create_service_api()
    async with aiohttp.ClientSession() as aiohttp_session:
        slider_list = await service_api.get_slider_list(
            id_token, access_token, aiohttp_session
        )
    devices = [
        _parse_device(device_data)
        for device_data in slider_list["data"]
        if device_data["type"] == "gateway"
    ]
    yield Client(devices)
