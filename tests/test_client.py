"""Tests for the UPGW client"""

# pylint: disable=redefined-outer-name

import asyncio
import contextlib
import unittest.mock
from concurrent.futures import Future

import pytest
from attrs import define
from awsiot.iotshadow import GetShadowResponse, ShadowStateWithDelta
from hypothesis import given
from hypothesis import strategies as st

import pyupgw.client
from pyupgw import GatewayAttributes, SystemMode, ThermostatAttributes, create_client

ID_TOKEN = "id_token"
ACCESS_TOKEN = "access_token"
USERNAME = "username"
PASSWORD = "password"


GatewayData = tuple[GatewayAttributes, list[ThermostatAttributes]]

gateway_data = st.tuples(
    st.builds(GatewayAttributes),
    st.lists(
        st.builds(
            ThermostatAttributes,
            system_mode=st.none(),
            temperature=st.none(),
            current_temperature=st.none(),
            min_temp=st.none(),
            max_temp=st.none(),
        )
    ),
)


@define
class _MockAws:
    authenticate: unittest.mock.AsyncMock
    get_tokens: unittest.mock.Mock
    get_credentials_provider: unittest.mock.Mock
    get_iot_shadow_client: unittest.mock.AsyncMock


@define
class _MockShadowClient:
    subscribe_to_get_shadow_accepted: unittest.mock.Mock
    subscribe_to_update_shadow_accepted: unittest.mock.Mock
    publish_get_shadow: unittest.mock.Mock
    publish_update_shadow: unittest.mock.Mock
    mqtt_connection: unittest.mock.MagicMock


def _instant_future(result):
    future = Future()
    future.set_result(result)
    return future


def _mock_aws(monkeypatch) -> tuple[_MockAws, _MockShadowClient]:
    mock_shadow_client = _MockShadowClient(
        subscribe_to_get_shadow_accepted=unittest.mock.Mock(
            side_effect=lambda *_, **__: (_instant_future(None), 0)
        ),
        subscribe_to_update_shadow_accepted=unittest.mock.Mock(
            side_effect=lambda *_, **__: (_instant_future(None), 0)
        ),
        publish_get_shadow=unittest.mock.Mock(
            side_effect=lambda *_, **__: _instant_future(None)
        ),
        publish_update_shadow=unittest.mock.Mock(
            side_effect=lambda *_, **__: _instant_future(None)
        ),
        mqtt_connection=unittest.mock.MagicMock(),
    )
    mock_shadow_client.mqtt_connection.disconnect.side_effect = lambda: _instant_future(
        None
    )
    mock_aws = _MockAws(
        authenticate=unittest.mock.AsyncMock(return_value=(ID_TOKEN, ACCESS_TOKEN)),
        get_tokens=unittest.mock.Mock(return_value=(ID_TOKEN, ACCESS_TOKEN)),
        get_credentials_provider=unittest.mock.Mock(return_value=object()),
        get_iot_shadow_client=unittest.mock.AsyncMock(return_value=mock_shadow_client),
    )
    monkeypatch.setattr(pyupgw.client, "_create_aws_api", lambda username: mock_aws)
    return mock_aws, mock_shadow_client


@define
class _MockServiceApi:
    get_slider_list: unittest.mock.AsyncMock
    get_slider_details: unittest.mock.AsyncMock


