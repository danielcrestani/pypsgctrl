## @file
# @brief Serial connection and general device settings.
from __future__ import annotations

import re
import threading
import time

from .channel import Channel
from .errors import PSGError, PSGTimeoutError, ProtocolError
from .registers import REGISTERS, _reg, _decimal, _encode, _decode
from .transport import Transport

## @brief Synchronous PSG9080 connection; transactions are protected by RLock.
class PSG9080:
    """Synchronous, transaction-locked PSG9080 connection.

    Injected transports are borrowed unless owns_transport=True. Serial ports
    opened by connect() are owned. A timed-out connection should be reopened:
    the wire protocol has no transaction identifiers.
    """
    ## @brief Create a driver using an injected transport.
    # @param transport Transport object; read() must have a finite timeout.
    # @param owns_transport Close the transport on close(); defaults to False.
    # @param response_timeout Positive finite response deadline in seconds.
    def __init__(self, transport: Transport, *, owns_transport=False, response_timeout=1.0):
        if isinstance(response_timeout, bool) or _decimal(response_timeout) <= 0:
            raise ValueError("response_timeout must be positive")
        self.response_timeout = float(response_timeout)
        self.transport = transport
        self._owns_transport = owns_transport
        self._closed = False
        self._lock = threading.RLock()
        self.ch1 = Channel(self, 1)
        self.ch2 = Channel(self, 2)

    ## @brief Open a serial port at 115200 baud, 8-N-1, without flow control.
    # @param port Serial port path or pyserial URL.
    # @param timeout Positive finite read, write, and response timeout in seconds.
    # @return PSG9080 owning the opened transport.
    # @exception PSGTimeoutError Incomplete response or expired timeout.
    # @exception ProtocolError Unexpected device response.
    # @exception ValueError Invalid input value.
    @classmethod
    def connect(cls, port: str, *, timeout: float = 1.0):
        if isinstance(timeout, bool) or _decimal(timeout) <= 0:
            raise ValueError('timeout must be positive and finite')
        timeout = float(timeout)
        import serial
        return cls(serial.serial_for_url(port, baudrate=115200, bytesize=8,
                   parity='N', stopbits=1, timeout=timeout, write_timeout=timeout),
                   owns_transport=True, response_timeout=timeout)

    ## @brief Close the driver and its owned transport; repeated calls are allowed.
    def close(self):
        with self._lock:
            if not self._closed and self._owns_transport:
                self.transport.close()
            self._closed = True

    ## @brief Enter the connection context.
    # @return This PSG9080 instance.
    def __enter__(self):
        return self

    ## @brief Close the connection when leaving the context.
    # @param args Context manager exception information.
    def __exit__(self, *args):
        self.close()

    ## @brief Get a channel object.
    # @param number Channel number 1 or 2; bool is rejected.
    # @return Channel.
    def channel(self, number):
        if isinstance(number, bool) or number not in (1, 2):
            raise ValueError('Channel must be 1 or 2')
        return self.ch1 if number == 1 else self.ch2

    def _exchange(self, operator, code, payload):
        if type(code) is not int or not 0 <= code <= 99:
            raise ValueError('Function code must be an integer in [0, 99]')
        if not re.fullmatch(r'[0-9a-fA-F,+-]+', payload):
            raise ValueError('Invalid raw payload')
        command = f':{operator}{code}={payload}.\r\n'.encode('ascii')
        with self._lock:
            if self._closed:
                raise PSGError('Connection is closed')
            # Drop stale bytes (a late reply after a timeout, or power-up
            # noise) so they cannot be mistaken for this command's response.
            reset = getattr(self.transport, 'reset_input_buffer', None)
            if callable(reset):
                reset()
            if self.transport.write(command) != len(command):
                raise ProtocolError('Incomplete transport write')
            deadline = time.monotonic() + self.response_timeout
            response = bytearray()
            while not response.endswith(b'\r\n'):
                if time.monotonic() >= deadline:
                    raise PSGTimeoutError("Response deadline exceeded; reopen connection")
                part = self.transport.read(1)
                if not part:
                    raise PSGTimeoutError('Timed out waiting for CRLF response; reopen connection')
                response.extend(part)
                if len(response) > 65536:
                    raise ProtocolError('Response exceeds 65536 bytes')
            try:
                line = bytes(response[:-2]).decode('ascii')
            except UnicodeDecodeError as exc:
                raise ProtocolError('Response is not ASCII') from exc
            if operator == 'w':
                if line not in ('OK', 'OK.', ':ok'):
                    raise ProtocolError(f'Write rejected: {line!r}')
                return ()
            match = re.fullmatch(r':r(\d{1,2})=([^\r\n]+)\.', line)
            if not match or int(match[1]) != code:
                raise ProtocolError(f'Unexpected read response: {line!r}')
            return tuple(match[2].split(','))

    ## @brief Read raw fields using :rCODE=0. followed by CRLF.
    # @param code Integer function code in 0..99.
    # @return tuple[str, ...] without unit conversion.
    # @exception PSGTimeoutError Incomplete response or expired timeout.
    # @exception ProtocolError Unexpected device response.
    # @exception ValueError Invalid input value.
    def read_raw(self, code):
        """Return unscaled ASCII fields from :rCODE=0. command."""
        return self._exchange('r', code, '0')

    ## @brief Write raw ASCII fields and verify an OK, OK., or :ok acknowledgment.
    # @param code Integer function code in 0..99.
    # @param fields Fields without a terminator or CRLF; hexadecimal selectors are supported.
    # @exception PSGTimeoutError Incomplete response or expired timeout.
    # @exception ProtocolError Unexpected device response.
    # @exception ValueError Invalid input value.
    def write_raw(self, code, *fields):
        """Write literal fields, including hexadecimal interface selectors."""
        self._exchange('w', code, ','.join(str(f) for f in fields))

    ## @brief Read a general parameter from REGISTERS.
    # @param name General register name.
    # @return Decimal or tuple[Decimal, ...]; interface returns tuple[int, ...].
    # @exception PSGTimeoutError Incomplete response or expired timeout.
    # @exception ProtocolError Unexpected device response.
    # @exception ValueError Invalid input value.
    # @exception KeyError Unknown parameter name.
    def get(self, name):
        reg = REGISTERS[name]
        fields = self.read_raw(reg.code)
        if name == 'interface':
            if len(fields) != 4 or any(not re.fullmatch('[0-9a-fA-F]{1,2}', f) for f in fields):
                raise ProtocolError('Invalid interface selector')
            return tuple(int(f, 16) for f in fields)
        if name == 'sync' and len(fields) == 1 and re.fullmatch('[01]{6}', fields[0]):
            fields = tuple(fields[0])
        return _decode(reg, fields)

    ## @brief Write a general parameter after validating its range and resolution.
    # @param name Writable general register name.
    # @param values Physical values in register field order.
    # @exception PSGTimeoutError Incomplete response or expired timeout.
    # @exception ProtocolError Unexpected device response.
    # @exception ValueError Invalid input value.
    # @exception KeyError Unknown parameter name.
    def set(self, name, *values):
        reg = REGISTERS[name]
        if not reg.writable or name == 'memory':
            raise ValueError('Use memory methods, or register is read-only')
        if len(values) != reg.count:
            raise ValueError(f'{name} requires {reg.count} values')
        if name == 'interface':
            encoded = [_encode(_reg(24, maximum=255), v) for v in values]
            self.write_raw(reg.code, *(format(int(v), 'x') for v in encoded))
        else:
            self.write_raw(reg.code, *(_encode(reg, v) for v in values))

    ## @brief Set both output states.
    # @param ch1 True/1 enables CH1; False/0 disables it.
    # @param ch2 True/1 enables CH2; False/0 disables it.
    # @exception PSGTimeoutError Incomplete response or expired timeout.
    # @exception ProtocolError Unexpected device response.
    # @exception ValueError Invalid input value.
    def set_outputs(self, ch1: bool, ch2: bool):
        self.set('outputs', ch1, ch2)

    ## @brief Configure synchronization with CH1 as the leader.
    # @param waveform Synchronization flag for waveform.
    # @param frequency Synchronization flag for frequency.
    # @param amplitude Synchronization flag for amplitude.
    # @param offset Synchronization flag for offset.
    # @param duty Synchronization flag for duty.
    # @param external Synchronization flag for external.
    # @exception PSGTimeoutError Incomplete response or expired timeout.
    # @exception ProtocolError Unexpected device response.
    # @exception ValueError Invalid input value.
    def set_sync(self, *, waveform=False, frequency=False, amplitude=False,
                 offset=False, duty=False, external=False):
        self.set('sync', waveform, frequency, amplitude, offset, duty, external)

    def _memory(self, slot, operation):
        self.write_raw(26, _encode(_reg(26), slot), operation)

    ## @brief Load parameters from memory using command 26/111.
    # @param slot Nonnegative integer memory slot; the upper limit is undocumented.
    # @exception PSGTimeoutError Incomplete response or expired timeout.
    # @exception ProtocolError Unexpected device response.
    # @exception ValueError Invalid input value.
    def load(self, slot):
        self._memory(slot, 111)

    ## @brief Save parameters to memory using command 26/222.
    # @param slot Nonnegative integer memory slot.
    # @exception PSGTimeoutError Incomplete response or expired timeout.
    # @exception ProtocolError Unexpected device response.
    # @exception ValueError Invalid input value.
    def save(self, slot):
        self._memory(slot, 222)

    ## @brief Clear one memory slot using command 26/333.
    # @param slot Nonnegative integer memory slot.
    # @exception PSGTimeoutError Incomplete response or expired timeout.
    # @exception ProtocolError Unexpected device response.
    # @exception ValueError Invalid input value.
    def clear(self, slot):
        self._memory(slot, 333)

    ## @brief Clear all memory slots using command 26/444.
    # @exception PSGTimeoutError Incomplete response or expired timeout.
    # @exception ProtocolError Unexpected device response.
    # @exception ValueError Invalid input value.
    def clear_all(self):
        self._memory(0, 444)

    ## @brief Configure measurement using command 62; does not start measurement.
    # @param dc False: AC; True: DC coupling at Ext.IN.
    # @param gate_seconds Gate time in 0.001..10 seconds, with a 0.001 s step.
    # @param low_frequency False: high-frequency mode; True: low-frequency mode.
    # @exception PSGTimeoutError Incomplete response or expired timeout.
    # @exception ProtocolError Unexpected device response.
    # @exception ValueError Invalid input value.
    def configure_measurement(self, *, dc=False, gate_seconds='0.02', low_frequency=False):
        self.write_raw(62, _encode(_reg(62, maximum=1), dc),
                       _encode(_reg(62, scale=1000, minimum='0.001', maximum=10), gate_seconds),
                       _encode(_reg(62, maximum=1), low_frequency))

    ## @brief Configure sweep using command 64; does not enable sweep.
    # @param channel Channel 1 or 2.
    # @param seconds Time in 0.01..640 seconds, with a 0.01 s step.
    # @param direction 0: increasing; 1: decreasing; 2: back and forth.
    # @param logarithmic False: linear sweep; True: logarithmic sweep.
    # @exception PSGTimeoutError Incomplete response or expired timeout.
    # @exception ProtocolError Unexpected device response.
    # @exception ValueError Invalid input value.
    def configure_sweep(self, *, channel=1, seconds=10, direction=0, logarithmic=False):
        self.channel(channel)
        self.write_raw(64, channel - 1,
                       _encode(_reg(64, scale=100, minimum='0.01', maximum=640), seconds),
                       _encode(_reg(64, maximum=2), direction),
                       _encode(_reg(64, maximum=1), logarithmic))
