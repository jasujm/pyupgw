"""Tests for the UPGW client"""

import asyncio
import contextlib
import logging
import unittest.mock

import pytest
from attrs import define
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

import pyupgw._api
import pyupgw._mqtt
import pyupgw.client
from pyupgw import (
    AuthenticationError,
    ClientError,
    DeviceType,
    GatewayAttributes,
    HvacAttributes,
    RunningState,
    SystemMode,
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


def _mock_aws(monkeypatch) -> _MockAws:
    mock_aws = _MockAws(
        authenticate=unittest.mock.Mock(return_value=(ID_TOKEN, ACCESS_TOKEN)),
        check_token=unittest.mock.Mock(return_value=False),
        get_tokens=unittest.mock.Mock(return_value=(ID_TOKEN, ACCESS_TOKEN)),
        get_credentials_provider=unittest.mock.Mock(return_value=object()),
    )
    monkeypatch.setattr(pyupgw.client, "_create_aws_api", lambda username: mock_aws)
    return mock_aws


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
                    {
                        "items": [
                            {
                                "id": str(item.id),
                                "device_code": item.device_code,
                                "model": item.model,
                                "name": item.name,
                            }
                            for item in gateways[i][1]
                        ]
                    },
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


@define
class _MockIotShadowMqtt:
    get: unittest.mock.AsyncMock
    update: unittest.mock.AsyncMock
    kwargs: dict

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _mock_shadow_iot(monkeypatch):
    ret = _MockIotShadowMqtt(
        get=unittest.mock.AsyncMock(return_value={}),
        update=unittest.mock.AsyncMock(),
        kwargs={},
    )

    def _create_client_mock(**kwargs):
        ret.kwargs = kwargs
        return ret

    class_mock = unittest.mock.MagicMock(side_effect=_create_client_mock)
    monkeypatch.setattr(pyupgw.client, "_create_iot_shadow_client", class_mock)
    return ret


@pytest.fixture(scope="session")
def client_setup():
    """Context manager to setup low level clients"""

    @contextlib.contextmanager
    def context(gateways: list[GatewayData]):
        with pytest.MonkeyPatch().context() as m:
            aws = _mock_aws(m)
            service_api = _mock_service_api(m, gateways)
            mqtt_client = _mock_shadow_iot(m)
            yield aws, service_api, mqtt_client

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
async def test_authenticate_with_misc_failure(client_setup):
    with client_setup([]) as (aws, _, _):
        aws.authenticate.side_effect = Exception("it fails :(")
        with pytest.raises(Exception):
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


@pytest.mark.asyncio
async def test_get_gateways_failure(client_setup):
    with client_setup([]) as (aws, service_api, _):
        service_api.get_slider_list.side_effect = Exception("It fails :(")
        with pytest.raises(ClientError):
            await create_client(USERNAME, PASSWORD).__aenter__()


@pytest.mark.asyncio
@given(
    gateway=...,
    hvac_attributes=st.builds(
        HvacAttributes,
        target_temperature=st.floats(0.0, 30.0),
        current_temperature=st.floats(0.0, 30.0),
        min_temp=st.floats(0.0, 30.0),
        max_temp=st.floats(0.0, 30.0),
        system_mode=st.sampled_from(SystemMode),
        running_state=st.sampled_from(RunningState),
    ),
)
async def test_refresh_device_states(
    gateway: GatewayData, hvac_attributes: HvacAttributes, client_setup
):
    # to satisfy mypy
    assert hvac_attributes.target_temperature is not None
    assert hvac_attributes.current_temperature is not None
    assert hvac_attributes.min_temp is not None
    assert hvac_attributes.max_temp is not None
    assert hvac_attributes.system_mode is not None
    assert hvac_attributes.running_state is not None
    with client_setup([gateway]) as (_, _, mqtt):
        mqtt.get.return_value = {
            "state": {
                "reported": {
                    "connected": "true",
                    "11": {
                        "properties": {
                            "ep1:sZDO:EUID": hvac_attributes.euid,
                            "ep1:sPowerMS:RadSerialNum": hvac_attributes.serial_number,
                            "ep1:sBasicS:ManufactureName": hvac_attributes.manufacturer,
                            "ep1:sZDO:FirmwareVersion": hvac_attributes.firmware_version,
                            "ep1:sTherS:HeatingSetpoint_x100": str(
                                round(100 * hvac_attributes.target_temperature)
                            ),
                            "ep1:sTherS:LocalTemperature_x100": str(
                                round(100 * hvac_attributes.current_temperature)
                            ),
                            "ep1:sTherS:MinHeatSetpoint_x100": str(
                                round(100 * hvac_attributes.min_temp)
                            ),
                            "ep1:sTherS:MaxHeatSetpoint_x100": str(
                                round(100 * hvac_attributes.max_temp)
                            ),
                            "ep1:sTherS:RunningMode": hvac_attributes.system_mode.value,
                            "ep1:sTherS:RunningState": hvac_attributes.running_state.value,
                        }
                    },
                }
            }
        }
        async with create_client(USERNAME, PASSWORD) as client:
            await client.refresh_all_devices()
            for _, device in client.get_devices():
                if device.get_type() == DeviceType.HVAC:
                    assert device.get_serial_number() == hvac_attributes.serial_number
                    assert device.get_manufacturer() == hvac_attributes.manufacturer
                    assert (
                        device.get_firmware_version()
                        == hvac_attributes.firmware_version
                    )
                    assert device.get_target_temperature() == round(
                        hvac_attributes.target_temperature, 2
                    )
                    assert device.get_current_temperature() == round(
                        hvac_attributes.current_temperature, 2
                    )
                    assert device.get_min_temp() == round(hvac_attributes.min_temp, 2)
                    assert device.get_max_temp() == round(hvac_attributes.max_temp, 2)
                    assert device.get_system_mode() == hvac_attributes.system_mode
                    assert device.get_running_state() == hvac_attributes.running_state


@pytest.mark.asyncio
@given(
    gateway_attributes=...,
    device_attributes=...,
)
async def test_refresh_device_states_fail(
    gateway_attributes: GatewayAttributes,
    device_attributes: HvacAttributes,
    client_setup,
):
    with client_setup([(gateway_attributes, [device_attributes])]) as (_, _, mqtt):
        mqtt.get.side_effect = Exception("It fails :(")
        async with create_client(USERNAME, PASSWORD) as client:
            gateway = client.get_gateways()[0]
            device = gateway.get_children()[0]
            with pytest.raises(ClientError):
                await client.refresh_device_state(gateway, device)


@pytest.mark.asyncio
@given(
    gateway_attributes=...,
    device_attributes=...,
    changes=st.fixed_dictionaries(
        {},
        optional={
            "target_temperature": st.floats(0.0, 30.0),
            "system_mode": st.sampled_from(SystemMode),
        },
    ),
)
async def test_update_device_state(
    gateway_attributes: GatewayAttributes,
    device_attributes: HvacAttributes,
    changes: dict,
    client_setup,
):
    with client_setup([(gateway_attributes, [device_attributes])]) as (_, _, mqtt):
        async with create_client(USERNAME, PASSWORD) as client:
            gateway = client.get_gateways()[0]
            device = gateway.get_children()[0]
            await client.update_device_state(gateway, device, changes)
            expected_properties = {}
            if (target_temperature := changes.get("target_temperature")) is not None:
                expected_properties["ep1:sTherS:SetHeatingSetpoint_x100"] = round(
                    100 * target_temperature
                )
            if (system_mode := changes.get("system_mode")) is not None:
                expected_properties["ep1:sTherS:SetSystemMode"] = system_mode.value
            mqtt.update.assert_awaited_with(
                device_attributes.device_code,
                {"state": {"desired": {"11": {"properties": expected_properties}}}},
            )


@pytest.mark.asyncio
@given(
    gateway_attributes=...,
    device_attributes=...,
    changes=st.fixed_dictionaries(
        {
            "target_temperature": st.floats(0.0, 30.0),
            "system_mode": st.sampled_from(SystemMode),
        }
    ),
)
async def test_update_device_state_fail(
    gateway_attributes: GatewayAttributes,
    device_attributes: HvacAttributes,
    changes: dict,
    client_setup,
):
    with client_setup([(gateway_attributes, [device_attributes])]) as (_, _, mqtt):
        mqtt.update.side_effect = Exception("It fails :(")
        async with create_client(USERNAME, PASSWORD) as client:
            gateway = client.get_gateways()[0]
            device = gateway.get_children()[0]
            with pytest.raises(ClientError):
                await client.update_device_state(gateway, device, changes)


@pytest.mark.asyncio
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    gateway_attributes=...,
    device_attributes=...,
    invalid_temperature=...,
)
async def test_update_device_state_warns_on_unparseable_attribute(
    gateway_attributes: GatewayAttributes,
    device_attributes: HvacAttributes,
    invalid_temperature: str,
    client_setup,
    caplog,
):
    try:
        float(invalid_temperature)
    except Exception:
        pass
    else:
        assume(False)
    try:
        with client_setup([(gateway_attributes, [device_attributes])]) as (_, _, mqtt):
            mqtt.get.return_value = {
                "state": {
                    "reported": {
                        "connected": "true",
                        "11": {
                            "properties": {
                                "ep1:sTherS:LocalTemperature_x100": invalid_temperature,
                            }
                        },
                    }
                }
            }
            async with create_client(USERNAME, PASSWORD) as client:
                gateway = client.get_gateways()[0]
                device = gateway.get_children()[0]
                with caplog.at_level(logging.WARNING):
                    await client.refresh_device_state(gateway, device)
                assert len(caplog.records) > 0
    finally:
        caplog.clear()


