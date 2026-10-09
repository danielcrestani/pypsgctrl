# API reference: pypsgctrl 0.1.3

[Русская версия](api_reference_ru.md)

PSG9080 driver for Python >= 3.10. Protocol source: `PSG Communication Protocol.pdf` (manufacturer document, not distributed here).
Public imports live in `pypsgctrl/__init__.py`; implementation is split into
`device.py`, `channel.py`, `registers.py`, `enums.py`, `errors.py`, and `transport.py`.
Serial dependency: `pyserial>=3.5`. Source documentation uses Doxygen comments
`## @brief`, `@param`, `@return`, and `@exception`.

## Quick start

From the repository root, install the package and run the tests:

```sh
python -m pip install .
python -m unittest discover -s tests -v
```

```python
from pypsgctrl import PSG9080, Waveform

with PSG9080.connect('/dev/cu.usbserial-2120', timeout=1.0) as psg:
    print(psg.ch1.frequency)           # Decimal, Hz
    print(psg.ch1.amplitude)           # Decimal, Vpp
    psg.ch1.waveform = Waveform.SINE
    psg.ch1.frequency = 3000
    psg.ch1.amplitude = '5.000'
    psg.set_outputs(True, False)
```

Writes change the device immediately. Opening a port does not enable outputs.
When synchronization is active, CH1 changes may affect CH2 according to the device settings.

## Types, units, and precision

Numeric inputs accept int, float, Decimal, IntEnum, and numeric strings.
Strings and Decimal represent exact fractions. NaN/Infinity are rejected;
values between register steps are rejected without rounding.
Physical values and numeric selectors are returned as Decimal; compound registers
return tuple[Decimal, ...]. Exceptions: enabled returns bool, interface returns
tuple[int, ...], and read_raw() returns tuple[str, ...]. Reads validate syntax
and field count but do not enforce the write range on device responses.

Frequencies are in Hz, durations in seconds, amplitudes in Vpp, offsets in V,
angles in degrees, and duty/AM depth in percent. Undocumented hardware limits,
such as MAXF and maximum amplitude, must be respected by the caller.

## PSG9080 connection

| API | Purpose |
| --- | --- |
| `PSG9080.connect(port, *, timeout=1.0)` | Opens a path/URL using pyserial at 115200, 8-N-1, without flow control. Returns a PSG9080 owning the port. A positive finite timeout applies to reads, writes, and responses. |
| `PSG9080(transport, *, owns_transport=False, response_timeout=1.0)` | Injects a transport; borrowed by default. |
| `close()` | Closes the driver and its owned transport; repeated calls are allowed. |
| `with PSG9080.connect(...) as psg` | Closes the connection even when an exception occurs. |
| `ch1`, `ch2`, `channel(number)` | Return Channel; number must be 1 or 2, not bool. |
| `get(name)` | Reads a general register from the catalog below. |
| `set(name, *values)` | Validates range/resolution and writes all fields. Returns None. |
| `set_outputs(ch1, ch2)` | Sets both outputs; True/1 enables and False/0 disables. |
| `set_sync(*, waveform=False, frequency=False, amplitude=False, offset=False, duty=False, external=False)` | Writes six synchronization flags; CH1 is the leader. |
| `load(slot)` / `save(slot)` / `clear(slot)` | Command 26, operations 111/222/333. slot is a nonnegative integer; the upper limit is undocumented. |
| `clear_all()` | Clears all memory slots using command 26/444. |

Read memory with get(); use the memory methods for writes. Saving, loading,
and clearing immediately affect memory or settings.

## Channel

Obtain Channel through the connection. The public constructor
`Channel(device, number)` does not validate the number; `PSG9080.channel()` does.
`ch.get(name)` and `ch.set(name, value)` use CHANNEL_REGISTERS.
frequency/enabled are separate properties, not names in that catalog.
All properties below support reading and writing.

