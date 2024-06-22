"""Test the JBD BMS implementation."""

import logging

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError
from bleak.uuids import normalize_uuid_str
from custom_components.bms_ble.plugins.jbd_bms import BMS
from typing_extensions import Buffer

from .bluetooth import generate_ble_device
from .conftest import MockBleakClient

LOGGER = logging.getLogger(__name__)
BT_FRAME_SIZE = 20


class MockJBDBleakClient(MockBleakClient):
    """Emulate a JBD BMS BleakClient."""

    HEAD_CMD = bytearray(b"\xDD")
    CMD_INFO = bytearray(b"\xa5\x03")

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str, data: Buffer
    ) -> bytearray:
        if (
            char_specifier == normalize_uuid_str("ff02")
            and bytearray(data)[0:3] == self.HEAD_CMD + self.CMD_INFO
        ):
            return bytearray(
                b"\xdd\x03\x00\x1D\x06\x18\xFE\xE1\x01\xF2\x01\xF4\x00\x2A\x2C\x7C\x00\x00\x00"
                b"\x00\x00\x00\x80\x64\x03\x04\x03\x0B\x8B\x0B\x8A\x0B\x84\xf8\x84\x77"
            )  # {'voltage': 15.6, 'current': -2.87, 'battery_level': 100, 'cycle_charge': 4.98, 'cycles': 42, 'temperature': 22.133333333333347}

        return bytearray()

    async def write_gatt_char(
        self,
        char_specifier: BleakGATTCharacteristic | int | str,
        data: Buffer,
        response: bool = None,  # type: ignore[implicit-optional] # same as upstream
    ) -> None:
        """Issue write command to GATT."""

        assert (
            self._notify_callback
        ), "write to characteristics but notification not enabled"

        resp = self._response(char_specifier, data)
        for notify_data in [
            resp[i : i + BT_FRAME_SIZE] for i in range(0, len(resp), BT_FRAME_SIZE)
        ]:
            self._notify_callback("MockJBDBleakClient", notify_data)


class MockInvalidBleakClient(MockJBDBleakClient):
    """Emulate a JBD BMS BleakClient returning wrong data."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str, data: Buffer
    ) -> bytearray:
        # LOGGER.debug(f"{char_specifier=}")
        # LOGGER.debug(f"{data=}")
        if char_specifier == normalize_uuid_str("ff02"):
            return bytearray(b"\xdd\x03\x00\x1d") + bytearray(31) + bytearray(b"\x77")

        return bytearray()

    async def disconnect(self) -> bool:
        """Mock disconnect to raise BleakError."""
        raise BleakError


class MockOversizedBleakClient(MockJBDBleakClient):
    """Emulate a JBD BMS BleakClient returning wrong data length."""

    def _response(
        self, char_specifier: BleakGATTCharacteristic | int | str, data: Buffer
    ) -> bytearray:
        if char_specifier == normalize_uuid_str("ff02"):
            return bytearray(
                b"\xdd\x03\x00\x1D\x06\x18\xFE\xE1\x01\xF2\x01\xF4\x00\x2A\x2C\x7C\x00\x00\x00"
                b"\x00\x00\x00\x80\x64\x03\x04\x03\x0B\x8B\x0B\x8A\x0B\x84\xf8\x84\x77"
                b"\00\00\00\00\00\00"  # oversized response
            )  # {'voltage': 15.6, 'current': -2.87, 'battery_level': 100, 'cycle_charge': 4.98, 'cycles': 42, 'temperature': 22.133333333333347}

        return bytearray()

    async def disconnect(self) -> bool:
        """Mock disconnect to raise BleakError."""
        raise BleakError

async def test_update(monkeypatch, reconnect_fixture) -> None:
    """Test JBD BMS data update."""

    monkeypatch.setattr(
        "custom_components.bms_ble.plugins.jbd_bms.BleakClient",
        MockJBDBleakClient,
    )

    bms = BMS(
        generate_ble_device("cc:cc:cc:cc:cc:cc", "MockBLEdevice", None, -73),
        reconnect_fixture,
    )

    result = await bms.async_update()

    assert result == {
        "numTemp": 3,
        "voltage": 15.6,
        "current": -2.87,
        "battery_level": 100,
        "cycle_charge": 4.98,
        "cycles": 42,
        "temperature": 22.133333333333347,
        "cycle_capacity": 77.688,
        "power": -44.772,
        "battery_charging": False,
        "runtime": 6246,
    }

    # query again to check already connected state
    result = await bms.async_update()
    assert bms._connected is not reconnect_fixture

    await bms.disconnect()


async def test_invalid_response(monkeypatch) -> None:
    """Test data update with BMS returning invalid data (wrong CRC)."""

    monkeypatch.setattr(
        "custom_components.bms_ble.plugins.jbd_bms.BleakClient",
        MockInvalidBleakClient,
    )

    bms = BMS(generate_ble_device("cc:cc:cc:cc:cc:cc", "MockBLEdevice", None, -73))

    result = await bms.async_update()

    assert result == {}

    await bms.disconnect()


async def test_oversized_response(monkeypatch) -> None:
    """Test data update with BMS returning oversized data, result shall still be ok."""

    monkeypatch.setattr(
        "custom_components.bms_ble.plugins.jbd_bms.BleakClient",
        MockOversizedBleakClient,
    )

    bms = BMS(generate_ble_device("cc:cc:cc:cc:cc:cc", "MockBLEdevice", None, -73))

    result = await bms.async_update()

    assert result == {
        "numTemp": 3,
        "voltage": 15.6,
        "current": -2.87,
        "battery_level": 100,
        "cycle_charge": 4.98,
        "cycles": 42,
        "temperature": 22.133333333333347,
        "cycle_capacity": 77.688,
        "power": -44.772,
        "battery_charging": False,
        "runtime": 6246,
    }

    await bms.disconnect()
