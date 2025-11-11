from PyQt6.QtMultimedia import QMediaPlayer
from cfg import config

class PlaybackController:
    """Manages the QMediaPlayer state and playback controls."""
    def __init__(self, media_player: QMediaPlayer):
        self.media_player = media_player
        self.compensation = config.get_frame_compensation(config.VIDEO_FPS_ORIGINAL)

    def toggle_play_pause(self):
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
        else:
            self.media_player.play()

    def step_by_frames(self, frame_delta: int):
        current_frame = self.get_current_frame()
        target_frame = max(0, current_frame + frame_delta)
        self.jump_to_frame(target_frame)

    def jump_to_frame(self, frame: int):
        position_ms = frame * (1000 / config.VIDEO_FPS_ORIGINAL)
        # apply compensation for float inaccuracy
        final_pos = position_ms - self.compensation if position_ms > 0 else 0
        self.media_player.setPosition(int(final_pos))

    def change_playback_rate(self, factor):
        if factor == -1:  # reset
            new_rate = 1.0
        else:
            new_rate = round(self.media_player.playbackRate() * factor, 1)
        self.media_player.setPlaybackRate(new_rate)
        return new_rate

    def get_current_frame(self) -> int:
        pos = self.media_player.position() + self.compensation
        return round(pos * config.VIDEO_FPS_ORIGINAL / 1000)