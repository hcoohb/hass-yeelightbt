"""Data models for the YeelightBt component."""

from dataclasses import dataclass

from bleak.backends.device import BLEDevice
from .yeelightbt.yeelightbt import YeelightBT


@dataclass
class YeelightBtConfigurationData:
    """Configuration data for YeelightBt."""

    ble_device: BLEDevice
    device: YeelightBT
    title: str