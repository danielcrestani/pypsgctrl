#!/usr/bin/env python3
"""Teste de hardware do pypsgctrl com o PSG9080.

Seguro para a bancada: desliga as saídas durante o teste, salva os valores
originais do CH1 e os restaura no final. Nada é aplicado às saídas BNC.

Uso:  python hw_check.py [/dev/ttyUSB0]
"""
import sys
import time
from decimal import Decimal

from pypsgctrl import PSG9080, Waveform, FrequencyUnit, PSGError

PORT = sys.argv[1] if len(sys.argv) > 1 else '/dev/ttyUSB0'
results = []


def check(name, fn):
    try:
        value = fn()
        results.append((name, 'OK', value))
        print(f'[ OK ] {name}: {value!r}')
        return value
    except Exception as exc:  # report and keep going
        results.append((name, 'FALHA', f'{type(exc).__name__}: {exc}'))
        print(f'[FAIL] {name}: {type(exc).__name__}: {exc}')
        return None


with PSG9080.connect(PORT, timeout=1.0) as g:
    ch = g.ch1

    # 1) Leitura bruta: mostra o formato real das respostas do aparelho.
    print('\n== Respostas brutas ==')
    for code in (10, 11, 13, 15, 17, 19, 21, 25, 28):
        check(f'read_raw({code})', lambda c=code: g.read_raw(c))

    # 2) Estado original (para restaurar depois).
    print('\n== Estado original ==')
    outputs = check('outputs', lambda: g.get('outputs'))
    orig = {n: check(f'ch1.{n}', lambda n=n: getattr(ch, n))
            for n in ('waveform', 'frequency', 'amplitude', 'offset', 'duty', 'phase')}
    orig_unit = None
    raw_f = check('unidade de frequência (raw 13)', lambda: g.read_raw(13))
    if raw_f and len(raw_f) == 2:
        orig_unit = int(raw_f[1])

    try:
        # 3) Desliga as saídas antes de mexer em qualquer coisa.
        print('\n== Escritas (saídas desligadas) ==')
        check('set_outputs(False, False)', lambda: g.set_outputs(False, False))

        def write_read(name, value, expect=None):
            def run():
                setattr(ch, name, value)
                got = getattr(ch, name)
                want = Decimal(str(int(value) if isinstance(value, Waveform) else value)) \
                    if expect is None else expect
                if got != want:
                    raise AssertionError(f'escrito {want}, lido {got}')
                return got
            check(f'ch1.{name} = {value}', run)

        write_read('waveform', Waveform.SINE)
        write_read('frequency', '1234.567')
        write_read('amplitude', '1.234')
        write_read('offset', '-1.5')
        write_read('offset', '1.5')
        write_read('duty', '33.33')
        write_read('phase', '90')

        # 4) Unidades de frequência (mHz/uHz não verificadas pelo autor).
        print('\n== Unidades de frequência ==')
        for unit, hz in [(FrequencyUnit.HZ, '25.786'), (FrequencyUnit.KHZ, '25786'),
                         (FrequencyUnit.MHZ, '2578600'), (FrequencyUnit.MILLIHZ, '0.025786'),
                         (FrequencyUnit.UHZ, '0.000025786')]:
            def run(unit=unit, hz=hz):
                ch.set_frequency(hz, display_unit=unit)
                raw = g.read_raw(13)
                got = ch.frequency
                if got != Decimal(hz):
                    raise AssertionError(f'escrito {hz} Hz, lido {got} Hz (raw {raw})')
                return f'{got} Hz (raw {raw}) - confira o display'
            check(f'frequência {hz} Hz em {unit.name}', run)
            time.sleep(0.5)

        # 5) Limite de offset positivo (correção nova): não deve chegar ao aparelho.
        print('\n== Validação local ==')
        def offset_limit():
            try:
                ch.offset = '10.01'
            except ValueError as exc:
                return f'rejeitado antes de enviar: {exc}'
            raise AssertionError('offset 10.01 V foi aceito')
        check('offset > +10 V', offset_limit)

        # 6) Robustez: lixo no buffer não pode quebrar o próximo comando.
        print('\n== Buffer residual ==')
        def stale():
            g.transport.write(b':r15=0.\r\n')  # comando sem ler a resposta
            time.sleep(0.2)                     # resposta fica parada no buffer
            return ch.amplitude                 # deve funcionar mesmo assim
        check('resposta atrasada descartada', stale)

        # 7) Velocidade: 50 leituras seguidas.
        def speed():
            t0 = time.monotonic()
            for _ in range(50):
                ch.amplitude
            return f'{(time.monotonic() - t0) / 50 * 1000:.1f} ms por comando'
        check('tempo por transação', speed)

    finally:
        print('\n== Restaurando estado original ==')
        for name in ('waveform', 'amplitude', 'offset', 'duty', 'phase'):
            if orig.get(name) is not None:
                check(f'restaura {name}', lambda n=name: setattr(ch, n, orig[n]))
        if orig.get('frequency') is not None:
            unit = orig_unit if orig_unit is not None else 0
            check('restaura frequency',
                  lambda: ch.set_frequency(orig['frequency'], display_unit=unit))
        if outputs is not None:
            check('restaura outputs', lambda: g.set_outputs(*(bool(v) for v in outputs)))

fails = [r for r in results if r[1] != 'OK']
print(f'\nResumo: {len(results) - len(fails)} OK, {len(fails)} falhas')
for name, _, detail in fails:
    print(f'  - {name}: {detail}')
sys.exit(1 if fails else 0)
