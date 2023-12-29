"""Tests for data models"""

import unittest.mock

import pytest
from attrs import asdict
from hypothesis import given
from hypothesis import strategies as st

from pyupgw import (
    Gateway,
    GatewayAttributes,
    SystemMode,
    ThermostatAttributes,
    ThermostatDevice,
)


@given(
    st.builds(
        ThermostatAttributes,
        temperature=st.floats(allow_nan=False),
        current_temperature=st.floats(allow_nan=False),
        min_temp=st.floats(allow_nan=False),
        max_temp=st.floats(allow_nan=False),
    )
)
def test_device(attributes: ThermostatAttributes):
    device = ThermostatDevice(
        attributes, unittest.mock.AsyncMock(), unittest.mock.AsyncMock()
    )
    assert device.get_attributes() == attributes
    assert device.get_id() == attributes.id
    assert device.get_type() == attributes.type
    assert device.get_device_code() == attributes.device_code
    assert device.get_model() == attributes.model
    assert device.get_name() == attributes.name
    assert device.get_system_mode() == attributes.system_mode
    assert device.get_temperature() == attributes.temperature
    assert device.get_current_temperature() == attributes.current_temperature
    assert device.get_min_temp() == attributes.min_temp
    assert device.get_max_temp() == attributes.max_temp


@given(...)
def test_device_set_attributes(
    attributes: ThermostatAttributes, new_attributes: ThermostatAttributes
):
    subscriber = unittest.mock.Mock()
    device = ThermostatDevice(
        attributes, unittest.mock.AsyncMock(), unittest.mock.AsyncMock()
    )
    device.subscribe(subscriber)
    device.set_attributes(asdict(new_attributes))
    assert device.get_attributes() == new_attributes
    subscriber.assert_called_with(device, asdict(new_attributes))


@given(...)
def test_device_set_attributes_empty_change(attributes: ThermostatAttributes):
    subscriber = unittest.mock.Mock()
    device = ThermostatDevice(
        attributes, unittest.mock.AsyncMock(), unittest.mock.AsyncMock()
    )
    device.subscribe(subscriber)
    device.set_attributes({})
    assert device.get_attributes() == attributes
    subscriber.assert_not_called()


@pytest.mark.asyncio
@given(...)
async def test_device_refresh(attributes: ThermostatAttributes):
    dispatch_refresh = unittest.mock.AsyncMock()
    device = ThermostatDevice(attributes, dispatch_refresh, unittest.mock.AsyncMock())
    await device.refresh()
    dispatch_refresh.assert_awaited_with(device)


@pytest.mark.asyncio
@given(...)
async def test_device_update(
    attributes: ThermostatAttributes, new_attributes: ThermostatAttributes
):
    dispatch_update = unittest.mock.AsyncMock()
    device = ThermostatDevice(attributes, unittest.mock.AsyncMock(), dispatch_update)
    await device.update(asdict(new_attributes))
    dispatch_update.assert_awaited_with(device, asdict(new_attributes))


@pytest.mark.asyncio
@given(...)
async def test_device_update_system_mode(
    attributes: ThermostatAttributes, system_mode: SystemMode
):
    dispatch_update = unittest.mock.AsyncMock()
    device = ThermostatDevice(attributes, unittest.mock.AsyncMock(), dispatch_update)
    await device.update_system_mode(system_mode)
    dispatch_update.assert_awaited_with(device, {"system_mode": system_mode})


@pytest.mark.asyncio
@given(attributes=..., temperature=st.floats(allow_nan=False))
async def test_device_update_temperature(
    attributes: ThermostatAttributes, temperature: float
):
    dispatch_update = unittest.mock.AsyncMock()
    device = ThermostatDevice(attributes, unittest.mock.AsyncMock(), dispatch_update)
    await device.update_temperature(temperature)
    dispatch_update.assert_awaited_with(device, {"temperature": temperature})


@given(...)
def test_gateway(attributes: GatewayAttributes, children: list[ThermostatAttributes]):
    gateway = Gateway(
        attributes, children, unittest.mock.AsyncMock(), unittest.mock.AsyncMock()
    )
    assert gateway.get_attributes() == attributes
    assert gateway.get_occupant() == attributes.occupant
    assert [child.get_attributes() for child in gateway.get_children()] == children


@pytest.mark.asyncio
@given(...)
async def test_gateway_refresh_child(
    attributes: GatewayAttributes, child_attributes: ThermostatAttributes
):
    dispatch_refresh = unittest.mock.AsyncMock()
    gateway = Gateway(
        attributes, [child_attributes], dispatch_refresh, unittest.mock.AsyncMock()
    )
    (child,) = gateway.get_children()
    await child.refresh()
    dispatch_refresh.assert_awaited_with(gateway, child)


@pytest.mark.asyncio
@given(...)
async def test_gateway_update_child(
    attributes: GatewayAttributes,
    child_attributes: ThermostatAttributes,
    new_child_attributes: ThermostatAttributes,
):
    dispatch_update = unittest.mock.AsyncMock()
    gateway = Gateway(
        attributes, [child_attributes], unittest.mock.AsyncMock(), dispatch_update
    )
    (child,) = gateway.get_children()
    await child.update(asdict(new_child_attributes))
    dispatch_update.assert_awaited_with(gateway, child, asdict(new_child_attributes))
