"""AWS IoT MQTT implementation"""

import asyncio
import contextlib
import functools
import itertools
import json
import logging
import re
import threading
import uuid
from collections.abc import Callable

from awscrt.auth import AwsSigningConfig, aws_sign_request
from awscrt.http import HttpHeaders, HttpRequest
from paho.mqtt.client import MQTT_ERR_SUCCESS, Client

from ._api import PYUPGW_AWS_IOT_ENDPOINT, PYUPGW_AWS_REGION, AwsApi
from .errors import ClientError

logger = logging.getLogger(__name__)

AWS_IOTDEVICEGATEWAY_SERVICE = "iotdevicegateway"
AWS_IOTDEVICEGATEWAY_MQTT_PATH = "/mqtt"
AWS_TOPIC_GET = "get"
AWS_TOPIC_UPDATE = "update"
AWS_TOPIC_ACCEPTED = "accepted"
AWS_TOPIC_REJECTED = "rejected"
AWS_TOPIC_RE = re.compile(
    r"\$aws/things/([\w-]+)/shadow/(get|update)/(accepted|rejected)"
)
MQTT_KEEPALIVE = 30
PUBLISHING_TIMEOUT = 60


def _aws_shadow_topic(thing_name: str, command: str, result: str | None = None):
    suffix = f"/{result}" if result is not None else ""
    return f"$aws/things/{thing_name}/shadow/{command}{suffix}"


