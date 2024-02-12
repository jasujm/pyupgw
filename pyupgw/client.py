"""Main client code"""

import asyncio
import contextlib
import functools
import logging
import typing
import uuid
from collections.abc import Callable, Iterable, Mapping

import aiohttp
from dict_deep import deep_get

from ._api import AwsApi, ServiceApi
from ._mqtt import IotShadowMqtt
from .errors import AuthenticationError, ClientError
from .models import (
    Device,
    DeviceType,
    Gateway,
    GatewayAttributes,
    HvacAttributes,
    HvacDevice,
    Occupant,
    RunningState,
    SystemMode,
)

if typing.TYPE_CHECKING:
    import concurrent.futures

logger = logging.getLogger(__name__)


def _parse_device_attributes(data):
    return {
        "id": uuid.UUID(data["id"]),
        "device_code": str(data["device_code"]),
        "model": str(data["model"]),
        "name": str(data["name"]),
    }


def _parse_gateway_attributes(data):
    gateway_data = data["gateway"]
    attributes = _parse_device_attributes(gateway_data)
    occupant_data = gateway_data["occupants_permissions"]["receiver_occupant"]
    occupant = Occupant(
        id=uuid.UUID(occupant_data["id"]),
        identity_id=str(occupant_data["identity_id"]),
    )
    return GatewayAttributes(type=DeviceType.GATEWAY, **attributes, occupant=occupant)


def _parse_hvac_devices(data):
    for item_data in data["items"]:
        if "items" in item_data:
            yield from _parse_hvac_devices(item_data)
        # the gateway itself appears under items, but let's exclude it
        elif "device_code" in item_data and "occupants_permissions" not in item_data:
            yield HvacAttributes(
                type=DeviceType.HVAC, **_parse_device_attributes(item_data)
            )


_SHADOW_TO_ATTRIBUTES_MAP: list[tuple[str, str, Callable[[typing.Any], typing.Any]]] = [
    ("serial_number", "ep1:sPowerMS:RadSerialNum", str),
    ("manufacturer", "ep1:sBasicS:ManufactureName", str),
    ("firmware_version", "ep1:sZDO:FirmwareVersion", str),
    ("target_temperature", "ep1:sTherS:HeatingSetpoint_x100", lambda v: float(v) / 100),
    (
        "current_temperature",
        "ep1:sTherS:LocalTemperature_x100",
        lambda v: float(v) / 100,
    ),
    ("min_temp", "ep1:sTherS:MinHeatSetpoint_x100", lambda v: float(v) / 100),
    ("max_temp", "ep1:sTherS:MaxHeatSetpoint_x100", lambda v: float(v) / 100),
    ("system_mode", "ep1:sTherS:RunningMode", SystemMode),
    ("running_state", "ep1:sTherS:RunningState", RunningState),
]


def _parse_shadow_attributes(shadow_state: Mapping[str, typing.Any] | None):
    properties = deep_get(shadow_state, ["state", "reported", "11", "properties"])
    if not properties:
        return {}
    ret = {}
    for attr_key, shadow_key, transform in _SHADOW_TO_ATTRIBUTES_MAP:
        if (value := properties.get(shadow_key)) is not None:
            try:
                ret[attr_key] = transform(value)
            except Exception as ex:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "Failed to parse state argument %s=%s",
                    shadow_key,
                    repr(value),
                    exc_info=ex,
                )
    return ret


_ATTRIBUTES_TO_SHADOW_MAP: list[tuple[str, str, Callable[[typing.Any], typing.Any]]] = [
    (
        "target_temperature",
        "ep1:sTherS:SetHeatingSetpoint_x100",
        lambda v: int(round(v * 100)),
    ),
    ("system_mode", "ep1:sTherS:SetSystemMode", lambda v: v.value),
]


def _create_shadow_update_attributes(changes: Mapping[str, typing.Any]):
    desired_properties: dict[str, typing.Any] = {}
    for attr_key, shadow_key, transform in _ATTRIBUTES_TO_SHADOW_MAP:
        if (value := changes.get(attr_key)) is not None:
            desired_properties[shadow_key] = transform(value)
    return {"state": {"desired": {"11": {"properties": desired_properties}}}}


