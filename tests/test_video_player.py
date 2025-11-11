"""
Tests for the VideoPlayer application.
"""
import sys
import os
from pathlib import Path
import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtMultimedia import QMediaPlayer

# Add src to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from gui import VideoPlayer


@pytest.fixture(scope="session")
def qapp():
    """Create QApplication instance for all tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app
    # Don't quit here as it may affect other tests


@pytest.fixture
def video_path():
    """Path to test video asset."""
    # Look for test video in tests/assets directory
    test_dir = Path(__file__).parent
    video_file = test_dir / "assets" / "frame_counter_11988_4200.mp4"
    
    if not video_file.exists():
        pytest.skip(f"Test video not found at {video_file}")
    
    return str(video_file)


@pytest.fixture
def player(qapp):
    """Create a VideoPlayer instance."""
    player = VideoPlayer(app=qapp)
    yield player
    # Clean up
    player.close()
    QApplication.processEvents()


class TestVideoPlayer:
    """Test suite for VideoPlayer application."""
    
    def test_window_creation(self, player):
        """Test that the video player window is created successfully."""
        assert player is not None
        assert player.windowTitle() != ""
        assert player.media_player is not None
        assert player.audio_output is not None
        
    def test_window_show(self, player):
        """Test that the window can be shown."""
        player.show()
        QApplication.processEvents()
        assert player.isVisible()
        
    def test_ui_components_exist(self, player):
        """Test that all major UI components are initialized."""
        assert player.play_btn is not None
        assert player.time_slider is not None
        assert player.time_label is not None
        assert player.frame_label is not None
        assert player.video_widget is not None
        assert player.markers_widget is not None
        
    def test_controllers_initialized(self, player):
        """Test that business logic controllers are initialized."""
        assert player.event_manager is not None
        assert player.playback_controller is not None
        assert player.key_handler is not None
        
    def test_load_video(self, player, video_path):
        """Test loading a video file."""
        player.show()
        QApplication.processEvents()
        
        # Load the video
        player.load_video(video_path)
        QApplication.processEvents()
        
        # Verify video is loaded
        assert player.fname == video_path
        assert player.media_player.source().isValid()
        assert "frame_counter_11988_4200.mp4" in player.windowTitle()
        assert player.play_btn.isEnabled()
        
    def test_video_playback_ready(self, player, video_path):
        """Test that video is ready for playback after loading."""
        player.show()
        player.load_video(video_path)
        
        # Wait a bit for media to load
        def check_duration():
            return player.media_player.duration() > 0
        
        # Poll for up to 2 seconds
        timeout = 2000
        interval = 100
        elapsed = 0
        while elapsed < timeout and not check_duration():
            QApplication.processEvents()
            QTimer.singleShot(interval, lambda: None)
            elapsed += interval
        
        # Check if duration is set (indicates video is loaded)
        duration = player.media_player.duration()
        assert duration > 0, "Video duration should be greater than 0"
        
    def test_playback_controller_integration(self, player, video_path):
        """Test that playback controller works with loaded video."""
        player.show()
        player.load_video(video_path)
        QApplication.processEvents()
        
        # Test frame operations
        initial_frame = player.playback_controller.get_current_frame()
        assert initial_frame >= 0
        
        # Test jumping to a frame
        player.playback_controller.jump_to_frame(100)
        QApplication.processEvents()
        
        current_frame = player.playback_controller.get_current_frame()
        assert current_frame >= 0  # Frame should be valid
        
    def test_event_manager_ready(self, player):
        """Test that event manager is ready to accept markers."""
        assert hasattr(player.event_manager, 'markers')
        assert isinstance(player.event_manager.markers, dict)
        assert len(player.event_manager.markers) == 0  # Should start empty
        
    def test_menu_actions_exist(self, player):
        """Test that menu actions are created."""
        menubar = player.menuBar()
        assert menubar is not None
        
        # Check that menus exist
        menus = [action.text() for action in menubar.actions()]
        assert "File" in menus
        assert "Workspace" in menus
        assert "Settings" in menus


class TestVideoPlayerWithoutVideo:
    """Tests that don't require a video file."""
    
    def test_initial_state(self, player):
        """Test initial state of the player."""
        assert player.fname is None
        assert player.is_slider_pressed is False
        assert player.frame_editing is False
        assert player.save_status is True
        
    def test_playback_state(self, player):
        """Test initial playback state."""
        state = player.media_player.playbackState()
        assert state == QMediaPlayer.PlaybackState.StoppedState
        
    def test_settings_loaded(self, player):
        """Test that settings are loaded."""
        assert player.settings is not None
        assert player.settings.organizationName() == 'mel.rnel'
        assert player.settings.applicationName() == 'EventMarkerRefactored'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
