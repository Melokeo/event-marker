import re
from collections import defaultdict

ADD_RE = re.compile(r"Marked event (\d+) at frame (\d+)")
DEL_RE = re.compile(r"Deleted marker (\d+) @ frame (\d+)")
UNDO_REMOVE_RE = re.compile(r"Undid remove for event (\d+)")
UNDO_ADD_RE = re.compile(r"Undid add for event (\d+)")

def infer_final_events(original: dict, history: str) -> dict[str, list[int]]:
    """
    Apply operation history to an initial dict of event->frames.
    Supports: add, delete, and LIFO undos for add/remove per event.
    """
    # normalize keys to strings and frames to sets for idempotency
    current = {str(k): set(v) for k, v in original.items()}
    add_stack = defaultdict(list)     # per-event stack of added frames (for undo add)
    del_stack = defaultdict(list)     # per-event stack of removed frames (for undo remove)

    for raw in history.splitlines():
        line = raw.strip()
        if not line:
            continue

        m = ADD_RE.match(line)
        if m:
            ev, frame = m.group(1), int(m.group(2))
            if ev not in current:
                current[ev] = set()
            current[ev].add(frame)
            add_stack[ev].append(frame)
            continue

        m = DEL_RE.match(line)
        if m:
            ev, frame = m.group(1), int(m.group(2))
            if ev not in current:
                current[ev] = set()
            # Only record a removal if it actually removed something
            if frame in current[ev]:
                current[ev].remove(frame)
                del_stack[ev].append(frame)
            continue

        m = UNDO_REMOVE_RE.match(line)
        if m:
            ev = m.group(1)
            if del_stack[ev]:
                frame = del_stack[ev].pop()
                current[ev].add(frame)
            continue

        m = UNDO_ADD_RE.match(line)
        if m:
            ev = m.group(1)
            if add_stack[ev]:
                frame = add_stack[ev].pop()
                current[ev].discard(frame)
            continue

        # ignore all other lines (e.g., "No audio device detected", "Loaded events ...")

    return {ev: sorted(frames) for ev, frames in current.items()}

# Example:
# final_state = infer_final_events(original, history_text)
