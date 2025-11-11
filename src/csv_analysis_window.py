"""
CSV Analysis Tool - Peak detection and batch screenshot functionality
"""

import os
import csv
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any
from dataclasses import dataclass
import time

from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QObject, QEventLoop
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QPushButton, QLabel, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QFileDialog, QTextEdit, QProgressBar, QTabWidget, QWidget,
    QCheckBox, QSlider, QSplitter, QTableWidget, QTableWidgetItem,
    QMessageBox, QScrollArea, QApplication,
)

try:
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    from scipy.signal import find_peaks, savgol_filter, resample
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    print("Warning: scipy not available, some features will be limited")

from cfg import config
from ol_logging import set_colored_logger

lg = set_colored_logger(__name__)

@dataclass
class PeakConfig:
    height: Optional[float] = None
    threshold: Optional[float] = None
    distance: Optional[int] = None
    prominence: Optional[float] = None
    width: Optional[float] = None
    rel_height: float = 0.5

class ScreenshotWorker(QObject):
    """worker thread for batch screenshot operations"""
    progress = pyqtSignal(int, int)  # current, total
    finished = pyqtSignal()
    error = pyqtSignal(str)
    
    def __init__(self, main_window, csv_frames: List[int], csv_fps: float, 
                 prefix: str = "peak", time_offset: float = 0.0):
        super().__init__()
        self.main_window = main_window
        self.csv_frames = csv_frames  # CSV sample indices
        self.csv_fps = csv_fps
        self.prefix = prefix
        self.should_stop = False
        self.video_fps = config.VIDEO_FPS_ORIGINAL
        self.time_offset_frames = time_offset
    
    def run(self):
        try:
            total = len(self.csv_frames)
            for i, csv_frame in enumerate(self.csv_frames):
                if self.should_stop:
                    break
                
                # convert CSV frame to video frame
                target_video_frame = self._csv_to_video_frame(csv_frame)
                
                # jump and wait for actual frame change
                self._jump_and_wait_for_frame(target_video_frame)
                
                # save with both CSV and video frame info
                self._save_frame_screenshot(csv_frame, target_video_frame)
                
                self.progress.emit(i + 1, total)
            
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

    def _jump_and_wait_for_frame(self, target_frame: int, max_wait_ms: int = 2000):
        was_playing = self.main_window.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if was_playing:
            self.main_window.media_player.pause()

        self.main_window.playback_controller.jump_to_frame(target_frame)

        # First wait for decoder to deliver the new frame
        landed = self._wait_for_frame_landed(target_frame, timeout_ms=max_wait_ms)

        if not landed:
            # Fallback: small poll in case frame lands right after timeout
            start = time.time()
            while (time.time() - start) < 0.25:
                QApplication.processEvents()
                if abs(self.main_window.playback_controller.get_current_frame() - target_frame) <= 1:
                    break
                time.sleep(0.01)

        # tiny settle to ensure QImage mapping succeeds
        time.sleep(0.03)
    
    def stop(self):
        self.should_stop = True
    
    def _csv_to_video_frame(self, csv_index: int) -> int:
        """convert CSV sample index to video frame with offset"""
        csv_time_sec = csv_index / self.csv_fps
        video_frame = int(csv_time_sec * self.video_fps)
        return video_frame + int(self.time_offset_frames)
    
    def _save_frame_screenshot(self, csv_frame: int, video_frame: int):
        """save screenshot with CSV and video frame info"""
        try:
            # use same shots directory as F12 screenshots
            shots = Path(__file__).resolve().parent / "shots"
            shots.mkdir(parents=True, exist_ok=True)
            
            base = os.path.splitext(os.path.basename(self.main_window.fname or "untitled"))[0]
            out = shots / f"{base}_{self.prefix}_csv{csv_frame:05d}_vid{video_frame:05d}.jpg"
            
            # get video frame and save
            video_sink = self.main_window.media_player.videoSink()
            if video_sink:
                vf = video_sink.videoFrame()
                if vf.isValid():
                    img = vf.toImage()
                    if not img.isNull():
                        img.save(str(out), "JPG", quality=95)
                    else:
                        lg.warning("Frame landed but QImage is null; skipping save")
                else:
                    lg.warning("VideoFrame invalid; skipping save")
            else:
                lg.warning("No video sink available")

        except Exception as e:
            lg.warning(f"Failed to save CSV frame {csv_frame} (video {video_frame}): {e}")
    
    def _wait_for_frame_landed(self, target_frame: int, timeout_ms: int = 2000) -> bool:
        """Block until QVideoSink emits a *new* frame that corresponds to target_frame."""
        vs = self.main_window.media_player.videoSink()
        if not vs:
            return False

        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)

        def on_frame_changed(_qvf):
            cur = self.main_window.playback_controller.get_current_frame()
            # tolerate off-by-one due to NTSC rounding
            if abs(cur - target_frame) <= 1:
                loop.quit()

        vs.videoFrameChanged.connect(on_frame_changed)
        timer.start(timeout_ms)
        loop.exec()
        try:
            vs.videoFrameChanged.disconnect(on_frame_changed)
        except Exception:
            pass
        return timer.isActive()  # True if quit before timeout

