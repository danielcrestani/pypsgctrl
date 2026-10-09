[English version](api_reference_en.md)

# API reference: pypsgctrl 0.1.3

Драйвер PSG9080 для Python >= 3.10. Источник протокола — `PSG Communication Protocol.pdf` (документ производителя, в репозиторий не включён).
Публичные импорты: `pypsgctrl/__init__.py`; реализация: `device.py`, `channel.py`,
`registers.py`, `enums.py`, `errors.py`, `transport.py`; serial-зависимость: `pyserial>=3.5`.
Документация в коде оформлена Doxygen-комментариями `## @brief`, `@param`, `@return`, `@exception`.

## Быстрый старт

Из корня репозитория установите пакет и запустите тесты:

```sh
python -m pip install .
python -m unittest discover -s tests -v
```

```python
from pypsgctrl import PSG9080, Waveform

with PSG9080.connect('/dev/cu.usbserial-2120', timeout=1.0) as psg:
    print(psg.ch1.frequency)           # Decimal, Гц
    print(psg.ch1.amplitude)           # Decimal, Вpp
    psg.ch1.waveform = Waveform.SINE
    psg.ch1.frequency = 3000
    psg.ch1.amplitude = '5.000'
    psg.set_outputs(True, False)
```

Записи немедленно изменяют параметры прибора. Открытие порта не включает выходы.
При активной синхронизации изменение CH1 может затрагивать CH2 согласно настройкам прибора.

## Типы, единицы и точность

Числовые входы принимают int, float, Decimal, IntEnum и числовые строки.
Строки и Decimal позволяют задать точные дроби. NaN/Infinity запрещены;
значения между шагами регистра отвергаются без округления.
Чтение физических величин и числовых селекторов возвращает `Decimal`;
составные регистры — `tuple[Decimal, ...]`. Исключения: `enabled` возвращает bool,
`interface` — `tuple[int, ...]`, `read_raw()` — `tuple[str, ...]`.
Чтение проверяет синтаксис и число полей, но не ограничивает ответ диапазоном записи.

Частоты выражены в Гц, длительности в секундах, амплитуды в Вpp,
смещения в В, углы в градусах, duty и глубина AM в процентах.
Неизвестные аппаратные пределы (MAXF, максимальная амплитуда и т. п.)
не заменены предположениями: их соблюдает вызывающий код.

## Соединение PSG9080

| API | Назначение |
| --- | --- |
| `PSG9080.connect(port, *, timeout=1.0)` | Открывает путь/URL через pyserial; 115200, 8-N-1, без flow control. Возвращает PSG9080, владеющий портом. Положительный конечный timeout применяется к чтению, записи и ответу. |
| `PSG9080(transport, *, owns_transport=False, response_timeout=1.0)` | Внедрение транспорта. По умолчанию транспорт заимствован. |
| `close()` | Закрывает драйвер и принадлежащий ему транспорт; повторный вызов допустим. |
| `with PSG9080.connect(...) as psg` | Закрывает соединение также при исключении. |
| `ch1`, `ch2`, `channel(number)` | Возвращают Channel; number — 1 или 2, bool запрещён. |
| `get(name)` | Читает общий регистр из каталога ниже. |
| `set(name, *values)` | Проверяет диапазон/шаг и записывает все поля общего регистра. Возвращает None. |
| `set_outputs(ch1, ch2)` | Устанавливает оба выхода; True/1 включает, False/0 выключает. |
| `set_sync(*, waveform=False, frequency=False, amplitude=False, offset=False, duty=False, external=False)` | Пишет шесть флагов синхронизации; ведущий канал CH1. |
| `load(slot)` / `save(slot)` / `clear(slot)` | Команда 26 с операциями 111/222/333. slot — неотрицательное целое число; верхний предел не определён протоколом. |
| `clear_all()` | Очищает все ячейки памяти командой 26/444. |

`memory` читается через get(); для записи используются методы памяти.
Сохранение, загрузка и очистка изменяют память/настройки немедленно.

## Канал Channel

Получайте Channel через соединение. Публичный конструктор `Channel(device, number)`
сам не проверяет номер; `PSG9080.channel()` выполняет эту проверку.
`ch.get(name)` / `ch.set(name, value)` работают с каталогом CHANNEL_REGISTERS.
Свойства frequency/enabled обслуживаются отдельно и не являются именами этого каталога.
Все свойства в таблице поддерживают чтение и запись.

