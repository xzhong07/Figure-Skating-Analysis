"""MediaPipe PoseLandmarker（Tasks API, VIDEO モード）の薄いラッパー。"""
from dataclasses import dataclass
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python import vision

NUM_LANDMARKS = 33


@dataclass
class PoseFrame:
    """1フレーム分の推定結果。未検出のときは各配列が None。"""

    frame_index: int
    timestamp_ms: int
    # (33, 3): 画像に対する正規化座標 x, y（0〜1）と相対深度 z
    landmarks: np.ndarray | None
    # (33, 3): 腰の中心を原点としたメートル単位の3D座標
    world_landmarks: np.ndarray | None
    # (33,): 各関節が見えている確からしさ（0〜1）
    visibility: np.ndarray | None

    @property
    def detected(self) -> bool:
        return self.landmarks is not None


class PoseEstimator:
    def __init__(
        self,
        model_path: str | Path,
        min_detection_confidence: float = 0.5,
        min_presence_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
    ) -> None:
        model_path = Path(model_path)
        if not model_path.exists():
            raise FileNotFoundError(
                f"モデルファイルが見つかりません: {model_path}\n"
                "python scripts/download_model.py を実行してください。"
            )
        options = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=min_detection_confidence,
            min_pose_presence_confidence=min_presence_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._landmarker = vision.PoseLandmarker.create_from_options(options)
        self._last_timestamp_ms = -1

    def process(self, frame_bgr: np.ndarray, frame_index: int, timestamp_ms: int) -> PoseFrame:
        # VIDEO モードはタイムスタンプが単調増加である必要がある
        timestamp_ms = max(timestamp_ms, self._last_timestamp_ms + 1)
        self._last_timestamp_ms = timestamp_ms

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, timestamp_ms)

        if not result.pose_landmarks:
            return PoseFrame(frame_index, timestamp_ms, None, None, None)

        lms = result.pose_landmarks[0]
        world = result.pose_world_landmarks[0]
        return PoseFrame(
            frame_index=frame_index,
            timestamp_ms=timestamp_ms,
            landmarks=np.array([[p.x, p.y, p.z] for p in lms], dtype=np.float32),
            world_landmarks=np.array([[p.x, p.y, p.z] for p in world], dtype=np.float32),
            visibility=np.array([p.visibility or 0.0 for p in lms], dtype=np.float32),
        )

    def close(self) -> None:
        self._landmarker.close()

    def __enter__(self) -> "PoseEstimator":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
