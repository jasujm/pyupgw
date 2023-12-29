"""Main client code"""

import asyncio
import contextlib
import functools
import logging
import typing
import uuid
from collections.abc import Callable, Iterable, Mapping

import aiohttp
from awscrt.mqtt import QoS
from awsiot.iotshadow import (
    GetShadowRequest,
    GetShadowResponse,
    GetShadowSubscriptionRequest,
    IotShadowClient,
    ShadowState,
    UpdateShadowRequest,
    UpdateShadowResponse,
    UpdateShadowSubscriptionRequest,
)
from dict_deep import deep_get

from ._api import AwsApi, AwsCredentialsProvider, ServiceApi
from .models import (
    Device,
    DeviceType,
    Gateway,
    GatewayAttributes,
    Occupant,
    SystemMode,
    ThermostatAttributes,
    ThermostatDevice,
)

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


def _parse_thermostat_devices(data):
    for item_data in data["items"]:
        if "items" in item_data:
            yield from _parse_thermostat_devices(item_data)
        # the gateway itself appears under items, but let's exclude it
        elif "device_code" in item_data and "occupants_permissions" not in item_data:
            yield ThermostatAttributes(
                type=DeviceType.DEVICE, **_parse_device_attributes(item_data)
            )


_SHADOW_TO_ATTRIBUTES_MAP: list[tuple[str, str, Callable[[typing.Any], typing.Any]]] = [
    ("temperature", "ep1:sTherS:HeatingSetpoint_x100", lambda v: float(v) / 100),
    (
        "current_temperature",
        "ep1:sTherS:LocalTemperature_x100",
        lambda v: float(v) / 100,
    ),
    ("min_temp", "ep1:sTherS:MinHeatSetpoint_x100", lambda v: float(v) / 100),
    ("max_temp", "ep1:sTherS:MaxHeatSetpoint_x100", lambda v: float(v) / 100),
    ("system_mode", "ep1:sTherS:RunningMode", SystemMode),
]


def _parse_shadow_attributes(shadow_state: Mapping[str, typing.Any]):
    ret = {}
    for attr_key, shadow_key, transform in _SHADOW_TO_ATTRIBUTES_MAP:
        if (
            value := deep_get(shadow_state, ["11", "properties", shadow_key])
        ) is not None:
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
        "temperature",
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
    return ShadowState(desired={"11": {"properties": desired_properties}})


async def _construct_client_data(id_token: str, access_token: str, client: "Client"):
    service_api = _create_service_api()
    gateways = []
    async with aiohttp.ClientSession() as aiohttp_session:
        slider_list = await service_api.get_slider_list(
            id_token, access_token, aiohttp_session
        )
        for gateway_data in slider_list["data"]:
            if gateway_data.get("type") == "gateway":
                attributes = _parse_gateway_attributes(gateway_data)
                slider_details = await service_api.get_slider_details(
                    str(attributes.id),
                    attributes.type.value,
                    id_token,
                    access_token,
                    aiohttp_session,
                )
                gateways.append(
                    Gateway(
                        attributes,
                        _parse_thermostat_devices(slider_details["data"]),
                        client.refresh_device_state,
                        client.update_device_state,
                    )
                )
    return gateways


def _create_aws_api(username: str):
    return AwsApi(username)


def _create_service_api():
    return ServiceApi()


class _CredentialsStore:
    """Cache and rotate AWS credentials"""

    def __init__(self, api: AwsApi):
        self._api = api
        self._credentials: dict[uuid.UUID, AwsCredentialsProvider] = {}

    def credentials_provider_for_occupant(self, occupant: Occupant):
        """Get credentials provider for an occupant"""
        credentials = self._credentials.get(occupant.id)
        if not credentials:
            credentials = self._api.get_credentials_provider(occupant.identity_id)
            self._credentials[occupant.id] = credentials
        return credentials


