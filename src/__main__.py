import sys
from PyQt6.QtWidgets import QApplication

from gui import VideoPlayer

if __name__ == '__main__':
    app = QApplication(sys.argv)
    player = VideoPlayer(app=app)
    player.show()
    sys.exit(app.exec())