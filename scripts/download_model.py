"""Download the MediaPipe pose model (about 6 MB) used for fall detection."""
import pathlib
import urllib.request

URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
)
target = pathlib.Path(__file__).resolve().parent.parent / "models" / "pose_landmarker_lite.task"
target.parent.mkdir(exist_ok=True)
urllib.request.urlretrieve(URL, target)
print(f"Saved {target} ({target.stat().st_size} bytes)")
