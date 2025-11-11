from PyQt6.QtCore import (
    Qt, QTimer
)
from PyQt6.QtGui import QFont, QCloseEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel
)

class MarkerFloat(QWidget):
    """a float window to display marker -- more obviously"""
    def __init__(self, player=None, clear_interval: int = 2000): 
        super().__init__()
        if player is not None:
            self.player = player
        self.clear_interval = clear_interval
        self.setup_ui()
        self.setup_timer()
    
    def setup_ui(self):
        self.setWindowTitle("MARKER")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        
        self.label = QLabel("-")
        
        font = QFont()
        font.setFamilies(["Cascadia Code", "Courier New", "monospace"])
        font.setPointSize(48)  
        font.setWeight(QFont.Weight.Bold)
        
        self.label.setFont(font)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("QLabel { background-color: #f0f0f0; border-radius: 5px; padding: 5px; }")
        
        layout.addWidget(self.label)
        self.setLayout(layout)
        
        self.resize(80, 80)  
    
    def setup_timer(self):
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.clear_display)
    
    def receive_string(self, text: str):
        """slot to receive string signals from main window"""
        self.label.setText(text)
        self.timer.start(self.clear_interval)  
    
    def clear_display(self):
        """clear after timeout"""
        self.label.setText("-")
    
    def closeEvent(self, event: QCloseEvent):
        """Update main window menu when marker float window is closed."""
        if hasattr(self, 'player'):
            if self.player and hasattr(self.player, 'marker_float_action'):
                self.player.marker_float_action.setChecked(False)
        super().closeEvent(event)