| Свойство | Коды CH1 / CH2 | Единица | Шаг | Диапазон записи |
| --- | --- | --- | --- | --- |
| `waveform` | 11 / 12 | код | 1 | 0..21 или 101..199 |
| `amplitude` | 15 / 16 | Вpp | 0.001 | 0..аппаратный предел |
| `offset` | 17 / 18 | В | 0.01 | -10..10 |
| `duty` | 19 / 20 | % | 0.01 | 0..100 |
| `phase` | 21 / 22 | ° | 0.01 | 0..359.99 |
| `modulation_frequency` | 43 / 44 | Гц | 0.001 | 0..1000000 |
| `am_depth` | 45 / 46 | % | 0.1 | 0..200 |
| `fm_deviation` | 47 / 48 | Гц | 0.1 | 0..аппаратный предел |
| `fsk_frequency` | 49 / 50 | Гц | 0.1 | 0..аппаратный предел |
| `pm_deviation` | 51 / 52 | ° | 0.1 | 0..359.9 |
| `pulse_width` | 53 / 54 | с | 1E-9 | 0..0.4 |
| `pulse_period` | 55 / 56 | с | 1E-8 | 0..4 |
| `frequency` | 13 / 14 | Гц | Обычно 0.001 | >= 0, MAXF определяется прибором |
| `enabled` | 10 (пара) | bool | — | False/True |

`enabled = value` читает состояния обоих выходов и сохраняет значение другого.
Чтение/запись защищены общей блокировкой экземпляра.
`waveform` возвращает Decimal кода; для известных встроенных форм можно использовать
`Waveform(int(ch.waveform))`. Для произвольных форм такой перевод в enum неприменим.

| Метод | Назначение |
| --- | --- |
| `set_arbitrary_waveform(slot)` | slot 1..99 преобразуется в код 101..199. |
| `set_frequency(hz, *, display_unit=FrequencyUnit.HZ)` | Частота всегда передаётся в Гц; параметр выбирает единицы отображения. |

Запись `ch.frequency = hz` выбирает HZ. Для unit HZ/KHZ/MHZ по примерам
протокола используются одинаковые тики 0.001 Гц. Для MILLIHZ/UHZ приняты
шаги 0.000001 / 0.000000001 Гц; эти режимы аппаратно не проверены.

## Общие регистры

Для составных параметров передавайте отдельные аргументы:
`psg.set('outputs', True, False)`, а не один tuple.
Доступ R означает только чтение; RW — чтение и запись.
Единичный шаг применяется также к селекторам и счётчикам.

| Имя | Код | Полей | Доступ | Масштаб: тиков/единицу | Диапазон записи каждого поля |
| --- | --- | --- | --- | --- | --- |
| `outputs` | 10 | 2 | RW | 1 | 0..1 |
| `interface` | 24 | 4 | RW | 1 | 0..255 (hex-селекторы) |
| `sync` | 25 | 6 | RW | 1 | 0..1 |
| `memory` | 26 | 1 | R | 1 | 0..не задан |
| `sound` | 27 | 1 | RW | 1 | 0..1 |
| `brightness` | 28 | 1 | RW | 1 | 0..100 |
| `language` | 29 | 1 | RW | 1 | 0..1 |
| `preset_wave_count` | 30 | 1 | RW | 1 | 0..39 |
| `arbitrary_wave_count` | 31 | 1 | RW | 1 | 0..99 |
| `wave_loading` | 32 | 1 | RW | 1 | 0..1 |
| `frequency_trim` | 33 | 1 | RW | 1 | не задан..не задан |
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
| `sweep_start_frequency` | 66 | 1 | RW | 10 | 0..не задан |
| `sweep_end_frequency` | 67 | 1 | RW | 10 | 0..не задан |
| `sweep_start_amplitude` | 68 | 1 | RW | 1000 | 0..не задан |
| `sweep_end_amplitude` | 69 | 1 | RW | 1000 | 0..не задан |
| `sweep_start_duty` | 70 | 1 | RW | 100 | 0..100 |
| `sweep_end_duty` | 71 | 1 | RW | 100 | 0..100 |
| `voltage_calibration_min` | 72 | 1 | RW | 1 | 0..не задан |
| `voltage_calibration_max` | 73 | 1 | RW | 1 | 0..не задан |
| `trigger` | 74 | 2 | RW | 1 | 0..1 |
| `counter` | 80 | 1 | R | 1 | 0..не задан |
| `measured_high_frequency` | 81 | 1 | R | 1 | 0..не задан |
| `measured_low_frequency` | 82 | 1 | R | 1000 | 0..не задан |
| `measured_positive_width` | 83 | 1 | R | 1000000000 | 0..не задан |
| `measured_negative_width` | 84 | 1 | R | 1000000000 | 0..не задан |
| `measured_period` | 85 | 1 | R | 100000000 | 0..не задан |
| `measured_duty` | 86 | 1 | R | 100 | 0..100 |

Порядок и смысл составных полей:

