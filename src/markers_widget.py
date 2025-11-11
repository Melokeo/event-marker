from typing import TYPE_CHECKING
from collections import defaultdict

from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtWidgets import QWidget

from cfg import config

if TYPE_CHECKING:
    from gui import VideoPlayer

class MarkersWidget(QWidget):
    """Widget to display event markers above the timeline."""
    jumpToFrame = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player: VideoPlayer = parent
        self.setMinimumHeight(16)
        self.marker_positions = []

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        slider = self.player.time_slider
        total_duration = self.player.media_player.duration()
        if total_duration <= 0:
            return

        slider_width = slider.width()
        duration_ratio = (slider_width - config.TIMELINE_MARKER_OFFSET[1]) / total_duration
        
        self.marker_positions.clear()
        marker_map = defaultdict(list)
        
        for evt, frames in self.player.event_manager.markers.items():
            idx = int(str(evt)[0]) - 1
            color = config.MARKER_COLORS[idx % len(config.MARKER_COLORS)]
            painter.setBrush(color)
            for frame in frames:
                time_pos = frame * (1000 / config.VIDEO_FPS_ORIGINAL)
                x_pos = int(time_pos * duration_ratio) + config.TIMELINE_MARKER_OFFSET[0]
                self.marker_positions.append((x_pos, frame))
                marker_map[evt].append((frame, x_pos))
                painter.drawEllipse(QRectF(x_pos, 5 + idx * 0.8, 3.5, 3.5))

        if config.PAIRING_ENABLED:
            painter.setPen(QColor(100, 100, 100))
            for start_type, end_type in config.PAIRING_RULES.items():
                starts, ends = sorted(marker_map.get(start_type, [])), sorted(marker_map.get(end_type, []))
                i = j = 0
                while i < len(starts) and j < len(ends):
                    if starts[i][0] < ends[j][0]:
                        painter.drawLine(starts[i][1], 13, ends[j][1], 13)
                        i += 1
                    j += 1
    
    def mousePressEvent(self, event):
        click_x = event.position().x()
        threshold = 5
        for x_pos, frame in self.marker_positions:
            if abs(click_x - x_pos) <= threshold:
                self.jumpToFrame.emit(frame)
                break