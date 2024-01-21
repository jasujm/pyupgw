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
    ErrorResponse,
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
    return ShadowState(desired={"11": {"properties": desired_properties}})


async def _construct_client_data(id_token: str, access_token: str, client: "Client"):
    service_api = _create_service_api()
    gateways = []
    async with aiohttp.ClientSession() as aiohttp_session:
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
    return gateways


def _create_aws_api(username: str):
    return AwsApi(username)


def _create_service_api():
    return ServiceApi()


class _CredentialsStore:
    """Cache and rotate AWS credentials"""

    def __init__(self, api: AwsApi):
        self._api = api
        self._credentials_providers: dict[uuid.UUID, AwsCredentialsProvider] = {}
        self._wrapped_credentials_providers: dict[
            uuid.UUID, AwsCredentialsProvider
        ] = {}

    def credentials_provider_for_occupant(self, occupant: Occupant):
        """Get credentials provider for an occupant"""
        credentials_provider = self._credentials_providers.get(occupant.id)
        if not credentials_provider:
            wrapped_credentials_provider = self._api.get_credentials_provider(
                occupant.identity_id
            )
            self._wrapped_credentials_providers[
                occupant.id
            ] = wrapped_credentials_provider
            credentials_provider = self._create_credentials_provider(occupant)
            self._credentials_providers[occupant.id] = credentials_provider
        return credentials_provider

    def _create_credentials_provider(self, occupant: Occupant):
        return AwsCredentialsProvider.new_delegate(
            functools.partial(self._get_credentials, occupant)
        )

    def _get_credentials(self, occupant: Occupant):
        token_expired = self._api.check_token()
        if token_expired:
            wrapped_credentials_provider = self._api.get_credentials_provider(
                occupant.identity_id
            )
            self._wrapped_credentials_providers[
                occupant.id
            ] = wrapped_credentials_provider
        else:
            wrapped_credentials_provider = self._wrapped_credentials_providers[
                occupant.id
            ]
        return wrapped_credentials_provider.get_credentials().result()


