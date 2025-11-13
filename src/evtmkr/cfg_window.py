import yaml
import re
from functools import partial
import logging
from copy import deepcopy

lg = logging.getLogger(__name__)

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget,
    QLineEdit, QPushButton, QCheckBox, QSpinBox, QDoubleSpinBox,
    QColorDialog, QFileDialog, QDialogButtonBox, QLabel, QMessageBox,
    QComboBox, QFrame, QScrollArea
)

from evtmkr.cfg import config

class ConfigWindow(QDialog):
    """A dialog window for editing application settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Configuration")
        self.setMinimumSize(550, 450)

        # create a deep copy of config data to work with
        self._config_copy = deepcopy(config._data)

        # main layout
        layout = QVBoxLayout(self)

        # tab widget for organizing settings
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # create tabs
        self.create_ui_tab()
        self.create_playback_tab()
        self.create_marker_tab()
        self.create_workspace_tab()

        # dialog buttons (Save, Apply, Cancel)
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Apply |
            QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.clicked.connect(self.handle_button_click)
        layout.addWidget(self.button_box)

        self.load_settings()

    def create_ui_tab(self):
        """Creates the 'UI' settings tab."""
        tab = QWidget()
        layout = QFormLayout(tab)
        
        self.ui_window_title = QLineEdit()
        self.ui_window_title.setEnabled(False)
        self.ui_marker_float_enabled = QCheckBox("Show floating marker window")
        self.ui_csv_plot_enabled = QCheckBox("Show CSV plot window on startup")
        
        layout.addRow("Window Title:", self.ui_window_title)
        layout.addRow(self.ui_marker_float_enabled)
        layout.addRow(self.ui_csv_plot_enabled)
        
        self.tabs.addTab(tab, "UI")

    def create_playback_tab(self):
        """Creates the 'Playback' settings tab."""
        tab = QWidget()
        layout = QFormLayout(tab)

        self.pb_fps = QDoubleSpinBox()
        self.pb_fps.setRange(1, 1000)
        self.pb_video_fps_original = QDoubleSpinBox()
        self.pb_video_fps_original.setRange(1, 1000)
        self.pb_large_step_multiplier = QSpinBox()
        self.pb_large_step_multiplier.setRange(1, 1000)
        self.pb_frame_step = QSpinBox()
        self.pb_frame_step.setRange(1, 10)
        
        layout.addRow("Playback FPS:", self.pb_fps)
        layout.addRow("Original Video FPS:", self.pb_video_fps_original)
        layout.addRow("Large Frame Step Multiplier:", self.pb_large_step_multiplier)
        layout.addRow("Frame Step:", self.pb_frame_step)
        
        self.tabs.addTab(tab, "Playback")

    def create_marker_tab(self):
        """Creates the 'Markers' settings tab with dynamic rows and a scroll area."""
        self.marker_tab = QWidget()
        main_layout = QVBoxLayout(self.marker_tab)

        # scroll area for marker definitions
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        main_layout.addWidget(scroll)
        
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll.setWidget(scroll_content)

        # --- marker definition area ---
        self.marker_rows_widget = QWidget()
        self.marker_rows_layout = QFormLayout(self.marker_rows_widget)
        self.marker_rows_layout.setContentsMargins(5, 5, 5, 5)
        scroll_layout.addWidget(self.marker_rows_widget)
        
        add_marker_btn = QPushButton("+ MARKER")
        add_marker_btn.clicked.connect(lambda: self.add_marker_row())
        scroll_layout.addWidget(add_marker_btn)

        # --- separator ---
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        scroll_layout.addWidget(line)

        # --- pairing settings area ---
        self.pairing_widget = QWidget()
        self.pairing_layout = QFormLayout(self.pairing_widget)
        self.marker_pairing_enabled = QCheckBox("Enable marker pairing")
        self.pairing_layout.addRow(self.marker_pairing_enabled)
        scroll_layout.addWidget(self.pairing_widget)

        scroll_layout.addStretch()
        self.tabs.addTab(self.marker_tab, "Markers")

    def add_marker_row(self, key_name=None, color=None, update_ui=True):
        """Adds a new row for configuring a single marker."""
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)

        # key selection dropdown
        key_combo = QComboBox()
        self.populate_key_combo(key_combo)
        if key_name:
            key_combo.setCurrentText(key_name)
        key_combo.currentTextChanged.connect(self.refresh_marker_ui)

        # color picker button
        color_btn = QPushButton()
        color_btn.setFixedSize(100, 25)
        color_btn.setFlat(True)
        color_btn.setAutoFillBackground(True)
        initial_color = color if color else QColor("lightgray")
        self.set_button_color(color_btn, initial_color)
        color_btn.clicked.connect(lambda: self.change_marker_color(color_btn))

        # remove button
        remove_btn = QPushButton("-")
        remove_btn.clicked.connect(lambda checked, rw=row_widget: self.remove_marker_row(rw))

        row_layout.addWidget(key_combo)
        row_layout.addWidget(color_btn)
        row_layout.addWidget(remove_btn)
        
        # add the new row to the form layout
        self.marker_rows_layout.addRow(f"Marker:", row_widget)
        
        if update_ui:
            self.refresh_marker_ui()

    def remove_marker_row(self, row_widget):
        """Removes a marker row from the layout."""
        # disconnect the combo’s signal (if still connected)
        try:
            row_widget.findChild(QComboBox).currentTextChanged.disconnect(self.refresh_marker_ui)
        except (TypeError, RuntimeError):
            pass

        # remove the whole row from the FormLayout
        self.marker_rows_layout.removeRow(row_widget)

        # safely delete the widget (ignore if it's already gone)
        try:
            row_widget.deleteLater()
        except RuntimeError:
            pass

        self.refresh_marker_ui()

    def populate_key_combo(self, combo):
        """Fills a QComboBox with a curated list of Qt keys."""
        if combo.count() > 0: return # already populated
        
        keys = []
        # function keys
        for i in range(1, 13):
            keys.append(f"F{i}")
        # number keys (main keyboard)
        for i in range(10):
            keys.append(str(i))
        # letter keys
        for i in range(ord('A'), ord('Z') + 1):
            keys.append(chr(i))
        
        qt_keys = [f"Key_{k}" for k in keys]
        combo.addItems(qt_keys)

    def get_marker_row_widgets(self):
        """Helper to get a list of all marker row widgets."""
        return [self.marker_rows_layout.itemAt(i, QFormLayout.ItemRole.FieldRole).widget() 
                for i in range(self.marker_rows_layout.rowCount())]

    def refresh_marker_ui(self):
        """Rebuilds all marker-related UI elements to be in sync."""
        # get current state
        row_widgets = self.get_marker_row_widgets()
        key_names = [row.findChild(QComboBox).currentText() for row in row_widgets]
        
        # remember current pairing selections
        old_pairing_selections = {}
        pairing_combos = self.pairing_widget.findChildren(QComboBox)
        for i, combo in enumerate(pairing_combos):
            old_pairing_selections[i] = combo.currentText()

        # relabel marker definition rows
        for i, row_widget in enumerate(row_widgets):
            label = self.marker_rows_layout.labelForField(row_widget)
            if label:
                label.setText(f"'{key_names[i]}':")
        
        # clear old pairing widgets, but keep the checkbox
        while self.pairing_layout.rowCount() > 1:
            self.pairing_layout.removeRow(1)

        if not key_names: return

        # rebuild pairing dropdowns
        for i, key_name in enumerate(key_names):
            combo = QComboBox()
            options = ["None"] + [k for k in key_names if k != key_name]
            combo.addItems(options)
            # restore old selection if possible
            if i in old_pairing_selections and old_pairing_selections[i] in options:
                combo.setCurrentText(old_pairing_selections[i])
            self.pairing_layout.addRow(f"Pair '{key_name}' with:", combo)

    def create_workspace_tab(self):
        """Creates the 'Workspace' settings tab."""
        tab = QWidget()
        layout = QFormLayout(tab)

        self.ws_auto_search = QCheckBox("Automatically search for event files on video load")
        layout.addRow(self.ws_auto_search)

        # default path editor
        path_layout = QHBoxLayout()
        self.ws_default_path = QLineEdit()
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_for_path)
        path_layout.addWidget(self.ws_default_path)
        path_layout.addWidget(browse_btn)

        layout.addRow("Default Work Path:", path_layout)
        self.tabs.addTab(tab, "Workspace")

    def load_settings(self):
        """Populates the widgets with current values from the config copy."""
        # clear existing dynamic rows first
        while self.marker_rows_layout.rowCount() > 0:
            self.remove_marker_row(self.get_marker_row_widgets()[0])

        # ui
        self.ui_window_title.setText(self._config_copy.get('ui', {}).get('window_title', ''))
        self.ui_marker_float_enabled.setChecked(self._config_copy.get('ui', {}).get('marker_float_enabled', False))
        self.ui_csv_plot_enabled.setChecked(self._config_copy.get('ui', {}).get('csv_plot_enabled', False))

        # playback
        self.pb_fps.setValue(self._config_copy.get('playback', {}).get('fps', 30.0))
        self.pb_video_fps_original.setValue(self._config_copy.get('playback', {}).get('video_fps_original', 119.88))
        self.pb_large_step_multiplier.setValue(self._config_copy.get('playback', {}).get('large_step_multiplier', 6))
        self.pb_frame_step.setValue(self._config_copy.get('playback', {}).get('frame_step', 1))

        # markers
        keys = self._config_copy.get('marker', {}).get('keys', [])
        colors_raw = self._config_copy.get('marker', {}).get('colors', [])
        colors = [QColor(*rgb) for rgb in colors_raw]
        for i, key_name in enumerate(keys):
            color = colors[i] if i < len(colors) else None
            self.add_marker_row(key_name, color, update_ui=False) # add rows without updating UI each time
        
        self.refresh_marker_ui() # update all labels and pairing options once

        # pairing
        self.marker_pairing_enabled.setChecked(self._config_copy.get('marker', {}).get('pairing', {}).get('enabled', False))
        rules = self._config_copy.get('marker', {}).get('pairing', {}).get('rules', {})
        
        # translate index-based rules from config to key-based UI
        key_names = [row.findChild(QComboBox).currentText() for row in self.get_marker_row_widgets()]
        index_to_key = {str(i + 1): key for i, key in enumerate(key_names)}
        pairing_combos = self.pairing_widget.findChildren(QComboBox)

        for i, combo in enumerate(pairing_combos):
            current_marker_index_str = str(i + 1)
            paired_marker_index_str = rules.get(current_marker_index_str)
            if paired_marker_index_str:
                paired_key_name = index_to_key.get(paired_marker_index_str)
                if paired_key_name:
                    combo.setCurrentText(paired_key_name)

        # workspace
        self.ws_auto_search.setChecked(self._config_copy.get('workspace', {}).get('auto_search_events', False))
        self.ws_default_path.setText(self._config_copy.get('workspace', {}).get('default_path', ''))

    def apply_changes(self):
        """Reads values from widgets, updates the actual config object, and saves."""
        lg.debug('cfg window: apply cfg changes')
        try:
            # read all values from widgets into the config copy
            # ui
            self._config_copy.setdefault('ui', {})['window_title'] = self.ui_window_title.text()
            self._config_copy['ui']['marker_float_enabled'] = self.ui_marker_float_enabled.isChecked()
            self._config_copy['ui']['csv_plot_enabled'] = self.ui_csv_plot_enabled.isChecked()

            # playback
            self._config_copy.setdefault('playback', {})['fps'] = self.pb_fps.value()
            self._config_copy['playback']['video_fps_original'] = self.pb_video_fps_original.value()
            self._config_copy['playback']['large_step_multiplier'] = self.pb_large_step_multiplier.value()
            self._config_copy['playback']['frame_step'] = self.pb_frame_step.value()

            # markers - keys and colors
            row_widgets = self.get_marker_row_widgets()
            keys = [row.findChild(QComboBox).currentText() for row in row_widgets]
            colors = []
            for row in row_widgets:
                color_btn = row.findChild(QPushButton)
                color = color_btn.palette().color(QPalette.ColorRole.Button)
                colors.append([color.red(), color.green(), color.blue()])
            
            self._config_copy.setdefault('marker', {})['keys'] = keys
            self._config_copy['marker']['colors'] = colors

            # markers - pairing (translate key-based UI to index-based config)
            self._config_copy['marker'].setdefault('pairing', {})['enabled'] = self.marker_pairing_enabled.isChecked()
            key_to_index = {key: str(i + 1) for i, key in enumerate(keys)}
            new_rules = {}
            pairing_combos = self.pairing_widget.findChildren(QComboBox)

            for i, combo in enumerate(pairing_combos):
                selected_key = combo.currentText()
                if selected_key != "None":
                    current_marker_index_str = str(i + 1)
                    paired_marker_index_str = key_to_index.get(selected_key)
                    if paired_marker_index_str:
                        new_rules[current_marker_index_str] = paired_marker_index_str
            self._config_copy['marker']['pairing']['rules'] = new_rules

            # workspace
            self._config_copy.setdefault('workspace', {})['auto_search_events'] = self.ws_auto_search.isChecked()
            self._config_copy['workspace']['default_path'] = self.ws_default_path.text()

            # now apply the copy to the actual config
            config._data = deepcopy(self._config_copy)
            config.save()
            config.reload()
            
            lg.debug('Changes applied w/o error')
            return True

        except Exception as e:
            QMessageBox.critical(self, "Error Applying Changes", f"Could not apply settings:\n{e}")
            return False

    def save_changes(self):
        """Applies changes and saves them to the config file."""
        if self.apply_changes():
            config.save()
            self.accept() # close dialog with 'ok' status

    def handle_button_click(self, button):
        """Handles clicks on the Save, Apply, and Cancel buttons."""
        role = self.button_box.buttonRole(button)
        if role == QDialogButtonBox.ButtonRole.AcceptRole: # save
            self.save_changes()
        elif role == QDialogButtonBox.ButtonRole.ApplyRole: # apply
            if self.apply_changes():
                 QMessageBox.information(self, "Success", "Settings applied successfully.")
        elif role == QDialogButtonBox.ButtonRole.RejectRole: # cancel
            self.reject()

    def change_marker_color(self, button):
        """Opens a color dialog to change a marker's color."""
        initial_color = button.palette().color(QPalette.ColorRole.Button)
        color = QColorDialog.getColor(initial_color, self, "Select Marker Color")
        if color.isValid():
            self.set_button_color(button, color)

    def set_button_color(self, button, color):
        """Sets the background color of a button."""
        palette = button.palette()
        palette.setColor(QPalette.ColorRole.Button, color)
        button.setPalette(palette)
        # set text color based on luminance for readability
        text_color = "black" if color.lightness() > 127 else "white"
        button.setStyleSheet(f"background-color: {color.name()}; color: {text_color};")
        button.setText(color.name())

    def browse_for_path(self):
        """Opens a dialog to select a directory."""
        directory = QFileDialog.getExistingDirectory(
            self, "Select Default Work Directory", self.ws_default_path.text()
        )
        if directory:
            self.ws_default_path.setText(directory)


