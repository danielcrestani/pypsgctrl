## @file
# @brief Register metadata and physical-value conversion.
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import IntEnum
import re

from .errors import ProtocolError

## @brief Immutable register descriptor: raw = value * scale + offset.
@dataclass(frozen=True)
class Register:
    ## @brief Protocol function code.
    code: int
    ## @brief Wire ticks per physical unit.
    scale: Decimal = Decimal(1)
    ## @brief Additive wire-value offset.
    offset: Decimal = Decimal(0)
    ## @brief Minimum physical value, or None for no lower bound.
    minimum: Decimal | None = Decimal(0)
    ## @brief Maximum physical value, or None for no upper bound.
    maximum: Decimal | None = None
    ## @brief Number of fields in a response or command.
    count: int = 1
    ## @brief Whether the general API permits writing this register.
    writable: bool = True


def _reg(code, scale=1, offset=0, minimum=0, maximum=None, count=1, writable=True):
    return Register(code, Decimal(str(scale)), Decimal(str(offset)),
                    None if minimum is None else Decimal(str(minimum)),
                    None if maximum is None else Decimal(str(maximum)), count, writable)


# scale is wire ticks per physical unit. Times are seconds, voltages Vpp/V,
# angles degrees, duty/depth percent, and frequencies Hz.
## @brief General register catalog; field order is documented in api_reference_en.md.
REGISTERS = {
    'outputs': _reg(10, maximum=1, count=2),
    'interface': _reg(24, count=4),
    'sync': _reg(25, maximum=1, count=6),
    'memory': _reg(26),
    'sound': _reg(27, maximum=1),
    'brightness': _reg(28, maximum=100),
    'language': _reg(29, maximum=1),
    'preset_wave_count': _reg(30, maximum=39),
    'arbitrary_wave_count': _reg(31, maximum=99),
    'wave_loading': _reg(32, maximum=1),
    'frequency_trim': _reg(33, minimum=None),
    'modulation': _reg(40, maximum=7, count=2),
    'modulation_waveform': _reg(41, maximum=9, count=2),
    'modulation_source': _reg(42, maximum=1, count=2),
    'pulse_inversion': _reg(57, maximum=1, count=2),
    'burst_idle': _reg(58, maximum=2, count=2),
    'polarity': _reg(59, maximum=1, count=2),
    'trigger_source': _reg(60, maximum=3, count=2),
    'burst_count': _reg(61, maximum=1000000000, count=2),
    'measurement_mode': _reg(63, maximum=1),
    'sweep_enabled': _reg(65, maximum=1, count=2),
    'sweep_start_frequency': _reg(66, scale=10),
    'sweep_end_frequency': _reg(67, scale=10),
    'sweep_start_amplitude': _reg(68, scale=1000),
    'sweep_end_amplitude': _reg(69, scale=1000),
    'sweep_start_duty': _reg(70, scale=100, maximum=100),
    'sweep_end_duty': _reg(71, scale=100, maximum=100),
    'voltage_calibration_min': _reg(72),
    'voltage_calibration_max': _reg(73),
    'trigger': _reg(74, maximum=1, count=2),
    'counter': _reg(80, writable=False),
    'measured_high_frequency': _reg(81, writable=False),
    'measured_low_frequency': _reg(82, scale=1000, writable=False),
    'measured_positive_width': _reg(83, scale=1000000000, writable=False),
    'measured_negative_width': _reg(84, scale=1000000000, writable=False),
    'measured_period': _reg(85, scale=100000000, writable=False),
    'measured_duty': _reg(86, scale=100, maximum=100, writable=False),
}
## @brief Channel register catalog: CH2 code equals CH1 code + 1.
CHANNEL_REGISTERS = {
    'waveform': _reg(11, maximum=199),
    'amplitude': _reg(15, scale=1000),
    'offset': _reg(17, scale=100, offset=1000, minimum=-10, maximum=10),
    'duty': _reg(19, scale=100, maximum=100),
    'phase': _reg(21, scale=100, maximum='359.99'),
    'modulation_frequency': _reg(43, scale=1000, maximum=1000000),
    'am_depth': _reg(45, scale=10, maximum=200),
    'fm_deviation': _reg(47, scale=10),
    'fsk_frequency': _reg(49, scale=10),
    'pm_deviation': _reg(51, scale=10, maximum='359.9'),
    'pulse_width': _reg(53, scale=1000000000, maximum='0.4'),
    'pulse_period': _reg(55, scale=100000000, maximum=4),
}


def _decimal(value):
    try:
        d = Decimal(int(value)) if isinstance(value, (bool, IntEnum)) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError('Expected a finite numeric value') from exc
    if not d.is_finite():
        raise ValueError('Expected a finite numeric value')
    return d


def _encode(reg, value):
    d = _decimal(value)
    if ((reg.minimum is not None and d < reg.minimum) or
            (reg.maximum is not None and d > reg.maximum)):
        raise ValueError(f'Value outside range [{reg.minimum}, {reg.maximum}]')
    raw = d * reg.scale + reg.offset
    if raw != raw.to_integral_value():
        raise ValueError(f'Value must be a multiple of {1 / reg.scale}')
    return str(int(raw))


def _decode(reg, fields):
    if len(fields) != reg.count or any(not re.fullmatch(r'-?\d+', f) for f in fields):
        raise ProtocolError(f'Invalid payload for register {reg.code}: {fields!r}')
    values = tuple((Decimal(f) - reg.offset) / reg.scale for f in fields)
    return values[0] if reg.count == 1 else values
