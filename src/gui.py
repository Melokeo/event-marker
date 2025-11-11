"""
An event marker that allows you to preview frames much smoother than
previous MATLAB code.

This is a refactored version with improved maintainability.

Requirements: PyQt6

Playback controls:
   - ←→ steps STEP numbers of frame (default STEP = 1 frame)
   - ↑↓ steps LARGE_STEP_MULTIPLIER*STEP of frame
   - space for play/pause
   - numpad +- adjust playback speed by 1.1x/0.9x
   - numpad Enter reset speed to 1x
       **speed changes sometimes have latency**
   - timeline is draggable

Marking controls:
   - 1~5 (above qwerty) sets marker at current timepoint
   - markers will appear above timeline, left click will jump
   - CTRL+Z undo, CTRL+SHIFT+Z redo
   - Marked events will be printed when the window closes

Contributed by: deepseek-r1, chatgpt-4o, Mel
Refactored: Gemini, Claude
Feb 2025
"""

import sys
import os
import re
import ast
import glob
import platform
import subprocess
import logging
from bisect import bisect_right
from pathlib import Path

from PyQt6.QtCore import (
    Qt, QUrl, QTime, QTimer, QEvent, QRectF, QPointF,
    QSettings, QSize, QPoint, pyqtSignal
)
from PyQt6.QtGui import QAction, QKeyEvent, QPainter, QColor, QTransform, QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSlider, QPushButton, QLabel, QLineEdit, QFileDialog,
    QSizePolicy, QMenu, QComboBox, QDialog
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoFrame

from marker_float import MarkerFloat
from event_manager import EventManager
from key_handler import KeyHandler
from cfg import config
from playback_controller import PlaybackController
from csv_window import CSVPlotWindow
from csv_analysis_window import CSVAnalysisWindow
from qivideo_widget import QIVideoWidget
from markers_widget import MarkersWidget
from cfg_window import ConfigWindow
from ol_logging import set_colored_logger

lg = set_colored_logger(__name__)
lg.setLevel(logging.DEBUG)

