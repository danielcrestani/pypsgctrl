"""Toolkit-independent logic for the PSG9080 GUI.

Everything here talks to a pypsgctrl.PSG9080 object and plain data, so it can
be tested with a fake transport and reused by the Bode analyzer later.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path

from pypsgctrl import FrequencyUnit

# Built-in waveform codes 0..21 (enum pypsgctrl.Waveform), Portuguese labels.
WAVEFORM_LABELS = [
    'Senoidal', 'Quadrada', 'Pulso', 'Triangular', 'Rampa', 'CMOS', 'DC',
    'Senoide parcial', 'Meia onda', 'Onda completa', 'Escada positiva',
    'Escada negativa', 'Trapézio positivo', 'Trapézio negativo', 'Ruído',
    'Exponencial subida', 'Exponencial descida', 'Logarítmica subida',
    'Logarítmica descida', 'Pulso sinc', 'Multi-áudio', 'Lorenz',
]
ARB_SLOTS = range(1, 100)  # codes 101..199


def waveform_choices():
    """List of (label, device code) for the waveform selector."""
    items = [(label, code) for code, label in enumerate(WAVEFORM_LABELS)]
    items += [(f'Arbitrária {slot:02d}', 100 + slot) for slot in ARB_SLOTS]
    return items


# Display units: (label, FrequencyUnit, Hz per displayed unit)
FREQ_UNITS = [
    ('Hz', FrequencyUnit.HZ, Decimal(1)),
    ('kHz', FrequencyUnit.KHZ, Decimal(1000)),
    ('MHz', FrequencyUnit.MHZ, Decimal(1000000)),
    ('mHz', FrequencyUnit.MILLIHZ, Decimal('0.001')),
    ('µHz', FrequencyUnit.UHZ, Decimal('0.000001')),
]
_UNIT_FACTOR = {int(u): f for _, u, f in FREQ_UNITS}


def parse_decimal(text):
    """Parse user text, accepting a decimal comma ("1,5") as well as a point."""
    text = str(text).strip().replace(' ', '').replace(',', '.')
    try:
        value = Decimal(text)
    except Exception as exc:
        raise ValueError(f'Número inválido: {text!r}') from exc
    if not value.is_finite():
        raise ValueError(f'Número inválido: {text!r}')
    return value


def to_hz(value, unit):
    """Convert a value typed in display unit `unit` to Hz."""
    return parse_decimal(value) * _UNIT_FACTOR[int(unit)]


def from_hz(hz, unit):
    """Convert Hz to the display unit, without trailing zeros."""
    value = Decimal(hz) / _UNIT_FACTOR[int(unit)]
    text = format(value.normalize(), 'f')
    return text if text != '-0' else '0'


@dataclass
class ChannelState:
    waveform: int = 0
    frequency_hz: Decimal = Decimal(1000)
    freq_unit: int = int(FrequencyUnit.HZ)
    amplitude: Decimal = Decimal(1)
    offset: Decimal = Decimal(0)
    duty: Decimal = Decimal(50)
    phase: Decimal = Decimal(0)
    enabled: bool = False

    def to_json(self):
        data = asdict(self)
        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in data.items()}

    @classmethod
    def from_json(cls, data):
        s = cls()
        s.waveform = int(data.get('waveform', s.waveform))
        s.freq_unit = int(data.get('freq_unit', s.freq_unit))
        s.enabled = bool(data.get('enabled', s.enabled))
        for name in ('frequency_hz', 'amplitude', 'offset', 'duty', 'phase'):
            if name in data:
                setattr(s, name, Decimal(str(data[name])))
        return s


def read_frequency(device, number):
    """Return (Hz, display unit code) for a channel."""
    channel = device.channel(number)
    fields = device.read_raw(12 + number)
    unit = int(fields[1]) if len(fields) == 2 else int(FrequencyUnit.HZ)
    return channel.frequency, unit


def read_channel(device, number, outputs=None):
    """Read a full ChannelState from the device."""
    ch = device.channel(number)
    if outputs is None:
        outputs = device.get('outputs')
    hz, unit = read_frequency(device, number)
    return ChannelState(
        waveform=int(ch.waveform), frequency_hz=hz, freq_unit=unit,
        amplitude=ch.amplitude, offset=ch.offset, duty=ch.duty, phase=ch.phase,
        enabled=bool(outputs[number - 1]),
    )


def read_all(device):
    """Read both channels with a single outputs query."""
    outputs = device.get('outputs')
    return read_channel(device, 1, outputs), read_channel(device, 2, outputs)


# Fields the UI edits individually. Each writer returns the value read back.
def write_field(device, number, name, value):
    """Write one channel field and return the device's read-back value.

    name: 'waveform' (int code), 'frequency' ((hz, unit)), or one of
    'amplitude', 'offset', 'duty', 'phase' (Decimal/str).
    """
    ch = device.channel(number)
    if name == 'waveform':
        ch.set('waveform', int(value))
        return int(ch.waveform)
    if name == 'frequency':
        hz, unit = value
        ch.set_frequency(hz, display_unit=int(unit))
        return read_frequency(device, number)
    if name in ('amplitude', 'offset', 'duty', 'phase'):
        ch.set(name, value)
        return ch.get(name)
    raise KeyError(name)


def set_output(device, number, enabled):
    """Switch one output, preserving the other; return both states."""
    device.channel(number).enabled = bool(enabled)
    return tuple(bool(v) for v in device.get('outputs'))


def _write_state(device, number, state):
    write_field(device, number, 'waveform', state.waveform)
    write_field(device, number, 'frequency', (state.frequency_hz, state.freq_unit))
    for name in ('amplitude', 'offset', 'duty', 'phase'):
        write_field(device, number, name, getattr(state, name))


def apply_state(device, ch1, ch2):
    """Write full states for both channels (used when loading a preset).

    Outputs are switched off first and set last, so the circuit under test
    never sees a half-configured signal.
    """
    device.set_outputs(False, False)
    _write_state(device, 1, ch1)
    _write_state(device, 2, ch2)
    device.set_outputs(ch1.enabled, ch2.enabled)


def apply_channel_state(device, number, state):
    """Write one channel's full state; the other channel is not touched.

    Only this channel's output is switched off during the update.
    """
    device.channel(number).enabled = False
    _write_state(device, number, state)
    device.channel(number).enabled = state.enabled


# ---- presets -------------------------------------------------------------

def default_preset_path():
    base = os.environ.get('XDG_CONFIG_HOME') or os.path.join(Path.home(), '.config')
    return Path(base) / 'psg9080-gui' / 'presets.json'


@dataclass
class Preset:
    """A saved configuration: one channel (applied to CH1 or CH2) or both.

    For a single-channel preset, `source` is the channel it was saved from
    and is only the default target when applying.
    """
    states: tuple  # (ChannelState,) or (ch1, ch2)
    source: int | None = None

    @classmethod
    def both(cls, ch1, ch2):
        return cls((ch1, ch2))

    @classmethod
    def channel(cls, state, source):
        return cls((state,), int(source))

    @property
    def is_single(self):
        return len(self.states) == 1

    def label(self):
        return f'CH{self.source}' if self.is_single else 'CH1 + CH2'

    def apply(self, device, target=None):
        """Write to the device. target picks the channel for single presets."""
        if self.is_single:
            apply_channel_state(device, int(target or self.source), self.states[0])
        else:
            apply_state(device, *self.states)

    def to_json(self):
        if self.is_single:
            return {'kind': 'channel', 'source': self.source,
                    'channel': self.states[0].to_json()}
        return {'kind': 'both', 'ch1': self.states[0].to_json(),
                'ch2': self.states[1].to_json()}

    @classmethod
    def from_json(cls, data):
        if data.get('kind') == 'channel':
            return cls.channel(ChannelState.from_json(data['channel']),
                               data.get('source', 1))
        # 'both', or the first format (no 'kind'), which only had both channels
        return cls.both(ChannelState.from_json(data['ch1']),
                        ChannelState.from_json(data['ch2']))


@dataclass
class PresetStore:
    path: Path = field(default_factory=default_preset_path)

    def load(self):
        try:
            data = json.loads(Path(self.path).read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {}
        return {name: Preset.from_json(p) for name, p in data.items()}

    def save_all(self, presets):
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {name: preset.to_json() for name, preset in sorted(presets.items())}
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        tmp.replace(path)  # atomic: a crash never leaves a half-written file

    def put(self, name, preset):
        presets = self.load()
        presets[name] = preset
        self.save_all(presets)

    def delete(self, name):
        presets = self.load()
        presets.pop(name, None)
        self.save_all(presets)
