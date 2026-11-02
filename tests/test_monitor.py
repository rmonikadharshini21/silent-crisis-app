"""Runs the real Monitor thread with a fake camera and fake pose landmarks."""
import os
from types import SimpleNamespace

import cv2
import numpy as np

from detection.monitor import Monitor

FPS = 15.0


class FakeCapture:
    def __init__(self, frames):
        self.frames = frames
        self.released = False

    def read(self):
        if self.frames <= 0:
            return False, None
        self.frames -= 1
        return True, np.zeros((90, 160, 3), dtype=np.uint8)

    def get(self, _prop):
        return FPS

    def release(self):
        self.released = True


def landmarks(shoulder_y, hip_y, hip_x=0.5):
    point = lambda x, y: SimpleNamespace(x=x, y=y, visibility=0.9)
    items = [point(0.5, 0.1) for _ in range(33)]
    items[11] = items[12] = point(0.5, shoulder_y)
    items[23] = items[24] = point(hip_x, hip_y)
    return items


class ScriptedEstimator:
    """Upright for 2 seconds, falls in under a second, then lies still."""

    def __init__(self):
        self.calls = 0
        self.closed = False

    def detect(self, _rgb, _ms):
        self.calls += 1
        t = self.calls / FPS
        if t < 2:
            return landmarks(0.3, 0.55)
        if t < 2.5:
            p = (t - 2) / 0.5
            return landmarks(0.3 + 0.5 * p, 0.55 + 0.25 * p, 0.5 + 0.3 * p)
        return landmarks(0.8, 0.8, 0.8)

    def close(self):
        self.closed = True


def run_monitor(frames, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    falls, ends = [], []
    estimator = ScriptedEstimator()
    capture = FakeCapture(frames)
    monitor = Monitor(
        "clip.mp4", estimator, falls.append, ends.append, capture_factory=lambda _: capture,
    )
    monitor.start()
    monitor.join(timeout=20)
    assert not monitor.is_alive()
    return monitor, estimator, capture, falls, ends


def test_fall_is_reported_once_and_detection_pauses(tmp_path, monkeypatch):
    monitor, estimator, capture, falls, ends = run_monitor(int(FPS * 6), tmp_path, monkeypatch)
    assert len(falls) == 1 and falls[0] >= 0.6
    assert estimator.calls < FPS * 6  # Paused after the fall until the outcome is known.
    assert ends == ["video_finished"]
    assert capture.released and estimator.closed
    assert monitor.latest_jpeg.startswith(b"\xff\xd8")


def test_no_video_file_is_written(tmp_path, monkeypatch):
    run_monitor(int(FPS * 4), tmp_path, monkeypatch)
    assert os.listdir(tmp_path) == []


def test_detection_error_ends_visibly_and_releases_camera(tmp_path, monkeypatch):
    class Broken(ScriptedEstimator):
        def detect(self, _rgb, _ms):
            raise ValueError("boom")

    ends = []
    capture = FakeCapture(5)
    estimator = Broken()
    monitor = Monitor("clip.mp4", estimator, print, ends.append, capture_factory=lambda _: capture)
    monitor.run()
    assert ends == ["error:ValueError"] and capture.released and estimator.closed


def test_jpeg_encoding_is_available():
    ok, _ = cv2.imencode(".jpg", np.zeros((4, 4, 3), dtype=np.uint8))
    assert ok
