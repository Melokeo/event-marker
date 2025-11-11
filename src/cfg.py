"""
Singleton configuration manager for evtmkr
"""

import yaml
from pathlib import Path
from typing import Any
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

class ConfigMeta(type):
    """Metaclass for singleton pattern"""
    _instances = {}
    
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]

class Config(metaclass=ConfigMeta):
    """Configuration manager that loads from yaml file."""
    
    def __init__(self, config_path: str = None):
        # only initialize once
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        
        self._config_file = config_path or "evt-config.yaml"
        self._data = {}
        self._cache = {}
        self.load_config()
    
    def load_config(self, config_path: str = None):
        """load configuration from yaml file"""
        if config_path:
            self._config_file = config_path
            
        config_file = Path(self._config_file)
        
        # look for config in multiple locations
        search_paths = [
            config_file,  # current directory
            Path(__file__).parent / config_file,  # script directory
            Path.home() / ".eventmarker" / config_file,  # user home
        ]
        
        for path in search_paths:
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        self._data = yaml.safe_load(f)
                    print(f"Loaded config from {path}")
                    self._process_config()
                    return
                except Exception as e:
                    print(f"Error loading config from {path}: {e}")
        
        # if no config found, use defaults
        print(f"No config file found, using defaults")
        self._use_defaults()
    
    def _use_defaults(self):
        """set default values if config file not found"""
        self._data = {
            'marker': {
                'colors': [
                    [172, 157, 147], [199, 184, 164], [147, 155, 144],
                    [180, 166, 169], [158, 170, 177]
                ],
                'keys': ['Key_1', 'Key_2', 'Key_3', 'Key_4', 'Key_5'],
                'pairing': {
                    'enabled': True,
                    'rules': {'1': '4'}
                }
            },
            'playback': {
                'fps': 30,
                'video_fps_original': 119.88,
                'large_step_multiplier': 6,
                'frame_step': 1,
                'frame_compensation': {
                    119.88: 3, 120: 3, 60: 2, 30: 1, 24: 1
                }
            },
            'timeline': {
                'marker_offset': [5, 15]
            },
            'ui': {
                'window_title': 'Event Marker (Refactored)',
                'marker_float_enabled': True,
                'csv_plot_enabled': True
            },
            'workspace': {
                'default_path': r'P:\projects\monkeys\Chronic_VLL\DATA\Pici',
                'auto_search_events': True
            }
        }
        self._process_config()
    
    def _process_config(self):
        """process loaded config and create cached objects"""
        # convert color lists to QColor objects
        self._cache['marker_colors'] = [
            QColor(*rgb) for rgb in self._data['marker']['colors']
        ]
        
        # convert key strings to Qt key constants
        self._cache['marker_keys'] = [
            getattr(Qt.Key, key) for key in self._data['marker']['keys']
        ]
        
        # convert frame_compensation keys to float
        comp = self._data['playback'].get('frame_compensation', {})
        self._cache['frame_compensation'] = {
            float(k): v for k, v in comp.items()
        }
    
    def reload(self, config_path: str = None):
        """reload configuration, useful for runtime changes"""
        self._cache.clear()
        self.load_config(config_path)
    
    def save(self, config_path: str = None):
        """save current configuration to yaml file"""
        save_path = config_path or self._config_file
        try:
            # convert QColor back to lists for saving
            save_data = self._data.copy()
            if 'marker' in save_data and 'colors' not in save_data['marker']:
                # if colors were modified at runtime
                save_data['marker']['colors'] = [
                    [c.red(), c.green(), c.blue()] 
                    for c in self._cache.get('marker_colors', [])
                ]
            
            with open(save_path, 'w', encoding='utf-8') as f:
                yaml.dump(save_data, f, default_flow_style=False, sort_keys=False)
            print(f"Saved config to {save_path}")
        except Exception as e:
            print(f"Error saving config: {e}")
    
    # property accessors
    @property
    def MARKER_COLORS(self) -> list[QColor]:
        return self._cache.get('marker_colors', [])
    
    @property
    def MARKER_KEYS(self) -> list:
        return self._cache.get('marker_keys', [])
    
    @property
    def PLAYBACK_FPS(self) -> int:
        return self._data.get('playback', {}).get('fps', 30)
    
    @property
    def VIDEO_FPS_ORIGINAL(self) -> float:
        return self._data.get('playback', {}).get('video_fps_original', 119.88)
    
    @property
    def LARGE_STEP_MULTIPLIER(self) -> int:
        return self._data.get('playback', {}).get('large_step_multiplier', 6)
    
    @property
    def FRAME_STEP(self) -> int:
        return self._data.get('playback', {}).get('frame_step', 1)
    
    @property
    def PAIRING_ENABLED(self) -> bool:
        return self._data.get('marker', {}).get('pairing', {}).get('enabled', True)
    
    @property
    def PAIRING_RULES(self) -> dict:
        return self._data.get('marker', {}).get('pairing', {}).get('rules', {})
    
    @property
    def TIMELINE_MARKER_OFFSET(self) -> list:
        return self._data.get('timeline', {}).get('marker_offset', [5, 15])
    
    @property
    def WINDOW_TITLE(self) -> str:
        return self._data.get('ui', {}).get('window_title', 'Event Marker')
    
    @property
    def MARKER_FLOAT_ENABLED(self) -> bool:
        return self._data.get('ui', {}).get('marker_float_enabled', True)
    
    @property
    def CSV_PLOT_ENABLED(self) -> bool:
        return self._data.get('ui', {}).get('csv_plot_enabled', True)
    
    @property
    def DEFAULT_WORK_PATH(self) -> str:
        return self._data.get('workspace', {}).get('default_path', '')
    
    @property
    def AUTO_SEARCH_EVENTS(self) -> bool:
        return self._data.get('workspace', {}).get('auto_search_events', True)
    
    def get_frame_compensation(self, fps: float) -> int:
        """get compensation value for given fps"""
        comp_dict = self._cache.get('frame_compensation', {})
        if fps in comp_dict:
            return comp_dict[fps]
        # find closest fps
        if comp_dict:
            closest_fps = min(comp_dict.keys(), key=lambda x: abs(x - fps))
            return comp_dict[closest_fps]
        return 3  # default
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """get config value using dot notation (e.g., 'playback.fps')"""
        keys = key_path.split('.')
        value = self._data
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return default
            else:
                return default
        return value
    
    def set(self, key_path: str, value: Any):
        """set config value using dot notation"""
        keys = key_path.split('.')
        data = self._data
        for key in keys[:-1]:
            if key not in data:
                data[key] = {}
            data = data[key]
        data[keys[-1]] = value
        
        # reprocess if needed
        if keys[0] in ['marker', 'playback']:
            self._process_config()


# create global instance
config = Config()