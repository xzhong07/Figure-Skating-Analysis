"""推定したランドマークをフレームに描画する。"""
from dataclasses import dataclass

import cv2
import numpy as np

from pose_estimator import PoseFrame

# MediaPipe Pose のランドマーク番号（顔の細かい点は鼻だけ使う）
NOSE = 0
L_SHOULDER, R_SHOULDER = 11, 12
L_ELBOW, R_ELBOW = 13, 14
L_WRIST, R_WRIST = 15, 16
L_HIP, R_HIP = 23, 24
L_KNEE, R_KNEE = 25, 26
L_ANKLE, R_ANKLE = 27, 28
L_HEEL, R_HEEL = 29, 30
L_FOOT, R_FOOT = 31, 32

LEFT_POINTS = [L_SHOULDER, L_ELBOW, L_WRIST, L_HIP, L_KNEE, L_ANKLE, L_HEEL, L_FOOT]
RIGHT_POINTS = [R_SHOULDER, R_ELBOW, R_WRIST, R_HIP, R_KNEE, R_ANKLE, R_HEEL, R_FOOT]

LEFT_BONES = [
    (L_SHOULDER, L_ELBOW), (L_ELBOW, L_WRIST),
    (L_SHOULDER, L_HIP), (L_HIP, L_KNEE), (L_KNEE, L_ANKLE),
    (L_ANKLE, L_HEEL), (L_HEEL, L_FOOT), (L_ANKLE, L_FOOT),
]
RIGHT_BONES = [
    (R_SHOULDER, R_ELBOW), (R_ELBOW, R_WRIST),
    (R_SHOULDER, R_HIP), (R_HIP, R_KNEE), (R_KNEE, R_ANKLE),
    (R_ANKLE, R_HEEL), (R_HEEL, R_FOOT), (R_ANKLE, R_FOOT),
]
CENTER_BONES = [(L_SHOULDER, R_SHOULDER), (L_HIP, R_HIP)]


@dataclass(frozen=True)
class SkeletonStyle:
    """色は BGR。thickness_scale は解像度から決まる線の太さに掛ける倍率。"""

    left: tuple[int, int, int]
    right: tuple[int, int, int]
    center: tuple[int, int, int]
    thickness_scale: float = 1.0


# 回転中に左右を見分けやすいよう左=青系 / 右=赤系
DEFAULT_STYLE = SkeletonStyle(left=(255, 140, 0), right=(0, 60, 255), center=(230, 230, 230))


def draw_skeleton(
    frame: np.ndarray, pose: PoseFrame, min_visibility: float = 0.5, style: SkeletonStyle = DEFAULT_STYLE
) -> np.ndarray:
    """frame に骨格を描画して返す（frame 自体を書き換える）。"""
    if not pose.detected:
        return frame
    h, w = frame.shape[:2]
    pts = np.column_stack((pose.landmarks[:, 0] * w, pose.landmarks[:, 1] * h))
    return draw_skeleton_points(frame, pts, pose.visibility >= min_visibility, style)


def draw_skeleton_points(
    frame: np.ndarray, points_px: np.ndarray, visible: np.ndarray, style: SkeletonStyle = DEFAULT_STYLE
) -> np.ndarray:
    """ピクセル座標 (33, 2) の骨格を描画する。visible が False の関節は描かない。"""
    h, w = frame.shape[:2]
    # 解像度に応じて線の太さを変える（1080p で約4px）
    thickness = max(1, round(max(2, min(h, w) / 270) * style.thickness_scale))
    radius = thickness + 2

    pts = points_px.round().astype(int)

    def bones(pairs, color):
        for a, b in pairs:
            if visible[a] and visible[b]:
                cv2.line(frame, tuple(pts[a]), tuple(pts[b]), color, thickness, cv2.LINE_AA)

    def joints(indices, color):
        for i in indices:
            if visible[i]:
                cv2.circle(frame, tuple(pts[i]), radius, color, -1, cv2.LINE_AA)
                cv2.circle(frame, tuple(pts[i]), radius, (0, 0, 0), 1, cv2.LINE_AA)

    bones(CENTER_BONES, style.center)
    # 首: 両肩の中点 → 鼻
    if visible[L_SHOULDER] and visible[R_SHOULDER] and visible[NOSE]:
        neck = tuple(((pts[L_SHOULDER] + pts[R_SHOULDER]) // 2))
        cv2.line(frame, neck, tuple(pts[NOSE]), style.center, thickness, cv2.LINE_AA)
    bones(LEFT_BONES, style.left)
    bones(RIGHT_BONES, style.right)
    joints(LEFT_POINTS, style.left)
    joints(RIGHT_POINTS, style.right)
    joints([NOSE], style.center)
    return frame


def draw_text_lines(frame: np.ndarray, lines: list[str]) -> np.ndarray:
    """左上から順に文字列を表示する（OpenCV の制約で ASCII のみ）。"""
    h, w = frame.shape[:2]
    scale = max(0.5, min(h, w) / 900)
    for i, text in enumerate(lines):
        org = (int(12 * scale), int(36 * scale * (i + 1)))
        cv2.putText(frame, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), int(4 * scale) + 1, cv2.LINE_AA)
        cv2.putText(frame, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), max(1, int(2 * scale)), cv2.LINE_AA)
    return frame


def draw_info(frame: np.ndarray, pose: PoseFrame) -> np.ndarray:
    """左上にフレーム番号・時刻・検出状態を表示する。"""
    text = f"frame {pose.frame_index}  {pose.timestamp_ms / 1000:.2f}s"
    if not pose.detected:
        text += "  (no pose)"
    return draw_text_lines(frame, [text])