async def _construct_client_data(id_token: str, access_token: str, client: "Client"):
    service_api = _create_service_api()
    gateways: list[Gateway] = []
    async with (
        aiohttp.ClientSession() as aiohttp_session,
        asyncio.TaskGroup() as task_group,
    ):

        async def _populate_gateway(gateway_data):
            attributes = _parse_gateway_attributes(gateway_data)
            slider_details = await service_api.get_slider_details(
                str(attributes.id),
                attributes.type.value,
                id_token,
                access_token,
                aiohttp_session,
            )
            logger.debug(
                "Fetched details for gateway %s: %r",
                attributes.id,
                slider_details,
                extra={"response": slider_details},
            )
            gateways.append(
                Gateway(
                    attributes,
                    _parse_hvac_devices(slider_details["data"]),
                    client.refresh_device_state,
                    client.update_device_state,
                )
            )

        slider_list = await service_api.get_slider_list(
            id_token, access_token, aiohttp_session
        )
        logger.debug(
            "Fetched list of gateways: %r",
            slider_list,
            extra={"response": slider_list},
        )
        for gateway_data in slider_list["data"]:
            if gateway_data.get("type") == "gateway":
                task_group.create_task(_populate_gateway(gateway_data))
    return gateways


def _create_aws_api(username: str):
    return AwsApi(username)


def _create_service_api():
    return ServiceApi()


class _MqttClientManager(contextlib.AbstractAsyncContextManager):
    """Manage shadow clients for devices"""

    def __init__(self, aws: AwsApi):
        self._aws = aws
        self._on_update_callbacks: list[Callable[[str, str, dict | None], None]] = []
        self._clients: dict[str, IotShadowMqtt] = {}
        self._loop = asyncio.get_running_loop()
        self._exit_stack = contextlib.AsyncExitStack()

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self._exit_stack.aclose()

    def register_callback(self, callback: Callable[[str, str, dict | None], None]):
        """Register callback that will be invoked when device state is updated

        The arguments to the callback will be the gateway device code, child
        device code, and the response, respectively.
        """
        self._on_update_callbacks.append(callback)

    def remove_callback(self, callback: Callable[[str, str, dict | None], None]):
        """Remove previously registered callback"""
        self._on_update_callbacks.remove(callback)

    async def client_for_gateway(
        self,
        occupant: Occupant,
        device_code: str,
        child_device_codes: list[str],
    ) -> IotShadowMqtt:
        """Get shadow client for a given gateway"""
        if existing_client := self._clients.get(device_code):
            return existing_client
        bound_on_response_state_received = functools.partial(
            self._on_response_state_received, device_code
        )
        client = await self._exit_stack.enter_async_context(
            IotShadowMqtt(
                aws=self._aws,
                identity_id=occupant.identity_id,
                client_name=device_code,
                thing_names=child_device_codes,
                loop=self._loop,
                on_response_state_received=bound_on_response_state_received,
            )
        )
        self._clients[device_code] = client
        return client

    def _on_response_state_received(
        self, device_code: str, child_device_code: str, response: dict | None
    ):
        for callback in self._on_update_callbacks:
            callback(device_code, child_device_code, response)


