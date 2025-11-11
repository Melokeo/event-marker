from collections import defaultdict

class EventManager:
    """Handles all logic for creating, storing, and modifying event markers."""
    def __init__(self):
        self.markers = defaultdict(list)
        self.undo_stack = []
        self.redo_stack = []

    def add_marker(self, event_type, frame):
        key = str(event_type)
        if frame not in self.markers[key]:
            self.markers[key].append(frame)
            self.markers[key].sort()
            self.undo_stack.append(('add', key, frame))
            self.redo_stack.clear()
            print(f"Marked event {key} at frame {frame}")
            return True
        return False

    def remove_marker_at_frame(self, frame):
        for mtype, frames in self.markers.items():
            if frame in frames:
                frames.remove(frame)
                self.undo_stack.append(('remove', mtype, frame))
                self.redo_stack.clear()
                print(f"Deleted marker {mtype} @ frame {frame}")
                return True
        return False

    def undo(self):
        if not self.undo_stack:
            return
        
        action_tuple = self.undo_stack.pop()
        action = action_tuple[0]
        
        if action == 'add':
            _, key, frame = action_tuple
            self.markers[key].remove(frame)
            self.redo_stack.append(action_tuple)
        elif action == 'remove':
            _, key, frame = action_tuple
            self.markers[key].append(frame)
            self.markers[key].sort()
            self.redo_stack.append(action_tuple)
        elif action == 'move':
            _, key, old_frame, new_frame = action_tuple
            self.markers[key].remove(new_frame)
            self.markers[key].append(old_frame)
            self.markers[key].sort()
            self.redo_stack.append(action_tuple)
        
        print(f"Undid {action} for event {action_tuple[1]}")

    def redo(self):
        if not self.redo_stack:
            return
            
        action_tuple = self.redo_stack.pop()
        action = action_tuple[0]

        if action == 'add':
            _, key, frame = action_tuple
            self.markers[key].append(frame)
            self.markers[key].sort()
            self.undo_stack.append(action_tuple)
        elif action == 'remove':
            _, key, frame = action_tuple
            self.markers[key].remove(frame)
            self.undo_stack.append(action_tuple)
        elif action == 'move':
            _, key, old_frame, new_frame = action_tuple
            self.markers[key].remove(old_frame)
            self.markers[key].append(new_frame)
            self.markers[key].sort()
            self.undo_stack.append(action_tuple)

        print(f"Redid {action} for event {action_tuple[1]}")

    def get_all_marker_frames(self):
        return sorted([frame for frames in self.markers.values() for frame in frames])

    def clear(self):
        self.markers.clear()
        self.undo_stack.clear()
        self.redo_stack.clear()