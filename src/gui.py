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
from pathlib import Path
from collections import defaultdict
from functools import partial
from typing import Optional, Any
import logging

import numpy as np
import csv
import yaml

from PyQt6.QtCore import (
    Qt, QUrl, QTime, QTimer, QEvent, QRectF, QPointF,
    QSettings, QSize, QPoint, pyqtSignal
)
from PyQt6.QtGui import QAction, QKeyEvent, QPainter, QColor, QTransform, QFont
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSlider, QPushButton, QLabel, QLineEdit, QFileDialog,
    QSizePolicy, QMenu, QComboBox
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

from marker_float import MarkerFloat
from event_manager import EventManager
from key_handler import KeyHandler
from cfg import config
from playback_controller import PlaybackController
from csv_window import CSVPlotWindow
from qivideo_widget import QIVideoWidget
from markers_widget import MarkersWidget

class VideoPlayer(QMainWindow):
    """Main application window, coordinates all other components."""
    marker_signal = pyqtSignal(str)

    def __init__(self):
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

        # float marker window
        self.marker_float = None
        if config.MARKER_FLOAT_ENABLED:
            self.marker_float = MarkerFloat()

        self.is_slider_pressed = False
        self.frame_editing = False
        self.save_status = True
        self.fname = None

        self.init_ui()
        self.connect_signals()

        # load settings and last state
        self.settings = QSettings('mel.rnel', 'EventMarkerRefactored')
        self.resize(self.settings.value("window/size", QSize(1420, 750)))
        self.move(self.settings.value("window/pos", QPoint(100, 100)))
        
        # setup csv plot window if enabled
        if config.CSV_PLOT_ENABLED:
            self.csv_plot_win = CSVPlotWindow(self)
            self.csv_plot_win.move(self.x() + 20, self.y() + self.height() - 170)
            self.csv_plot_win.show()
        
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

        # show marker float if enabled
        if self.marker_float:
            self.marker_float.show()

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
        csv_plot_action.setChecked(config.CSV_PLOT_ENABLED and self.csv_plot_win is not None)
        csv_plot_action.triggered.connect(self.toggle_csv_plot)
        workspace_menu.addAction(csv_plot_action)
        self.csv_plot_action = csv_plot_action

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

    def update_duration(self, duration):
        self.time_slider.setRange(0, duration)

    def keyPressEvent(self, event: QKeyEvent):
        self.key_handler.handle_key_press(event)
    
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and not self.frame_editing:
            self.keyPressEvent(event)
            return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        self.media_player.stop()
        print("Recorded Events:", dict(self.event_manager.markers))
        self.save_event()
        
        self.settings.setValue("window/size", self.size())
        self.settings.setValue("window/pos", self.pos())
        self.settings.sync()
        
        # close child windows
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
                self.save_status = True
                print(f"Loaded events from {file_name}")
        except Exception as e:
            print(f"Error loading event file: {e}")

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
        print(f'Matched task format {vid_base}')
        
        for f in txts:
            if vid_base in os.path.basename(f):
                print(f'Auto load event {f}')
                self._read_event_file(f)
                return

    def save_event(self):
        if not any(self.event_manager.markers.values()):
            print("Nothing to save.")
            return

        if not self.fname:
            print("Cannot save, no video file is loaded.")
            return

        # check if content changed
        if self.save_status and len(self.event_manager.undo_stack) + len(self.event_manager.redo_stack) == 0:
            print("Nothing new to save.")
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

            file_path = os.path.join(base_path, f'event-{fnm}.txt')
            
            # check if file exists with same content
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r') as f:
                        existing_data = ast.literal_eval(f.read())
                    if existing_data == dict(self.event_manager.markers):
                        print(f'Events unchanged, not saving to {file_path}')
                        self.save_status = True
                        self.event_manager.undo_stack.clear()
                        self.event_manager.redo_stack.clear()
                        return
                except:
                    pass  # if can't read, just overwrite
            
            # save the file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(str(dict(self.event_manager.markers)))

            print(f'Successfully saved events to {file_path}')
            self.save_status = True
            self.event_manager.undo_stack.clear()
            self.event_manager.redo_stack.clear()

            # open file in system viewer
            if platform.system() == 'Windows':
                os.startfile(file_path)
            elif platform.system() == 'Darwin':
                subprocess.call(['open', file_path])
            else:
                subprocess.call(['xdg-open', file_path])

        except Exception as e:
            print(f'Error when saving events; please copy data manually!!\n{e}')
            print("Recorded Events:", dict(self.event_manager.markers))

    def save_event_as(self):
        if not any(self.event_manager.markers.values()):
            print('Nothing to save.')
            return

        if not self.fname:
            print("Cannot save, no video file is loaded.")
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

                print(f'Successfully saved events to {file_path}')
                
                # update evt_save_path when user saves to a new location
                self.settings.setValue('Path/evt_save_path', os.path.dirname(file_path))
                self.save_status = True

            except Exception as e:
                print(f'Error when saving events as new file; please copy data manually!!\n{e}')
                print("Recorded Events:", dict(self.event_manager.markers))

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
            print("Invalid frame number.")
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
                self.marker_float = MarkerFloat()
                self.marker_signal.connect(self.marker_float.receive_string)
            self.marker_float.show()
        else:
            if self.marker_float:
                self.marker_float.hide()
    
    def toggle_csv_plot(self, checked):
        if checked:
            if not self.csv_plot_win:
                self.csv_plot_win = CSVPlotWindow(self)
                self.csv_plot_win.move(self.x() + 20, self.y() + self.height() - 170)
            self.csv_plot_win.show()
        else:
            if self.csv_plot_win:
                self.csv_plot_win.hide()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    player = VideoPlayer()
    player.show()
    sys.exit(app.exec())