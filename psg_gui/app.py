"""PSG9080 control panel (PySide6).

Run with:  python -m psg_gui   (or the `psg-gui` command after pip install)
All serial I/O runs on one worker thread, so the window never freezes, and
every write is followed by a read-back so the panel shows what the device
actually accepted.
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from pypsgctrl import PSG9080, PSGError, PSGTimeoutError

from . import model

APP_NAME = 'PSG9080'
YES = QMessageBox.StandardButton.Yes


@contextmanager
def blocked(widget):
    """Temporarily stop a widget from emitting signals (works on any PySide6)."""
    previous = widget.blockSignals(True)
    try:
        yield
    finally:
        widget.blockSignals(previous)


class IoRunner(QObject):
    """Runs device calls one at a time off the GUI thread."""
    finished = Signal(object, object, object)  # callback, result, error
    busy_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='psg-io')
        self._pending = 0

    def submit(self, fn, callback):
        self._pending += 1
        if self._pending == 1:
            self.busy_changed.emit(True)
        future = self._pool.submit(fn)

        def done(f):
            error = f.exception()
            # Signal emission from the worker thread is queued to the GUI thread.
            self.finished.emit(callback, None if error else f.result(), error)
        future.add_done_callback(done)

    def task_done(self):
        self._pending -= 1
        if self._pending == 0:
            self.busy_changed.emit(False)

    def shutdown(self):
        self._pool.shutdown(wait=True)


def _spin(decimals, minimum, maximum, step, suffix):
    box = QDoubleSpinBox()
    box.setDecimals(decimals)
    box.setRange(minimum, maximum)
    box.setSingleStep(step)
    box.setSuffix(suffix)
    box.setKeyboardTracking(False)  # write on Enter/arrows/focus-out, not per keystroke
    box.setAccelerated(True)
    box.setMinimumWidth(130)
    return box


class ChannelPanel(QGroupBox):
    """Controls for one channel. Emits edits; never talks to the device."""
    field_edited = Signal(int, str, object)
    output_toggled = Signal(int, bool)

    SPINS = {  # name: (decimals, min, max, step, suffix)
        'amplitude': (3, 0, 20, 0.1, ' Vpp'),
        'offset': (2, -10, 10, 0.1, ' V'),
        'duty': (2, 0, 100, 1, ' %'),
        'phase': (2, 0, 359.99, 1, ' °'),
    }
    LABELS = {'amplitude': 'Amplitude', 'offset': 'Offset', 'duty': 'Duty cycle',
              'phase': 'Fase'}

    def __init__(self, number, color):
        super().__init__(f'CH{number}')
        self.number = number
        self._freq_hz = Decimal(0)
        self.setStyleSheet(
            f'QGroupBox {{ font-weight: bold; border: 2px solid {color}; border-radius: 6px;'
            f' margin-top: 10px; padding-top: 8px; }}'
            f'QGroupBox::title {{ color: {color}; subcontrol-origin: margin; left: 10px; }}')

        self.output = QPushButton('SAÍDA DESLIGADA')
        self.output.setCheckable(True)
        self.output.setMinimumHeight(40)
        self.output.setStyleSheet(
            'QPushButton { font-weight: bold; border-radius: 4px; background: #555; color: #ddd; }'
            'QPushButton:checked { background: #2e9d4a; color: white; }'
            'QPushButton:disabled { background: #333; color: #777; }')
        self.output.toggled.connect(self._output_text)
        self.output.clicked.connect(lambda on: self.output_toggled.emit(self.number, on))

        self.waveform = QComboBox()
        for label, code in model.waveform_choices():
            self.waveform.addItem(label, code)
        self.waveform.setMaxVisibleItems(25)
        self.waveform.activated.connect(
            lambda _i: self.field_edited.emit(self.number, 'waveform',
                                              self.waveform.currentData()))

        self.freq = QLineEdit()
        self.freq.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.freq.setMinimumWidth(130)
        self.freq.editingFinished.connect(self._freq_edited)
        self.unit = QComboBox()
        for label, unit, _factor in model.FREQ_UNITS:
            self.unit.addItem(label, int(unit))
        self.unit.activated.connect(self._unit_changed)
        freq_row = QHBoxLayout()
        freq_row.addWidget(self.freq, 1)
        freq_row.addWidget(self.unit)

        form = QFormLayout()
        form.addRow('Forma de onda', self.waveform)
        form.addRow('Frequência', freq_row)
        self.spins = {}
        for name, args in self.SPINS.items():
            box = _spin(*args)
            box.valueChanged.connect(lambda v, n=name, b=box: self._spin_edited(n, b))
            self.spins[name] = box
            form.addRow(self.LABELS[name], box)

        layout = QVBoxLayout(self)
        layout.addWidget(self.output)
        layout.addLayout(form)

    # -- user edits -> signals
    def _output_text(self, on):
        self.output.setText('SAÍDA LIGADA' if on else 'SAÍDA DESLIGADA')

    def _spin_edited(self, name, box):
        value = Decimal(f'{box.value():.{box.decimals()}f}')
        self.field_edited.emit(self.number, name, value)

    def _freq_edited(self):
        if not self.freq.isModified():
            return  # focus left without a change
        self.freq.setModified(False)
        try:
            hz = model.to_hz(self.freq.text(), self.unit.currentData())
        except ValueError as exc:
            self.field_edited.emit(self.number, 'invalid', str(exc))
            return
        self.field_edited.emit(self.number, 'frequency', (hz, self.unit.currentData()))

    def _unit_changed(self, _index):
        # Same frequency, shown in the newly selected unit.
        self.field_edited.emit(self.number, 'frequency',
                               (self._freq_hz, self.unit.currentData()))

    # -- device values -> widgets (signals blocked so nothing is re-sent)
    def show_field(self, name, value):
        if name == 'waveform':
            index = self.waveform.findData(int(value))
            with blocked(self.waveform):
                if index >= 0:
                    self.waveform.setCurrentIndex(index)
        elif name == 'frequency':
            hz, unit = value
            self._freq_hz = Decimal(hz)
            with blocked(self.unit):
                self.unit.setCurrentIndex(max(0, self.unit.findData(int(unit))))
            self.freq.setText(model.from_hz(hz, unit))
            self.freq.setModified(False)
        elif name == 'enabled':
            with blocked(self.output):
                self.output.setChecked(bool(value))
            self._output_text(bool(value))
        else:
            with blocked(self.spins[name]):
                self.spins[name].setValue(float(value))

    def show_state(self, state: model.ChannelState):
        self.show_field('waveform', state.waveform)
        self.show_field('frequency', (state.frequency_hz, state.freq_unit))
        for name in self.SPINS:
            self.show_field(name, getattr(state, name))
        self.show_field('enabled', state.enabled)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('PSG9080 — painel de controle')
        self.device: PSG9080 | None = None
        self.settings = QSettings('psg9080-gui', 'psg9080-gui')
        self.presets = model.PresetStore()
        self.io = IoRunner()
        self.io.finished.connect(self._io_finished)
        self.io.busy_changed.connect(self._busy)

        # connection bar
        self.port = QComboBox()
        self.port.setEditable(True)
        self.port.setMinimumWidth(260)
        refresh = QPushButton('↻')
        refresh.setToolTip('Procurar portas seriais')
        refresh.setFixedWidth(36)
        refresh.clicked.connect(self.refresh_ports)
        self.connect_btn = QPushButton('Conectar')
        self.connect_btn.clicked.connect(self.toggle_connection)
        self.read_btn = QPushButton('Ler do aparelho')
        self.read_btn.setToolTip('Atualiza o painel com os valores atuais do gerador')
        self.read_btn.clicked.connect(self.read_device)
        self.all_off_btn = QPushButton('Desligar saídas')
        self.all_off_btn.setStyleSheet('QPushButton { color: #c0392b; font-weight: bold; }')
        self.all_off_btn.clicked.connect(self.all_outputs_off)
        bar = QHBoxLayout()
        bar.addWidget(QLabel('Porta'))
        bar.addWidget(self.port, 1)
        bar.addWidget(refresh)
        bar.addWidget(self.connect_btn)
        bar.addSpacing(12)
        bar.addWidget(self.read_btn)
        bar.addWidget(self.all_off_btn)

        # channels
        self.panels = {1: ChannelPanel(1, '#e6b800'), 2: ChannelPanel(2, '#2fa8d8')}
        channels = QHBoxLayout()
        for panel in self.panels.values():
            panel.field_edited.connect(self.on_field_edited)
            panel.output_toggled.connect(self.on_output_toggled)
            channels.addWidget(panel)

        # presets
        self.preset_box = QComboBox()
        self.preset_box.setMinimumWidth(200)
        apply_btn = QPushButton('Aplicar')
        apply_btn.clicked.connect(self.apply_preset)
        save_btn = QPushButton('Salvar atual…')
        save_btn.clicked.connect(self.save_preset)
        del_btn = QPushButton('Excluir')
        del_btn.clicked.connect(self.delete_preset)
        presets = QHBoxLayout()
        presets.addWidget(QLabel('Presets'))
        presets.addWidget(self.preset_box, 1)
        for b in (apply_btn, save_btn, del_btn):
            presets.addWidget(b)
        self._preset_buttons = (apply_btn, save_btn, del_btn)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addLayout(bar)
        layout.addLayout(channels)
        layout.addLayout(presets)
        self.setCentralWidget(root)

        self.status_label = QLabel()
        self.statusBar().addPermanentWidget(self.status_label)

        quit_action = QAction('Sair', self)
        quit_action.setShortcut('Ctrl+Q')
        quit_action.triggered.connect(self.close)
        self.addAction(quit_action)

        self.refresh_ports()
        self.reload_presets()
        self._set_connected(False)

    # ---- helpers
    def run(self, fn, callback=None):
        self.io.submit(fn, callback)

    def _io_finished(self, callback, result, error):
        self.io.task_done()
        if error is not None:
            self._handle_error(error)
        elif callback is not None:
            callback(result)

    def _busy(self, busy):
        self.status_label.setText('comunicando…' if busy else '')

    def message(self, text, error=False):
        self.statusBar().setStyleSheet('color: #c0392b;' if error else '')
        self.statusBar().showMessage(text, 8000)

    def _handle_error(self, error):
        self.connect_btn.setEnabled(True)  # never leave it stuck after a failed connect
        if isinstance(error, PSGTimeoutError):
            self.message('Sem resposta do gerador. Reconecte.', error=True)
            QMessageBox.warning(self, APP_NAME,
                                'O gerador não respondeu a tempo.\n\n'
                                'Confira o cabo USB e se o aparelho está ligado, '
                                'depois desconecte e conecte de novo.')
            self.read_device()
        elif isinstance(error, ValueError):
            self.message(f'Valor recusado: {error}', error=True)
            self.read_device()  # put the widgets back to the device's values
        elif isinstance(error, (PSGError, OSError)):
            self.message(f'Erro: {error}', error=True)
            if isinstance(error, OSError):
                self._drop_device()
        else:
            self.message(f'Erro inesperado: {type(error).__name__}: {error}', error=True)

    def _set_connected(self, connected):
        self.connect_btn.setText('Desconectar' if connected else 'Conectar')
        self.port.setEnabled(not connected)
        for widget in (self.read_btn, self.all_off_btn, *self._preset_buttons,
                       *self.panels.values()):
            widget.setEnabled(connected)
        self._preset_buttons[2].setEnabled(True)  # deleting a preset works offline

    def _drop_device(self):
        if self.device is not None:
            try:
                self.device.close()
            except Exception:
                pass
        self.device = None
        self._set_connected(False)

    # ---- connection
    def refresh_ports(self):
        from serial.tools import list_ports
        current = self.port.currentText() or self.settings.value('port', '/dev/ttyUSB0')
        ports = sorted(list_ports.comports(), key=lambda p: p.device)
        self.port.clear()
        for p in ports:
            if 'ttyS' in p.device and p.description in ('n/a', ''):
                continue  # skip legacy on-board serial ports
            self.port.addItem(p.device)
            self.port.setItemData(self.port.count() - 1, p.description, Qt.ItemDataRole.ToolTipRole)
        index = self.port.findText(current)
        if index >= 0:
            self.port.setCurrentIndex(index)
        elif current:
            self.port.setEditText(current)

    def toggle_connection(self):
        if self.device is not None:
            device = self.device
            self.device = None
            self._set_connected(False)
            self.run(device.close, lambda _r: self.message('Desconectado.'))
            return
        port = self.port.currentText().strip()
        if not port:
            return
        self.connect_btn.setEnabled(False)

        def opened(device):
            self.device = device
            self.settings.setValue('port', port)
            self._set_connected(True)
            self.message(f'Conectado em {port}.')
            self.read_device()

        def open_port():
            device = PSG9080.connect(port, timeout=1.0)
            try:
                device.get('outputs')  # prove something PSG9080-like answers
            except Exception:
                device.close()
                raise
            return device

        def finished(result):
            self.connect_btn.setEnabled(True)
            opened(result)

        self.run(open_port, finished)

    # ---- device actions
    def read_device(self):
        device = self.device
        if device is None:
            return

        def show(states):
            self.panels[1].show_state(states[0])
            self.panels[2].show_state(states[1])
        self.run(lambda: model.read_all(device), show)

    def on_field_edited(self, number, name, value):
        if name == 'invalid':
            self.message(value, error=True)
            self.read_device()
            return
        device = self.device
        if device is None:
            return
        panel = self.panels[number]
        self.run(lambda: model.write_field(device, number, name, value),
                 lambda readback: panel.show_field(name, readback))

    def on_output_toggled(self, number, on):
        device = self.device
        if device is None:
            return

        def show(outputs):
            for n, state in zip((1, 2), outputs):
                self.panels[n].show_field('enabled', state)
        self.run(lambda: model.set_output(device, number, on), show)

    def all_outputs_off(self):
        device = self.device
        if device is None:
            return

        def done(_r):
            for panel in self.panels.values():
                panel.show_field('enabled', False)
            self.message('Saídas desligadas.')
        self.run(lambda: device.set_outputs(False, False), done)

    # ---- presets
    def reload_presets(self, select=None):
        names = sorted(self.presets.load())
        self.preset_box.clear()
        self.preset_box.addItems(names)
        if select in names:
            self.preset_box.setCurrentText(select)

    def save_preset(self):
        device = self.device
        if device is None:
            return
        name, ok = QInputDialog.getText(self, APP_NAME, 'Nome do preset:',
                                        text=self.preset_box.currentText())
        name = name.strip()
        if not ok or not name:
            return
        if name in self.presets.load() and QMessageBox.question(
                self, APP_NAME, f'Substituir o preset "{name}"?') != YES:
            return

        def store(states):
            self.presets.put(name, *states)
            self.reload_presets(select=name)
            self.message(f'Preset "{name}" salvo.')
        self.run(lambda: model.read_all(device), store)

    def apply_preset(self):
        device, name = self.device, self.preset_box.currentText()
        if device is None or not name:
            return
        ch1, ch2 = self.presets.load()[name]

        def show(states):
            self.panels[1].show_state(states[0])
            self.panels[2].show_state(states[1])
            self.message(f'Preset "{name}" aplicado.')
        self.run(lambda: (model.apply_state(device, ch1, ch2), model.read_all(device))[1], show)

    def delete_preset(self):
        name = self.preset_box.currentText()
        if name and QMessageBox.question(
                self, APP_NAME, f'Excluir o preset "{name}"?') == YES:
            self.presets.delete(name)
            self.reload_presets()

    def closeEvent(self, event):
        device, self.device = self.device, None
        if device is not None:
            self.io.submit(device.close, None)
        self.io.shutdown()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow()
    window.resize(820, 420)
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
