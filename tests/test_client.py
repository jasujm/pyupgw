"""Tests for the UPGW client"""

# pylint: disable=redefined-outer-name

import contextlib
import unittest.mock
from concurrent.futures import Future

import pytest
from attrs import define
from hypothesis import given
from hypothesis import strategies as st

import pyupgw._api
import pyupgw.client
from pyupgw import (
    AuthenticationError,
    GatewayAttributes,
    HvacAttributes,
    create_api,
    create_client,
)

ID_TOKEN = "id_token"
ACCESS_TOKEN = "access_token"
USERNAME = "username"
PASSWORD = "password"


GatewayData = tuple[GatewayAttributes, list[HvacAttributes]]


@define
class _MockAws:
    authenticate: unittest.mock.Mock
    check_token: unittest.mock.Mock
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
        authenticate=unittest.mock.Mock(return_value=(ID_TOKEN, ACCESS_TOKEN)),
        check_token=unittest.mock.Mock(return_value=False),
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
async def test_authenticate_with_success(client_setup):
    with client_setup([]) as (aws, _, _):
        api = await create_api(USERNAME, PASSWORD)
    assert api is aws
    aws.authenticate.assert_called_with(PASSWORD)


class NotAuthorized(Exception):
    """Mock not authorized exception"""


@pytest.mark.asyncio
async def test_authenticate_with_failure(client_setup):
    with client_setup([]) as (aws, _, _):
        aws.authenticate.side_effect = NotAuthorized("wrong password")
        with pytest.raises(AuthenticationError):
            await create_api(USERNAME, PASSWORD)
    aws.authenticate.assert_called_with(PASSWORD)


@pytest.mark.asyncio
@given(
    gateways=st.lists(
        st.tuples(
            st.builds(GatewayAttributes),
            st.lists(
                st.builds(
                    HvacAttributes,
                    system_mode=st.none(),
                    target_temperature=st.none(),
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

        aws.authenticate.assert_called_once()
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