| Property | Codes CH1 / CH2 | Unit | Step | Write range |
| --- | --- | --- | --- | --- |
| `waveform` | 11 / 12 | code | 1 | 0..21 or 101..199 |
| `amplitude` | 15 / 16 | Vpp | 0.001 | 0..device limit |
| `offset` | 17 / 18 | V | 0.01 | -10..10 |
| `duty` | 19 / 20 | % | 0.01 | 0..100 |
| `phase` | 21 / 22 | ° | 0.01 | 0..359.99 |
| `modulation_frequency` | 43 / 44 | Hz | 0.001 | 0..1000000 |
| `am_depth` | 45 / 46 | % | 0.1 | 0..200 |
| `fm_deviation` | 47 / 48 | Hz | 0.1 | 0..device limit |
| `fsk_frequency` | 49 / 50 | Hz | 0.1 | 0..device limit |
| `pm_deviation` | 51 / 52 | ° | 0.1 | 0..359.9 |
| `pulse_width` | 53 / 54 | s | 1E-9 | 0..0.4 |
| `pulse_period` | 55 / 56 | s | 1E-8 | 0..4 |
| `frequency` | 13 / 14 | Hz | Usually 0.001 | >= 0, MAXF depends on the device |
| `enabled` | 10 (pair) | bool | — | False/True |

Assigning enabled reads both output states and preserves the other channel.
The read/modify/write sequence uses the instance lock. waveform returns a
Decimal code; use `Waveform(int(ch.waveform))` for known built-in waveforms.
Arbitrary waveform codes cannot be converted to Waveform.

| Method | Purpose |
| --- | --- |
| `set_arbitrary_waveform(slot)` | Converts slot 1..99 to waveform code 101..199. |
| `set_frequency(hz, *, display_unit=FrequencyUnit.HZ)` | Always accepts Hz; selects display units separately. |

Assigning ch.frequency selects HZ. Protocol examples use the same 0.001 Hz ticks
for HZ/KHZ/MHZ. MILLIHZ/UHZ are interpreted as 0.000001/0.000000001 Hz steps;
these display modes have not been verified on hardware.

## General registers

Pass compound values as separate arguments: `psg.set('outputs', True, False)`,
rather than a single tuple. R means read-only; RW means read/write.
A step of one also applies to selectors and counters.