class VideoPlayer(QMainWindow):
    """Main application window, coordinates all other components."""
    marker_signal = pyqtSignal(str)

    def __init__(self, app: QApplication):
        super().__init__()
        self.setWindowTitle(config.WINDOW_TITLE)
        self.setGeometry(100, 100, 1420, 750)
        
        # core components
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        
        # business logic controllers
        self.event_manager = EventManager()
        self.playback_controller = PlaybackController(self.media_player)
        self.key_handler = KeyHandler(self, self.playback_controller, self.event_manager)

        # ui components
        self.video_widget = QIVideoWidget()
        self.media_player.setVideoOutput(self.video_widget)
        self.markers_widget = MarkersWidget(self)
        self.csv_plot_win = None
        self.frame_timer = QTimer()
        self.marker_float = None
        if config.MARKER_FLOAT_ENABLED:
            self.marker_float = MarkerFloat(player=self)
        self.config_win = None

        self.is_slider_pressed = False
        self.frame_editing = False
        self.save_status = True
        self.fname = None

        # frame updater
        self._sorted_marker_events: list[tuple[int, str]] = []
        self._sorted_marker_frames: list[int] = [] # [frame] ascending, for bisect
        self._scan_idx: int = 0
        self._last_frame: int = 0

        self.init_ui()
        self.connect_signals()

        # load settings and last state
        self.settings = QSettings('mel.rnel', 'EventMarkerRefactored')
        self.resize(self.settings.value("window/size", QSize(1420, 750)))
        self.move(self.settings.value("window/pos", QPoint(100, 100)))
        
        # setup csv plot window if enabled
        self.csv_plot_win = CSVPlotWindow(self)
        if config.CSV_PLOT_ENABLED:
            self.csv_plot_win.show()
        else:
            self.csv_plot_win.hide()
        
        # show marker float if enabled
        if self.marker_float:
            self.marker_float.show()
            self.marker_float.raise_()
        
        self._set_float_window_pos()
        
        app.installEventFilter(self)

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(5, 0, 5, 0)
        layout.setSpacing(0)
        layout.addWidget(self.video_widget)

        # controls layout
        control_layout = QHBoxLayout()
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(5)

        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedSize(30, 30)
        control_layout.addWidget(self.play_btn)

        # slider and markers
        slider_container = QWidget()
        slider_layout = QVBoxLayout(slider_container)
        slider_layout.setContentsMargins(0, 0, 0, 0)
        slider_layout.setSpacing(0)
        slider_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.time_slider = QSlider(Qt.Orientation.Horizontal)
        self.time_slider.setMinimumHeight(25)
        slider_layout.addWidget(self.markers_widget)
        slider_layout.addWidget(self.time_slider)
        control_layout.addWidget(slider_container, 1)

        # info labels
        info_container = QWidget()
        info_layout = QVBoxLayout(info_container)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(2)
        info_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # top row
        top_row = QHBoxLayout()
        self.time_label = QLabel("00:00:00 / 00:00:00")
        self.frame_label = QLabel("Frame: 0")
        self.frame_input = QLineEdit()
        self.frame_input.setFixedWidth(100)
        self.frame_input.setVisible(False)
        self.speed_label = QLabel("1.0x")
        self.speed_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        top_row.addWidget(self.time_label)
        top_row.addWidget(self.frame_label)
        top_row.addWidget(self.frame_input)
        top_row.addWidget(self.speed_label)
        info_layout.addLayout(top_row)

        # bottom row
        bottom_row = QHBoxLayout()
        self.delicate_label = QLabel("Combo Mark: OFF")
        self.marker_label = QLabel("Marker: –")

        # set fixed height for bottom row labels to align them
        h = self.time_label.sizeHint().height()
        for lbl in (self.delicate_label, self.marker_label):
            lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            lbl.setFixedHeight(h)

        bottom_row.addWidget(self.delicate_label)
        bottom_row.addWidget(self.marker_label)
        info_layout.addLayout(bottom_row)

        control_layout.addWidget(info_container, 0)
        
        # finalize layout
        layout.addLayout(control_layout)
        self.init_menubar()

    def init_menubar(self):
        menubar = self.menuBar()
        
        # file menu
        file_menu = menubar.addMenu("File")
        open_action = QAction("Open new video", self)
        open_action.triggered.connect(self.open_file_dialog)
        file_menu.addAction(open_action)
        
        open_events_action = QAction("Read saved events", self)
        open_events_action.triggered.connect(self.load_events)
        file_menu.addAction(open_events_action)
        
        save_action = QAction("Save events", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_event)
        file_menu.addAction(save_action)
        
        save_as_action = QAction("Save events as", self)
        save_as_action.triggered.connect(self.save_event_as)
        file_menu.addAction(save_as_action)
        
        # workspace menu
        workspace_menu = menubar.addMenu("Workspace")
        
        # toggle marker float
        marker_float_action = QAction("Show Marker Float", self)
        marker_float_action.setCheckable(True)
        marker_float_action.setChecked(config.MARKER_FLOAT_ENABLED and self.marker_float is not None)
        marker_float_action.triggered.connect(self.toggle_marker_float)
        workspace_menu.addAction(marker_float_action)
        self.marker_float_action = marker_float_action
        
        # toggle csv plot
        csv_plot_action = QAction("Show CSV Plot", self)
        csv_plot_action.setCheckable(True)
        csv_plot_action.setChecked(config.CSV_PLOT_ENABLED)   # small problem here, this window is None at this point
        csv_plot_action.triggered.connect(self.toggle_csv_plot)
        workspace_menu.addAction(csv_plot_action)
        self.csv_plot_action = csv_plot_action

        # 
        csv_analysis_action = QAction("CSV Analysis & Peaks", self)
        csv_analysis_action.triggered.connect(self.open_csv_analysis)
        workspace_menu.addAction(csv_analysis_action)

        # settings
        settings_menu = menubar.addMenu("Settings")
        edit_cfg_action = QAction("Edit Config...", self)
        # edit_cfg_action.setEnabled(False)   # .. until implemented
        edit_cfg_action.triggered.connect(self.open_config_window)
        settings_menu.addAction(edit_cfg_action)

    def connect_signals(self):
        # playback signals
        self.play_btn.clicked.connect(self.playback_controller.toggle_play_pause)
        self.media_player.playbackStateChanged.connect(self.on_playback_state_changed)
        
        # position/duration signals
        self.frame_timer.timeout.connect(self.update_position)
        self.media_player.positionChanged.connect(self.update_position)
        self.media_player.durationChanged.connect(self.update_duration)
        
        # slider signals
        self.time_slider.sliderPressed.connect(self.slider_pressed)
        self.time_slider.sliderReleased.connect(self.slider_released)
        self.time_slider.sliderMoved.connect(lambda pos: self.media_player.setPosition(int(pos)))

        # widget-to-controller signals
        self.markers_widget.jumpToFrame.connect(self.playback_controller.jump_to_frame)
        self.frame_input.returnPressed.connect(self.jump_to_frame_from_input)
        self.frame_label.mouseDoubleClickEvent = self.enable_frame_edit

        # marker float updater
        if self.marker_float:
            self.marker_signal.connect(self.marker_float.receive_string)

    # event handlers and slots
    
    def on_playback_state_changed(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.play_btn.setText("⏸")
            self.frame_timer.start(int(1000 / config.PLAYBACK_FPS))
        else:
            self.play_btn.setText("▶")
            self.frame_timer.stop()
            
    def update_position(self):
        if not self.is_slider_pressed:
            self.time_slider.setValue(self.media_player.position())
        
        pos_ms, dur_ms = self.media_player.position(), self.media_player.duration()
        current_time = QTime(0, 0, 0).addMSecs(pos_ms).toString("HH:mm:ss")
        duration = QTime(0, 0, 0).addMSecs(dur_ms).toString("HH:mm:ss")
        self.time_label.setText(f"{current_time} / {duration}")
        
        frame = self.playback_controller.get_current_frame()
        self.frame_label.setText(f"Frame: {frame}")
        self.update_current_marker_label(frame)

        # emit MarkerFloat events (not when scrubbing/paused)
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState and not self.is_slider_pressed:
            self.consume_passed_markers(frame)
        else:
            # keep pointer in sync quietly while scrubbing/paused
            if self._sorted_marker_frames:
                self._scan_idx = bisect_right(self._sorted_marker_frames, frame)
            self._last_frame = frame

    def update_duration(self, duration):
        self.time_slider.setRange(0, duration)

    def keyPressEvent(self, event: QKeyEvent):
        self.key_handler.handle_key_press(event)
    
    def eventFilter(self, obj, event):
        # don't intercept keys when CSV analysis window is active and focused
        if hasattr(self, 'csv_analysis_win') and self.csv_analysis_win and self.csv_analysis_win.isVisible():
            focused_widget = QApplication.focusWidget()
            if focused_widget and focused_widget.window() == self.csv_analysis_win:
                return False
        
        if event.type() == QEvent.Type.KeyPress and not self.frame_editing:
            self.keyPressEvent(event)
            return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        self.media_player.stop()
        lg.info(f"Recorded Events: {dict(self.event_manager.markers)}")
        self.save_event()
        
        self.settings.setValue("window/size", self.size())
        self.settings.setValue("window/pos", self.pos())
        self.settings.sync()
        
        # save and close child win
        if self.csv_plot_win and self.csv_plot_win.isVisible():
            self.settings.setValue("csv_window/pos", self.csv_plot_win.pos())
            self.settings.setValue("csv_window/size", self.csv_plot_win.size())
            self.csv_plot_win.close()

        if self.marker_float and self.marker_float.isVisible():
            self.settings.setValue("marker_float/pos", self.marker_float.pos())
            self.settings.setValue("marker_float/size", self.marker_float.size())
            self.marker_float.close()
        
        if self.csv_plot_win:
            self.csv_plot_win.close()
        if self.marker_float:
            self.marker_float.close()

        super().closeEvent(event)

    def slider_pressed(self):
        self.is_slider_pressed = True
        
    def slider_released(self):
        self.is_slider_pressed = False
        target_frame = round(self.time_slider.value() * config.VIDEO_FPS_ORIGINAL / 1000)
        self.playback_controller.jump_to_frame(target_frame)

    # file i/o

    def open_file_dialog(self):
        last_path = self.settings.value('Path/last_vid_path', config.DEFAULT_WORK_PATH)
        file_name, _ = QFileDialog.getOpenFileName(self, "Select video", last_path, "Video (*.mp4 *.avi *.mkv *.mov)")
        if file_name:
            self.load_video(file_name)

    def load_video(self, file_path):
        if self.fname:  # save previous work
            self.save_event()
        
        self.event_manager.clear()
        self.markers_widget.update()
        self.fname = file_path
        
        self.media_player.setSource(QUrl.fromLocalFile(file_path))
        self.setWindowTitle(f"{config.WINDOW_TITLE} - {os.path.basename(file_path)}")
        self.play_btn.setEnabled(True)
        self.settings.setValue('Path/last_vid_path', os.path.dirname(file_path))

        self._rebuild_marker_scan()

        if config.AUTO_SEARCH_EVENTS:
            self.load_events_silent()

    def load_events(self):
        """manually load events file"""
        last_path = self.settings.value('Path/evt_dir', os.path.dirname(self.fname) if self.fname else config.DEFAULT_WORK_PATH)
        file_name, _ = QFileDialog.getOpenFileName(self, "Select event file", last_path, "Text file (*.txt)")
        if not file_name:
            return
        self._read_event_file(file_name)
        # update evt_dir when user manually opens an event file
        self.settings.setValue('Path/evt_dir', os.path.dirname(file_name))

    def _read_event_file(self, file_name: str):
        try:
            with open(file_name, 'r') as f:
                data = ast.literal_eval(f.read())
                self.event_manager.clear()
                self.event_manager.markers.update({k: sorted(v) for k, v in data.items()})
                self.markers_widget.update()
                self._rebuild_marker_scan()
                self.save_status = True
                lg.info(f"Loaded events from {file_name}")
        except Exception as e:
            lg.error(f"Error loading event file: {e}")

    def load_events_silent(self):
        """called upon new video opens, search for event in evt_dir folder"""
        if not self.fname:
            return
        
        # use evt_dir for auto-loading
        last_path = self.settings.value('Path/evt_dir', None)
        if not last_path or not os.path.exists(last_path):
            return
            
        txts = glob.glob(os.path.join(last_path, 'event-*.txt'))
        m = re.search(r'2025\d{4}-(Pici|Fusillo)-(TS|BBT|Brinkman|Pull).*?-\d{1,2}', self.fname, re.IGNORECASE)
        if not m:
            return
        vid_base = m.group()
        lg.debug(f'Matched task format {vid_base}')
        
        for f in txts:
            if vid_base in os.path.basename(f):
                lg.info(f'Auto load event {f}')
                self._read_event_file(f)
                return

    def save_event(self):
        if not any(self.event_manager.markers.values()):
            lg.info("Nothing to save.")
            return

        if not self.fname:
            lg.warning("Cannot save, no video file is loaded.")
            return

        # check if content changed
        if self.save_status and len(self.event_manager.undo_stack) + len(self.event_manager.redo_stack) == 0:
            lg.info("Nothing new to save.")
            return

        try:
            m = re.search(r'2025\d{4}-(Pici|Fusillo)-(TS|BBT|Brinkman|Pull).*?-\d{1,2}', self.fname, re.IGNORECASE)
            fnm = m.group() if m else os.path.splitext(os.path.basename(self.fname))[0]

            # use evt_save_path for saving
            base_path = self.settings.value(
                'Path/evt_save_path',
                os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Marked Events'),
                type=str
            )
            os.makedirs(base_path, exist_ok=True)

            file_path = os.path.join(base_path, f'event-{fnm}')
            
            # check if file exists with same content
            while os.path.exists(file_path+'.txt'):
                try:
                    with open(file_path+'.txt', 'r') as f:
                        existing_data = ast.literal_eval(f.read())
                    if existing_data == dict(self.event_manager.markers):
                        lg.debug(f'Events unchanged, not saving to {file_path}')
                        self.save_status = True
                        self.event_manager.undo_stack.clear()
                        self.event_manager.redo_stack.clear()
                        return
                    else:
                        file_path += '(new)'
                except:
                    break  # if can't read, just overwrite
            
            file_path += '.txt'
            # save the file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(str(dict(self.event_manager.markers)))

            lg.info(f'Successfully saved events to {file_path}')
            self.save_status = True
            self.event_manager.undo_stack.clear()
            self.event_manager.redo_stack.clear()

        except Exception as e:
            lg.error(f'Error when saving events; please copy data manually!!\n{e}')
            lg.error(f"Recorded Events: {dict(self.event_manager.markers)}")

        try:
            # open file in system viewer
            if platform.system() == 'Windows':
                os.startfile(file_path)
            elif platform.system() == 'Darwin':
                subprocess.call(['open', file_path])
            else:
                subprocess.call(['xdg-open', file_path])
        except OSError as e:
            lg.warning(f'Failed to open saved event txt: {e}')        

    def save_event_as(self):
        if not any(self.event_manager.markers.values()):
            lg.info('Nothing to save.')
            return

        if not self.fname:
            lg.warning("Cannot save, no video file is loaded.")
            return

        # default filename
        base_name = os.path.splitext(os.path.basename(self.fname))[0]
        default_name = f'event-{base_name}.txt'

        last_save_path = self.settings.value('Path/evt_save_path', os.path.dirname(self.fname))
        default_path = os.path.join(last_save_path, default_name)

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Events As", default_path, "Text Files (*.txt);;All Files (*)"
        )

        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(str(dict(self.event_manager.markers)))

                lg.info(f'Successfully saved events to {file_path}')
                
                # update evt_save_path when user saves to a new location
                self.settings.setValue('Path/evt_save_path', os.path.dirname(file_path))
                self.save_status = True

            except Exception as e:
                lg.warning(f'Error when saving events as new file; please copy data manually!!\n{e}')
                lg.warning(f"Recorded Events: {dict(self.event_manager.markers)}")

    # frame editing

    def enable_frame_edit(self, event):
        self.frame_editing = True
        self.frame_label.setVisible(False)
        self.frame_input.setVisible(True)
        self.frame_input.setText(str(self.playback_controller.get_current_frame()))
        self.frame_input.setFocus()
        self.media_player.pause()

    def jump_to_frame_from_input(self):
        try:
            frame_text = self.frame_input.text()
            if frame_text == '':
                # empty input resumes playback
                self.media_player.play()
            else:
                frame_number = int(frame_text)
                self.playback_controller.jump_to_frame(frame_number)
        except (ValueError, TypeError):
            lg.warning("Invalid frame number.")
        finally:
            self.frame_editing = False
            self.frame_input.setVisible(False)
            self.frame_label.setVisible(True)
            self.setFocus()
            
    def update_current_marker_label(self, frame):
        name = None
        for key, frames in self.event_manager.markers.items():
            if frame in frames:
                name = key
                break
        txt = f"Marker: {name}" if name else "Marker: –"
        if self.marker_label.text() != txt:
            self.marker_label.setText(txt)
        if name and self.marker_float:
            self.marker_signal.emit(str(name))

    # workspace menu handlers
    
    def toggle_marker_float(self, checked):
        if checked:
            if not self.marker_float:
                self.marker_float = MarkerFloat(player=self)
                self.marker_signal.connect(self.marker_float.receive_string)
            self.marker_float.show()
        else:
            if self.marker_float:
                self.marker_float.hide()
    
    def toggle_csv_plot(self, checked):
        if checked:
            if not self.csv_plot_win:
                self.csv_plot_win = CSVPlotWindow(self)
            self.csv_plot_win.show()
        else:
            if self.csv_plot_win:
                self.csv_plot_win.hide()
        self._set_float_window_pos()
    
    def _set_float_window_pos(self):
        if self.csv_plot_win and self.csv_plot_win.isVisible():
            csv_pos = self.settings.value("csv_window/pos", QPoint(self.x() + 20, self.y() + self.height() - 170))
            csv_size = self.settings.value("csv_window/size", self.csv_plot_win.size())
            self.csv_plot_win.move(csv_pos)
            self.csv_plot_win.resize(csv_size)
        if self.marker_float and self.marker_float.isVisible():
            marker_pos = self.settings.value("marker_float/pos", QPoint(self.x() - 50, self.y() + 50))
            marker_size = self.settings.value("marker_float/size", self.marker_float.size())
            self.marker_float.move(marker_pos)
            self.marker_float.resize(marker_size)

    def open_config_window(self):
        """Opens the modal configuration dialog."""
        if not self.config_win:
            self.config_win = ConfigWindow(self)
        
        # The exec() call makes the dialog modal.
        # It returns a result (Accepted or Rejected) when closed.
        result = self.config_win.exec()

        if result == QDialog.DialogCode.Accepted:
            print("Configuration saved. Applying changes to main window...")
            self.on_config_changed()
        else:
            print("Configuration changes cancelled.")
        
        # Since the dialog is closed, we can dereference it.
        self.config_win = None

    def open_csv_analysis(self):
        """opens the CSV analysis window"""
        if not hasattr(self, 'csv_analysis_win') or self.csv_analysis_win is None:
            self.csv_analysis_win = CSVAnalysisWindow(self)
        self.csv_analysis_win.show()
        self.csv_analysis_win.raise_()

    def on_config_changed(self):
        """Updates the main window UI after config changes are saved."""
        self.setWindowTitle(config.WINDOW_TITLE)
        # self.key_handler.update_marker_keys() #TODO sth like this
        self.markers_widget.update()
        # You can add more UI updates here if needed, e.g., for toggling plots
        self.marker_float_action.setChecked(config.MARKER_FLOAT_ENABLED)
        self.toggle_marker_float(config.MARKER_FLOAT_ENABLED)

        self.csv_plot_action.setChecked(config.CSV_PLOT_ENABLED)
        self.toggle_csv_plot(config.CSV_PLOT_ENABLED)

    def _rebuild_marker_scan(self):
        items: list[tuple[int, str]] = []
        for name, frames in self.event_manager.markers.items():
            for f in frames:
                items.append((int(f), str(name)))
        items.sort(key=lambda t: t[0])
        self._sorted_marker_events = items
        self._sorted_marker_frames = [f for f, _ in items]
        cur = self.playback_controller.get_current_frame()
        self._scan_idx = bisect_right(self._sorted_marker_frames, cur)  # first > cur
        self._last_frame = cur

    def consume_passed_markers(self, current_frame: int):
        # backward seek: just reposition pointer, no emit
        if current_frame < self._last_frame:
            self._scan_idx = bisect_right(self._sorted_marker_frames, current_frame)
            self._last_frame = current_frame
            return
        # forward: emit every marker crossed since last frame
        while self._scan_idx < len(self._sorted_marker_events) and self._sorted_marker_events[self._scan_idx][0] <= current_frame:
            _, name = self._sorted_marker_events[self._scan_idx]
            if self.marker_float:           # MarkerFloat wired via self.marker_signal
                self.marker_signal.emit(name)
            self._scan_idx += 1
        self._last_frame = current_frame

    def save_screenshot(self):
        try:
            shots = Path(__file__).resolve().parent / "shots" 
            shots.mkdir(parents=True, exist_ok=True)

            base = os.path.splitext(os.path.basename(self.fname or "untitled"))[0]
            frame = self.playback_controller.get_current_frame()
            out = shots / f"{base}_{frame:05d}.jpg"

            # temporarily pause to ensure frame is ready
            was_playing = self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            if was_playing:
                self.media_player.pause()

            # get the video sink and current frame
            video_sink = self.media_player.videoSink()
            if video_sink:
                current_frame = video_sink.videoFrame()
                if current_frame.isValid():
                    # convert video frame to QImage then save
                    image = current_frame.toImage()
                    if not image.isNull():
                        ok = image.save(str(out), "JPG", quality=95)
                        lg.info(f"{'Saved' if ok else 'Failed'} screenshot: {out}")
                    else:
                        lg.warning("Failed to convert video frame to image")
                else:
                    lg.warning("No valid video frame available")
            else:
                lg.warning("No video sink available")

            # resume playback if it was playing
            if was_playing:
                self.media_player.play()

        except Exception as e:
            lg.error(f"Screenshot error: {e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    player = VideoPlayer(app=app)
    player.show()
    sys.exit(app.exec())