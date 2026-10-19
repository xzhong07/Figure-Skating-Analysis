"""比較するキーフレームを選ぶ。お手本と自分で、それぞれの踏切・着氷を基準に同じ定義で選ぶ。"""
import numpy as np

from metrics import Geometry

# (キー, 表示名)
KEYFRAMES = [
    ("K1", "踏切準備"),
    ("K2", "踏切"),
    ("K3", "回転し始め"),
    ("K4", "空中（頂点）"),
    ("K5", "回転の終わり"),
    ("K6", "着氷"),
    ("K7", "着氷後の姿勢"),
]
KEYFRAME_NAMES = dict(KEYFRAMES)


def select_keyframes(geom: Geometry) -> dict[str, int]:
    ev, fps, n = geom.events, geom.fps, geom.n
    air = ev.landing - ev.takeoff

    # 踏切準備: 踏切の0.4秒前〜踏切で、踏切足（左）のひざが最も深く曲がったフレーム
    start = max(0, ev.takeoff - round(0.4 * fps))
    knee = geom.series("takeoff_knee")[start : ev.takeoff + 1]
    if np.all(np.isnan(knee)):
        k1 = max(0, ev.takeoff - round(0.2 * fps))
    else:
        k1 = start + int(np.nanargmin(knee))

    return {
        "K1": k1,
        "K2": ev.takeoff,
        "K3": ev.takeoff + round(air * 0.25),
        "K4": ev.apex,
        "K5": ev.takeoff + round(air * 0.8),
        "K6": ev.landing,
        "K7": min(n - 1, ev.landing + round(0.3 * fps)),
    }