class IotShadowMqtt(
    contextlib.AbstractAsyncContextManager
):  # pylint: disable=too-many-instance-attributes
    """MQTT client that interacts with the AWS IoT shadow service

    Spawns a Paho MQTT based network loop that will:
    - Handle connecting to AWS IoT via MQTT over WebSocket
    - Handle sourcing credentials
    - Handle reconnecting, and respawning connection from time to time
    - Give asyncio interface to interacting with the network thread
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        *,
        aws: AwsApi,
        identity_id: str,
        client_name: str,
        thing_names: list[str],
        loop: asyncio.AbstractEventLoop,
        on_response_state_received: Callable[[str, dict | None], None],
    ):
        self._aws = aws
        self._identity_id = identity_id
        self._client_name = client_name
        self._thing_names = thing_names
        self._on_response_state_received = on_response_state_received
        self._loop = loop
        self._client: Client | None = None
        self._publish_lock = threading.Lock()
        self._async_initialized_event = asyncio.Event()
        self._async_quit_done_event = asyncio.Event()
        self._thread = threading.Thread(target=self._mqtt_loop)
        self._pending_publish_futures: dict[str, asyncio.Future] = {}
        self._pending_tasks: list[asyncio.Task] = []

    async def __aenter__(self):
        self._thread.start()
        await self._async_initialized_event.wait()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        for task in self._pending_tasks:
            task.cancel()
        for future in self._pending_publish_futures.values():
            future.cancel()
        self._client.disconnect()
        await self._async_quit_done_event.wait()
        self._thread.join()

    async def get(self, thing_name: str):
        """Publish message to get topic for ``thing_name`` and await response"""
        return await self._publish(thing_name, "get", {})

    async def update(self, thing_name: str, payload: dict):
        """Publish ``payload`` to update topic for ``thing_name`` and await response"""
        return await self._publish(thing_name, "update", payload)

    def _build_headers(self, headers):
        self._aws.check_token()
        credentials_provider = self._aws.get_credentials_provider(self._identity_id)
        signing_config = AwsSigningConfig(
            credentials_provider=credentials_provider,
            region=PYUPGW_AWS_REGION,
            service=AWS_IOTDEVICEGATEWAY_SERVICE,
        )
        http_request = HttpRequest(
            path=AWS_IOTDEVICEGATEWAY_MQTT_PATH,
            headers=HttpHeaders(list(headers.items())),
        )
        signed_http_request = aws_sign_request(
            http_request=http_request,
            signing_config=signing_config,
        ).result()
        return dict(signed_http_request.headers)

    def _mqtt_loop(self):
        client = Client(
            client_id=f"{self._client_name}-{uuid.uuid4()}", transport="websockets"
        )
        client.ws_set_options(
            path=AWS_IOTDEVICEGATEWAY_MQTT_PATH, headers=self._build_headers
        )
        client.tls_set()
        client.on_message = self._on_message
        client.on_connect = self._on_connect
        client.on_subscribe = self._on_subscribe
        client.on_disconnect = self._on_disconnect
        client.connect(PYUPGW_AWS_IOT_ENDPOINT, 443, keepalive=MQTT_KEEPALIVE)
        client.loop_forever()
        self._loop.call_soon_threadsafe(self._async_quit_done_event.set)

    def _on_connect(self, client, _userdata, _flags, _rc):
        logger.info("MQTT client connected")
        client.subscribe(
            [
                (_aws_shadow_topic(thing_name, command, result), 0)
                for (thing_name, command, result) in itertools.product(
                    self._thing_names,
                    [AWS_TOPIC_GET, AWS_TOPIC_UPDATE],
                    [AWS_TOPIC_ACCEPTED, AWS_TOPIC_REJECTED],
                )
            ]
        )

    def _on_subscribe(self, client, _userdata, _mid, _granted_qos):
        logger.info("MQTT client subscribed to topics")
        with self._publish_lock:
            self._client = client
        # We are here after reconnecting. Request new state from devices.
        if self._async_initialized_event.is_set():
            for thing_name in self._thing_names:
                self._loop.call_soon_threadsafe(self._async_get, thing_name)
        self._loop.call_soon_threadsafe(self._async_initialized_event.set)

    def _on_message(self, _client, _userdata, message):
        logger.debug("Received message from %s: %r", message.topic, message.payload)
        parsed_topic = AWS_TOPIC_RE.fullmatch(message.topic)
        if parsed_topic:
            thing_name, _command, result = parsed_topic.groups()
            try:
                parsed_payload = json.loads(message.payload)
            except json.JSONDecodeError:
                logger.warning("Unable to parse MQTT message: %r", message.payload)
                parsed_payload = None
            if result == AWS_TOPIC_ACCEPTED:
                self._loop.call_soon_threadsafe(
                    self._accepted_callback, thing_name, parsed_payload
                )
            elif result == AWS_TOPIC_REJECTED:
                self._loop.call_soon_threadsafe(self._rejected_callback, parsed_payload)

    def _on_disconnect(self, _client, _userdata, rc):
        if rc != MQTT_ERR_SUCCESS:
            logger.warning("MQTT client unexpectedly disconnected with code %r", rc)
        else:
            logger.info("MQTT client disconnected")

    def _accepted_callback(self, thing_name: str, payload: dict | None):
        if publish_future := self._get_pending_publish_future_for_response(payload):
            publish_future.set_result(payload)
        self._on_response_state_received(thing_name, payload)

    def _rejected_callback(self, payload: dict | None):
        if publish_future := self._get_pending_publish_future_for_response(payload):
            publish_future.set_exception(ClientError(f"Message rejected: {payload!r}"))

    def _get_pending_publish_future_for_response(self, payload: dict | None):
        client_token = payload.pop("clientToken", None) if payload else None
        if (
            client_token
            and (publish_future := self._pending_publish_futures.get(client_token))
            and not publish_future.done()
        ):
            return publish_future
        return None

    async def _publish(self, thing_name: str, command: str, payload: dict):
        topic = _aws_shadow_topic(thing_name, command)
        client_token = str(uuid.uuid4())
        payload["clientToken"] = client_token
        publish_future = self._loop.create_future()
        self._pending_publish_futures[client_token] = publish_future
        try:
            async with asyncio.timeout(PUBLISHING_TIMEOUT):
                await asyncio.to_thread(self._do_publish, topic, json.dumps(payload))
                return await publish_future
        finally:
            self._pending_publish_futures.pop(client_token, None)

    def _do_publish(self, topic: str, payload: str):
        with self._publish_lock:
            if not self._client:
                raise ClientError("MQTT client not initialized")
            logger.debug("Publishing message to %s: %r", topic, payload)
            self._client.publish(topic, payload)

    def _async_get(self, thing_name: str):
        task = self._loop.create_task(self.get(thing_name))
        self._pending_tasks.append(task)
        task.add_done_callback(functools.partial(self._pending_tasks.remove, task))
