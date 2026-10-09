## @file
# @brief Injected transport interface.
from __future__ import annotations

from typing import Protocol

## @brief Transport contract requiring a finite read timeout.
class Transport(Protocol):
    ## @brief Write command bytes.
    # @param data ASCII command terminated with CRLF.
    # @return Number of bytes actually written.
    def write(self, data: bytes) -> int: ...
    ## @brief Read up to size bytes with a finite timeout.
    # @param size Requested byte count.
    # @return bytes; empty bytes indicate a timeout.
    def read(self, size: int = 1) -> bytes: ...
    ## @brief Close transport resources.
    def close(self) -> None: ...
    # Optional: reset_input_buffer() -> None. When present (pyserial has it),
    # it is called before every command to discard stale input.
