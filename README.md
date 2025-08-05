# event-marker

A qt-based video player for manual, frame level event marking.

Was written after being tortured by OOM caused by previous matlab playback. 

## Playback
- `← →` steps `STEP` number of frames (default `STEP = 1 frame`);
- `↑ ↓` steps more (`LARGE_STEP_MULTIPLIER*STEP`) of frames;
- `space` for play/pause;
- `numpad +-` adjust playback speed by 1.1x/0.9x;
- `numpad Enter` resets speed to 1x;
- double click on the right-bottom frame number label to enter and jump to target frame.
- timeline is draggable.

## Marking controls
- `1..5` (above qwerty) sets marker at current timepoint;
- markers will appear as dots and lines above timeline; left click will jump to that frame;
- `CTRL+Z` undo, `CTRL+SHIFT+Z` redo (no ctrl+Y, no)
- marked events will be printed when the window closes
- the events will be saved, if any change were made, on:
  - new video is opened
  - window is closed
  - pressing `CTRL+S`
