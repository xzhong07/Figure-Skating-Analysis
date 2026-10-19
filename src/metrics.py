"""骨格からジャンプの姿勢・タイミングの測定値を計算する。

- 長さは胴体の長さ（肩の中点〜腰の中点）で割った比で表し、体格とカメラ距離の差をなくす
- 2D の値はカメラの動きを打ち消した画面座標で測る（y は下向きが正）
- 回転量だけは 3D（world 座標）の肩の線の向きから測る
- 使う関節の visibility が VIS_MIN 未満のときは None（判定できない）を返す
"""
from collections.abc import Callable

import numpy as np

from jump_events import body_series, fill_missing
from skeleton_drawer import (
    L_ANKLE, L_HIP, L_KNEE, L_SHOULDER, L_WRIST, NOSE,
    R_ANKLE, R_HIP, R_KNEE, R_SHOULDER, R_WRIST,
)

VIS_MIN = 0.5
GRAVITY = 9.81
# 肩幅（または腰幅）が胴体のこの割合未満なら真横から見ているとみなし、傾きを判定しない
MIN_WIDTH_RATIO = 0.4
# 手首が胴体の中心線からこの距離（胴体比）以上離れたら「腕を開いた」とみなす
ARM_OPEN_DISTANCE = 0.8


def angle_deg(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """点 b における角 abc（度）。"""
    v1, v2 = a - b, c - b
    cos = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9)
    return float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))))


def tilt_from_vertical(bottom: np.ndarray, top: np.ndarray) -> float:
    """bottom → top の線の鉛直からの角度（度、x が正の向きに傾くと正）。"""
    v = top - bottom
    return float(np.degrees(np.arctan2(v[0], -v[1])))


