"""PoseFrame の列とランドマークJSONの相互変換。"""
import json
from pathlib import Path

import numpy as np

from pose_estimator import NUM_LANDMARKS, PoseFrame
from video_io import VideoInfo


def pose_to_dict(pose: PoseFrame) -> dict:
    d = {"frame": pose.frame_index, "timestamp_ms": pose.timestamp_ms, "detected": pose.detected}
    if pose.detected:
        d["landmarks"] = pose.landmarks.round(5).tolist()
        d["world_landmarks"] = pose.world_landmarks.round(5).tolist()
        d["visibility"] = pose.visibility.round(4).tolist()
    return d


def pose_from_dict(d: dict) -> PoseFrame:
    if not d["detected"]:
        return PoseFrame(d["frame"], d["timestamp_ms"], None, None, None)
    return PoseFrame(
        frame_index=d["frame"],
        timestamp_ms=d["timestamp_ms"],
        landmarks=np.array(d["landmarks"], dtype=np.float32),
        world_landmarks=np.array(d["world_landmarks"], dtype=np.float32),
        visibility=np.array(d["visibility"], dtype=np.float32),
    )


def save_landmarks(path: Path, source: Path, model_name: str, info: VideoInfo, poses: list[PoseFrame]) -> None:
    data = {
        "source": str(source),
        "model": model_name,
        "fps": info.fps,
        "width": info.width,
        "height": info.height,
        "num_landmarks": NUM_LANDMARKS,
        "frames": [pose_to_dict(p) for p in poses],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def load_landmarks(path: Path) -> tuple[dict, list[PoseFrame]]:
    """(メタ情報, PoseFrame の列) を返す。メタ情報は frames 以外のキー。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    frames = data.pop("frames")
    return data, [pose_from_dict(d) for d in frames]