class _MqttClientManager(contextlib.AbstractAsyncContextManager):
    """Manage shadow clients for devices"""

    def __init__(self, aws: AwsApi, credentials_store: _CredentialsStore):
        self._aws = aws
        self._credentials_store = credentials_store
        self._on_update_callbacks: list[
            Callable[[str, str, GetShadowResponse | UpdateShadowResponse], None]
        ] = []
        self._shadow_clients: dict[uuid.UUID, IotShadowClient] = {}

    async def __aexit__(self, exc_type, exc_value, traceback):
        await asyncio.gather(
            *(
                asyncio.wrap_future(client.mqtt_connection.disconnect())
                for client in self._shadow_clients.values()
            )
        )

    def register_callback(
        self, callback: Callable[[str, str, GetShadowResponse], None]
    ):
        """Register callback that will be invoked when device state is updated

        The arguments to the callback will be the gateway device code, child
        device code, and the response, respectively.
        """
        self._on_update_callbacks.append(callback)

    def remove_callback(self, callback: Callable[[str, str, GetShadowResponse], None]):
        """Remove previously registered callback"""
        self._on_update_callbacks.remove(callback)

    async def client_for_gateway(
        self,
        occupant: Occupant,
        device_code: str,
        child_device_codes: Iterable[str],
    ) -> IotShadowClient:
        """Get shadow client for a given gateway"""
        client = self._shadow_clients.get(occupant.id)
        if not client:
            client = await self._build_shadow_client_with_subscriptions(
                occupant, device_code, child_device_codes
            )
            self._shadow_clients[occupant.id] = client
        return client

    async def _build_shadow_client_with_subscriptions(
        self,
        occupant: Occupant,
        device_code: str,
        child_device_codes: Iterable[str],
    ):
        loop = asyncio.get_event_loop()
        shadow_client = await self._aws.get_iot_shadow_client(
            device_code,
            self._credentials_store.credentials_provider_for_occupant(occupant),
        )
        subscription_futures = []
        for child_device_code in child_device_codes:
            bound_on_update = functools.partial(
                loop.call_soon_threadsafe,
                self._on_update_callback,
                device_code,
                child_device_code,
            )
            subscription_futures.extend(
                [
                    shadow_client.subscribe_to_get_shadow_accepted(
                        GetShadowSubscriptionRequest(thing_name=child_device_code),
                        QoS.AT_MOST_ONCE,
                        bound_on_update,
                    ),
                    shadow_client.subscribe_to_update_shadow_accepted(
                        UpdateShadowSubscriptionRequest(thing_name=child_device_code),
                        QoS.AT_MOST_ONCE,
                        bound_on_update,
                    ),
                ]
            )
        await asyncio.gather(
            *(asyncio.wrap_future(future) for (future, _) in subscription_futures)
        )
        return shadow_client

    def _on_update_callback(
        self,
        device_code: str,
        child_device_code: str,
        response: GetShadowResponse | UpdateShadowResponse,
    ):
        logger.debug(
            "Received shadow doc for %s in %s: %r",
            child_device_code,
            device_code,
            response,
            extra={"response": response},
        )
        for callback in self._on_update_callbacks:
            callback(device_code, child_device_code, response)