if __name__ == "__main__":
    """
    Standalone mode for debugging the config window.
    Run with: python src/cfg_window.py
    
    This allows testing the config UI without launching the main app.
    Changes are written to the actual evt-config.yaml file.
    """
    import sys
    from pathlib import Path
    from PyQt6.QtWidgets import QApplication

    lg.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    lg.addHandler(ch)
    
    print("="*60)
    print("Event Marker - Standalone Configuration Editor")
    print("="*60)
    print(f"\nLoaded config from: {config._config_file}")
    print(f"Config location: {Path(config._config_file).absolute()}")
    print("\nCurrent settings:")
    print(f"  Markers: {len(config.MARKER_KEYS)} configured")
    print(f"  Window Title: {config.WINDOW_TITLE}")
    print(f"  Marker Float: {config.MARKER_FLOAT_ENABLED}")
    print(f"  CSV Plot: {config.CSV_PLOT_ENABLED}")
    print(f"  Playback FPS: {config.PLAYBACK_FPS}")
    print(f"  Video FPS: {config.VIDEO_FPS_ORIGINAL}")
    print("="*60 + "\n")
    
    app = QApplication(sys.argv)
    
    # Create config window
    window = ConfigWindow()
    window.setWindowTitle("Event Marker - Configuration (Debug Mode)")
    
    # Show as non-modal window
    window.setWindowModality(Qt.WindowModality.NonModal)
    window.show()
    
    # Run event loop
    result = app.exec()
    
    # Print results
    print("\n" + "="*60)

    if window.result() == QDialog.DialogCode.Accepted:
        print("✓ Configuration SAVED to evt-config.yaml")
        print("="*60)
        print("\nUpdated settings:")
        print(f"  Markers: {len(config.MARKER_KEYS)} configured")
        print(f"  Marker Keys: {config.MARKER_KEYS}")
        print(f"  Window Title: {config.WINDOW_TITLE}")
        print(f"  Marker Float: {config.MARKER_FLOAT_ENABLED}")
        print(f"  CSV Plot: {config.CSV_PLOT_ENABLED}")
        print(f"  Playback FPS: {config.PLAYBACK_FPS}")
        print(f"  Video FPS: {config.VIDEO_FPS_ORIGINAL}")
        print(f"  Large Step: {config.LARGE_STEP_MULTIPLIER}")
        print(f"  Frame Step: {config.FRAME_STEP}")
        print(f"  Auto Search: {config.AUTO_SEARCH_EVENTS}")
        print(f"  Default Path: {config.DEFAULT_WORK_PATH}")
        print(f"\n  Config file: {Path(config._config_file).absolute()}")
    else:
        print("Configuration CANCELLED - No changes saved")
    print("="*60 + "\n")
    
    sys.exit(result)