| Имя | Поля / значения |
| --- | --- |
| outputs | CH1, CH2; 0 выключен, 1 включён |
| interface | Четыре hex-селектора интерфейса; значения соответствуют меню прибора |
| sync | waveform, frequency, amplitude, offset, duty, external; 0/1 |
| modulation | CH1, CH2; enum Modulation |
| modulation_waveform | CH1, CH2; 0 sine, 1 square, 2 triangle, 3 rising sawtooth, 4 falling sawtooth, 5..9 arbitrary 101..105 |
| modulation_source | CH1, CH2; 0 internal, 1 external |
| pulse_inversion | CH1, CH2; 0 normal, 1 inverted |
| burst_idle | CH1, CH2; 0 zero, 1 positive maximum, 2 negative maximum |
| polarity | CH1, CH2; 0 positive, 1 negative |
| trigger_source | CH1, CH2; enum TriggerSource |
| burst_count | Число импульсов CH1, CH2 |
| sweep_enabled | Sweep, voltage control; 0/1 |
| trigger | CH1, CH2; 0/1 |

Прочие селекторы: sound 0/1; brightness проценты; language 0 English / 1 Chinese;
wave_loading 0 automatic / 1 fast; measurement_mode 0 counter / 1 measurement.
Диапазон и физическая единица frequency_trim не определены документом;
API передаёт целое значение без масштабирования. voltage_calibration_min/max — сырые целые.
measured_high_frequency имеет шаг 1 Гц, measured_low_frequency — 0.001 Гц,
measured_positive_width/negative_width — 1 нс, measured_period — 10 нс,
measured_duty — 0.01%. sweep_start/end_frequency — 0.1 Гц,
sweep_start/end_amplitude — 0.001 Вpp, sweep_start/end_duty — 0.01%.

## Измерение и sweep

`configure_measurement(*, dc=False, gate_seconds='0.02', low_frequency=False)`
пишет команду 62: AC/DC, gate 0.001..10 с с шагом 0.001 с, high/low frequency.
Метод конфигурирует режим; запуск выполняется отдельно.

`configure_sweep(*, channel=1, seconds=10, direction=0, logarithmic=False)`
пишет команду 64: канал 1/2, время 0.01..640 с с шагом 0.01 с,
направление 0 увеличение / 1 уменьшение / 2 туда-обратно,
линейный или логарифмический режим. Sweep включается отдельно.
Команды 62 и 64 читаются через read_raw(), без автоматического преобразования.

```python
from pypsgctrl import PSG9080

with PSG9080.connect('/dev/cu.usbserial-2120') as psg:
    psg.configure_measurement(dc=False, gate_seconds='0.1', low_frequency=True)
    psg.set('measurement_mode', 1)
    print(psg.get('measured_low_frequency'))  # Гц
    print(psg.get('measured_duty'))           # %

    psg.set('sweep_start_frequency', 100)
    psg.set('sweep_end_frequency', 10000)
    psg.configure_sweep(channel=1, seconds=10, direction=2, logarithmic=True)
    psg.set('sweep_enabled', 1, 0)
    # Когда sweep больше не нужен:
    psg.set('sweep_enabled', 0, 0)
```

## Перечисления

### Waveform

| Имя | Код |
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

| Имя | Код |
| --- | --- |
| `HZ` | 0 |
| `KHZ` | 1 |
| `MHZ` | 2 |
| `MILLIHZ` | 3 |
| `MHZ_SMALL` | 3 |
| `UHZ` | 4 |

### Modulation

| Имя | Код |
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

| Имя | Код |
| --- | --- |
| `KEY` | 0 |
| `INTERNAL` | 1 |
| `EXTERNAL_AC` | 2 |
| `EXTERNAL_DC` | 3 |

MHZ_SMALL — совместимый alias MILLIHZ (миллигерцы), не мегагерцы.

## Примеры модуляции, памяти и произвольной формы

```python
from pypsgctrl import PSG9080, Modulation, TriggerSource

with PSG9080.connect('/dev/cu.usbserial-2120') as psg:
    psg.set('modulation', Modulation.AM, Modulation.BURST)
    psg.set('modulation_source', 0, 0)
    psg.ch1.am_depth = 80
    psg.ch1.modulation_frequency = 500
    psg.set('trigger_source', TriggerSource.KEY, TriggerSource.EXTERNAL_DC)
    psg.set('burst_count', 10, 20)
    psg.ch2.set_arbitrary_waveform(1)   # Выбирает существующую форму 01
    # Загрузка отсчётов произвольной формы не описана протоколом и не реализована.
    psg.save(52)
    psg.load(52)
```

## Сырой API и транспорт

