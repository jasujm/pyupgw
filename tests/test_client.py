"""Tests for the UPGW client"""

import unittest.mock

from attrs import define, field
from hypothesis import given
import pytest

from pyupgw import create_client, Device
import pyupgw.client


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
@given(...)
async def test_get_devices(devices: list[Device], id_token: str, access_token: str):
    with pytest.MonkeyPatch().context() as monkeypatch:
        aws = _mock_aws(monkeypatch)
        service_api = _mock_service_api(monkeypatch)

        aws.authenticate.return_value = (id_token, access_token)

        service_api.get_slider_list.return_value = {
            "data": [
                {
                    "id": str(device.id),
                    "type": device.type.value,
                    "gateway": {
                        "id": str(device.id),
                        "device_code": device.device_code,
                        "model": device.model,
                        "name": device.name,
                    },
                }
                for device in devices
            ]
        }

        async with create_client("user", "password") as client:
            assert client.get_devices() == devices

        aws.authenticate.assert_awaited()
        service_api.get_slider_list.assert_awaited_with(
            id_token, access_token, unittest.mock.ANY
        )
