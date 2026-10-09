import unittest
from decimal import Decimal
from unittest.mock import patch
from pypsgctrl import PSG9080, Waveform, ProtocolError, PSGTimeoutError, PSGError, REGISTERS, CHANNEL_REGISTERS


class Fake:
    """Minimal byte-stream transport for deterministic protocol tests."""
    def __init__(self, *replies):
        self.data = bytearray(''.join(replies).encode('ascii'))
        self.commands = []
        self.closed = False
    def write(self, data):
        self.commands.append(data)
        return len(data)
    def read(self, size=1):
        part = bytes(self.data[:size])
        del self.data[:size]
        return part
    def close(self):
        self.closed = True


class DriverTests(unittest.TestCase):
    """Verify wire compatibility and validation without attached hardware."""
    def test_channel_values(self):
        # Check documented encodings and inverse conversions for both channels.
        examples = [('waveform', Waveform.SQUARE, '1'), ('amplitude', '5', '5000'),
                    ('offset', '-9.99', '1'), ('duty', 50, '5000'),
                    ('phase', '359.99', '35999'), ('modulation_frequency',500,'500000'),
                    ('am_depth',80,'800'), ('fm_deviation',2000,'20000'),
                    ('fsk_frequency',100,'1000'), ('pm_deviation',180,'1800'),
                    ('pulse_width','0.00002','20000'), ('pulse_period','0.0002','20000')]
        for name, value, raw in examples:
            for channel in (1,2):
                code = CHANNEL_REGISTERS[name].code + channel - 1
                with self.subTest(name=name, channel=channel):
                    fake = Fake('OK\r\n', f':r{code}={raw}.\r\n')
                    ch = PSG9080(fake).channel(channel)
                    setattr(ch,name,value)
                    self.assertEqual(getattr(ch,name), Decimal(int(value)) if isinstance(value, Waveform) else Decimal(str(value)))
                    self.assertEqual(fake.commands,[f':w{code}={raw}.\r\n'.encode(),f':r{code}=0.\r\n'.encode()])

    def test_frequency_units(self):
        # Ensure display units retain the intended frequency in physical Hz.
        for unit, raw in [(0,'25786'),(1,'25786'),(2,'25786'),(3,'25786000'),(4,'25786000000')]:
            fake = Fake('OK\r\n',f':r13={raw},{unit}.\r\n')
            ch = PSG9080(fake).ch1
            ch.set_frequency('25.786',display_unit=unit)
            self.assertEqual(ch.frequency,Decimal('25.786'))
            self.assertEqual(fake.commands[0],f':w13={raw},{unit}.\r\n'.encode())

    def test_sync_compact_and_csv(self):
        # Accept both documented synchronization response formats.
        for response in ('110000','1,1,0,0,0,0'):
            self.assertEqual(PSG9080(Fake(f':r25={response}.\r\n')).get('sync'),(1,1,0,0,0,0))

    def test_outputs_preserve_other_channel(self):
        # Changing one output must preserve the other channel state.
        fake = Fake(':r10=0,1.\r\n','OK\r\n')
        PSG9080(fake).ch1.enabled = True
        self.assertEqual(fake.commands[-1],b':w10=1,1.\r\n')

    def test_validation_before_io(self):
        # Invalid requests must fail before any bytes are written.
        fake=Fake()
        d=PSG9080(fake)
        for name, value in [('waveform',22),('amplitude',-1),('amplitude','0.0001'),
                            ('offset',-11),('duty',101),('phase',360),('pulse_width',1),
                            ('pulse_period',5),('am_depth',201),('amplitude','NaN')]:
            with self.subTest(name=name,value=value), self.assertRaises(ValueError):
                d.ch1.set(name,value)
        for action in [lambda:d.channel(True),lambda:d.channel(3),lambda:d.set('outputs',1),
                       lambda:d.set('counter',1),lambda:d.write_raw(100,0),
                       lambda:d.write_raw(10,'1.\r\n:w10=0')]:
            with self.assertRaises(ValueError): action()
        self.assertEqual(fake.commands,[])

    def test_malformed_replies(self):
        # Reject wrong codes, malformed payloads, and incomplete responses.
        for response in [':r16=05000.\r\n',':r15=abc.\r\n',':r15=1,2.\r\n','ERR\r\n',':r15=1\r\n']:
            with self.subTest(response=response),self.assertRaises(ProtocolError):
                _=PSG9080(Fake(response)).ch1.amplitude
        with self.assertRaises(ProtocolError): PSG9080(Fake('ERROR\r\n')).set_outputs(1,1)
        with self.assertRaises(PSGTimeoutError): PSG9080(Fake(':r10=1')).get('outputs')

    def test_partial_write(self):
        # A short transport write must not be treated as a successful command.
        fake=Fake()
        fake.write=lambda data:len(data)-1
        with self.assertRaises(ProtocolError): PSG9080(fake).get('outputs')

    def test_lifecycle(self):
        # Close owned transports only and reject use after driver closure.
        for owned in (False,True):
            fake=Fake()
            with PSG9080(fake,owns_transport=owned): pass
            self.assertEqual(fake.closed,owned)
        d=PSG9080(Fake())
        d.close()
        with self.assertRaises(PSGError): d.read_raw(10)

    def test_memory_and_configuration(self):
        # Match memory, measurement, and sweep commands to protocol examples.
        fake=Fake(*(['OK\r\n']*6))
        d=PSG9080(fake)
        d.load(52); d.save(52); d.clear(57); d.clear_all()
        d.configure_measurement()
        d.configure_sweep(channel=2)
        self.assertEqual(fake.commands,[b':w26=52,111.\r\n',b':w26=52,222.\r\n',
            b':w26=57,333.\r\n',b':w26=0,444.\r\n',b':w62=0,20,0.\r\n',b':w64=1,1000,0,0.\r\n'])

    def test_all_global_registers(self):
        # Exercise read/write scaling across the general register catalog.
        for name,reg in REGISTERS.items():
            if name=='interface': continue  # hexadecimal selectors use raw access
            fields=','.join(['0']*reg.count)
            fake=Fake(f':r{reg.code}={fields}.\r\n','OK\r\n')
            d=PSG9080(fake)
            value=d.get(name)
            if reg.writable and name!='memory':
                d.set(name,*(value if isinstance(value,tuple) else (value,)))
                self.assertEqual(fake.commands[-1],f':w{reg.code}={fields}.\r\n'.encode())

    def test_hardware_ack(self):
        # Accept the lowercase acknowledgment observed on the real PSG9080.
        fake = Fake(':ok\r\n')
        PSG9080(fake).set('brightness', 99)
        self.assertEqual(fake.commands, [b':w28=99.\r\n'])

    def test_hex_interface(self):
        # UI selectors use hexadecimal fields rather than decimal strings.
        fake = Fake(':r24=00,01,00,0c.\r\n', 'OK\r\n')
        d = PSG9080(fake)
        self.assertEqual(d.get('interface'), (0, 1, 0, 12))
        d.set('interface', 0, 1, 0, 10)
        self.assertEqual(fake.commands[-1], b':w24=0,1,0,a.\r\n')

    def test_stale_input_is_discarded(self):
        # A late reply left over from a timed-out command must not poison the next one.
        class Flushable(Fake):
            def __init__(self, stale, *replies):
                super().__init__(stale)
                self.replies = list(replies)
            def reset_input_buffer(self):
                self.data = bytearray(self.replies.pop(0).encode('ascii'))
        fake = Flushable(':r10=1,1.\r\n', ':r15=5000.\r\n')
        self.assertEqual(PSG9080(fake).ch1.amplitude, Decimal(5))

    def test_offset_upper_limit(self):
        # Positive offset is bounded like the negative side (raw 2000 = +10 V).
        fake = Fake()
        with self.assertRaises(ValueError): PSG9080(fake).ch1.offset = '10.01'
        self.assertEqual(fake.commands, [])

    def test_timeout_validation(self):
        # Non-numeric or boolean timeouts raise ValueError, not TypeError.
        for bad in ('abc', True, 0, -1, float('inf'), float('nan')):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError): PSG9080.connect('loop://', timeout=bad)
                with self.assertRaises(ValueError): PSG9080(Fake(), response_timeout=bad)

    def test_serial_settings(self):
        # Assert 115200 baud, 8-N-1, timeouts, and owned-port lifecycle.
        with patch('serial.serial_for_url',return_value=Fake()) as factory:
            with PSG9080.connect('loop://',timeout=0.5): pass
            factory.assert_called_once_with('loop://',baudrate=115200,bytesize=8,parity='N',stopbits=1,timeout=0.5,write_timeout=0.5)


if __name__=='__main__': unittest.main()
