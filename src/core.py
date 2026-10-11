"""
core.py - Core detection engine (audio removed)
"""

import subprocess
import json
from dataclasses import dataclass, field
from typing import Optional, Tuple, List
import numpy as np
import os

# ─── Configuration ───────────────────────────────────────────────────────────

@dataclass
class Config:
    # Visual analysis
    frame_extraction_fps: float = 30.0
    purple_hue_min: float = 250.0
    purple_hue_max: float = 275.0
    purple_saturation_min: float = 0.75
    purple_value_min: float = 0.10
    purple_dominance_ratio: float = 0.60
    pixel_difference: float = 40.0
    pixel_change_ratio: float = 0.50

    # Search bounds
    search_window_sec: float = 25.0
    min_load_duration_sec: float = 0.3
    max_load_duration_sec: float = 50.0

    # Transition detection
    transition_frames_needed: int = 2


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclass
class LoadingSegment:
    start_sec: float
    end_sec: float
    confidence: float = 0.0

    @property
    def duration(self) -> float:
        return self.end_sec - self.start_sec

    def to_dict(self) -> dict:
        return {
            "start_sec": round(self.start_sec, 3),
            "end_sec": round(self.end_sec, 3),
            "duration_sec": round(self.duration, 3),
            "confidence": round(self.confidence, 3),
        }

    def __repr__(self):
        return f"[{self.start_sec:.2f}s -> {self.end_sec:.2f}s] ({self.duration:.2f}s, conf={self.confidence:.0%})"


@dataclass
class AnalysisResult:
    video_path: str
    total_duration_sec: float
    segments: List[LoadingSegment] = field(default_factory=list)
    rta_time_sec: float = 0.0

    @property
    def total_loading_time(self) -> float:
        return sum(s.duration for s in self.segments)

    @property
    def adjusted_time(self) -> float:
        return self.rta_time_sec - self.total_loading_time

    def to_report(self) -> dict:
        return {
            "video": self.video_path,
            "total_duration_sec": round(self.total_duration_sec, 2),
            "rta_time_sec": round(self.rta_time_sec, 2),
            "segments": [s.to_dict() for s in self.segments],
            "segment_count": len(self.segments),
            "total_loading_sec": round(self.total_loading_time, 3),
            "adjusted_time_sec": round(self.adjusted_time, 3),
        }


# ─── Video Acquisition ───────────────────────────────────────────────────────

