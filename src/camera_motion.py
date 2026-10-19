"""背景の動きからカメラのパン・チルト・ズームを推定する。

人物の周りを除いた背景の特徴点をフレーム間で追跡し、拡大縮小＋回転＋平行移動を当てはめる。
これを積み重ねると、各フレームの座標を最初のフレームの座標に写す変換が得られる。
"""
from pathlib import Path

import cv2
import numpy as np

from pose_estimator import PoseFrame

WORK_WIDTH = 960  # 処理を速くするため、この幅に縮小して推定する
MAX_FEATURES = 400


def person_mask(shape: tuple[int, int], pose: PoseFrame) -> np.ndarray:
    """人物の周りを 0、背景を 255 にしたマスク。"""
    h, w = shape
    mask = np.full((h, w), 255, np.uint8)
    if pose.detected:
        xs, ys = pose.landmarks[:, 0] * w, pose.landmarks[:, 1] * h
        size = ys.max() - ys.min()
        x0, x1 = int(xs.min() - 0.4 * size), int(xs.max() + 0.4 * size)
        y0, y1 = int(ys.min() - 0.3 * size), int(ys.max() + 0.2 * size)
        mask[max(0, y0) : max(0, y1), max(0, x0) : max(0, x1)] = 0
    return mask


def estimate_camera_motion(video: Path, poses: list[PoseFrame]) -> np.ndarray:
    """(N, 3, 3): フレーム i のピクセル座標をフレーム 0 のピクセル座標に写す変換。"""
    cap = cv2.VideoCapture(str(video))
    transforms = []
    acc = np.eye(3)
    prev_gray = prev_mask = None
    scale = 1.0
    index = 0
    while True:
        ok, frame = cap.read()
        if not ok or index >= len(poses):
            break
        scale = WORK_WIDTH / frame.shape[1]
        gray = cv2.cvtColor(cv2.resize(frame, None, fx=scale, fy=scale), cv2.COLOR_BGR2GRAY)
        mask = person_mask(gray.shape, poses[index])
        if prev_gray is not None:
            step = _frame_step(prev_gray, prev_mask, gray)
            acc = acc @ step
        transforms.append(acc.copy())
        prev_gray, prev_mask = gray, mask
        index += 1
    cap.release()

    # 縮小した座標での変換を、元の解像度の座標での変換に直す
    s = np.diag([scale, scale, 1.0])
    s_inv = np.diag([1 / scale, 1 / scale, 1.0])
    return np.array([s_inv @ t @ s for t in transforms])


def _frame_step(prev_gray: np.ndarray, prev_mask: np.ndarray, gray: np.ndarray) -> np.ndarray:
    """現フレーム → 前フレームの変換 (3, 3)。推定できなければ動きなしとみなす。"""
    pts = cv2.goodFeaturesToTrack(prev_gray, MAX_FEATURES, 0.01, 8, mask=prev_mask)
    if pts is None or len(pts) < 10:
        return np.eye(3)
    nxt, status, _ = cv2.calcOpticalFlowPyrLK(prev_gray, gray, pts, None)
    good = status.ravel() == 1
    if good.sum() < 10:
        return np.eye(3)
    m, _ = cv2.estimateAffinePartial2D(nxt[good], pts[good], method=cv2.RANSAC, ransacReprojThreshold=2.0)
    if m is None:
        return np.eye(3)
    return np.vstack([m, [0, 0, 1]])


def stabilize_points(points_px: np.ndarray, transforms: np.ndarray) -> np.ndarray:
    """(N, 33, 2) のピクセル座標を、各フレームの変換でフレーム 0 の座標に写す。"""
    homogeneous = np.concatenate([points_px, np.ones(points_px.shape[:2] + (1,))], axis=-1)
    return np.einsum("nij,nkj->nki", transforms[:, :2, :], homogeneous)
