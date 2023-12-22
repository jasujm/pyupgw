"""Main client code"""

import uuid
import contextlib

import aiohttp

from ._api import AwsApi, ServiceApi
from .models import DeviceType, DeviceAttributes, Occupant
from .gateway import Gateway


def _parse_gateway_attributes_and_occupant(data):
    gateway_data = data["gateway"]
    attributes = DeviceAttributes(
        id=uuid.UUID(data["id"]),
        type=DeviceType(data["type"]),
        device_code=str(gateway_data["device_code"]),
        model=str(gateway_data["model"]),
        name=str(gateway_data["name"]),
    )
    occupant_data = gateway_data["occupant_permissions"]["receiver_occupant"]
    occupant = Occupant(
        id=uuid.UUID(occupant_data["id"]),
        email=str(occupant_data["email"]),
        first_name=str(occupant_data["first_name"]),
        last_name=str(occupant_data["last_name"]),
        identity_id=str(occupant_data["identity_id"]),
    )
    return attributes, occupant


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

    def __init__(self, gateways: list[Gateway]):
        """
        Parameters:
          gateways: managed gateways
        """
        self._gateways = gateways

    def get_gateways(self):
        """Get the managed gateways"""
        return self._gateways


@contextlib.asynccontextmanager
async def create_client(username: str, password: str):
    """Create Unisenza Plus Gateway client

    This function is used as a context manager that initializes and manages
    resources for a :class:`Client` instance.

    .. code-block:: python

        async with create_client("user@example.com", "password") as client:
           print(client.get_gateways())
    """

    aws = _create_aws_api(username)
    id_token, access_token = await aws.authenticate(password)
    service_api = _create_service_api()
    async with aiohttp.ClientSession() as aiohttp_session:
        slider_list = await service_api.get_slider_list(
            id_token, access_token, aiohttp_session
        )
    gateways = [
        Gateway(*_parse_gateway_attributes_and_occupant(gateway_data))
        for gateway_data in slider_list["data"]
        if gateway_data["type"] == "gateway"
    ]
    yield Client(gateways)
