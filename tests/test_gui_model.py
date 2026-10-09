import json
import re
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from pypsgctrl import PSG9080, FrequencyUnit
from psg_gui import model


class SimulatedPSG:
    """Register-level PSG9080 simulator speaking the real wire protocol.

    Initial values copy the read_raw() output captured from real hardware.
    """
    def __init__(self):
        self.regs = {10: '1,1', 11: '000', 12: '000', 13: '000010000000,0',
                     14: '000010000000,0', 15: '05000', 16: '05000', 17: '1000',
                     18: '1000', 19: '5000', 20: '5000', 21: '00000', 22: '00000'}
        self.out = bytearray()
        self.writes = []

    def write(self, data):
        m = re.fullmatch(rb':([rw])(\d+)=(.*)\.\r\n', data)
        op, code, payload = m[1].decode(), int(m[2]), m[3].decode()
        if op == 'w':
            self.writes.append((code, payload))
            self.regs[code] = payload
            self.out += b':ok\r\n'
        else:
            self.out += f':r{code}={self.regs[code]}.\r\n'.encode()
        return len(data)

    def read(self, size=1):
        part = bytes(self.out[:size])
        del self.out[:size]
        return part

    def reset_input_buffer(self):
        self.out.clear()

    def close(self):
        pass


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.sim = SimulatedPSG()
        self.dev = PSG9080(self.sim)

    def test_read_all_matches_hardware_capture(self):
        ch1, ch2 = model.read_all(self.dev)
        for ch in (ch1, ch2):
            self.assertEqual(ch.waveform, 0)
            self.assertEqual(ch.frequency_hz, Decimal(10000))
            self.assertEqual(ch.freq_unit, 0)
            self.assertEqual(ch.amplitude, Decimal(5))
            self.assertEqual(ch.offset, Decimal(0))
            self.assertEqual(ch.duty, Decimal(50))
            self.assertTrue(ch.enabled)

    def test_unit_conversion(self):
        cases = [('1,5', FrequencyUnit.KHZ, Decimal(1500)),
                 ('2.5786', FrequencyUnit.MHZ, Decimal(2578600)),
                 ('25.786', FrequencyUnit.MILLIHZ, Decimal('0.025786')),
                 ('25.786', FrequencyUnit.UHZ, Decimal('0.000025786'))]
        for text, unit, hz in cases:
            with self.subTest(text=text, unit=unit):
                self.assertEqual(model.to_hz(text, unit), hz)
                self.assertEqual(model.parse_decimal(model.from_hz(hz, unit)),
                                 model.parse_decimal(text))
        self.assertEqual(model.from_hz(Decimal('1000.000'), FrequencyUnit.HZ), '1000')
        self.assertEqual(model.from_hz(Decimal('0'), FrequencyUnit.KHZ), '0')
        with self.assertRaises(ValueError):
            model.parse_decimal('abc')

    def test_write_field_returns_readback(self):
        self.assertEqual(model.write_field(self.dev, 2, 'amplitude', '1.234'), Decimal('1.234'))
        self.assertEqual(self.sim.writes[-1], (16, '1234'))
        hz, unit = model.write_field(self.dev, 1, 'frequency', (Decimal(1500), FrequencyUnit.KHZ))
        self.assertEqual((hz, unit), (Decimal(1500), 1))
        self.assertEqual(model.write_field(self.dev, 1, 'waveform', 105), 105)

    def test_invalid_value_sends_nothing(self):
        with self.assertRaises(ValueError):
            model.write_field(self.dev, 1, 'offset', '12')
        self.assertEqual(self.sim.writes, [])

    def test_set_output_preserves_other(self):
        self.assertEqual(model.set_output(self.dev, 1, False), (False, True))
        self.assertEqual(self.sim.writes[-1], (10, '0,1'))

    def test_apply_state_outputs_off_first_and_last(self):
        ch1 = model.ChannelState(waveform=1, frequency_hz=Decimal(2000), freq_unit=1,
                                 amplitude=Decimal(2), offset=Decimal('-0.5'),
                                 duty=Decimal(25), phase=Decimal(0), enabled=True)
        ch2 = model.ChannelState(enabled=False)
        model.apply_state(self.dev, ch1, ch2)
        self.assertEqual(self.sim.writes[0], (10, '0,0'))
        self.assertEqual(self.sim.writes[-1], (10, '1,0'))
        got1, got2 = model.read_all(self.dev)
        self.assertEqual(got1, ch1)
        self.assertEqual(got2, ch2)

    def test_presets_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = model.PresetStore(Path(tmp) / 'sub' / 'presets.json')
            self.assertEqual(store.load(), {})
            a = model.ChannelState(amplitude=Decimal('3.3'), enabled=True)
            b = model.ChannelState(freq_unit=2, frequency_hz=Decimal(1000000))
            store.put('Ambos', model.Preset.both(a, b))
            store.put('Só CH2', model.Preset.channel(b, 2))
            loaded = store.load()
            self.assertEqual(loaded['Ambos'], model.Preset.both(a, b))
            self.assertEqual(loaded['Só CH2'], model.Preset.channel(b, 2))
            self.assertEqual(loaded['Ambos'].label(), 'CH1 + CH2')
            self.assertEqual(loaded['Só CH2'].label(), 'CH2')
            store.delete('Ambos')
            self.assertEqual(list(store.load()), ['Só CH2'])

    def test_presets_first_format_still_loads(self):
        # Presets saved by the first GUI version had only ch1/ch2 keys.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'presets.json'
            a = model.ChannelState(waveform=1).to_json()
            path.write_text(json.dumps({'testequadrada': {'ch1': a, 'ch2': a}}))
            preset = model.PresetStore(path).load()['testequadrada']
            self.assertFalse(preset.is_single)
            self.assertEqual(preset.states[0].waveform, 1)

    def test_single_channel_preset_leaves_other_channel_alone(self):
        state = model.ChannelState(waveform=3, frequency_hz=Decimal(500), amplitude=Decimal(2),
                                   enabled=True)
        before_ch1 = model.read_channel(self.dev, 1)
        model.Preset.channel(state, 1).apply(self.dev, target=2)  # saved from CH1, applied to CH2
        got1, got2 = model.read_all(self.dev)
        self.assertEqual(got1, before_ch1)
        self.assertEqual(got2, state)
        touched = {code for code, _ in self.sim.writes}
        self.assertFalse(touched & {11, 13, 15, 17, 19, 21})  # no CH1 registers written
        self.assertEqual(self.sim.writes[0], (10, '1,0'))   # only CH2 output switched off
        self.assertEqual(self.sim.writes[-1], (10, '1,1'))

    def test_waveform_choices(self):
        choices = model.waveform_choices()
        self.assertEqual(len(choices), 22 + 99)
        self.assertEqual(choices[0], ('Senoidal', 0))
        self.assertEqual(choices[-1], ('Arbitrária 99', 199))


if __name__ == '__main__':
    unittest.main()