class CSVAnalysisWindow(QDialog):
    """comprehensive CSV analysis tool with peak detection and batch screenshots"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.setWindowTitle("CSV Analysis & Peak Detection")
        self.setGeometry(200, 200, 1200, 800)
        
        # data storage
        self.csv_data: Optional[pd.DataFrame] = None
        self.video_fps: float = config.VIDEO_FPS_ORIGINAL
        self.csv_fps: Optional[float] = None
        self.selected_column: Optional[str] = None
        self.peaks: List[int] = []
        self.peak_config = PeakConfig()
        self.time_offset_frames = 0.0
        
        # registration state
        self.registration_pairs: List[Tuple[int, int]] = []  # (csv_frame, video_frame)
        self.registration_mode = False
        self.refinement_mode = False
        self.current_refinement_idx = 0
        self.refinement_peaks: List[int] = []
        
        # worker thread
        self.screenshot_worker = None
        self.worker_thread = None
        
        if not HAS_SCIPY:
            QMessageBox.warning(self, "Missing Dependencies", 
                              "scipy is required for advanced peak detection. "
                              "Install with: pip install scipy matplotlib")

        self.init_ui()
        self.setup_connections()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # main splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)
        
        # left panel - controls
        control_panel = self.create_control_panel()
        splitter.addWidget(control_panel)
        
        # right panel - plot and data
        right_panel = self.create_right_panel()
        splitter.addWidget(right_panel)
        
        splitter.setSizes([400, 800])
        
        # bottom progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
    def create_control_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # file loading section
        file_group = QGroupBox("CSV File")
        file_layout = QVBoxLayout(file_group)
        
        file_btn_layout = QHBoxLayout()
        self.load_csv_btn = QPushButton("Load CSV")
        self.csv_file_label = QLabel("No file loaded")
        file_btn_layout.addWidget(self.load_csv_btn)
        file_btn_layout.addWidget(self.csv_file_label, 1)
        file_layout.addLayout(file_btn_layout)
        
        # fps and frame matching
        fps_layout = QHBoxLayout()
        fps_layout.addWidget(QLabel("CSV Sample Rate:"))
        self.csv_fps_combo = QComboBox()
        self.csv_fps_combo.setEditable(True)
        self.csv_fps_combo.addItems([
            "30.00", "59.94", "60.00", "119.88", "120.00", "1000.00"
        ])
        self.csv_fps_combo.setCurrentText("119.88")
        fps_layout.addWidget(self.csv_fps_combo)

        self.auto_resample_cb = QCheckBox("Auto resample to video FPS")
        self.auto_resample_cb.setChecked(False)
        fps_layout.addWidget(self.auto_resample_cb)
        file_layout.addLayout(fps_layout)

        self.frame_match_label = QLabel("Frame count: Not loaded")
        file_layout.addWidget(self.frame_match_label)

        self.resample_info_label = QLabel("")
        self.resample_info_label.setStyleSheet("color: #666; font-size: 10px;")
        file_layout.addWidget(self.resample_info_label)
        
        layout.addWidget(file_group)
        
        # column selection
        col_group = QGroupBox("Column Selection")
        col_layout = QVBoxLayout(col_group)
        
        self.column_combo = QComboBox()
        col_layout.addWidget(self.column_combo)
        
        self.stats_label = QLabel("Select column for statistics")
        col_layout.addWidget(self.stats_label)
        
        layout.addWidget(col_group)
        
        # peak detection parameters
        peak_group = QGroupBox("Peak Detection")
        peak_layout = QGridLayout(peak_group)
        
        row = 0
        peak_layout.addWidget(QLabel("Min Height:"), row, 0)
        self.height_spin = QDoubleSpinBox()
        self.height_spin.setRange(-999999, 999999)
        self.height_spin.setDecimals(3)
        self.height_checkbox = QCheckBox("Enable")
        peak_layout.addWidget(self.height_checkbox, row, 1)
        peak_layout.addWidget(self.height_spin, row, 2)
        
        row += 1
        peak_layout.addWidget(QLabel("Prominence:"), row, 0)
        self.prominence_spin = QDoubleSpinBox()
        self.prominence_spin.setRange(0, 999999)
        self.prominence_spin.setDecimals(3)
        self.prominence_checkbox = QCheckBox("Enable")
        peak_layout.addWidget(self.prominence_checkbox, row, 1)
        peak_layout.addWidget(self.prominence_spin, row, 2)
        
        row += 1
        peak_layout.addWidget(QLabel("Min Distance:"), row, 0)
        self.distance_spin = QSpinBox()
        self.distance_spin.setRange(1, 10000)
        self.distance_spin.setValue(10)
        self.distance_checkbox = QCheckBox("Enable")
        peak_layout.addWidget(self.distance_checkbox, row, 1)
        peak_layout.addWidget(self.distance_spin, row, 2)
        
        row += 1
        peak_layout.addWidget(QLabel("Min Width:"), row, 0)
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(0.1, 1000)
        self.width_spin.setDecimals(1)
        self.width_checkbox = QCheckBox("Enable")
        peak_layout.addWidget(self.width_checkbox, row, 1)
        peak_layout.addWidget(self.width_spin, row, 2)
        
        row += 1
        self.detect_peaks_btn = QPushButton("Detect Peaks")
        peak_layout.addWidget(self.detect_peaks_btn, row, 0, 1, 3)
        
        row += 1
        self.peaks_found_label = QLabel("Peaks found: 0")
        peak_layout.addWidget(self.peaks_found_label, row, 0, 1, 3)
        
        layout.addWidget(peak_group)
        
        # registration section
        reg_group = QGroupBox("Smart Registration")
        reg_layout = QVBoxLayout(reg_group)
        
        # main controls
        reg_controls = QHBoxLayout()
        self.start_reg_btn = QPushButton("Start Registration")
        self.clear_reg_btn = QPushButton("Clear")
        self.apply_reg_btn = QPushButton("Apply")
        self.apply_reg_btn.setEnabled(False)
        
        reg_controls.addWidget(self.start_reg_btn)
        reg_controls.addWidget(self.clear_reg_btn)
        reg_controls.addWidget(self.apply_reg_btn)
        reg_layout.addLayout(reg_controls)
        
        # refinement controls (hidden initially)
        self.refinement_widget = QWidget()
        refinement_layout = QHBoxLayout(self.refinement_widget)
        refinement_layout.setContentsMargins(0, 0, 0, 0)
        
        self.add_point_btn = QPushButton("Add Point")
        self.skip_point_btn = QPushButton("Skip")
        self.finish_early_btn = QPushButton("Finish Early")
        
        self.add_point_btn.setEnabled(False)
        self.skip_point_btn.setEnabled(False)
        self.finish_early_btn.setEnabled(False)
        
        refinement_layout.addWidget(self.add_point_btn)
        refinement_layout.addWidget(self.skip_point_btn)
        refinement_layout.addWidget(self.finish_early_btn)
        reg_layout.addWidget(self.refinement_widget)
        self.refinement_widget.setVisible(False)
        
        # status and quality
        self.reg_status_label = QLabel("Click 'Start Registration' to begin")
        reg_layout.addWidget(self.reg_status_label)
        
        self.quality_label = QLabel("")
        self.quality_label.setStyleSheet("font-weight: bold;")
        reg_layout.addWidget(self.quality_label)
        
        # results table
        self.reg_table = QTableWidget(0, 2)
        self.reg_table.setHorizontalHeaderLabels(["CSV", "Video"])
        self.reg_table.setMaximumHeight(60)
        reg_layout.addWidget(self.reg_table)
        
        layout.addWidget(reg_group)
        
        # screenshot section
        screenshot_group = QGroupBox("Batch Screenshots")
        screenshot_layout = QVBoxLayout(screenshot_group)
        
        prefix_layout = QHBoxLayout()
        prefix_layout.addWidget(QLabel("Filename prefix:"))
        self.prefix_edit = QLineEdit("peak")
        prefix_layout.addWidget(self.prefix_edit)
        screenshot_layout.addLayout(prefix_layout)
        
        self.screenshot_peaks_btn = QPushButton("Screenshot All Peaks")
        self.screenshot_peaks_btn.setEnabled(False)
        screenshot_layout.addWidget(self.screenshot_peaks_btn)
        
        self.stop_screenshots_btn = QPushButton("Stop")
        self.stop_screenshots_btn.setEnabled(False)
        screenshot_layout.addWidget(self.stop_screenshots_btn)
        
        layout.addWidget(screenshot_group)
        
        layout.addStretch()
        return widget
    
    def create_right_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # plot area
        if HAS_SCIPY:
            self.figure = Figure(figsize=(10, 6))
            self.canvas = FigureCanvas(self.figure)
            layout.addWidget(self.canvas)
        else:
            no_plot_label = QLabel("Install matplotlib and scipy for plotting")
            no_plot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(no_plot_label)
        
        # data preview table
        table_group = QGroupBox("Data Preview")
        table_layout = QVBoxLayout(table_group)
        
        self.data_table = QTableWidget()
        self.data_table.setMaximumHeight(200)
        table_layout.addWidget(self.data_table)
        
        layout.addWidget(table_group)
        
        return widget
    
    def setup_connections(self):
        self.load_csv_btn.clicked.connect(self.load_csv_file)
        self.csv_fps_combo.currentTextChanged.connect(self.on_sample_rate_changed)
        self.auto_resample_cb.stateChanged.connect(self.on_resample_setting_changed)
        self.column_combo.currentTextChanged.connect(self.on_column_changed)
        self.detect_peaks_btn.clicked.connect(self.detect_peaks)
        self.screenshot_peaks_btn.clicked.connect(self.start_batch_screenshots)
        self.stop_screenshots_btn.clicked.connect(self.stop_batch_screenshots)
        
        # registration connections
        self.start_reg_btn.clicked.connect(self.start_registration)
        self.clear_reg_btn.clicked.connect(self.clear_registration_pairs)
        self.apply_reg_btn.clicked.connect(self.on_apply_registration)
        self.add_point_btn.clicked.connect(self.add_current_point)
        self.skip_point_btn.clicked.connect(self.skip_current_point)
        self.finish_early_btn.clicked.connect(self.finish_registration_early)
        
        self._peak_artist = None
        if HAS_SCIPY:
            self._mpl_pick_cid = self.canvas.mpl_connect('pick_event', self.on_peak_pick)
        
        # connect peak parameter changes to auto-update
        for checkbox in [self.height_checkbox, self.prominence_checkbox, 
                        self.distance_checkbox, self.width_checkbox]:
            checkbox.stateChanged.connect(self.on_peak_params_changed)
        
        for spinbox in [self.height_spin, self.prominence_spin, 
                       self.distance_spin, self.width_spin]:
            spinbox.valueChanged.connect(self.on_peak_params_changed)
    
    def load_csv_file(self):
        # determine default path
        default_path = ""
        if self.main_window and self.main_window.fname:
            video_path = Path(self.main_window.fname)
            # look for ../Task relative to video file
            task_dir1 = video_path.parent.parent.parent.parent / "Task"
            task_dir2 = video_path.parent.parent.parent.parent.parent / "Task"
            print(task_dir1, task_dir2)
            if task_dir1.exists() and task_dir1.is_dir():
                default_path = str(task_dir1)
            elif task_dir2.exists() and task_dir2.is_dir():
                default_path = str(task_dir2)
            else:
                # fallback to video directory
                default_path = str(video_path.parent)
        else:
            # no video loaded, use last known path or default
            default_path = self.settings.value('csv_analysis/last_path', config.DEFAULT_WORK_PATH) if hasattr(self, 'settings') else ""

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Data File",
            default_path,
            "Data Files (*.csv *.tsv *.parquet *.parq);;CSV Files (*.csv *.tsv);;Parquet Files (*.parquet *.parq);;All Files (*)"
        )
        if not file_path:
            return

        try:
            df = self._read_table(file_path)
            self.csv_data = df

            if hasattr(self, 'original_csv_data'):
                delattr(self, 'original_csv_data')

            self.csv_file_label.setText(os.path.basename(file_path))
            self.update_column_combo()
            self.update_data_preview()

            if self.auto_resample_cb.isChecked():
                self.auto_resample_data()
            else:
                self.update_frame_matching()

            lg.info(f"Loaded data: {df.shape[0]} rows, {df.shape[1]} columns")

            self.clear_registration_pairs()

        except RuntimeError as e:
            QMessageBox.warning(self, "Optional Dependency Missing", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load data file:\n{e}")
            return

    def _read_table(self, file_path: str) -> pd.DataFrame:
        ext = Path(file_path).suffix.lower()
        if ext in {".parquet", ".parq"}:
            try:
                return pd.read_parquet(file_path)
            except ImportError:
                raise RuntimeError("Parquet engine not found. Install 'pyarrow' or 'fastparquet'.")
        
        encodings = ["utf-8", "latin-1", "cp1252"]
        seps = [",", ";", "\t"]
        if ext == ".tsv":
            seps = ["\t"]
        for enc in encodings:
            for sep in seps:
                try:
                    df = pd.read_csv(file_path, encoding=enc, sep=sep)
                    if df.shape[1] > 1 or len(df) > 10:
                        return df
                except Exception:
                    pass
        raise ValueError("Could not parse CSV/TSV file with common encodings/separators.")
    
    def update_column_combo(self):
        self.column_combo.clear()
        if self.csv_data is not None:
            numeric_cols = self.csv_data.select_dtypes(include=[np.number]).columns.tolist()
            self.column_combo.addItems(numeric_cols)

    def on_column_changed(self):
        if self.csv_data is not None and self.column_combo.currentText():
            self.selected_column = self.column_combo.currentText()
            self.update_column_stats()
            self.plot_data()
            self.detect_peaks()

    def on_sample_rate_changed(self):
        try:
            self.csv_fps = float(self.csv_fps_combo.currentText())
        except ValueError:
            self.csv_fps = 30.0
            self.csv_fps_combo.setCurrentText("30.00")
        
        self.update_frame_matching()

    def on_resample_setting_changed(self):
        self.update_frame_matching()

    def update_frame_matching(self):
        if self.csv_data is None:
            self.frame_match_label.setText("Frame count: No CSV loaded")
            return
        
        csv_samples = len(self.csv_data)
        try:
            self.csv_fps = float(self.csv_fps_combo.currentText())
        except ValueError:
            self.csv_fps = 30.0
        
        csv_duration_sec = csv_samples / self.csv_fps
        
        if self.main_window and hasattr(self.main_window, 'media_player'):
            video_duration_ms = self.main_window.media_player.duration()
            if video_duration_ms > 0:
                video_duration_sec = video_duration_ms / 1000.0
                
                time_diff = abs(video_duration_sec - csv_duration_sec)
                if time_diff < 1.0:
                    status = "✓"
                elif time_diff < 5.0:
                    status = "~"
                else:
                    status = "⚠"
                
                text = (f"CSV: {csv_duration_sec:.1f}s ({csv_samples} @ {self.csv_fps}Hz) | "
                       f"Video: {video_duration_sec:.1f}s {status}")
                
                if hasattr(self, 'time_offset_frames') and abs(self.time_offset_frames) > 0.1:
                    text += f" (offset: {self.time_offset_frames:.1f}f)"
                
                self.frame_match_label.setText(text)
            else:
                self.frame_match_label.setText(f"CSV: {csv_duration_sec:.1f}s ({csv_samples} samples @ {self.csv_fps}Hz)")
        else:
            self.frame_match_label.setText(f"CSV: {csv_duration_sec:.1f}s ({csv_samples} samples @ {self.csv_fps}Hz)")

    def csv_frame_to_video_frame(self, csv_index: int) -> int:
        """convert CSV sample index to video frame with offset"""
        if not self.csv_fps:
            return csv_index
        
        csv_time_sec = csv_index / self.csv_fps
        video_frame = int(csv_time_sec * self.video_fps)
        
        if hasattr(self, 'time_offset_frames'):
            video_frame += int(self.time_offset_frames)
        
        return video_frame

    def video_frame_to_csv_index(self, video_frame: int) -> int:
        """convert video frame to CSV index with offset"""
        if not self.csv_fps:
            return video_frame
        
        if hasattr(self, 'time_offset_frames'):
            video_frame -= int(self.time_offset_frames)
        
        video_time_sec = video_frame / self.video_fps
        csv_index = int(video_time_sec * self.csv_fps)
        return max(0, min(csv_index, len(self.csv_data) - 1)) if self.csv_data is not None else csv_index

    def auto_resample_data(self):
        """automatically resample CSV data to match video fps"""
        if not HAS_SCIPY or self.csv_data is None or not hasattr(self.main_window, 'media_player'):
            return
        
        video_duration_ms = self.main_window.media_player.duration()
        if video_duration_ms <= 0:
            self.resample_info_label.setText("⚠ No video loaded for resampling")
            return
        
        video_duration_sec = video_duration_ms / 1000.0
        target_samples = int(video_duration_sec * self.video_fps)
        
        original_samples = len(self.csv_data)
        if abs(target_samples - original_samples) < 5:
            self.resample_info_label.setText("✓ No resampling needed")
            return
        
        try:
            resampled_data = {}
            for col in self.csv_data.select_dtypes(include=[np.number]).columns:
                original_signal = self.csv_data[col].values
                resampled_signal = resample(original_signal, target_samples)
                resampled_data[col] = resampled_signal
            
            for col in self.csv_data.select_dtypes(exclude=[np.number]).columns:
                original_values = self.csv_data[col].values
                if len(original_values) >= target_samples:
                    indices = np.linspace(0, len(original_values)-1, target_samples, dtype=int)
                    resampled_data[col] = original_values[indices]
                else:
                    repeat_factor = target_samples // len(original_values) + 1
                    extended = np.tile(original_values, repeat_factor)
                    resampled_data[col] = extended[:target_samples]
            
            if not hasattr(self, 'original_csv_data'):
                self.original_csv_data = self.csv_data.copy()
            
            self.csv_data = pd.DataFrame(resampled_data)
            self.peaks = []
            self.peaks_found_label.setText("Peaks found: 0")
            self.screenshot_peaks_btn.setEnabled(False)
            
            self.update_column_combo()
            self.update_frame_matching()
            self.update_data_preview()
            
            resample_ratio = target_samples / original_samples
            self.resample_info_label.setText(
                f"✓ Resampled: {original_samples}→{target_samples} samples (×{resample_ratio:.3f})"
            )
            
            if self.selected_column and self.selected_column in self.csv_data.columns:
                self.update_column_stats()
                self.plot_data()
                self.detect_peaks()
            
            lg.info(f"Auto-resampled CSV from {original_samples} to {target_samples} samples")
            
        except Exception as e:
            lg.error(f"Auto-resample failed: {e}")
            self.resample_info_label.setText(f"⚠ Resample failed: {str(e)[:30]}...")
    
    def update_column_stats(self):
        if self.csv_data is None or not self.selected_column:
            return
        
        col_data = self.csv_data[self.selected_column]
        stats = {
            'Min': col_data.min(),
            'Max': col_data.max(),
            'Mean': col_data.mean(),
            'Std': col_data.std(),
            'Count': len(col_data)
        }
        
        stats_text = " | ".join([f"{k}: {v:.3f}" if isinstance(v, float) else f"{k}: {v}" 
                                for k, v in stats.items()])
        self.stats_label.setText(stats_text)
    
    def plot_data(self):
        if not HAS_SCIPY or self.csv_data is None or not self.selected_column:
            return
        
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        
        col_data = self.csv_data[self.selected_column].values
        x_frames = np.arange(len(col_data))
        
        ax.plot(x_frames, col_data, 'b-', linewidth=1, label=self.selected_column)
        
        # plot peaks if detected - with bounds checking
        if self.peaks:
            valid_peaks = [p for p in self.peaks if 0 <= p < len(col_data)]
            if valid_peaks != self.peaks:
                # some peaks were invalid, update the list
                self.peaks = valid_peaks
                self.peaks_found_label.setText(f"Peaks found: {len(self.peaks)}")
                self.screenshot_peaks_btn.setEnabled(len(self.peaks) > 0)
            
            if valid_peaks:
                peak_values = col_data[valid_peaks]
                line, = ax.plot(valid_peaks, peak_values, 'ro', markersize=4, label=f'Peaks ({len(valid_peaks)})')
                line.set_picker(5)  # 5px tolerance
                self._peak_artist = line
        
        ax.set_xlabel('Frame')
        ax.set_ylabel('Value')
        ax.set_title(f'Data: {self.selected_column}')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        self.canvas.draw()
    
    def on_peak_params_changed(self):
        if hasattr(self, '_peak_update_timer'):
            self._peak_update_timer.stop()
        else:
            self._peak_update_timer = QTimer()
            self._peak_update_timer.setSingleShot(True)
            self._peak_update_timer.timeout.connect(self.detect_peaks)
        
        self._peak_update_timer.start(300)  # 300ms delay for smooth interaction
    
    def detect_peaks(self):
        if not HAS_SCIPY or self.csv_data is None or not self.selected_column:
            self.peaks = []
            self.peaks_found_label.setText("Peaks found: 0")
            return
        
        col_data = self.csv_data[self.selected_column].values
        
        # build parameters dict
        peak_kwargs = {}
        
        if self.height_checkbox.isChecked():
            peak_kwargs['height'] = self.height_spin.value()
        
        if self.prominence_checkbox.isChecked():
            peak_kwargs['prominence'] = self.prominence_spin.value()
        
        if self.distance_checkbox.isChecked():
            peak_kwargs['distance'] = self.distance_spin.value()
        
        if self.width_checkbox.isChecked():
            peak_kwargs['width'] = self.width_spin.value()
        
        try:
            peaks, properties = find_peaks(col_data, **peak_kwargs)
            self.peaks = peaks.tolist()
            self.peaks_found_label.setText(f"Peaks found: {len(self.peaks)}")
            self.screenshot_peaks_btn.setEnabled(len(self.peaks) > 0)
            
            self.plot_data()  # update plot with peaks
            
        except Exception as e:
            lg.warning(f"Peak detection error: {e}")
            self.peaks = []
            self.peaks_found_label.setText("Peak detection failed")
            self.screenshot_peaks_btn.setEnabled(False)
    
    def update_data_preview(self):
        if self.csv_data is None:
            return
        
        # show first 10 rows
        preview_data = self.csv_data.head(10)
        self.data_table.setRowCount(len(preview_data))
        self.data_table.setColumnCount(len(preview_data.columns))
        self.data_table.setHorizontalHeaderLabels([str(col) for col in preview_data.columns])
        
        for i, (_, row) in enumerate(preview_data.iterrows()):
            for j, value in enumerate(row):
                item = QTableWidgetItem(str(value))
                self.data_table.setItem(i, j, item)
        
        self.data_table.resizeColumnsToContents()
    
    def on_peak_pick(self, event):
        if getattr(self, "_peak_artist", None) is None or event.artist is not self._peak_artist:
            return
        if not self.peaks:
            return

        try:
            picked_idx = int(event.ind[0])
            if picked_idx < 0 or picked_idx >= len(self.peaks):
                return
            
            csv_frame = int(self.peaks[picked_idx])
            
            if not self.registration_mode:
                # normal mode: jump to corresponding video frame
                if self.csv_data is None or not hasattr(self.main_window, 'playback_controller'):
                    return
                video_frame = self.csv_frame_to_video_frame(csv_frame)
                self._safe_jump_to_frame(video_frame)
            else:
                # registration mode: add this peak automatically
                video_frame = self.main_window.playback_controller.get_current_frame()
                self.add_registration_pair(csv_frame, video_frame)
                
                if len(self.registration_pairs) < 2:
                    self.reg_status_label.setText(f"Step 2: Click another peak far from the first one...")
                else:
                    # enough for basic fit, start smart refinement
                    self._start_refinement_mode()
                    
        except Exception as e:
            lg.warning(f"Peak pick failed: {e}")

    def _safe_jump_to_frame(self, video_frame):
        """safely pause and jump to frame"""
        try:
            if self.main_window.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.main_window.media_player.pause()
            self.main_window.playback_controller.jump_to_frame(video_frame)
        except Exception as e:
            lg.warning(f"Failed to jump to frame {video_frame}: {e}")

    # Registration methods
    def start_registration(self):
        """start the streamlined registration workflow"""
        self.registration_mode = True
        self.registration_pairs.clear()
        self.refinement_mode = False
        self.current_refinement_idx = 0
        
        self.start_reg_btn.setText("Stop Registration")
        self.start_reg_btn.clicked.disconnect()
        self.start_reg_btn.clicked.connect(self.stop_registration)
        
        self.reg_status_label.setText("Step 1: Click peak → navigate video → click same peak (need 2 for rough registration)")
        self.quality_label.setText("")
        self.update_registration_table()

    def stop_registration(self):
        """stop registration and return to normal mode"""
        self.registration_mode = False
        self.refinement_mode = False
        
        self.start_reg_btn.setText("Start Registration")
        self.start_reg_btn.clicked.disconnect()
        self.start_reg_btn.clicked.connect(self.start_registration)
        
        self.refinement_widget.setVisible(False)
        self.reg_status_label.setText("Registration stopped")
        self.quality_label.setText("")

    def _apply_initial_registration(self):
        """apply rough registration with initial 2 points"""
        if len(self.registration_pairs) < 2:
            return
            
        csv_frames = np.array([pair[0] for pair in self.registration_pairs])
        video_frames = np.array([pair[1] for pair in self.registration_pairs])
        
        try:
            coeffs = np.polyfit(csv_frames, video_frames, 1)
            slope, intercept = coeffs
            
            # apply rough registration parameters
            self.csv_fps = self.video_fps / slope
            self.csv_fps_combo.setCurrentText(f"{self.csv_fps:.2f}")
            self.time_offset_frames = intercept
            
            # update frame matching display
            self.update_frame_matching()
            
            r_squared = self._get_current_r_squared()
            self.reg_status_label.setText(f"Rough registration applied (R²={r_squared:.3f}). Refining...")
            
            lg.info(f"Applied rough registration: slope={slope:.4f}, intercept={intercept:.2f}")
            
        except Exception as e:
            lg.warning(f"Initial registration failed: {e}")
            self.reg_status_label.setText("Initial registration failed - continuing with manual alignment")

    def _start_refinement_mode(self):
        """apply initial registration then start refinement"""
        # apply rough registration with just 2 points
        self._apply_initial_registration()
        
        # now start refinement mode
        self.refinement_mode = True
        self.current_refinement_idx = 0
        
        # select strategic refinement peaks
        self._select_refinement_peaks()
        
        # show refinement controls
        self.refinement_widget.setVisible(True)
        self.add_point_btn.setEnabled(True)
        self.skip_point_btn.setEnabled(True)
        self.finish_early_btn.setEnabled(True)
        
        # update quality display
        self._update_quality_assessment()
        
        # jump to first refinement peak using the rough registration
        self._jump_to_next_refinement_peak()

    def _select_refinement_peaks(self):
        """intelligently select 5-8 peaks spread across timeline for refinement"""
        if len(self.peaks) <= 10:
            # few peaks: use all except already registered
            self.refinement_peaks = [p for p in self.peaks 
                                   if not any(pair[0] == p for pair in self.registration_pairs)]
        else:
            # many peaks: select strategically spaced ones
            total_peaks = len(self.peaks)
            indices = [0, total_peaks//4, total_peaks//2, 3*total_peaks//4, total_peaks-1]
            indices = sorted(set(indices))
            
            if len(indices) < 7 and total_peaks > 20:
                indices.extend([total_peaks//8, 7*total_peaks//8])
            
            candidate_peaks = [self.peaks[i] for i in sorted(set(indices)) if i < len(self.peaks)]
            self.refinement_peaks = [p for p in candidate_peaks 
                                   if not any(pair[0] == p for pair in self.registration_pairs)]

    def _jump_to_next_refinement_peak(self):
        """jump to next strategic peak for refinement"""
        while self.current_refinement_idx < len(self.refinement_peaks):
            csv_frame = self.refinement_peaks[self.current_refinement_idx]
            
            # estimate video frame and jump
            estimated_video_frame = self.csv_frame_to_video_frame(csv_frame)
            self._safe_jump_to_frame(estimated_video_frame)
            
            remaining = len(self.refinement_peaks) - self.current_refinement_idx
            self.reg_status_label.setText(f"Peak {csv_frame}: Check alignment ({remaining} strategic points left)")
            return
        
        # no more peaks to refine
        self._finish_registration()

    def add_current_point(self):
        """add current peak to registration"""
        if self.current_refinement_idx < len(self.refinement_peaks):
            csv_frame = self.refinement_peaks[self.current_refinement_idx]
            video_frame = self.main_window.playback_controller.get_current_frame()
            self.add_registration_pair(csv_frame, video_frame)
            
            self.current_refinement_idx += 1
            self._update_quality_assessment()
            
            # early stop if quality is excellent
            if len(self.registration_pairs) >= 4 and self._get_current_r_squared() > 0.98:
                self.quality_label.setText("Quality: Excellent - can finish early!")
                self.finish_early_btn.setStyleSheet("background-color: #4CAF50; font-weight: bold;")
            
            self._jump_to_next_refinement_peak()

    def skip_current_point(self):
        """skip current peak and move to next"""
        self.current_refinement_idx += 1
        self._jump_to_next_refinement_peak()

    def finish_registration_early(self):
        """stop refinement early if quality is good enough"""
        if len(self.registration_pairs) >= 2:
            self._finish_registration()
        else:
            self.reg_status_label.setText("Need at least 2 points before finishing")

    def _finish_registration(self):
        """complete registration workflow"""
        self.refinement_mode = False
        self.refinement_widget.setVisible(False)
        
        if len(self.registration_pairs) >= 2:
            self.apply_reg_btn.setEnabled(True)
            r_sq = self._get_current_r_squared()
            self.reg_status_label.setText(f"Registration ready! Quality: R²={r_sq:.3f}")
            
            if r_sq > 0.95:
                self.quality_label.setText("Quality: Good")
                self.quality_label.setStyleSheet("color: green; font-weight: bold;")
            else:
                self.quality_label.setText("Quality: Poor - consider more points")
                self.quality_label.setStyleSheet("color: orange; font-weight: bold;")
            
            self.on_apply_registration()
        else:
            self.reg_status_label.setText("Need at least 2 points for registration")

    def _update_quality_assessment(self):
        """update quality indicator during refinement"""
        if len(self.registration_pairs) >= 2:
            r_sq = self._get_current_r_squared()
            self.quality_label.setText(f"Current quality: R²={r_sq:.3f}")
            
            if r_sq > 0.98:
                self.quality_label.setStyleSheet("color: green; font-weight: bold;")
            elif r_sq > 0.95:
                self.quality_label.setStyleSheet("color: blue; font-weight: bold;")
            else:
                self.quality_label.setStyleSheet("color: red; font-weight: bold;")

    def _get_current_r_squared(self) -> float:
        """calculate current registration quality"""
        if len(self.registration_pairs) < 2:
            return 0.0
        
        try:
            csv_frames = np.array([pair[0] for pair in self.registration_pairs])
            video_frames = np.array([pair[1] for pair in self.registration_pairs])
            
            coeffs = np.polyfit(csv_frames, video_frames, 1)
            slope, intercept = coeffs
            
            video_pred = slope * csv_frames + intercept
            ss_res = np.sum((video_frames - video_pred) ** 2)
            ss_tot = np.sum((video_frames - np.mean(video_frames)) ** 2)
            return 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        except:
            return 0.0

    def add_registration_pair(self, csv_frame: int, video_frame: int):
        """add a csv->video frame correspondence"""
        # check for duplicates
        for i, (existing_csv, existing_video) in enumerate(self.registration_pairs):
            if existing_csv == csv_frame:
                # update existing pair
                self.registration_pairs[i] = (csv_frame, video_frame)
                self.update_registration_table()
                return
        
        # add new pair
        self.registration_pairs.append((csv_frame, video_frame))
        self.registration_pairs.sort(key=lambda x: x[0])  # sort by csv frame
        self.update_registration_table()

    def update_registration_table(self):
        """refresh the registration pairs table"""
        self.reg_table.setRowCount(len(self.registration_pairs))
        
        for row, (csv_frame, video_frame) in enumerate(self.registration_pairs):
            csv_item = QTableWidgetItem(str(csv_frame))
            csv_item.setFlags(csv_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.reg_table.setItem(row, 0, csv_item)
            
            video_item = QTableWidgetItem(str(video_frame))
            video_item.setFlags(video_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.reg_table.setItem(row, 1, video_item)
        
        self.reg_table.resizeColumnsToContents()

    def clear_registration_pairs(self):
        """clear all registration pairs"""
        self.registration_pairs.clear()
        self.update_registration_table()
        self.apply_reg_btn.setEnabled(False)
        self.reg_status_label.setText("All registration pairs cleared")
        self.quality_label.setText("")

    def on_apply_registration(self):
        """finalize and confirm the registration"""
        if len(self.registration_pairs) < 2:
            QMessageBox.warning(self, "Insufficient Data", "Need at least 2 registration pairs")
            return
        
        # re-calculate with all points (may have been refined)
        csv_frames = np.array([pair[0] for pair in self.registration_pairs])
        video_frames = np.array([pair[1] for pair in self.registration_pairs])
        
        try:
            coeffs = np.polyfit(csv_frames, video_frames, 1)
            slope, intercept = coeffs
            
            # calculate final quality
            video_pred = slope * csv_frames + intercept
            ss_res = np.sum((video_frames - video_pred) ** 2)
            ss_tot = np.sum((video_frames - np.mean(video_frames)) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
            
            # apply final parameters
            self.csv_fps = self.video_fps / slope
            self.csv_fps_combo.setCurrentText(f"{self.csv_fps:.2f}")
            self.time_offset_frames = intercept
            
            # stop registration mode
            self.stop_registration()
            
            msg = (f"Final registration complete:\n"
                f"Points used: {len(self.registration_pairs)}\n"
                f"Slope: {slope:.4f}\n" 
                f"Offset: {intercept:.2f} frames\n"  
                f"Quality: R²={r_squared:.4f}\n"
                f"CSV rate: {self.csv_fps:.2f} Hz")
            
            if r_squared < 0.95:
                msg += f"\n⚠ Warning: Low quality (R²={r_squared:.3f})"
            else:
                msg += f"\n✓ Good registration quality"
            
            QMessageBox.information(self, "Registration Complete", msg)
            
            self.update_frame_matching()
            lg.info(f"Final registration: {len(self.registration_pairs)} points, R²={r_squared:.4f}")
            
        except Exception as e:
            QMessageBox.critical(self, "Registration Failed", f"Could not finalize registration:\n{e}")

    # Screenshot methods
    def start_batch_screenshots(self):
        if not self.peaks or not self.main_window:
            return
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(self.peaks))
        self.progress_bar.setValue(0)
        
        self.screenshot_peaks_btn.setEnabled(False)
        self.stop_screenshots_btn.setEnabled(True)
        
        # create worker thread with offset
        self.screenshot_worker = ScreenshotWorker(
            self.main_window, 
            self.peaks.copy(),
            self.csv_fps,
            self.prefix_edit.text() or "peak",
            getattr(self, 'time_offset_frames', 0.0)
        )
        
        self.worker_thread = QThread()
        self.screenshot_worker.moveToThread(self.worker_thread)
        
        # connect signals
        self.worker_thread.started.connect(self.screenshot_worker.run)
        self.screenshot_worker.progress.connect(self.update_progress)
        self.screenshot_worker.finished.connect(self.on_screenshots_finished)
        self.screenshot_worker.error.connect(self.on_screenshots_error)
        
        self.worker_thread.start()
    
    def stop_batch_screenshots(self):
        if self.screenshot_worker:
            self.screenshot_worker.stop()
    
    def update_progress(self, current: int, total: int):
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(f"Screenshot {current}/{total}")
    
    def on_screenshots_finished(self):
        self.progress_bar.setVisible(False)
        self.screenshot_peaks_btn.setEnabled(True)
        self.stop_screenshots_btn.setEnabled(False)
        
        if self.worker_thread:
            self.worker_thread.quit()
            self.worker_thread.wait()
            self.worker_thread = None
        
        QMessageBox.information(self, "Complete", f"Successfully captured {len(self.peaks)} peak screenshots")
    
    def on_screenshots_error(self, error_msg: str):
        self.progress_bar.setVisible(False)
        self.screenshot_peaks_btn.setEnabled(True)
        self.stop_screenshots_btn.setEnabled(False)
        
        QMessageBox.critical(self, "Error", f"Screenshot batch failed:\n{error_msg}")