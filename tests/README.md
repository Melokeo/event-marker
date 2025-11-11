# Event Marker Tests

## Setup

1. Place the test video file in `tests/assets/`:
   ```
   tests/assets/frame_counter_11988_4200.mp4
   ```

2. Install test dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

## Running Tests

Run all tests:
```bash
pytest
```

Run with verbose output:
```bash
pytest -v
```

Run specific test file:
```bash
pytest tests/test_video_player.py
```

Run specific test:
```bash
pytest tests/test_video_player.py::TestVideoPlayer::test_load_video
```

## Test Coverage

Generate coverage report:
```bash
pytest --cov=src --cov-report=html
```

View coverage in browser:
```bash
# Windows
start htmlcov/index.html

# Linux/Mac
open htmlcov/index.html
```

## Notes

- Tests require a GUI environment (X server on Linux, display on Windows/Mac)
- Some tests may be skipped if the test video is not found
- Tests create a QApplication instance that persists across the session
