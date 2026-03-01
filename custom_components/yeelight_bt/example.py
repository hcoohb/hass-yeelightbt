from __future__ import annotations

import asyncio
import logging
import sys

from bleak import AdvertisementData, BleakScanner, BLEDevice
from bleak.exc import BleakError

from yeelightbt.yeelightbt import YeelightBT

ADDRESS = "F8:24:41:E6:3E:39"


_LOGGER = logging.getLogger(__name__)


async def main(address: str) -> None:
    """Associate with a lamp."""

    found_lamp_evt = asyncio.Event()
    lamp_device = None

    def callback(device: BLEDevice, advertising_data: AdvertisementData):
        nonlocal lamp_device
        if device.address == address:
            lamp_device = device
            _LOGGER.info(
                f"Found lamp: {device}, with advData: {advertising_data}"
            )
            found_lamp_evt.set()

    async with BleakScanner(detection_callback=callback):
        await found_lamp_evt.wait()

    if not lamp_device:
        raise BleakError(f"A device with address {address} could not be found.")

    lamp = YeelightBT(lamp_device)

    await lamp.get_state()
    # await lamp.turn_on()
    # await lamp.get_state()
    await asyncio.sleep(2)
    # await lamp.get_serial()
    # await lamp.factory_reset()
    
    # await lamp.associate()
    await lamp.set_brightness(36)
    # await asyncio.sleep(2)
    # await lamp.get_state()
    # await lamp.set_name("A new Super Name! thst is look")
    # await asyncio.sleep(10)
    # await lamp.set_color(10,50,250, 92)
    # await asyncio.sleep(2)
    # await lamp.get_state()
    # await lamp.get_name()
    # # await lamp.turn_off()
    # await asyncio.sleep(2)
    await lamp.get_name()
    # # # await lamp.set_temperature(6000, 92)
    # # # await lamp.set_brightness(5)
    # # # await lamp.associate()
    # await asyncio.sleep(2)
    # await lamp.set_temperature(6000, 0)

    # # # # await lamp.set_brightness(5)
    # # # # await lamp.associate()
    # # await asyncio.sleep(2)
    # # # await lamp.get_state()
    # # # await asyncio.sleep(2)
    # await lamp.set_brightness(100)
    # await asyncio.sleep(2)
    # await lamp.get_state()
    # await lamp.turn_on()
    # # await asyncio.sleep(10)
    # # await lamp.turn_off()
    # await asyncio.sleep(2)
    # await lamp.get_state()
    # await asyncio.sleep(2)
    # await lamp.set_color(100,50,50,0)
    # await asyncio.sleep(2)
    # await lamp.get_state()
    # await asyncio.sleep(2)
    # await lamp.get_versions()
    # await lamp.get_stats()
    await asyncio.sleep(2)
    # await lamp.turn_off()
    # await asyncio.sleep(10)
    await asyncio.sleep(30)
    # associationdata = await lamp.associate(activation_code)
    # _LOGGER.info(
    #     "Association data: %s",
    #     associationdata.to_json() if associationdata else "<None>",
    # )

if __name__ == "__main__":
    logging.basicConfig(format='%(asctime)s %(levelname)s:%(module)s:%(funcName)s: %(message)s', level=logging.DEBUG)
    logging.getLogger("bleak.backends.bluezdbus.manager").setLevel(logging.WARNING)
    asyncio.run(main(sys.argv[1] if len(sys.argv) == 2 else ADDRESS))