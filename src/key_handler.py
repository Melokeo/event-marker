from typing import TYPE_CHECKING
import os
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent

from cfg import config

if TYPE_CHECKING:
    from gui import VideoPlayer
    from playback_controller import PlaybackController
    from event_manager import EventManager

class KeyHandler:
    """Maps keyboard inputs to specific actions."""
    def __init__(self, main_window: 'VideoPlayer', playback_controller: 'PlaybackController', event_manager: 'EventManager'):
        self.window = main_window
        self.playback = playback_controller
        self.events = event_manager

        self.delicate_mode = False
        self.pending_num = None

    def handle_key_press(self, event: QKeyEvent):
        if self.window.frame_editing:
            return
        
        key = event.key()
        modifiers = event.modifiers()
        
        # combo marking mode logic
        if self.delicate_mode and self.pending_num and event.text().isalpha():
            marker_id = f"{self.pending_num}{event.text().lower()}"
            self.events.add_marker(marker_id, self.playback.get_current_frame())
            self.pending_num = None
            self.window.markers_widget.update()
            self.window.update_current_marker_label(self.playback.get_current_frame())
            return

        if key == Qt.Key.Key_Space:
            self.playback.toggle_play_pause()

        elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.events.remove_marker_at_frame(self.playback.get_current_frame()):
                self.window.markers_widget.update()

        elif key == Qt.Key.Key_Left:
            if modifiers & Qt.KeyboardModifier.AltModifier:
                if self._nudge_marker(-config.FRAME_STEP):
                    self.window.markers_widget.update()
                    self.playback.step_by_frames(-config.FRAME_STEP)
            elif modifiers == Qt.KeyboardModifier.ControlModifier:
                self.jump_to_adjacent_marker(forward=False)
            else:
                self.playback.step_by_frames(-config.FRAME_STEP)
                self.pending_num = None  # clear pending on movement

        elif key == Qt.Key.Key_Right:
            if modifiers & Qt.KeyboardModifier.AltModifier:
                if self._nudge_marker(config.FRAME_STEP):
                    self.window.markers_widget.update()
                    self.playback.step_by_frames(config.FRAME_STEP)
            elif modifiers == Qt.KeyboardModifier.ControlModifier:
                self.jump_to_adjacent_marker(forward=True)
            else:
                self.playback.step_by_frames(config.FRAME_STEP)
                self.pending_num = None  # clear pending on movement

        elif key == Qt.Key.Key_Up:
            if modifiers & Qt.KeyboardModifier.AltModifier:
                if self._nudge_marker(-config.FRAME_STEP * config.LARGE_STEP_MULTIPLIER):
                    self.window.markers_widget.update()
            else:
                self.playback.step_by_frames(-config.FRAME_STEP * config.LARGE_STEP_MULTIPLIER)
                self.pending_num = None  # clear pending on movement

        elif key == Qt.Key.Key_Down:
            if modifiers & Qt.KeyboardModifier.AltModifier:
                if self._nudge_marker(config.FRAME_STEP * config.LARGE_STEP_MULTIPLIER):
                    self.window.markers_widget.update()
            else:
                self.playback.step_by_frames(config.FRAME_STEP * config.LARGE_STEP_MULTIPLIER)
                self.pending_num = None  # clear pending on movement

        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Minus):
            factor = 1.1 if key == Qt.Key.Key_Plus else 0.9
            new_rate = self.playback.change_playback_rate(factor)
            self.window.speed_label.setText(f"{new_rate}x")

        elif key == Qt.Key.Key_Enter:
            new_rate = self.playback.change_playback_rate(-1)  # reset speed
            self.window.speed_label.setText(f"{new_rate}x")

        elif key in config.MARKER_KEYS:
            num = key - Qt.Key.Key_0
            if self.delicate_mode:
                self.pending_num = num
            else:
                if self.events.add_marker(num, self.playback.get_current_frame()):
                    self.window.markers_widget.update()
                    self.window.update_current_marker_label(self.playback.get_current_frame())

        elif key == Qt.Key.Key_D and modifiers == Qt.KeyboardModifier.ControlModifier:
            self.toggle_delicate_mode()

        elif key == Qt.Key.Key_Z and modifiers == Qt.KeyboardModifier.ControlModifier:
            self.events.undo()
            self.window.markers_widget.update()

        elif key == Qt.Key.Key_Z and modifiers == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            self.events.redo()
            self.window.markers_widget.update()

        elif key == Qt.Key.Key_S and modifiers == Qt.KeyboardModifier.ControlModifier:
            self.window.save_event()

        elif key == Qt.Key.Key_F12:
            self.window.save_screenshot()

    def jump_to_adjacent_marker(self, forward: bool):
        all_frames = self.events.get_all_marker_frames()
        if not all_frames:
            return
        
        current_frame = self.playback.get_current_frame()
        
        if forward:
            targets = [f for f in all_frames if f > current_frame]
            if targets:
                self.playback.jump_to_frame(min(targets))
        else:
            targets = [f for f in all_frames if f < current_frame]
            if targets:
                self.playback.jump_to_frame(max(targets))

    def toggle_delicate_mode(self):
        self.delicate_mode = not self.delicate_mode
        self.pending_num = None
        status = 'ON' if self.delicate_mode else 'OFF'
        print(f"Combo marking mode {status}")
        self.window.delicate_label.setText(f"Combo Mark: {status}")

    def _nudge_marker(self, frame_delta: int) -> bool:
        """Finds a marker at the current frame and moves it by the delta."""
        current_frame = self.playback.get_current_frame()

        # find which marker type is at the current frame
        target_mtype = None
        for mtype, frames in self.events.markers.items():
            if current_frame in frames:
                target_mtype = mtype
                break
        
        if not target_mtype:
            return False  # no marker to nudge

        frames = self.events.markers[target_mtype]
        try:
            index = frames.index(current_frame)
        except ValueError:
            return False

        # define bounds to prevent crossing adjacent markers of the same type
        lower_bound = frames[index - 1] + 1 if index > 0 else 0
        upper_bound = frames[index + 1] - 1 if index < len(frames) - 1 else float('inf')

        # calculate and clamp the new frame position
        new_frame = int(max(lower_bound, min(current_frame + frame_delta, upper_bound)))

        if new_frame == current_frame:
            return False  # no change occurred

        # update the frame, sort the list, and log the action for undo
        frames[index] = new_frame
        frames.sort()
        
        # update all matching entries in undo stack
        for uidx, action_tuple in enumerate(self.events.undo_stack):
            if len(action_tuple) == 3:  # add/remove actions
                action, etype, uframe = action_tuple
                if etype == target_mtype and uframe == current_frame:
                    self.events.undo_stack[uidx] = (action, etype, new_frame)
            elif len(action_tuple) == 4:  # move actions
                action, etype, old_frame, uframe = action_tuple
                if etype == target_mtype and uframe == current_frame:
                    self.events.undo_stack[uidx] = (action, etype, old_frame, new_frame)
        
        # add new move action
        self.events.undo_stack.append(('move', target_mtype, current_frame, new_frame))
        self.events.redo_stack.clear()
        
        print(f"Nudged marker {target_mtype} from {current_frame} to {new_frame}")
        return True
    
    def _get_shots_dir(self) -> Path:
        sd = Path(__file__).parent / 'shots'
        sd.mkdir(exist_ok=True)
        return sd