class _MqttClientManager(contextlib.AbstractAsyncContextManager):
    """Manage shadow clients for devices"""

    def __init__(self, aws: AwsApi, credentials_store: _CredentialsStore):
        self._aws = aws
        self._credentials_store = credentials_store
        self._on_update_callbacks: list[
            Callable[[str, str, UpdateShadowResponse], None]
        ] = []
        self._shadow_clients: dict[uuid.UUID, IotShadowClient] = {}
        self._pending_responses: dict[str, asyncio.Future] = {}

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

    @contextlib.asynccontextmanager
    async def publishing(self):
        """Publishing context that helps waiting for reply"""
        client_token = str(uuid.uuid4())
        exit_stack = contextlib.ExitStack()

        async def wrap_publish(
            publish: Callable[[typing.Any, QoS], "concurrent.futures.Future"],
            request: typing.Any,
        ):
            loop = asyncio.get_event_loop()
            response_future = loop.create_future()
            self._pending_responses[client_token] = response_future
            exit_stack.callback(self._pending_responses.pop, client_token)
            await asyncio.wrap_future(
                publish(
                    request,
                    QoS.AT_MOST_ONCE,
                )
            )
            return await response_future

        with exit_stack:
            yield wrap_publish, client_token

    async def _build_shadow_client_with_subscriptions(
        self,
        occupant: Occupant,
        device_code: str,
        child_device_codes: Iterable[str],
    ):
        loop = asyncio.get_event_loop()
        credentials_provider = await asyncio.to_thread(
            functools.partial(
                self._credentials_store.credentials_provider_for_occupant,
                occupant,
            )
        )
        shadow_client = await self._aws.get_iot_shadow_client(
            device_code, credentials_provider
        )
        subscription_futures = []
        for child_device_code in child_device_codes:
            bound_on_get = functools.partial(
                loop.call_soon_threadsafe,
                self._on_get_callback,
            )
            bound_on_update = functools.partial(
                loop.call_soon_threadsafe,
                self._on_update_callback,
                device_code,
                child_device_code,
            )
            bound_on_error = functools.partial(
                loop.call_soon_threadsafe,
                self._on_error_callback,
            )
            subscription_futures.extend(
                [
                    shadow_client.subscribe_to_get_shadow_accepted(
                        GetShadowSubscriptionRequest(thing_name=child_device_code),
                        QoS.AT_MOST_ONCE,
                        bound_on_get,
                    ),
                    shadow_client.subscribe_to_get_shadow_rejected(
                        GetShadowSubscriptionRequest(thing_name=child_device_code),
                        QoS.AT_MOST_ONCE,
                        bound_on_error,
                    ),
                    shadow_client.subscribe_to_update_shadow_accepted(
                        UpdateShadowSubscriptionRequest(thing_name=child_device_code),
                        QoS.AT_MOST_ONCE,
                        bound_on_update,
                    ),
                    shadow_client.subscribe_to_update_shadow_rejected(
                        UpdateShadowSubscriptionRequest(thing_name=child_device_code),
                        QoS.AT_MOST_ONCE,
                        bound_on_error,
                    ),
                ]
            )
        await asyncio.gather(
            *(asyncio.wrap_future(future) for (future, _) in subscription_futures)
        )
        return shadow_client

    def _resolve_response_future(
        self,
        response: GetShadowResponse | UpdateShadowResponse,
    ):
        if (
            (client_token := response.client_token)
            and (response_future := self._pending_responses.get(client_token))
            and not response_future.done()
        ):
            response_future.set_result(response)

    def _on_error_callback(
        self,
        response: ErrorResponse,
    ):
        if (
            (client_token := response.client_token)
            and (response_future := self._pending_responses.get(client_token))
            and not response_future.done()
        ):
            response_future.set_exception(
                ClientError(f"Request rejected: {response.message} ({response.code})")
            )

    def _on_get_callback(
        self,
        response: GetShadowResponse,
    ):
        self._resolve_response_future(response)

    def _on_update_callback(
        self,
        device_code: str,
        child_device_code: str,
        response: UpdateShadowResponse,
    ):
        self._resolve_response_future(response)
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
        self._credentials_store = _CredentialsStore(aws)
        self._mqtt_client_manager = _MqttClientManager(aws, self._credentials_store)
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
        """Populate devices from the server"""
        id_token, access_token = await asyncio.to_thread(self._aws.get_tokens)
        self._gateways = await _construct_client_data(id_token, access_token, self)

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

        The coroutine completes when the server has responded with the new state.

        Arguments:
          gateway: the gateway the device is connected to
          device: the device whose state is refreshed

        Raises:
          ClientError: if the request to get device state fails
        """
        client = await self._mqtt_client_for_gateway(gateway)
        async with self._mqtt_client_manager.publishing() as (
            wrap_publish,
            client_token,
        ):
            request = GetShadowRequest(
                thing_name=device.get_device_code(), client_token=client_token
            )
            logger.debug(
                "Publishing get shadow request for %s: %r",
                device.get_device_code(),
                request,
                extra={"request": request},
            )
            response = await wrap_publish(client.publish_get_shadow, request)
            logger.debug(
                "Get shadow response for %s: %r",
                device.get_device_code(),
                response,
                extra={"response": response},
            )
        changes = _parse_shadow_attributes(response.state.reported)
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
        async with self._mqtt_client_manager.publishing() as (
            wrap_publish,
            client_token,
        ):
            request = UpdateShadowRequest(
                client_token=client_token,
                thing_name=device.get_device_code(),
                state=_create_shadow_update_attributes(changes),
            )
            logger.debug(
                "Publishing update shadow request for %s: %r",
                device.get_device_code(),
                request,
                extra={"request": request},
            )
            await wrap_publish(client.publish_update_shadow, request)

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
        logger.debug(
            "Received update for %s in %s: %r",
            child_device_code,
            device_code,
            response,
            extra={"response": response},
        )
        for gateway in self._gateways:
            if gateway.get_device_code() == device_code:
                for child in gateway.get_children():
                    if child.get_device_code() == child_device_code:
                        changes = _parse_shadow_attributes(response.state.reported)
                        child.set_attributes(changes)


async def create_api(username: str, password: str) -> AwsApi:
    """Create authenticated AWS API instance

    The instance can be used to create :class:`Client` instance.  For a single
    step creation, use :func:`create_client()` function instead.

    Arguments:
      username, password: the credentials used to log into the cloud service

    Raises:
      AuthenticationError: if authentication fails
    """
    aws = _create_aws_api(username)
    logger.debug("Authenticating user %s", username)
    try:
        await asyncio.to_thread(functools.partial(aws.authenticate, password))
    except Exception as ex:
        raise AuthenticationError(f"Failed to authenticate {username}") from ex
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