def _mock_service_api(monkeypatch, gateways: list[GatewayData]) -> _MockServiceApi:
    slider_list_data = [
        {
            "id": str(attributes.id),
            "type": attributes.type.value,
            "gateway": {
                "id": str(attributes.id),
                "device_code": attributes.device_code,
                "model": attributes.model,
                "name": attributes.name,
                "occupants_permissions": {
                    "receiver_occupant": {
                        "id": str(attributes.occupant.id),
                        "identity_id": attributes.occupant.identity_id,
                    }
                },
            },
        }
        for (attributes, _) in gateways
    ]

    slider_details_map = {
        slider_data["id"]: {
            "data": {
                **slider_data,
                "items": [
                    slider_data["gateway"],
                    *(
                        {
                            "id": str(item.id),
                            "device_code": item.device_code,
                            "model": item.model,
                            "name": item.name,
                        }
                        for item in gateways[i][1]
                    ),
                ],
            }
        }
        for (i, slider_data) in enumerate(slider_list_data)
    }

    def get_slider_details_impl(slider_id, *_, **__):
        return slider_details_map[str(slider_id)]

    ret = _MockServiceApi(
        get_slider_list=unittest.mock.AsyncMock(
            return_value={"data": slider_list_data}
        ),
        get_slider_details=unittest.mock.AsyncMock(side_effect=get_slider_details_impl),
    )
    monkeypatch.setattr(pyupgw.client, "_create_service_api", lambda: ret)

    return ret


@st.composite
def _gateway_data_and_items(draw, items):
    size = draw(st.integers(min_value=0, max_value=10))
    gateway_data = draw(
        st.tuples(
            st.builds(GatewayAttributes),
            st.lists(st.builds(ThermostatAttributes), min_size=size, max_size=size),
        )
    )
    items = draw(
        st.lists(
            items,
            min_size=size,
            max_size=size,
        )
    )
    return gateway_data, items


@pytest.fixture(scope="session")
def client_setup():
    """Context manager to setup low level clients"""

    @contextlib.contextmanager
    def context(gateways: list[GatewayData]):
        with pytest.MonkeyPatch().context() as m:
            aws, shadow_client = _mock_aws(m)
            service_api = _mock_service_api(m, gateways)
            yield aws, service_api, shadow_client

    return context


@pytest.mark.asyncio
@given(
    gateways=st.lists(
        st.tuples(
            st.builds(GatewayAttributes),
            st.lists(
                st.builds(
                    ThermostatAttributes,
                    system_mode=st.none(),
                    temperature=st.none(),
                    current_temperature=st.none(),
                    min_temp=st.none(),
                    max_temp=st.none(),
                )
            ),
        )
    )
)
async def test_get_gateways(gateways: list[GatewayData], client_setup):
    with client_setup(gateways) as (aws, service_api, _):
        async with create_client(USERNAME, PASSWORD) as client:
            for (
                expected_attributes,
                expected_children_attributes,
            ), actual_gateway in zip(gateways, client.get_gateways()):
                assert actual_gateway.get_attributes() == expected_attributes
                assert [
                    device.get_attributes() for device in actual_gateway.get_children()
                ] == expected_children_attributes

        aws.authenticate.assert_awaited_once()
        service_api.get_slider_list.assert_awaited_once_with(
            ID_TOKEN, ACCESS_TOKEN, unittest.mock.ANY
        )
        for expected_attributes, _ in gateways:
            service_api.get_slider_details.assert_any_await(
                str(expected_attributes.id),
                expected_attributes.type.value,
                ID_TOKEN,
                ACCESS_TOKEN,
                unittest.mock.ANY,
            )


