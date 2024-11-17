"""Exceptions."""

from bleak.exc import BleakError
from bleak_retry_connector import BLEAK_RETRY_EXCEPTIONS as BLEAK_EXCEPTIONS

from .models import DisconnectReason

class YBTError(Exception):
    """Base class for exceptions."""


class Disconnected(YBTError):
    """Raised when the connection is lost."""

    def __init__(self, reason: DisconnectReason):
        self.reason = reason
        super().__init__(reason.name)

class InvalidCommand(YBTError):
    """Raised when a received command can't be parsed."""


class Timeout(BleakError, YBTError):
    """Raised when trying to associate with wrong activation code."""

class NotConnected(YBTError):
    """Raised when connection is lost while sending a command."""
