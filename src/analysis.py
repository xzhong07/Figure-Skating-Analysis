"""お手本との比較から、キーフレーム・測定値・アドバイスと再生範囲を求める。

advice_video.py（動画の出力）と app.py（アプリ）の共通部分。
"""
from dataclasses import dataclass

from advice_rules import Advice, generate_advice
from keyframes import select_keyframes
from metrics import FRAME_METRICS, Geometry
from overlay import Comparison

LEAD_S = 0.8  # 踏切の前・着氷の後に再生する秒数

Values = dict[str, dict[str, float | None]]


@dataclass
class AdviceResult:
    my_kf: dict[str, int]
    ref_kf: dict[str, int]
    my_values: Values
    ref_values: Values
    advice: dict[str, list[Advice]]
    start: int  # 再生範囲（自分のフレーム番号）
    end: int


def collect_values(geom: Geometry, keyframes: dict[str, int]) -> Values:
    overall = geom.overall()
    return {
        key: {**{m: geom.frame_metric(m, frame) for m in FRAME_METRICS}, **overall}
        for key, frame in keyframes.items()
    }


def analyze(comp: Comparison) -> AdviceResult:
    my_geom, ref_geom = Geometry(comp.me), Geometry(comp.ref)
    my_kf, ref_kf = select_keyframes(my_geom), select_keyframes(ref_geom)
    my_values, ref_values = collect_values(my_geom, my_kf), collect_values(ref_geom, ref_kf)
    advice = generate_advice(my_values, ref_values)

    me = comp.me
    start = max(0, me.events.takeoff - round(LEAD_S * me.fps))
    # 着氷後のキーフレーム（K7）が LEAD_S より後になる場合もそこまで再生する
    end = min(len(me.poses) - 1, max(me.events.landing + round(LEAD_S * me.fps), max(my_kf.values())))
    return AdviceResult(my_kf, ref_kf, my_values, ref_values, advice, start, end)
