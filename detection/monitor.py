"""Reads frames on the local machine and runs the fall rules. Frames are never saved."""
import threading
import time

import cv2

from .rules import FallDetector, Settings, sample_from_landmarks

SKELETON = [(11, 12), (11, 23), (12, 24), (23, 24), (11, 13), (13, 15), (12, 14), (14, 16),
            (23, 25), (25, 27), (24, 26), (26, 28)]


class CameraUnavailable(RuntimeError):
    pass


def open_capture(source):
    if isinstance(source, int):
        capture = cv2.VideoCapture(source, cv2.CAP_DSHOW)
    else:
        capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        capture.release()
        raise CameraUnavailable("The camera or video could not be opened.")
    return capture


class Monitor(threading.Thread):
    def __init__(self, source, estimator, on_fall, on_end, threshold=0.6, capture_factory=open_capture):
        super().__init__(daemon=True)
        self.is_file = not isinstance(source, int)
        self._capture = capture_factory(source)
        self._estimator = estimator
        self._on_fall = on_fall
        self._on_end = on_end
        self._detector = FallDetector(Settings(threshold=threshold))
        self._stop_event = threading.Event()
        self._paused = threading.Event()
        self._reset = threading.Event()
        self._frame_lock = threading.Lock()
        self._jpeg = None
        self.person_visible = False

    @property
    def latest_jpeg(self):
        with self._frame_lock:
            return self._jpeg

    def stop(self):
        self._stop_event.set()

    @property
    def stopped(self):
        return self._stop_event.is_set()

    def pause(self):
        self._paused.set()

    def resume(self):
        self._reset.set()
        self._paused.clear()

    def run(self):
        reason = "stopped"
        started = time.monotonic()
        fps = self._capture.get(cv2.CAP_PROP_FPS) or 15.0
        index = 0
        last_ms = -1
        try:
            while not self._stop_event.is_set():
                ok, frame = self._capture.read()
                if not ok:
                    reason = "video_finished" if self.is_file else "camera_lost"
                    break
                index += 1
                t = index / fps if self.is_file else time.monotonic() - started
                if self._reset.is_set():
                    self._reset.clear()
                    self._detector.reset()
                landmarks = None
                if not self._paused.is_set():
                    ms = max(int(t * 1000), last_ms + 1)
                    last_ms = ms
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    landmarks = self._estimator.detect(rgb, ms)
                    height, width = frame.shape[:2]
                    sample = None
                    if landmarks:
                        sample = sample_from_landmarks(landmarks, t, width / height)
                    self.person_visible = sample is not None
                    score = self._detector.update(sample, t)
                    if score is not None:
                        self.pause()
                        self._on_fall(score)
                self._publish(frame, landmarks)
                if self.is_file:
                    delay = started + index / fps - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
        except Exception as error:  # A detection error must never end silently.
            reason = f"error:{type(error).__name__}"
        finally:
            self._stop_event.set()
            self._capture.release()
            self._estimator.close()
            self._on_end(reason)

    def _publish(self, frame, landmarks):
        if landmarks:
            height, width = frame.shape[:2]
            point = lambda i: (int(landmarks[i].x * width), int(landmarks[i].y * height))
            for a, b in SKELETON:
                cv2.line(frame, point(a), point(b), (180, 220, 60), 2)
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            with self._frame_lock:
                self._jpeg = encoded.tobytes()
