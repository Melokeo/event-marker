from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QPainter, QTransform
from PyQt6.QtMultimediaWidgets import QVideoWidget

class QIVideoWidget(QVideoWidget):
    """Video widget with zoom and pan functionality."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.zoom_factor = 1.0
        self.pan_offset = QPointF(0, 0)
        self._last_mouse_pos = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_PaintOnScreen, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, False)

    def wheelEvent(self, event):
        factor = 1.1 if event.angleDelta().y() > 0 else 1/1.1
        self.zoom_factor *= factor
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._last_mouse_pos = event.position()

    def mouseMoveEvent(self, event):
        if self._last_mouse_pos:
            delta = event.position() - self._last_mouse_pos
            self.pan_offset += delta
            self._last_mouse_pos = event.position()
            self.update()

    def mouseReleaseEvent(self, event):
        self._last_mouse_pos = None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        transform = QTransform()
        transform.translate(self.pan_offset.x(), self.pan_offset.y())
        transform.scale(self.zoom_factor, self.zoom_factor)
        painter.setTransform(transform)
        super().paintEvent(event)