@pytest.mark.asyncio
@given(
    gateway_attributes=...,
    device_attributes=...,
    target_temperature=st.floats(0.0, 30.0),
)
async def test_receive_response_state(
    gateway_attributes: GatewayAttributes,
    device_attributes: HvacAttributes,
    target_temperature: float,
    client_setup,
):
    target_temperature = round(target_temperature, 2)
    assume(gateway_attributes.device_code != device_attributes.device_code)
    with client_setup([(gateway_attributes, [device_attributes])]) as (_, _, mqtt):
        async with create_client(USERNAME, PASSWORD) as client:
            gateway = client.get_gateways()[0]
            device = gateway.get_children()[0]

            update_event = asyncio.Event()

            def _on_update(_device, _changes):
                update_event.set()
                assert _device is device
                assert _changes["target_temperature"] == target_temperature

            device.subscribe(_on_update)

            await client.refresh_device_state(gateway, device)
            on_response_state_received = mqtt.kwargs["on_response_state_received"]
            on_response_state_received(
                device_attributes.device_code,
                {
                    "state": {
                        "reported": {
                            "connected": "true",
                            "11": {
                                "properties": {
                                    "ep1:sTherS:HeatingSetpoint_x100": str(
                                        round(100 * target_temperature)
                                    ),
                                }
                            },
                        }
                    }
                },
            )

            async with asyncio.timeout(0.1):
                await update_event.wait()

            assert device.get_target_temperature() == target_temperature

            device.unsubscribe(_on_update)