@pytest.mark.asyncio
@given(
    gateway_data_and_update_replies=_gateway_data_and_items(
        st.fixed_dictionaries(
            {
                "system_mode": st.sampled_from(SystemMode),
                "temperature": st.floats(5.0, 30.0).map(lambda v: round(v, 2)),
                "current_temperature": st.floats(5.0, 30.0).map(lambda v: round(v, 2)),
                "min_temp": st.floats(5.0, 30.0).map(lambda v: round(v, 2)),
                "max_temp": st.floats(5.0, 30.0).map(lambda v: round(v, 2)),
            }
        )
    )
)
async def test_refresh_device_state(gateway_data_and_update_replies, client_setup):
    gateway_data, update_replies = gateway_data_and_update_replies
    with client_setup([gateway_data]) as (aws, _, shadow_client):
        async with create_client(USERNAME, PASSWORD) as client:
            gateway = client.get_gateways()[0]
            await client.refresh_all_devices()
            for subscribe_call, device, update_reply in zip(
                shadow_client.subscribe_to_get_shadow_accepted.call_args_list,
                gateway.get_children(),
                update_replies,
            ):
                update_event = asyncio.Event()
                notify_update = unittest.mock.Mock(
                    side_effect=lambda *_: update_event.set()  # pylint: disable=cell-var-from-loop
                )
                device.subscribe(notify_update)
                update_callback = subscribe_call.args[2]
                update_callback(
                    GetShadowResponse(
                        state=ShadowStateWithDelta(
                            reported={
                                "11": {
                                    "properties": {
                                        "ep1:sTherS:RunningMode": update_reply[
                                            "system_mode"
                                        ].value,
                                        "ep1:sTherS:HeatingSetpoint_x100": round(
                                            update_reply["temperature"] * 100
                                        ),
                                        "ep1:sTherS:LocalTemperature_x100": round(
                                            update_reply["current_temperature"] * 100
                                        ),
                                        "ep1:sTherS:MinHeatSetpoint_x100": round(
                                            update_reply["min_temp"] * 100
                                        ),
                                        "ep1:sTherS:MaxHeatSetpoint_x100": round(
                                            update_reply["max_temp"] * 100
                                        ),
                                    }
                                }
                            }
                        )
                    )
                )
                await update_event.wait()
                device.unsubscribe(notify_update)
                notify_update.assert_called()
                attributes = device.get_attributes()
                assert {
                    "system_mode": attributes.system_mode,
                    "temperature": attributes.temperature,
                    "current_temperature": attributes.current_temperature,
                    "min_temp": attributes.min_temp,
                    "max_temp": attributes.max_temp,
                } == update_reply

        if gateway.get_children():
            aws.get_credentials_provider.assert_called_with(
                gateway.get_occupant().identity_id
            )
            aws.get_iot_shadow_client.assert_called()
            shadow_client.subscribe_to_get_shadow_accepted.assert_called()
            shadow_client.publish_get_shadow.assert_called()
        else:
            shadow_client.subscribe_to_get_shadow_accepted.assert_not_called()
            shadow_client.publish_get_shadow.assert_not_called()


@pytest.mark.asyncio
@given(
    gateway_data_and_update_requests=_gateway_data_and_items(
        st.fixed_dictionaries(
            {
                "system_mode": st.sampled_from(SystemMode),
                "temperature": st.floats(5.0, 30.0).map(lambda v: round(v, 2)),
            }
        ),
    )
)
async def test_update_device_state(gateway_data_and_update_requests, client_setup):
    gateway_data, update_requests = gateway_data_and_update_requests
    with client_setup([gateway_data]) as (aws, _, shadow_client):
        async with create_client(USERNAME, PASSWORD) as client:
            gateway = client.get_gateways()[0]
            for device, update_request in zip(
                gateway.get_children(),
                update_requests,
            ):
                await client.update_device_state(gateway, device, update_request)
                shadow_client.publish_update_shadow.assert_called()
                actual_request = shadow_client.publish_update_shadow.call_args.args[0]
                desired_properties = {}
                if "temperature" in update_request:
                    desired_properties["ep1:sTherS:SetHeatingSetpoint_x100"] = round(
                        update_request["temperature"] * 100
                    )
                if "system_mode" in update_request:
                    desired_properties["ep1:sTherS:SetSystemMode"] = update_request[
                        "system_mode"
                    ].value
                assert actual_request.state.desired == {
                    "11": {"properties": desired_properties}
                }

        if gateway.get_children():
            aws.get_iot_shadow_client.assert_called()
            aws.get_credentials_provider.assert_called_with(
                gateway.get_occupant().identity_id
            )
            shadow_client.subscribe_to_update_shadow_accepted.assert_called()
            shadow_client.publish_update_shadow.assert_called()
        else:
            shadow_client.subscribe_to_update_shadow_accepted.assert_not_called()
            shadow_client.publish_update_shadow.assert_not_called()
