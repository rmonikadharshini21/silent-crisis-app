"""Fall rules: a sudden drop, then a low body position with little movement.

No trained model is involved. Coordinates are normalised to the image, with y
increasing downwards. These thresholds are starting values to tune with staged
falls on the demo laptop.
"""
import math
from dataclasses import dataclass, field

NOSE, L_SHOULDER, R_SHOULDER, L_HIP, R_HIP = 0, 11, 12, 23, 24
MIN_VISIBILITY = 0.4


@dataclass
class Sample:
    t: float
    cy: float  # Vertical centre of the torso.
    angle: float  # Torso angle from vertical, in degrees.
    length: float  # Torso length.
    visibility: float = 1.0


@dataclass
class Settings:
    threshold: float = 0.6
    drop_window: float = 1.0  # A drop must happen within this many seconds.
    min_drop: float = 0.10
    drop_ratio: float = 0.7  # Minimum drop, as a share of torso length.
    still_seconds: float = 2.0
    still_range: float = 0.05
    low_angle: float = 50.0
    recovered_angle: float = 40.0
    lost_seconds: float = 3.0
    timeout_seconds: float = 6.0


def sample_from_landmarks(landmarks, t, aspect=16 / 9):
    """Build a Sample from MediaPipe landmarks, or None if the body is not visible."""
    nose = landmarks[NOSE]
    shoulders = (landmarks[L_SHOULDER], landmarks[R_SHOULDER])
    hips = (landmarks[L_HIP], landmarks[R_HIP])
    if min(s.visibility for s in shoulders) < MIN_VISIBILITY:
        return None
    sx = sum(s.x for s in shoulders) / 2
    sy = sum(s.y for s in shoulders) / 2
    if min(h.visibility for h in hips) >= MIN_VISIBILITY:
        hx = sum(h.x for h in hips) / 2
        hy = sum(h.y for h in hips) / 2
        dx, dy = (hx - sx) * aspect, hy - sy
        cy = (sy + hy) / 2
        scale = 1.0
        visibility = min(s.visibility for s in (*shoulders, *hips))
    else:
        # A laptop webcam often sees only the upper body, so use head to shoulders.
        dx, dy = (sx - nose.x) * aspect, sy - nose.y
        cy = sy
        scale = 2.5
        visibility = min(nose.visibility, *(s.visibility for s in shoulders))
    return Sample(
        t=t,
        cy=cy,
        angle=math.degrees(math.atan2(abs(dx), abs(dy))),
        length=math.hypot(dx, dy) * scale,
        visibility=visibility,
    )


@dataclass
class FallDetector:
    settings: Settings = field(default_factory=Settings)

    def __post_init__(self):
        self.reset()

    def reset(self):
        self._history = []
        self._dropped_at = None
        self._baseline = 0.0
        self._drop = 0.0
        self._length = 0.0
        self._after = []
        self._last_seen = None

    def update(self, sample, t):
        """Feed one frame. Returns a confidence score when a fall is confirmed."""
        if self._dropped_at is None:
            return self._watch(sample, t)
        return self._confirm(sample, t)

    def _watch(self, sample, t):
        s = self.settings
        if sample is None:
            # The person may have dropped out of the bottom of the frame.
            if self._history:
                self._last_seen = self._history[-1].t
                peak = min(self._history, key=lambda h: h.cy)
                last = self._history[-1]
                needed = max(s.min_drop, s.drop_ratio * peak.length) * 0.5
                if last.cy - peak.cy >= needed and last.t - peak.t <= s.drop_window:
                    self._begin_drop(peak, last.cy - peak.cy, last.t)
                    return None
            self._history = []
            return None
        self._history = [h for h in self._history if sample.t - h.t <= s.drop_window]
        self._history.append(sample)
        peak = min(self._history, key=lambda h: h.cy)
        drop = sample.cy - peak.cy
        if drop >= max(s.min_drop, s.drop_ratio * peak.length):
            self._begin_drop(peak, drop, sample.t)
        return None

    def _begin_drop(self, peak, drop, t):
        self._dropped_at = t
        self._baseline = peak.cy
        self._drop = drop
        self._length = peak.length or 0.2
        self._after = []
        self._last_seen = t

    def _confirm(self, sample, t):
        s = self.settings
        if sample is None:
            if t - self._last_seen >= s.lost_seconds:
                self.reset()
                score = 0.65  # Weaker evidence than seeing the person lie still.
                return score if score >= s.threshold else None
            return None

        self._last_seen = sample.t
        recovered = (
            sample.angle < s.recovered_angle
            and sample.cy < self._baseline + 0.4 * self._drop
        )
        if recovered or sample.t - self._dropped_at > s.timeout_seconds:
            self.reset()
            return None

        self._drop = max(self._drop, sample.cy - self._baseline)
        self._after.append(sample)
        window = [a for a in self._after if sample.t - a.t <= s.still_seconds * 0.75]
        if sample.t - self._dropped_at < s.still_seconds:
            return None

        low = sample.angle >= s.low_angle and sample.cy >= self._baseline + 0.5 * self._drop
        spread = max(a.cy for a in window) - min(a.cy for a in window)
        if not low or spread >= s.still_range:
            return None

        score = (
            0.35 * min(1.0, self._drop / (1.2 * self._length))
            + 0.35 * min(1.0, sample.angle / 80.0)
            + 0.20 * (1.0 - spread / s.still_range)
            + 0.10 * sample.visibility
        )
        self.reset()
        return round(score, 2) if score >= s.threshold else None