def get_video_duration(video_path: str) -> float:
    """Get video duration in seconds via ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


# ─── Visual Analysis ─────────────────────────────────────────────────────────

def extract_frame_rgb(
    video_path: str,
    timestamp_sec: float,
) -> Optional[np.ndarray]:
    """
    Extract a single RGB frame at a given timestamp.
    Returns (640, 360, 3) uint8 array or None.
    """
    width, height = 640, 360

    cmd = [
        "ffmpeg",
        "-ss", f"{float(timestamp_sec):.3f}",
        "-i", video_path,
        "-frames:v", "1",
        "-vf", f"scale={width}:{height}",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-hide_banner",
        "-loglevel", "error",
        "-"
    ]

    result = subprocess.run(cmd, capture_output=True)
    expected_bytes = width * height * 3

    if result.returncode != 0 or len(result.stdout) != expected_bytes:
        return None

    return np.frombuffer(result.stdout, dtype=np.uint8).reshape(height, width, 3).copy()

def rgb_to_hsv(rgb: np.ndarray) -> np.ndarray:
    """Convert RGB uint8 array to HSV float (H: 0-360, S: 0-1, V: 0-1)."""
    rgb_norm = rgb.astype(np.float32) / 255.0
    r, g, b = rgb_norm[:, :, 0], rgb_norm[:, :, 1], rgb_norm[:, :, 2]

    maxc = np.max(rgb_norm, axis=2)
    minc = np.min(rgb_norm, axis=2)
    delta = maxc - minc

    # Hue calculation
    h = np.zeros_like(maxc)
    mask = delta > 0
    rc = mask & (rgb_norm[:, :, 0] == maxc)
    h[rc] = 60.0 * (((g[rc] - b[rc]) / delta[rc]) % 6.0)
    gc = mask & (rgb_norm[:, :, 1] == maxc)
    h[gc] = 60.0 * (((b[gc] - r[gc]) / delta[gc]) + 2.0)
    bc = mask & (rgb_norm[:, :, 2] == maxc)
    h[bc] = 60.0 * (((r[bc] - g[bc]) / delta[bc]) + 4.0)

    # Saturation
    s = np.where(maxc > 0, delta / (maxc + 1e-10), 0)

    # Value
    v = maxc

    return np.stack([h, s, v], axis=2)


def is_purple_frame(frame: np.ndarray, config: Config) -> Tuple[bool, float]:
    """
    Check if a frame is predominantly purple (loading screen).
    Returns (is_purple, purple_ratio).
    """
    hsv = rgb_to_hsv(frame)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

    purple_mask = (
        ((h >= config.purple_hue_min) | (h <= (config.purple_hue_max - 360))) &
        (s >= config.purple_saturation_min) &
        (v >= config.purple_value_min)
    )

    ratio = np.mean(purple_mask)
    return ratio >= config.purple_dominance_ratio, float(ratio)


def is_different_from(ref_frame: np.ndarray, frame: np.ndarray, config: Config) -> Tuple[bool, float]:
    """
    Check if a frame is different enough from a reference frame (KeyArt).
    Return (is_different, difference_ratio).
    """
    f1 = ref_frame.astype(np.float32)
    f2 = frame.astype(np.float32)

    diff = np.abs(f1 - f2)
    threshold = config.pixel_difference
    change_ratio = np.mean(np.any(diff > threshold, axis=2))

    return change_ratio >= config.pixel_change_ratio, float(change_ratio)


def three_frame_diff(f1: np.ndarray, f2: np.ndarray, f3: np.ndarray, config: Config) -> Tuple[bool, bool]:
    """
    Compare three successive frames to detect abrupt transitions.
    Returns (first_change, second_change) booleans.
    """
    diff12 = is_different_from(f1, f2, config)[1]
    diff23 = is_different_from(f2, f3, config)[1]

    if diff12 < 100 * diff23:
        return (False, True)
    if diff23 < 100 * diff12:
        return (True, False)
    return (False, False)


def compute_visual_confidence(anchor_sec: float, boundary_sec: float,
                               is_start: bool = True) -> float:
    """
    Simple visual confidence based on search distance from anchor.
    """
    distance = abs(anchor_sec - boundary_sec)
    max_dist = Config.search_window_sec
    confidence = max(0.0, 1.0 - (distance / max_dist))
    return float(confidence)


# ─── Core Detection: Anchor-Based Boundary Search ───────────────────────────

def find_segment_boundary(
    anchor_sec: float,
    video_path: str,
    config: Config,
    forward: bool = False
) -> Tuple[float, float]:
    """
    Search boundary of a loading section from anchor.
    When forward is False it goes backward.
    Returns (boundary_time_sec, confidence).
    """
    fps = config.frame_extraction_fps
    step_sec = 1.0 / fps * 32
    min_step_sec = 1.0 / fps
    max_offset = int(config.search_window_sec * fps)

    ref_frame = extract_frame_rgb(video_path, float(anchor_sec))
    if ref_frame is None:
        print(f"[warn] Could not extract reference frame at {anchor_sec:.2f}s")
        return anchor_sec, 0.0

    t_off = float(anchor_sec)
    cnt = 0

    while cnt < max_offset:
        temp_t = t_off - (-1) ** forward * step_sec
        temp_frame = extract_frame_rgb(video_path, temp_t)

        if temp_frame is None:
            print(f"[warn] Could not extract frame at {temp_t:.2f}s, stopping search")
            break

        is_purple, _ = is_purple_frame(temp_frame, config)

        if is_purple:
            boundary = temp_t
            confidence = compute_visual_confidence(anchor_sec, boundary, not forward)
            return boundary, confidence

        is_diff, _ = is_different_from(ref_frame, temp_frame, config)

        if is_diff:
            if min_step_sec < step_sec:
                step_sec /= 2
            else:
                frame1 = extract_frame_rgb(video_path, t_off)
                frame2 = extract_frame_rgb(video_path, t_off - (-1) ** forward * step_sec)
                frame3 = extract_frame_rgb(video_path, t_off - 2 * (-1) ** forward * step_sec)

                if all(f is not None for f in [frame1, frame2, frame3]):
                    b1, b2 = three_frame_diff(frame1, frame2, frame3, config)
                    if b1:
                        boundary = t_off
                        confidence = compute_visual_confidence(anchor_sec, boundary, not forward)
                        return boundary, confidence
                    elif b2:
                        boundary = t_off - (-1) ** forward * step_sec
                        confidence = compute_visual_confidence(anchor_sec, boundary, not forward)
                        return boundary, confidence
        else:
            t_off = temp_t
        cnt += step_sec

    return anchor_sec, 0.1


def find_segment_start(
    anchor_sec: float,
    video_path: str,
    config: Config,
) -> Tuple[float, float]:
    return find_segment_boundary(anchor_sec, video_path, config, False)


def find_segment_end(
    anchor_sec: float,
    video_path: str,
    config: Config,
) -> Tuple[float, float]:
    return find_segment_boundary(anchor_sec, video_path, config, True)


def detect_loading_from_anchor(
    anchor_sec: float,
    video_path: str,
    config: Config,
) -> Optional[LoadingSegment]:
    """Given an anchor timestamp within a loading segment, detect its boundaries."""
    print(f"\n[detect] Searching from anchor at {anchor_sec:.2f}s...")
    start_sec, start_conf = find_segment_start(anchor_sec, video_path, config)
    end_sec, end_conf = find_segment_end(anchor_sec, video_path, config)

    duration = end_sec - start_sec
    if duration < config.min_load_duration_sec:
        print(f"[detect] Segment too short ({duration:.2f}s < {config.min_load_duration_sec}s), skipping.")
        return None
    if duration > config.max_load_duration_sec:
        print(f"[detect] Segment too long ({duration:.2f}s > {config.max_load_duration_sec}s), skipping.")
        return None

    confidence = (start_conf + end_conf) / 2
    seg = LoadingSegment(start_sec=start_sec, end_sec=end_sec, confidence=confidence)
    print(f"[detect] Found: {seg}")
    return seg


# ─── CLI Helpers ────────────────────────────────────────────────────────────

def format_timestamp(seconds: float) -> str:
    m, s = divmod(float(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{int(h)}:{int(m):02d}:{s:06.3f}"
    return f"{int(m):02d}:{s:06.3f}"


def parse_timestamp(ts: str) -> float:
    """Parse 'HH:MM:SS.mmm', 'MM:SS.mmm', or 'SS.mmm' into seconds."""
    parts = ts.split(":")
    if len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    else:
        return float(parts[0])