class Client(contextlib.AbstractAsyncContextManager):
    """Unisenza Plus client

    The recommended way to start a client session is with
    :func:`create_client()` context manager.  Alternatively,
    :func:`create_api()` can be used to create the AWS API instance manually
    before creating the client.

    The newly created ``Client`` object doesn't initially know about any
    devices.  :meth:`populate_devices()` needs to be called to fetch them from
    the server.

    Parameters:
      aws: The AWS API object user to access the backend service.  The
           authentication needs to be performed before creating the ``Client``
           object.
    """

    def __init__(self, aws: AwsApi):
        self._exit_stack = contextlib.AsyncExitStack()
        self._aws = aws
        self._gateways: list[Gateway] = []
        self._mqtt_client_manager = _MqttClientManager(aws)
        self._exit_stack.push_async_exit(self._mqtt_client_manager)
        self._mqtt_client_manager.register_callback(self._on_update_device)
        self._exit_stack.callback(
            self._mqtt_client_manager.remove_callback, self._on_update_device
        )

    async def aclose(self):
        """Release all resources acquired by the client

        When the ``Client`` object is used as context manager, this is
        automatically called on exit.
        """
        await self._exit_stack.aclose()

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.aclose()

    async def populate_devices(self):
        """Populate devices from the server

        Raises:
          ClientError: if populating device data fails
        """
        try:
            id_token, access_token = await asyncio.to_thread(self._aws.get_tokens)
            self._gateways = await _construct_client_data(id_token, access_token, self)
        except Exception as ex:  # pylint: disable=broad-exception-caught
            raise ClientError("Failed to populate devices") from ex

    def get_gateways(self) -> list[Gateway]:
        """Get the managed gateways"""
        return self._gateways

    def get_devices(self) -> Iterable[tuple[Gateway, HvacDevice]]:
        """Get pairs of gateways and managed devices"""
        for gateway in self._gateways:
            for child in gateway.get_children():
                yield gateway, child

    async def refresh_all_devices(self):
        """Refresh states of all managed devices

        This is a convenience function that calls :meth:`refresh_device_state()`
        for all devices known to the client.

        Raises:
          ClientError: if the request to get device state fails
        """
        async with asyncio.TaskGroup() as task_group:
            for gateway, child in self.get_devices():
                task_group.create_task(self.refresh_device_state(gateway, child))

    async def refresh_device_state(
        self,
        gateway: Gateway,
        device: Device,
    ):
        """Refresh state of a device from the server

        The coroutine completes when the server has responded with the new state.

        Arguments:
          gateway: the gateway the device is connected to
          device: the device whose state is refreshed

        Raises:
          ClientError: if the request to get device state fails
        """
        client = await self._mqtt_client_for_gateway(gateway)
        device_code = device.get_device_code()
        logger.debug("Requesting get device state for %s", device_code)
        try:
            response = await client.get(device.get_device_code())
        except Exception as ex:
            raise ClientError(f"Unable to request state for {device_code}") from ex
        logger.debug(
            "Get device state response for %s: %r",
            device_code,
            response,
            extra={"response": response},
        )
        changes = _parse_shadow_attributes(response)
        device.set_attributes(changes)

    async def update_device_state(
        self,
        gateway: Gateway,
        device: Device,
        changes: Mapping[str, typing.Any],
    ):
        """Update the state of a device managed by the client

        This method will send the changed values to the server.  The coroutine
        will complete after the server has accepted the request, but not yet
        necessarily applied the changes.

        The update itself is asynchronous, and the in-memory attributes of the
        device models will only be updated after the server has acknowledged
        that it has applied the changes.  :meth:`Device.subscribe()` can be used
        to subscribe to the updates of the in-memory model.

        Arguments:
          gateway: the gateway the device is connected to
          device: the device whose state is updated
          changes: the changes to be published

        Raises:
          ClientError: if the request to update device state fails
        """
        client = await self._mqtt_client_for_gateway(gateway)
        device_code = device.get_device_code()
        request = _create_shadow_update_attributes(changes)
        logger.debug(
            "Requesting update device state for %s: %r",
            device_code,
            request,
            extra={"request": request},
        )
        try:
            await client.update(device_code, request)
        except Exception as ex:
            raise ClientError(
                f"Unable to update device state for {device_code}"
            ) from ex

    async def _mqtt_client_for_gateway(self, gateway: Gateway):
        return await self._mqtt_client_manager.client_for_gateway(
            gateway.get_occupant(),
            gateway.get_device_code(),
            [child.get_device_code() for child in gateway.get_children()],
        )

    def _on_update_device(
        self,
        device_code: str,
        child_device_code: str,
        response: dict | None,
    ):
        logger.debug(
            "Received update device state for %s: %r",
            child_device_code,
            response,
            extra={"response": response},
        )
        for gateway in self._gateways:
            if gateway.get_device_code() == device_code:
                for child in gateway.get_children():
                    if child.get_device_code() == child_device_code:
                        changes = _parse_shadow_attributes(response)
                        child.set_attributes(changes)

    async def _refresh_all_for_occupant(self, occupant: Occupant):
        async with asyncio.TaskGroup() as task_group:
            for gateway in self.get_gateways():
                if gateway.get_occupant() == occupant:
                    for child in gateway.get_children():
                        task_group.create_task(
                            self.refresh_device_state(gateway, child)
                        )


async def create_api(username: str, password: str) -> AwsApi:
    """Create authenticated AWS API instance

    The instance can be used to create :class:`Client` instance.  For a single
    step creation, use :func:`create_client()` function instead.

    Arguments:
      username, password: the credentials used to log into the cloud service

    Raises:
      AuthenticationError: if authentication fails
    """
    aws = await asyncio.to_thread(_create_aws_api, username)
    logger.debug("Authenticating user %s", username)
    try:
        await asyncio.to_thread(aws.authenticate, password)
    except Exception as ex:
        # This is a convoluted way of figuring out if the exception is
        # NotAuthorizedException. botocore generates exception types on the fly,
        # so I can't just import the correct exception type and except it...
        if "NotAuthorized" in str(
            deep_get(ex, ["__class__", "__name__"], getter=getattr)
        ):
            raise AuthenticationError(f"Failed to authenticate {username}") from ex
        raise
    return aws


@contextlib.asynccontextmanager
async def create_client(username: str, password: str):
    """Create Unisenza Plus client

    This function returns a context manager that initializes and manages
    resources for a :class:`Client` instance.  It also takes care of
    authenticating and populating devices from the server.

    .. code-block:: python

        async with create_client("user@example.com", "password") as client:
           ...  # use client

    Arguments:
      username, password: the credentials used to log into the cloud service
    """

    aws = await create_api(username, password)
    async with Client(aws) as client:
        await client.populate_devices()
        yield client
