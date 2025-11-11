from typing import TYPE_CHECKING
import csv

import numpy as np

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent, QCloseEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QComboBox, QFileDialog
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

if TYPE_CHECKING:
    from gui import VideoPlayer

class CSVPlotWindow(QWidget):
    def __init__(self, player):
        super().__init__(player, Qt.WindowType.Window | Qt.WindowType.Tool)
        self.player: VideoPlayer = player
        self.setWindowTitle("CSV Plot")
        self.setFixedSize(1500, 200)
        layout = QVBoxLayout(self)
        hl = QHBoxLayout()
        self.load_btn = QPushButton("Load CSV")
        self.combo = QComboBox()
        hl.addWidget(self.load_btn)
        hl.addWidget(self.combo)
        layout.addLayout(hl)
        self.fig = Figure(figsize=(8, 1.5))
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvas(self.fig)
        self.line, = self.ax.plot([], [], lw=1)
        self.ax2 = self.ax.twinx()
        self.diff_line, = self.ax2.plot([], [], lw=1, linestyle='--')
        self.cursor_line = self.ax.axvline(0, color='red')
        layout.addWidget(self.canvas)
        self.data = {}
        self.data_diff = {}
        self.win_size = 1200
        self.load_btn.clicked.connect(self._load_csv)
        self.combo.currentTextChanged.connect(self._update_plot)
        player.media_player.positionChanged.connect(self._on_position)
        self.canvas.mpl_connect("button_press_event", self._on_click)

    def _load_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select CSV", "", "CSV Files (*.csv)")
        if not path:
            return
        with open(path) as f:
            reader = csv.reader(f)
            headers = next(reader)
            cols = list(zip(*reader))
        self.data.clear()
        self.combo.blockSignals(True)
        self.combo.clear()
        for h, col in zip(headers, cols):
            try:
                arr = np.array(col, float)
                self.data[h] = arr
                self.data_diff[h] = np.diff(arr, prepend=arr[0])
                self.combo.addItem(h)
            except ValueError:
                pass
        self.combo.blockSignals(False)
        if self.combo.count():
            self.combo.setCurrentIndex(0)
            self._update_plot()

    def _on_position(self, ms):
        frame = self.player.playback_controller.get_current_frame()
        self._draw(frame)

    def _update_plot(self, name=None):
        self.cur_name = self.combo.currentText()
        arr, diff = self.data[self.cur_name], self.data_diff[self.cur_name]
        self.ax.set_ylim(arr.min(), arr.max())
        self.ax2.set_ylim(diff.min(), diff.max())
        frame = self.player.playback_controller.get_current_frame()
        self._draw(frame)

    def _draw(self, frame):
        if not hasattr(self, 'cur_name'):
            return
        arr, diff = self.data[self.cur_name], self.data_diff[self.cur_name]
        half = self.win_size // 2
        lo, hi = max(frame - half, 0), min(frame + half, len(arr))
        x = np.arange(lo, hi)
        self.line.set_data(x, arr[lo:hi])
        self.cursor_line.set_xdata([frame])
        self.diff_line.set_data(x, diff[lo:hi])
        self.ax.set_xlim(lo, hi)
        self.canvas.draw_idle()

    def _on_click(self, ev):
        if ev.xdata is None:
            return
        self.player.playback_controller.jump_to_frame(int(round(ev.xdata)))

    def closeEvent(self, event: QCloseEvent):
        """Update main window menu when CSV plot window is closed."""
        if hasattr(self.player, 'csv_plot_action'):
            self.player.csv_plot_action.setChecked(False)
        super().closeEvent(event)