`read_raw(code)` отправляет `:rCODE=0.\r\n`, возвращает tuple строк.
`write_raw(code, *fields)` отправляет `:wCODE=FIELDS.\r\n`, возвращает None.
Код — именно int в диапазоне 0..99. Поля проходят проверку ASCII-алфавита;
семантика, количество полей и диапазоны raw-команд не проверяются.
Передавайте целые wire-значения без точки и CRLF; дробные физические значения
предварительно масштабируются. Код ответа чтения обязан совпадать с запросом.
Подтверждения записи: `OK`, `OK.` и полученный на приборе `:ok`, с CRLF.

```python
from pypsgctrl import PSG9080

with PSG9080.connect('/dev/cu.usbserial-2120') as psg:
    print(psg.read_raw(13))              # Например ('000003000000', '0')
    psg.write_raw(24, '0', '1', '0', 'a')
    # Эквивалентная запись через общий API:
    psg.set('interface', 0, 1, 0, 10)
```

Transport — typing.Protocol с методами `write(data: bytes) -> int`,
`read(size: int = 1) -> bytes`, `close() -> None`.
read() должен иметь конечный таймаут: драйвер не способен прервать блокирующий вызов.
Срок response_timeout проверяется между вызовами read(), поэтому медленный
транспорт может превысить его на длительность одного чтения.
Частичная запись считается ошибкой; ответ ограничен 65536 байтами.

```python
import serial
from pypsgctrl import PSG9080

transport = serial.Serial('/dev/cu.usbserial-2120', 115200,
                          timeout=1, write_timeout=1)
try:
    with PSG9080(transport, owns_transport=False, response_timeout=1) as psg:
        print(psg.ch1.frequency)
    # Заимствованный транспорт остаётся открытым.
finally:
    transport.close()
```

## Register и каталоги

`Register(code, scale=Decimal(1), offset=Decimal(0), minimum=Decimal(0),
maximum=None, count=1, writable=True)` — frozen dataclass.
Сериализация: `raw = physical * scale + offset`; чтение выполняет обратное преобразование.
minimum/maximum относятся к физическому значению; None означает отсутствие границы.
Для offset каналов scale=100 и offset=1000: 0 В соответствует raw 1000.
REGISTERS и CHANNEL_REGISTERS — доступные словари описаний. Код CH2 равен коду CH1+1.
Специальные форматы interface, sync и frequency обрабатываются отдельно.

## Ошибки и конкурентный доступ

| Исключение | Причина |
| --- | --- |
| `PSGError` | Базовое исключение; также обращение к закрытому драйверу |
| `ProtocolError(PSGError)` | Неполная запись, неправильный ASCII/framing/код/число полей, отклонённая запись |
| `PSGTimeoutError(PSGError, TimeoutError)` | Неполный ответ или превышение срока ответа |
| `ValueError` | Неверное значение, шаг, код, номер канала, число полей или попытка записи read-only регистра |
| `KeyError` | Неизвестное имя get/set |
| Исключения pyserial | Ошибки открытия порта и транспорта; передаются без обёртки |

После таймаута закройте и заново откройте соединение: протокол не имеет
идентификаторов транзакций и поздний ответ может быть принят за следующий.
Драйвер сам не повторяет команды записи. Записи нескольких параметров
не являются одной атомарной транзакцией. RLock защищает обмен потоков одного
экземпляра; один порт должен принадлежать одному экземпляру/процессу.

## Неоднозначности протокола и аппаратная проверка

* unit 3/4 частоты: принята трактовка из примеров; аппаратно не проверена.
* width/period: документ противоречит сам себе в максимуме wire-значения.
  Приняты консервативные максимумы 0.4/4 с и шаги 1/10 нс.
* Команда 63: текст указывает два поля, таблица — один режим. API использует
  один режим; альтернативный формат доступен через write_raw().
* r25 принимает компактные шесть бит и CSV. В w64 повторное n3 принято как n4.
* Максимальные частота, амплитуда, положительное смещение, номер памяти
  и диапазон frequency_trim документом полностью не определены.
* При первом чтении brightness прибор вернул 101; запись 101 ограничивается
  до 100. Записываемый диапазон API сохранён 0..100, фактическое чтение может быть выше.

2026-10-07: 13 тестов библиотеки прошли на Python 3.10.6.
На USB `/dev/cu.usbserial-2120`, 115200, 8-N-1 проверены чтение,
изменение яркости 20/100, фазы CH2, а также формы/частоты/амплитуды CH1:
синус 1 кГц / 2 Вpp, меандр 2 кГц / 4 Вpp, треугольник 500 Гц / 1 Вpp.
Пользователь подтвердил видимые изменения. После демонстрации восстановлены
синус 3 кГц / 5 Вpp, яркость 100. Физический сигнал измерительным прибором не проверялся.