class Client(contextlib.AbstractAsyncContextManager):
    """Unisenza Plus Gateway client

    The recommended way to start a client session is with
    :func:`create_client()` context manager.

    Parameters:
      aws: The AWS API object user to access the backend service.  The
           authentication needs to be performed before creting the ``Client``
           object.
    """

    def __init__(self, aws: AwsApi):
        self._exit_stack = contextlib.AsyncExitStack()
        self._aws = aws
        self._gateways: list[Gateway] = []
        self._credentials_store = _CredentialsStore(aws)
        self._mqtt_client_manager = _MqttClientManager(aws, self._credentials_store)
        self._exit_stack.push_async_exit(self._mqtt_client_manager)

    async def aclose(self):
        """Release all resources acquired by the client

        This method is automatically called when the client is used as context
        manager.
        """
        await self._exit_stack.aclose()

    async def __aenter__(self):
        loop = asyncio.get_event_loop()
        callback = functools.partial(loop.call_soon_threadsafe, self._on_update_device)
        self._mqtt_client_manager.register_callback(callback)
        self._exit_stack.callback(self._mqtt_client_manager.remove_callback, callback)
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.aclose()

    async def populate_devices(self):
        """Populate devices from the server"""
        id_token, access_token = self._aws.get_tokens()
        self._gateways = await _construct_client_data(id_token, access_token, self)

    def get_gateways(self) -> list[Gateway]:
        """Get the managed gateways"""
        return self._gateways

    def get_devices(self) -> Iterable[tuple[Gateway, ThermostatDevice]]:
        """Get tuples of gateways and devices managed by them"""
        for gateway in self._gateways:
            for child in gateway.get_children():
                yield gateway, child

    async def refresh_all_devices(self):
        """Refresh states of all managed devices

        This is a convenience function that calls :meth:`refresh_device_state()`
        for all devices known to the client.
        """
        publish_futures = []
        for gateway, child in self.get_devices():
            publish_futures.append(self.refresh_device_state(gateway, child))
        await asyncio.gather(*publish_futures)

    async def refresh_device_state(
        self,
        gateway: Gateway,
        device: Device,
    ):
        """Refresh state of a device from the server

        The coroutine completes when the server has acknowledged the request to
        get the states.  To get notified when the updated state is available,
        use :meth:`Device.subscribe()`

        Arguments:
          gateway: the gateway the device is connected to
          device: the device whose state is refreshed
        """
        client = await self._mqtt_client_for_gateway(gateway)
        request = GetShadowRequest(thing_name=device.get_device_code())
        logger.debug(
            "Publishing get shadow request for %s: %r",
            device.get_device_code(),
            request,
            extra={"request": request},
        )
        return asyncio.wrap_future(
            client.publish_get_shadow(
                request,
                QoS.AT_MOST_ONCE,
            )
        )

    async def update_device_state(
        self,
        gateway: Gateway,
        device: Device,
        changes: Mapping[str, typing.Any],
    ):
        """Update the state of a device managed by the client

        This method will send the changed values to the upstream server.  The
        in-memory attributes will only be updated after the server has
        acknowledged that it has applied the changes.

        The coroutine completes when the server has acknowledged the request to
        get the states.  To get notified when the updated state is available,
        use :meth:`Device.subscribe()`

        Arguments:
          gateway: the gateway the device is connected to
          device: the device whose state is updated
          changes: the changes to be published
        """
        client = await self._mqtt_client_for_gateway(gateway)
        request = UpdateShadowRequest(
            thing_name=device.get_device_code(),
            state=_create_shadow_update_attributes(changes),
        )
        logger.debug(
            "Publishing update shadow request for %s: %r",
            device.get_device_code(),
            request,
            extra={"request": request},
        )
        await asyncio.wrap_future(
            client.publish_update_shadow(request, QoS.AT_MOST_ONCE)
        )

    def _mqtt_client_for_gateway(self, gateway: Gateway):
        return self._mqtt_client_manager.client_for_gateway(
            gateway.get_occupant(),
            gateway.get_device_code(),
            [child.get_device_code() for child in gateway.get_children()],
        )

    def _on_update_device(
        self,
        device_code: str,
        child_device_code: str,
        response: GetShadowResponse | UpdateShadowResponse,
    ):
        for gateway in self._gateways:
            if gateway.get_device_code() == device_code:
                for child in gateway.get_children():
                    if child.get_device_code() == child_device_code:
                        changes = _parse_shadow_attributes(response.state.reported)
                        child.set_attributes(changes)


@contextlib.asynccontextmanager
async def create_client(username: str, password: str):
    """Create Unisenza Plus Gateway client

    This function returns a context manager that initializes and manages
    resources for a :class:`Client` instance.  It also takes care of
    authenticating and populating devices from the server.

    .. code-block:: python

        async with create_client("user@example.com", "password") as client:
           ...  # use client

    Arguments:
      username, password: the credentials used to log into the cloud service
    """

    aws = _create_aws_api(username)
    await aws.authenticate(password)
    async with Client(aws) as client:
        await client.populate_devices()
        yield client
