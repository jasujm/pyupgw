"""Tests for the UPGW client"""

import unittest.mock

import pytest
from attrs import define, field
from hypothesis import given
from hypothesis import strategies as st

import pyupgw.client
from pyupgw import DeviceAttributes, DeviceType, GatewayAttributes, create_client


def _mock_aws(monkeypatch):
    @define
    class _MockAws:
        authenticate = field(default=unittest.mock.AsyncMock())

    ret = _MockAws()
    monkeypatch.setattr(pyupgw.client, "_create_aws_api", lambda username: ret)
    return ret


def _mock_service_api(monkeypatch):
    @define
    class _MockServiceApi:
        get_slider_list = field(default=unittest.mock.AsyncMock())
        get_slider_details = field(default=unittest.mock.AsyncMock())

    ret = _MockServiceApi()
    monkeypatch.setattr(pyupgw.client, "_create_service_api", lambda: ret)
    return ret


@pytest.mark.asyncio
@given(
    gateways=st.lists(
        st.tuples(
            st.builds(GatewayAttributes),
            st.lists(st.builds(DeviceAttributes, type=st.just(DeviceType.DEVICE))),
        )
    ),
    id_token=...,
    access_token=...,
)
async def test_get_gateways(
    gateways: list[tuple[GatewayAttributes, list[DeviceAttributes]]],
    id_token: str,
    access_token: str,
):
    with pytest.MonkeyPatch().context() as monkeypatch:
        aws = _mock_aws(monkeypatch)
        service_api = _mock_service_api(monkeypatch)

        aws.authenticate.return_value = (id_token, access_token)

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
                            "email": attributes.occupant.email,
                            "first_name": attributes.occupant.first_name,
                            "last_name": attributes.occupant.last_name,
                            "identity_id": attributes.occupant.identity_id,
                        }
                    },
                },
            }
            for (attributes, _) in gateways
        ]

        service_api.get_slider_list.return_value = {"data": slider_list_data}

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

        service_api.get_slider_details.side_effect = get_slider_details_impl

        async with create_client("user", "password") as client:
            for (
                expected_attributes,
                expected_children_attributes,
            ), actual_gateway in zip(gateways, client.get_gateways()):
                assert actual_gateway.get_attributes() == expected_attributes
                assert [
                    device.get_attributes() for device in actual_gateway.get_children()
                ] == expected_children_attributes

        aws.authenticate.assert_awaited()
        service_api.get_slider_list.assert_awaited_with(
            id_token, access_token, unittest.mock.ANY
        )
