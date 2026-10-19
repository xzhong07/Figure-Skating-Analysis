"""お手本の骨格を自分の動画に重ねるための、時間と空間の対応づけ。

- 時間: 踏切と着氷を基準点にした区分線形の伸縮で、自分の各フレームに対応するお手本の時刻を決める
- 空間: 胴体の長さで拡大率、胴体の中心で平行移動を決める（回転はさせない）
"""
import numpy as np

from jump_events import JumpEvents, fill_missing, rolling
from pose_estimator import NUM_LANDMARKS, PoseFrame
from skeleton_drawer import L_HIP, L_SHOULDER, R_HIP, R_SHOULDER

TORSO_POINTS = [L_SHOULDER, R_SHOULDER, L_HIP, R_HIP]
TORSO_SMOOTH_HALF = 7
SCALE_SMOOTH_HALF = 5
# 自分の骨格が未検出のとき、前後から変換を補間してよい最大のフレーム数
MAX_GAP = 10

# 左右反転のときに入れ替えるランドマーク番号（MediaPipe Pose の左右の対）
MIRROR_INDEX = [0, 4, 5, 6, 1, 2, 3, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15,
                18, 17, 20, 19, 22, 21, 24, 23, 26, 25, 28, 27, 30, 29, 32, 31]


def to_pixels(poses: list[PoseFrame], width: int, height: int, mirror: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """(N, 33, 2) のピクセル座標と (N, 33) の visibility を返す。未検出フレームは NaN と 0。

    mirror=True のときは左右反転し、左右のランドマークも入れ替える
    （反転した映像では、元の右半身が自分の左半身と同じ側に来るため）。
    """
    pts = np.full((len(poses), NUM_LANDMARKS, 2), np.nan)
    vis = np.zeros((len(poses), NUM_LANDMARKS))
    for i, p in enumerate(poses):
        if not p.detected:
            continue
        pts[i, :, 0] = p.landmarks[:, 0] * width
        pts[i, :, 1] = p.landmarks[:, 1] * height
        vis[i] = p.visibility
    if mirror:
        pts[:, :, 0] = width - pts[:, :, 0]
        pts = pts[:, MIRROR_INDEX]
        vis = vis[:, MIRROR_INDEX]
    return pts, vis


def torso_center(pts: np.ndarray) -> np.ndarray:
    """(..., 33, 2) → (..., 2): 両肩と両腰の4点の平均。"""
    return pts[..., TORSO_POINTS, :].mean(axis=-2)


def torso_length(pts: np.ndarray) -> np.ndarray:
    """(..., 33, 2) → (...): 肩の中点から腰の中点までの長さ。"""
    shoulder = (pts[..., L_SHOULDER, :] + pts[..., R_SHOULDER, :]) / 2
    hip = (pts[..., L_HIP, :] + pts[..., R_HIP, :]) / 2
    return np.linalg.norm(shoulder - hip, axis=-1)


def map_time(
    my_events: JumpEvents, my_fps: float, my_count: int,
    ref_events: JumpEvents, ref_fps: float, ref_count: int,
) -> np.ndarray:
    """自分の各フレームに対応するお手本のフレーム位置（小数）を返す。範囲外は NaN。"""
    t = np.arange(my_count) / my_fps
    my_t0, my_t1 = my_events.takeoff / my_fps, my_events.landing / my_fps
    ref_t0, ref_t1 = ref_events.takeoff / ref_fps, ref_events.landing / ref_fps
    air_ratio = (ref_t1 - ref_t0) / (my_t1 - my_t0)

    ref_t = np.where(
        t < my_t0,
        ref_t0 + (t - my_t0),
        np.where(t <= my_t1, ref_t0 + (t - my_t0) * air_ratio, ref_t1 + (t - my_t1)),
    )
    ref_frame = ref_t * ref_fps
    ref_frame[(ref_frame < 0) | (ref_frame > ref_count - 1)] = np.nan
    return ref_frame


def sample_pose(pts: np.ndarray, vis: np.ndarray, position: float) -> tuple[np.ndarray, np.ndarray] | None:
    """小数のフレーム位置の骨格を前後2フレームの線形補間で求める。片方が未検出ならもう片方を使う。"""
    lo = int(np.floor(position))
    hi = min(lo + 1, len(pts) - 1)
    a = position - lo
    lo_ok, hi_ok = not np.isnan(pts[lo, 0, 0]), not np.isnan(pts[hi, 0, 0])
    if lo_ok and hi_ok:
        return pts[lo] * (1 - a) + pts[hi] * a, np.minimum(vis[lo], vis[hi])
    if lo_ok or hi_ok:
        i = lo if lo_ok else hi
        return pts[i], vis[i]
    return None


def fill_short_gaps(values: np.ndarray, max_gap: int) -> np.ndarray:
    """(N, k) の NaN の行を、max_gap フレーム以下の欠けに限り前後から線形補間する。"""
    values = values.copy()
    valid = ~np.isnan(values[:, 0])
    idx = np.arange(len(values))
    i = 0
    while i < len(values):
        if valid[i]:
            i += 1
            continue
        j = i
        while j < len(values) and not valid[j]:
            j += 1
        if 0 < i and j < len(values) and j - i <= max_gap:
            for k in range(values.shape[1]):
                values[i:j, k] = np.interp(idx[i:j], [i - 1, j], [values[i - 1, k], values[j, k]])
        i = j
    return values


class Aligner:
    """お手本の骨格を、自分の動画の各フレームの座標に写す。"""

    def __init__(
        self,
        my_pts: np.ndarray, my_fps: float, my_events: JumpEvents,
        ref_pts: np.ndarray, ref_vis: np.ndarray, ref_fps: float, ref_events: JumpEvents,
    ) -> None:
        self.ref_pts, self.ref_vis = ref_pts, ref_vis
        n = len(my_pts)
        self.ref_frame = map_time(my_events, my_fps, n, ref_events, ref_fps, len(ref_pts))

        # 自分側: 胴体の中心（短い欠けのみ補間）と、平滑化した胴体の長さ
        self.my_center = fill_short_gaps(torso_center(my_pts), MAX_GAP)
        my_torso = rolling(fill_missing(torso_length(my_pts)), TORSO_SMOOTH_HALF)
        # お手本側: 平滑化した胴体の長さを、対応するフレーム位置で読む
        ref_torso = rolling(fill_missing(torso_length(ref_pts)), TORSO_SMOOTH_HALF)
        ref_torso_at = np.interp(np.nan_to_num(self.ref_frame), np.arange(len(ref_torso)), ref_torso)

        scale = my_torso / ref_torso_at
        scale[np.isnan(self.ref_frame)] = np.nan
        valid = ~np.isnan(scale)
        if valid.any():
            scale[valid] = rolling(scale[valid], SCALE_SMOOTH_HALF)
        self.scale = scale

    def transform(self, my_index: int) -> tuple[np.ndarray, np.ndarray, dict] | None:
        """自分のフレーム番号に対する (お手本の骨格のピクセル座標, visibility, 変換の情報)。描けないときは None。"""
        position = self.ref_frame[my_index]
        center = self.my_center[my_index]
        if np.isnan(position) or np.isnan(center[0]):
            return None
        sampled = sample_pose(self.ref_pts, self.ref_vis, position)
        if sampled is None:
            return None
        ref_pose, vis = sampled
        s = self.scale[my_index]
        ref_center = torso_center(ref_pose)
        mapped = (ref_pose - ref_center) * s + center
        info = {"scale": float(s), "ref_center": ref_center.tolist(), "my_center": center.tolist()}
        return mapped, vis, info
