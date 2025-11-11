import sys
from PyQt6.QtWidgets import QApplication

from gui import VideoPlayer

def main():
    """Main entry point for the event-marker application."""
    app = QApplication(sys.argv)
    player = VideoPlayer(app=app)
    player.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()