| Name | Code | Fields | Access | Scale: ticks/unit | Write range per field |
| --- | --- | --- | --- | --- | --- |
| `outputs` | 10 | 2 | RW | 1 | 0..1 |
| `interface` | 24 | 4 | RW | 1 | 0..255 (hex selectors) |
| `sync` | 25 | 6 | RW | 1 | 0..1 |
| `memory` | 26 | 1 | R | 1 | 0..unspecified |
| `sound` | 27 | 1 | RW | 1 | 0..1 |
| `brightness` | 28 | 1 | RW | 1 | 0..100 |
| `language` | 29 | 1 | RW | 1 | 0..1 |
| `preset_wave_count` | 30 | 1 | RW | 1 | 0..39 |
| `arbitrary_wave_count` | 31 | 1 | RW | 1 | 0..99 |
| `wave_loading` | 32 | 1 | RW | 1 | 0..1 |
| `frequency_trim` | 33 | 1 | RW | 1 | unspecified..unspecified |
| `modulation` | 40 | 2 | RW | 1 | 0..7 |
| `modulation_waveform` | 41 | 2 | RW | 1 | 0..9 |
| `modulation_source` | 42 | 2 | RW | 1 | 0..1 |
| `pulse_inversion` | 57 | 2 | RW | 1 | 0..1 |
| `burst_idle` | 58 | 2 | RW | 1 | 0..2 |
| `polarity` | 59 | 2 | RW | 1 | 0..1 |
| `trigger_source` | 60 | 2 | RW | 1 | 0..3 |
| `burst_count` | 61 | 2 | RW | 1 | 0..1000000000 |
| `measurement_mode` | 63 | 1 | RW | 1 | 0..1 |
| `sweep_enabled` | 65 | 2 | RW | 1 | 0..1 |
| `sweep_start_frequency` | 66 | 1 | RW | 10 | 0..unspecified |
| `sweep_end_frequency` | 67 | 1 | RW | 10 | 0..unspecified |
| `sweep_start_amplitude` | 68 | 1 | RW | 1000 | 0..unspecified |
| `sweep_end_amplitude` | 69 | 1 | RW | 1000 | 0..unspecified |
| `sweep_start_duty` | 70 | 1 | RW | 100 | 0..100 |
| `sweep_end_duty` | 71 | 1 | RW | 100 | 0..100 |
| `voltage_calibration_min` | 72 | 1 | RW | 1 | 0..unspecified |
| `voltage_calibration_max` | 73 | 1 | RW | 1 | 0..unspecified |
| `trigger` | 74 | 2 | RW | 1 | 0..1 |
| `counter` | 80 | 1 | R | 1 | 0..unspecified |
| `measured_high_frequency` | 81 | 1 | R | 1 | 0..unspecified |
| `measured_low_frequency` | 82 | 1 | R | 1000 | 0..unspecified |
| `measured_positive_width` | 83 | 1 | R | 1000000000 | 0..unspecified |
| `measured_negative_width` | 84 | 1 | R | 1000000000 | 0..unspecified |
| `measured_period` | 85 | 1 | R | 100000000 | 0..unspecified |
| `measured_duty` | 86 | 1 | R | 100 | 0..100 |

Compound field order and meanings:

| Name | Fields / values |
| --- | --- |
| outputs | CH1, CH2; 0 off, 1 on |
| interface | Four hexadecimal UI selectors matching device menus |
| sync | waveform, frequency, amplitude, offset, duty, external; 0/1 |
| modulation | CH1, CH2; Modulation enum |
| modulation_waveform | CH1, CH2; 0 sine, 1 square, 2 triangle, 3 rising sawtooth, 4 falling sawtooth, 5..9 arbitrary 101..105 |
| modulation_source | CH1, CH2; 0 internal, 1 external |
| pulse_inversion | CH1, CH2; 0 normal, 1 inverted |
| burst_idle | CH1, CH2; 0 zero, 1 positive maximum, 2 negative maximum |
| polarity | CH1, CH2; 0 positive, 1 negative |
| trigger_source | CH1, CH2; TriggerSource enum |
| burst_count | Pulse counts for CH1, CH2 |
| sweep_enabled | Sweep, voltage control; 0/1 |
| trigger | CH1, CH2; 0/1 |

Other selectors: sound 0/1; brightness in percent; language 0 English/1 Chinese;
wave_loading 0 automatic/1 fast; measurement_mode 0 counter/1 measurement.
The frequency_trim range and physical unit are undocumented; the API passes
an integer without scaling. voltage_calibration_min/max are raw integers.
measured_high_frequency uses a 1 Hz step; measured_low_frequency 0.001 Hz;
measured_positive_width/negative_width 1 ns; measured_period 10 ns;
measured_duty 0.01%. sweep_start/end_frequency use 0.1 Hz,
sweep_start/end_amplitude 0.001 Vpp, and sweep_start/end_duty 0.01%.

## Measurement and sweep

`configure_measurement(*, dc=False, gate_seconds='0.02', low_frequency=False)`
writes command 62: AC/DC coupling, gate time 0.001..10 s with a 0.001 s step,
and high/low frequency mode. Configuration does not start measurement.

`configure_sweep(*, channel=1, seconds=10, direction=0, logarithmic=False)`
writes command 64: channel 1/2, time 0.01..640 s with a 0.01 s step,
direction 0 increasing/1 decreasing/2 back and forth, linear or logarithmic mode.
Enable sweep separately. Read commands 62/64 using read_raw(), without unit conversion.

