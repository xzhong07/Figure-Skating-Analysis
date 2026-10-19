"""骨格の時系列から踏切・頂点・着氷のフレームを検出する。

カメラのパン・チルト・ズームを打ち消した座標（camera_motion.py）で判定する。
1. 腰が最も大きく上がったフレームを頂点とする
2. 頂点の前で「いちばん低い足」が最も速く上がっているフレームから時間を戻り、
   足が上がり始める直前を踏切とする
3. 頂点の後で足が最も速く下がっているフレームから時間を進め、足が止まったところを着氷とする

氷の高さそのものは、スケーターの移動やズームで画面内の位置が変わるので使わず、足の速度で判定する。
"""
from dataclasses import dataclass

import numpy as np

from skeleton_drawer import L_ANKLE, L_HIP, L_SHOULDER, R_FOOT, R_HIP, R_SHOULDER

# 足の上下の速さがこれ（胴体の長さ/秒）を超えていれば空中とみなす
# 空中では 3〜6、踏切直前と着氷直後は 1 未満（お手本と自分の動画で確認）
FOOT_VELOCITY = 1.0
# 頂点の探索で「直前の最も低い腰の位置」を見る時間幅（秒）
BASELINE_WINDOW_S = 1.0
# 頂点の前後で、足が最も速く動くフレームを探す時間幅（秒）
PEAK_SEARCH_S = 0.5
# 胴体の長さの平滑化（前後のフレーム数）
TORSO_SMOOTH_HALF = 7

FOOT_POINTS = list(range(L_ANKLE, R_FOOT + 1))  # 足首・かかと・つま先（左右）


@dataclass
class JumpEvents:
    takeoff: int  # 氷に着いている最後のフレーム
    apex: int
    landing: int  # 再び氷に着いた最初のフレーム

    def phase(self, frame: float) -> str:
        if frame < self.takeoff:
            return "approach"
        if frame <= self.landing:
            return "air"
        return "landing"


def fill_missing(values: np.ndarray) -> np.ndarray:
    """NaN を前後の値から線形補間する（端は最も近い値で埋める）。"""
    values = values.astype(np.float64).copy()
    valid = ~np.isnan(values)
    if not valid.any():
        raise ValueError("骨格が1フレームも検出されていません。")
    idx = np.arange(len(values))
    values[~valid] = np.interp(idx[~valid], idx[valid], values[valid])
    return values


def rolling(values: np.ndarray, half: int, func=np.median) -> np.ndarray:
    """前後 half フレームの窓で func を適用する。"""
    n = len(values)
    return np.array([func(values[max(0, i - half) : i + half + 1]) for i in range(n)])


def body_series(points_px: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(腰の中心の y, いちばん低い足の y, 胴体の長さ) をピクセルで返す。未検出は補間済み。

    points_px: (N, 33, 2)。未検出フレームは NaN。y は下向きが正。
    """
    shoulder = (points_px[:, L_SHOULDER] + points_px[:, R_SHOULDER]) / 2
    hip = (points_px[:, L_HIP] + points_px[:, R_HIP]) / 2
    hip_y = fill_missing(hip[:, 1])
    foot_y = fill_missing(points_px[:, FOOT_POINTS, 1].max(axis=1))
    torso = rolling(fill_missing(np.linalg.norm(shoulder - hip, axis=1)), TORSO_SMOOTH_HALF)
    return rolling(hip_y, 1, np.mean), rolling(foot_y, 1, np.mean), torso


def detect_jump(
    points_px: np.ndarray, fps: float, takeoff: int | None = None, landing: int | None = None
) -> JumpEvents:
    """踏切・頂点・着氷を検出する。takeoff / landing を渡すとその値を優先する。

    points_px はカメラの動きを打ち消したピクセル座標 (N, 33, 2) を渡す。
    """
    hip_y, foot_y, torso = body_series(points_px)
    n = len(hip_y)

    if takeoff is not None and landing is not None:
        apex = takeoff + int(np.argmin(hip_y[takeoff : landing + 1]))
        return JumpEvents(takeoff, apex, landing)

    # 頂点: 直前 BASELINE_WINDOW_S 秒間で最も低かった腰の位置からの上昇量が最大のフレーム
    window = max(1, round(BASELINE_WINDOW_S * fps))
    baseline = np.array([hip_y[max(0, i - window) : i + 1].max() for i in range(n)])
    apex = int(np.argmax((baseline - hip_y) / torso))

    search = max(1, round(PEAK_SEARCH_S * fps))
    # rise[i]: フレーム i-1 → i で足が上がった速さ、fall[i]: フレーム i → i+1 で足が下がった速さ（胴体の長さ/秒）
    rise = np.zeros(n)
    rise[1:] = (foot_y[:-1] - foot_y[1:]) / torso[1:] * fps
    fall = np.zeros(n)
    fall[:-1] = (foot_y[1:] - foot_y[:-1]) / torso[:-1] * fps

    if takeoff is None:
        start = max(1, apex - search)
        takeoff = start + int(np.argmax(rise[start : apex + 1]))
        while takeoff > 0 and rise[takeoff] > FOOT_VELOCITY:
            takeoff -= 1
    if landing is None:
        end = min(n - 1, apex + search)
        landing = apex + int(np.argmax(fall[apex : end + 1]))
        while landing < n - 1 and fall[landing] > FOOT_VELOCITY:
            landing += 1

    if not takeoff < apex < landing:
        raise ValueError(
            f"ジャンプを検出できませんでした（踏切={takeoff}, 頂点={apex}, 着氷={landing}）。"
            "--*-takeoff / --*-landing で手動指定してください。"
        )
    return JumpEvents(takeoff, apex, landing)
