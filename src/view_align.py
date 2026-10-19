"""お手本の3D骨格を、自分の動画の撮影角度に合わせて回してから画面に写す。

MediaPipe の world 座標は腰を原点とし、カメラを基準にした向き（x=右、y=下、z=奥行き）を持つ。
そのため、撮影角度の違いは鉛直軸（y軸）まわりの回転で表せる。
踏切の直前は体の向きがそろいやすいので、そこでの体の向きの差を「撮影角度の差」とみなし、
動画全体で一定の回転量としてお手本の骨格を回す（フレームごとには合わせないので、空中の回転の差は残る）。
"""
import numpy as np

from alignment import MIRROR_INDEX
from jump_events import JumpEvents, fill_missing, rolling
from skeleton_drawer import L_HIP, L_SHOULDER, R_HIP, R_SHOULDER

# 撮影角度の差を測る区間（踏切の何秒前から踏切まで）
OFFSET_WINDOW_S = 0.4
# 推定した差のばらつきがこれ（度）を超えたら、推定が不安定だと警告する
SPREAD_WARNING_DEG = 30.0


def _fill_and_smooth(values: np.ndarray) -> np.ndarray:
    return rolling(fill_missing(values), 1, np.mean)


def body_yaw(world: np.ndarray) -> np.ndarray:
    """(N,) 体の向き（度）。腰の線と肩の線（左→右）の水平面での向きを平均したもの。"""
    vectors = []
    for left, right in ((L_HIP, R_HIP), (L_SHOULDER, R_SHOULDER)):
        v = world[:, right] - world[:, left]
        length = np.hypot(v[:, 0], v[:, 2])
        vectors.append(np.stack([v[:, 0] / length, v[:, 2] / length], axis=1))
    mean = (vectors[0] + vectors[1]) / 2
    x, z = _fill_and_smooth(mean[:, 0]), _fill_and_smooth(mean[:, 1])
    return np.degrees(np.arctan2(z, x))


def mirror_world(world: np.ndarray) -> np.ndarray:
    """左右反転（x を反転し、左右のランドマークを入れ替える）。"""
    mirrored = world.copy()
    mirrored[:, :, 0] = -mirrored[:, :, 0]
    return mirrored[:, MIRROR_INDEX]


def estimate_view_offset(
    my_world: np.ndarray, my_events: JumpEvents, my_fps: float, ref_world: np.ndarray, ref_frame: np.ndarray
) -> tuple[float, float]:
    """(撮影角度の差, ばらつき) を度で返す。差 = 自分の体の向き − お手本の体の向き。

    ref_frame: 自分の各フレームに対応するお手本のフレーム位置（alignment.map_time の結果）。
    """
    my_yaw, ref_yaw = body_yaw(my_world), body_yaw(ref_world)
    start = max(0, my_events.takeoff - round(OFFSET_WINDOW_S * my_fps))
    diffs = []
    for i in range(start, my_events.takeoff + 1):
        if np.isnan(ref_frame[i]):
            continue
        j = int(round(ref_frame[i]))
        diffs.append(np.radians(my_yaw[i] - ref_yaw[j]))
    if not diffs:
        return 0.0, 180.0
    mean = np.mean(np.exp(1j * np.array(diffs)))
    offset = float(np.degrees(np.angle(mean)))
    spread = float(np.degrees(np.sqrt(max(0.0, -2 * np.log(min(1.0, max(abs(mean), 1e-9)))))))
    return offset, spread


def rotate_about_vertical(world: np.ndarray, degrees: float) -> np.ndarray:
    """y軸（鉛直）まわりに回す。体の向き（body_yaw）が degrees だけ増える向き。"""
    t = np.radians(degrees)
    rotated = world.copy()
    x, z = world[..., 0], world[..., 2]
    rotated[..., 0] = x * np.cos(t) - z * np.sin(t)
    rotated[..., 2] = x * np.sin(t) + z * np.cos(t)
    return rotated


def project(world: np.ndarray) -> np.ndarray:
    """(N, 33, 2) 正射影した座標（メートル）。細かい揺れを抑えるため3フレームで平滑化する。未検出は NaN のまま。"""
    missing = np.isnan(world[:, 0, 0])
    if missing.all():
        return world[:, :, :2].copy()
    projected = np.empty(world.shape[:2] + (2,))
    for k in range(world.shape[1]):
        for axis in range(2):
            projected[:, k, axis] = _fill_and_smooth(world[:, k, axis])
    projected[missing] = np.nan
    return projected