```python
from pypsgctrl import PSG9080

with PSG9080.connect('/dev/cu.usbserial-2120') as psg:
    psg.configure_measurement(dc=False, gate_seconds='0.1', low_frequency=True)
    psg.set('measurement_mode', 1)
    print(psg.get('measured_low_frequency'))  # Hz
    print(psg.get('measured_duty'))           # %

    psg.set('sweep_start_frequency', 100)
    psg.set('sweep_end_frequency', 10000)
    psg.configure_sweep(channel=1, seconds=10, direction=2, logarithmic=True)
    psg.set('sweep_enabled', 1, 0)
    # Disable sweep when finished:
    psg.set('sweep_enabled', 0, 0)
```

## Enumerations

### Waveform

| Name | Code |
| --- | --- |
| `SINE` | 0 |
| `SQUARE` | 1 |
| `PULSE` | 2 |
| `TRIANGLE` | 3 |
| `SLOPE` | 4 |
| `CMOS` | 5 |
| `DC` | 6 |
| `PARTIAL_SINE` | 7 |
| `HALF_WAVE` | 8 |
| `FULL_WAVE` | 9 |
| `POSITIVE_LADDER` | 10 |
| `NEGATIVE_LADDER` | 11 |
| `POSITIVE_TRAPEZOID` | 12 |
| `NEGATIVE_TRAPEZOID` | 13 |
| `NOISE` | 14 |
| `EXPONENTIAL_RISE` | 15 |
| `EXPONENTIAL_FALL` | 16 |
| `LOGARITHMIC_RISE` | 17 |
| `LOGARITHMIC_FALL` | 18 |
| `SINKER_PULSE` | 19 |
| `MULTI_AUDIO` | 20 |
| `LORENZ` | 21 |

### FrequencyUnit

| Name | Code |
| --- | --- |
| `HZ` | 0 |
| `KHZ` | 1 |
| `MHZ` | 2 |
| `MILLIHZ` | 3 |
| `MHZ_SMALL` | 3 |
| `UHZ` | 4 |

### Modulation

| Name | Code |
| --- | --- |
| `AM` | 0 |
| `FM` | 1 |
| `PM` | 2 |
| `ASK` | 3 |
| `FSK` | 4 |
| `PSK` | 5 |
| `PULSE` | 6 |
| `BURST` | 7 |

### TriggerSource

| Name | Code |
| --- | --- |
| `KEY` | 0 |
| `INTERNAL` | 1 |
| `EXTERNAL_AC` | 2 |
| `EXTERNAL_DC` | 3 |


MHZ_SMALL is a compatibility alias for MILLIHZ (millihertz), not megahertz.

## Modulation, memory, and arbitrary waveform examples

```python
from pypsgctrl import PSG9080, Modulation, TriggerSource

with PSG9080.connect('/dev/cu.usbserial-2120') as psg:
    psg.set('modulation', Modulation.AM, Modulation.BURST)
    psg.set('modulation_source', 0, 0)
    psg.ch1.am_depth = 80
    psg.ch1.modulation_frequency = 500
    psg.set('trigger_source', TriggerSource.KEY, TriggerSource.EXTERNAL_DC)
    psg.set('burst_count', 10, 20)
    psg.ch2.set_arbitrary_waveform(1)   # Select existing arbitrary waveform 01
    # Uploading samples is undocumented by this protocol and is not implemented.
    psg.save(52)
    psg.load(52)
```

## Raw API and transport

`read_raw(code)` sends `:rCODE=0.\r\n` and returns a tuple of strings.
`write_raw(code, *fields)` sends `:wCODE=FIELDS.\r\n` and returns None.
The code must be int in 0..99. Fields are checked against the ASCII alphabet;
raw-command semantics, field counts, and ranges are not validated.
Pass integer wire values without a trailing period or CRLF. Physical fractions
must be scaled beforehand. The read-response code must match the request.
Write acknowledgments are OK, OK., or the hardware-observed :ok, followed by CRLF.

