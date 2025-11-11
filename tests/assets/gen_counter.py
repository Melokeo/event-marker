import cv2
import numpy as np

def create_frame_counter_video(
    output_path: str = "frame_counter_11988_25000.mp4",
    fps: float = 119.88,
    total_frames: int = 25000,
    width: int = 100,
    height: int = 100
) -> None:
    # define codec and create video writer
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
    
    for frame_num in range(total_frames):
        # create black frame
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        
        # add frame number text
        text = str(frame_num)
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.3
        color = (255, 255, 255)  # white text
        thickness = 1
        
        # get text size for centering
        text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
        text_x = (width - text_size[0]) // 2
        text_y = (height + text_size[1]) // 2
        
        cv2.putText(frame, text, (text_x, text_y), font, font_scale, color, thickness)
        out.write(frame)
        
        # progress indicator every 1000 frames
        if frame_num % 1000 == 0:
            print(f"Progress: {frame_num}/{total_frames} frames")
    
    out.release()
    print(f"Video saved as {output_path}")

if __name__ == "__main__":
    create_frame_counter_video()