class Geometry:
    """1本の動画の測定。subject は overlay.Subject。"""

    def __init__(self, subject) -> None:
        self.p = subject.stable
        self.vis = subject.vis
        self.world = subject.world
        self.fps = subject.fps
        self.events = subject.events
        self.n = len(self.p)
        _, _, self.torso = body_series(self.p)
        hip_x = fill_missing((self.p[:, L_HIP, 0] + self.p[:, R_HIP, 0]) / 2)
        t = self.events.takeoff
        before = max(0, t - round(0.3 * self.fps))
        after = min(self.n - 1, t + 3)
        # 進行方向（画面上の x の向き）。踏切前後の腰の移動から決める
        self.direction = 1.0 if hip_x[after] >= hip_x[before] else -1.0
        self._series: dict[str, np.ndarray] = {}

    # ---- 1フレームの測定値 ----

    def _ok(self, i: int, *indices: int) -> bool:
        return bool(all(self.vis[i, j] >= VIS_MIN for j in indices)) and not np.isnan(self.p[i, 0, 0])

    def _mid(self, i: int, a: int, b: int) -> np.ndarray:
        return (self.p[i, a] + self.p[i, b]) / 2

    def frame_metric(self, name: str, i: int) -> float | None:
        if not 0 <= i < self.n or np.isnan(self.p[i, 0, 0]):
            return None
        return FRAME_METRICS[name](self, i)

    def series(self, name: str) -> np.ndarray:
        """全フレームの測定値（判定できないフレームは NaN）。"""
        if name not in self._series:
            values = [self.frame_metric(name, i) for i in range(self.n)]
            self._series[name] = np.array([np.nan if v is None else v for v in values])
        return self._series[name]

    def trunk_lean(self, i: int) -> float | None:
        if not self._ok(i, L_SHOULDER, R_SHOULDER, L_HIP, R_HIP):
            return None
        lean = tilt_from_vertical(self._mid(i, L_HIP, R_HIP), self._mid(i, L_SHOULDER, R_SHOULDER))
        return lean * self.direction

    def landing_lean(self, i: int) -> float | None:
        """着氷後の前傾（度）。着氷後は後ろ向きに滑るので、進行方向と逆（着氷足の上）に傾くのを正とする。"""
        lean = self.trunk_lean(i)
        return None if lean is None else -lean

    def _knee(self, i: int, hip: int, knee: int, ankle: int) -> float | None:
        if not self._ok(i, hip, knee, ankle):
            return None
        return angle_deg(self.p[i, hip], self.p[i, knee], self.p[i, ankle])

    def takeoff_knee(self, i: int) -> float | None:
        return self._knee(i, L_HIP, L_KNEE, L_ANKLE)

    def landing_knee(self, i: int) -> float | None:
        return self._knee(i, R_HIP, R_KNEE, R_ANKLE)

    def free_thigh(self, i: int) -> float | None:
        """右の太ももの、真下からの角度（0°=真下、90°=水平）。"""
        if not self._ok(i, R_HIP, R_KNEE):
            return None
        return angle_deg(self.p[i, R_HIP] + np.array([0.0, 1.0]), self.p[i, R_HIP], self.p[i, R_KNEE])

    def _wrists(self, i: int) -> list[int]:
        return [w for w in (L_WRIST, R_WRIST) if self.vis[i, w] >= VIS_MIN]

    def arm_height(self, i: int) -> float | None:
        """手首の肩からの高さ（胴体比、上が正）。見えている手首の平均。"""
        wrists = self._wrists(i)
        if not wrists or not self._ok(i, L_SHOULDER, R_SHOULDER):
            return None
        shoulder_y = self._mid(i, L_SHOULDER, R_SHOULDER)[1]
        return float(np.mean([(shoulder_y - self.p[i, w, 1]) / self.torso[i] for w in wrists]))

    def takeoff_foot_ahead(self, i: int) -> float | None:
        """踏切足（左）の足首が腰よりどれだけ進行方向の前にあるか（胴体比）。"""
        if not self._ok(i, L_ANKLE, L_HIP, R_HIP):
            return None
        return float((self.p[i, L_ANKLE, 0] - self._mid(i, L_HIP, R_HIP)[0]) * self.direction / self.torso[i])

    def _line_tilt(self, i: int, left: int, right: int) -> float | None:
        """左右の点を結ぶ線の水平からの角度（度）。右側が下がっていると正。"""
        if not self._ok(i, left, right):
            return None
        v = self.p[i, right] - self.p[i, left]
        if np.linalg.norm(v) / self.torso[i] < MIN_WIDTH_RATIO:
            return None
        return float(np.degrees(np.arctan2(v[1], abs(v[0]))))

    def shoulder_tilt(self, i: int) -> float | None:
        return self._line_tilt(i, L_SHOULDER, R_SHOULDER)

    def hip_tilt(self, i: int) -> float | None:
        return self._line_tilt(i, L_HIP, R_HIP)

    def _gap(self, i: int, a: int, b: int) -> float | None:
        if not self._ok(i, a, b):
            return None
        return float(np.linalg.norm(self.p[i, a] - self.p[i, b]) / self.torso[i])

    def ankle_gap(self, i: int) -> float | None:
        return self._gap(i, L_ANKLE, R_ANKLE)

    def knee_gap(self, i: int) -> float | None:
        return self._gap(i, L_KNEE, R_KNEE)

    def arm_span(self, i: int) -> float | None:
        return self._gap(i, L_WRIST, R_WRIST)

    def arm_tuck(self, i: int) -> float | None:
        """手首から胴体の中心線（腰の中点〜肩の中点を通る直線）までの距離（胴体比）。見えている手首の平均。"""
        wrists = self._wrists(i)
        if not wrists or not self._ok(i, L_SHOULDER, R_SHOULDER, L_HIP, R_HIP):
            return None
        a, b = self._mid(i, L_HIP, R_HIP), self._mid(i, L_SHOULDER, R_SHOULDER)
        axis = (b - a) / (np.linalg.norm(b - a) + 1e-9)
        dists = []
        for w in wrists:
            d = self.p[i, w] - a
            dists.append(abs(d[0] * axis[1] - d[1] * axis[0]))
        return float(np.mean(dists) / self.torso[i])

    def axis_tilt(self, i: int) -> float | None:
        """足首の中点 → 肩の中点の線の、鉛直からの傾き（度、絶対値）。"""
        if not self._ok(i, L_ANKLE, R_ANKLE, L_SHOULDER, R_SHOULDER):
            return None
        return abs(tilt_from_vertical(self._mid(i, L_ANKLE, R_ANKLE), self._mid(i, L_SHOULDER, R_SHOULDER)))

    def head_drop(self, i: int) -> float | None:
        """鼻の高さが肩の中点からどれだけ下か（胴体比）。通常は負で、大きいほど頭が下がっている。"""
        if not self._ok(i, NOSE, L_SHOULDER, R_SHOULDER):
            return None
        return float((self.p[i, NOSE, 1] - self._mid(i, L_SHOULDER, R_SHOULDER)[1]) / self.torso[i])

    def free_leg_extension(self, i: int) -> float | None:
        """着氷後のフリーレッグ（左脚：腰→足首）の、真下からの角度（度）。後ろへ大きく伸ばすほど大きい。"""
        if not self._ok(i, L_HIP, L_ANKLE):
            return None
        return angle_deg(self.p[i, L_HIP] + np.array([0.0, 1.0]), self.p[i, L_HIP], self.p[i, L_ANKLE])

    # ---- ジャンプ全体の測定値 ----

    def _window(self, start_s: float, end_s: float, base: int) -> slice:
        a = max(0, base + round(start_s * self.fps))
        b = min(self.n, base + round(end_s * self.fps) + 1)
        return slice(a, b)

    @staticmethod
    def _nan_max(values: np.ndarray) -> float | None:
        return None if np.all(np.isnan(values)) else float(np.nanmax(values))

    @staticmethod
    def _nan_min(values: np.ndarray) -> float | None:
        return None if np.all(np.isnan(values)) else float(np.nanmin(values))

    def overall(self) -> dict[str, float | None]:
        ev, fps = self.events, self.fps
        air_time = (ev.landing - ev.takeoff) / fps
        hip_y = fill_missing((self.p[:, L_HIP, 1] + self.p[:, R_HIP, 1]) / 2)
        air = slice(ev.takeoff, ev.landing + 1)

        # 腕の振りの速さ: 見えている手首が左右で入れ替わると平均が飛ぶので、手首ごとに速度を求める
        shoulder_y = (self.p[:, L_SHOULDER, 1] + self.p[:, R_SHOULDER, 1]) / 2
        arm_velocity = np.full(self.n, np.nan)
        for w in (L_WRIST, R_WRIST):
            height = (shoulder_y - self.p[:, w, 1]) / self.torso
            height[self.vis[:, w] < VIS_MIN] = np.nan
            velocity = np.full(self.n, np.nan)
            velocity[1:-1] = (height[2:] - height[:-2]) / 2 * fps
            arm_velocity = np.fmax(arm_velocity, velocity)

        tuck = self.series("arm_tuck")
        open_frame = None
        for i in range(ev.apex, min(self.n, ev.landing + round(0.5 * fps))):
            if not np.isnan(tuck[i]) and tuck[i] >= ARM_OPEN_DISTANCE:
                open_frame = i
                break

        axis = self.series("axis_tilt")[air]
        rotation = self.air_rotation()
        return {
            "air_time": air_time,
            "height_cm": GRAVITY * air_time**2 / 8 * 100,
            "hip_rise": float(np.max((hip_y[ev.takeoff] - hip_y[air]) / self.torso[air])),
            "air_rotation": rotation,
            "rotation_speed": None if rotation is None else rotation / 360 / air_time,
            "free_thigh_peak": self._nan_max(self.series("free_thigh")[self._window(-0.15, 0.15, ev.takeoff)]),
            "arm_swing_speed": self._nan_max(arm_velocity[self._window(-0.3, 0.1, ev.takeoff)]),
            "arm_open_before_landing": None if open_frame is None else (ev.landing - open_frame) / fps,
            "landing_knee_min": self._nan_min(self.series("landing_knee")[self._window(0, 0.2, ev.landing)]),
            "axis_tilt_air": None if np.all(np.isnan(axis)) else float(np.nanmean(axis)),
        }

    def air_rotation(self) -> float | None:
        """踏切から着氷までに肩の線が回った角度（度、3D の world 座標から）。"""
        v = self.world[:, R_SHOULDER] - self.world[:, L_SHOULDER]
        if np.all(np.isnan(v[:, 0])):
            return None
        yaw = np.unwrap(np.arctan2(fill_missing(v[:, 2]), fill_missing(v[:, 0])))
        return float(abs(np.degrees(yaw[self.events.landing] - yaw[self.events.takeoff])))


FRAME_METRICS: dict[str, Callable[[Geometry, int], float | None]] = {
    "trunk_lean": Geometry.trunk_lean,
    "landing_lean": Geometry.landing_lean,
    "takeoff_knee": Geometry.takeoff_knee,
    "landing_knee": Geometry.landing_knee,
    "free_thigh": Geometry.free_thigh,
    "arm_height": Geometry.arm_height,
    "takeoff_foot_ahead": Geometry.takeoff_foot_ahead,
    "shoulder_tilt": Geometry.shoulder_tilt,
    "hip_tilt": Geometry.hip_tilt,
    "ankle_gap": Geometry.ankle_gap,
    "knee_gap": Geometry.knee_gap,
    "arm_span": Geometry.arm_span,
    "arm_tuck": Geometry.arm_tuck,
    "axis_tilt": Geometry.axis_tilt,
    "head_drop": Geometry.head_drop,
    "free_leg_extension": Geometry.free_leg_extension,
}