```python
from pypsgctrl import PSG9080

with PSG9080.connect('/dev/cu.usbserial-2120') as psg:
    print(psg.read_raw(13))              # Example: ('000003000000', '0')
    psg.write_raw(24, '0', '1', '0', 'a')
    # Equivalent general API call:
    psg.set('interface', 0, 1, 0, 10)
```

Transport is a typing.Protocol with `write(data: bytes) -> int`,
`read(size: int = 1) -> bytes`, and `close() -> None`.
read() must have a finite timeout; the driver cannot interrupt a blocking call.
response_timeout is checked between read() calls, so a slow transport may exceed
it by the duration of one read. Partial writes are errors; responses are limited
to 65536 bytes.

```python
import serial
from pypsgctrl import PSG9080

transport = serial.Serial('/dev/cu.usbserial-2120', 115200,
                          timeout=1, write_timeout=1)
try:
    with PSG9080(transport, owns_transport=False, response_timeout=1) as psg:
        print(psg.ch1.frequency)
    # A borrowed transport remains open.
finally:
    transport.close()
```

## Register and catalogs

`Register(code, scale=Decimal(1), offset=Decimal(0), minimum=Decimal(0),
maximum=None, count=1, writable=True)` is a frozen dataclass.
Encoding uses `raw = physical * scale + offset`; decoding performs the inverse.
minimum/maximum apply to physical values; None means no bound.
Channel offset has scale=100 and offset=1000: 0 V maps to raw 1000.
REGISTERS and CHANNEL_REGISTERS are accessible descriptor dictionaries.
The CH2 code equals the CH1 code + 1. interface, sync, and frequency have special formats.

## Errors and concurrency

| Exception | Cause |
| --- | --- |
| PSGError | Base exception; also access to a closed driver |
| ProtocolError(PSGError) | Partial write, invalid ASCII/framing/code/field count, or rejected write |
| PSGTimeoutError(PSGError, TimeoutError) | Incomplete response or expired response deadline |
| ValueError | Invalid value, resolution, code, channel, field count, or write to a read-only register |
| KeyError | Unknown get/set name |
| pyserial exceptions | Port opening or transport errors; propagated without wrapping |

After a timeout, close and reopen the connection: the protocol has no transaction
IDs, so a late response could be mistaken for the next one. Writes are never
retried automatically. Multiple parameter writes are not an atomic transaction.
RLock protects exchanges between threads of one instance. A port should belong
to only one instance/process.

## Protocol ambiguities and hardware verification

* Frequency units 3/4 verified on hardware (PSG9080, 2026-10-09).
* Width/period wire maxima conflict with the document's physical maxima.
  Conservative limits of 0.4/4 s and steps of 1/10 ns are used.
* Command 63 is described with two fields in the text but one mode in the table.
  The API uses one mode; use write_raw() for an alternative format.
* r25 accepts six compact bits or CSV. The repeated n3 in w64 is interpreted as n4.
* Maximum frequency/amplitude/positive offset/memory slot and the frequency_trim
  range are not fully specified by the document.
* Initial brightness readback was 101, but writing 101 was clamped to 100 by the
  device. The API write range remains 0..100; readback can exceed it.

On 2026-10-07, 13 library tests passed on Python 3.10.6 before publication preparation.
Hardware checks on `/dev/cu.usbserial-2120`, 115200, 8-N-1 covered reads, brightness
20/100, CH2 phase, and CH1 waveform/frequency/amplitude: sine 1 kHz/2 Vpp,
square 2 kHz/4 Vpp, triangle 500 Hz/1 Vpp. The user confirmed visible changes.
Sine 3 kHz/5 Vpp and brightness 100 were restored. The analog signal was not
verified using measurement equipment.
