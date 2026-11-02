"""MediaPipe pose landmarks for one video stream."""
import pathlib

MODEL_PATH = pathlib.Path(__file__).resolve().parent.parent / "models" / "pose_landmarker_lite.task"


class ModelMissing(RuntimeError):
    pass


class PoseEstimator:
    def __init__(self, model_path=MODEL_PATH):
        if not pathlib.Path(model_path).exists():
            raise ModelMissing("Pose model not found. Run: python scripts/download_model.py")
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import (
            PoseLandmarker,
            PoseLandmarkerOptions,
            RunningMode,
        )

        self._mp = mp
        self._landmarker = PoseLandmarker.create_from_options(
            PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(model_path)),
                running_mode=RunningMode.VIDEO,
                num_poses=1,
            )
        )

    def detect(self, rgb_frame, timestamp_ms):
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb_frame)
        result = self._landmarker.detect_for_video(image, timestamp_ms)
        return result.pose_landmarks[0] if result.pose_landmarks else None

    def close(self):
        self._landmarker.close()
