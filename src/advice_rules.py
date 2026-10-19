"""お手本との差からアドバイス文を作るルール表。

1つのルールで、1つの測定項目を1つのキーフレームで比べる。
差 = 自分 − お手本。|差| がしきい値以上なら、差の向きに応じて low（自分が小さい）か high（自分が大きい）の文を出す。
文が空のときは、その向きの差は問題にしない（例: お手本より高く跳べている）。
しきい値と文章はこの表だけを直せば調整できる。
"""
from collections.abc import Callable
from dataclasses import asdict, dataclass

MAX_ADVICE_PER_KEYFRAME = 3
GOOD_SEVERITY = 0.5  # 重要度がこれ未満なら「お手本に近い」とみなす


def _deg(v: float) -> str:
    return f"{v:.0f}°"


def _ratio(v: float) -> str:
    return f"胴体の{v:.2f}倍"


def _sec(v: float) -> str:
    return f"{v:.2f}秒"


def _lean(v: float) -> str:
    return f"前に{v:.0f}°" if v >= 0 else f"後ろに{-v:.0f}°"


def _foot_ahead(v: float) -> str:
    return f"腰より前に胴体の{v:.2f}倍" if v >= 0 else f"腰より後ろに胴体の{-v:.2f}倍"


# 測定項目の表示名と、値の書き方
METRICS: dict[str, tuple[str, Callable[[float], str]]] = {
    "trunk_lean": ("上体の傾き", _lean),
    "landing_lean": ("上体の傾き", _lean),
    "takeoff_knee": ("踏切足のひざの角度", _deg),
    "landing_knee_min": ("着氷足のひざの最小角度", _deg),
    "free_thigh_peak": ("振り上げ足（右太もも）の角度", _deg),
    "arm_height": ("手首の高さ（肩から）", _ratio),
    "arm_swing_speed": ("腕の振り上げの速さ", lambda v: f"胴体の{v:.1f}倍/秒"),
    "takeoff_foot_ahead": ("踏切足の位置", _foot_ahead),
    "shoulder_tilt": ("肩の傾き", _deg),
    "ankle_gap": ("両足首の間隔", _ratio),
    "knee_gap": ("両ひざの間隔", _ratio),
    "arm_tuck": ("腕と体の距離", _ratio),
    "axis_tilt": ("軸の傾き", _deg),
    "axis_tilt_air": ("空中の軸の傾き（平均）", _deg),
    "head_drop": ("頭の位置（肩からの高さ）", lambda v: f"胴体の{-v:.2f}倍"),
    "height_cm": ("ジャンプの高さ（推定）", lambda v: f"{v:.0f}cm"),
    "air_time": ("滞空時間", _sec),
    "air_rotation": ("空中での回転量", _deg),
    "rotation_speed": ("回転速度", lambda v: f"{v:.2f}回転/秒"),
    "arm_open_before_landing": (
        "腕を開くタイミング",
        lambda v: f"着氷の{v:.2f}秒前" if v >= 0 else f"着氷の{-v:.2f}秒後",
    ),
    "free_leg_extension": ("フリーレッグの上がり", _deg),
    "arm_span": ("両手首の間隔", _ratio),
}


@dataclass(frozen=True)
class Rule:
    keyframe: str
    metric: str
    threshold: float
    low: str  # 自分 < お手本 のときの文
    high: str  # 自分 > お手本 のときの文
    absolute: bool = False  # 絶対値で比べる（傾きの向きは問わない）。文の {side} に下がっている側が入る
    draw: str | None = None  # 一時停止中に描く測定線（advice_video.py の ANNOTATIONS のキー）


RULES = [
    # ---- K1 踏切準備 ----
    Rule("K1", "takeoff_knee", 15,
         low="踏切前にひざを深く曲げすぎています。沈み込みすぎるとタイミングが遅れるので、お手本くらいの深さで踏み込みましょう。",
         high="踏み込みが浅いです。踏切足のひざをもう少し曲げて、氷を押す力をためましょう。",
         draw="takeoff_knee"),
    Rule("K1", "trunk_lean", 10,
         low="踏み込みで上体が後ろに残っています。体重を踏切足の上にのせ、上体をやや前に保ちましょう。",
         high="踏み込みで上体が前に倒れすぎています。頭と胸を起こし、背すじを伸ばしたまま踏み込みましょう。",
         draw="trunk"),
    # ---- K2 踏切 ----
    Rule("K2", "free_thigh_peak", 12,
         low="右足の振り上げが低めです。踏切と同時に、ひざから前上方へ大きく引き上げましょう。",
         high="", draw="thigh"),
    Rule("K2", "arm_height", 0.25,
         low="踏切で腕の振り上げが足りません。両腕を胸の高さまでしっかり引き上げ、上へ向かう勢いを作りましょう。",
         high="踏切で腕が上がりすぎています。肩に力が入ると軸がぶれやすいので、胸の高さで止めましょう。",
         draw="arms"),
    Rule("K2", "arm_swing_speed", 3.0,
         low="腕の振り上げがゆっくりです。踏切の直前に、後ろから前へ素早く振り上げましょう。",
         high=""),
    Rule("K2", "trunk_lean", 10,
         low="踏切で上体が後ろに倒れています。体重が後ろに残ると高さが出にくいので、上体を起こして踏切足の真上にのりましょう。",
         high="踏切で上体が前に突っ込んでいます。胸を起こし、まっすぐ上へ跳び上がる意識を持ちましょう。",
         draw="trunk"),
    Rule("K2", "takeoff_knee", 12,
         low="踏切の瞬間もひざが曲がったままです。ひざと足首を最後までしっかり伸ばして氷を押し切りましょう。",
         high="", draw="takeoff_knee"),
    Rule("K2", "takeoff_foot_ahead", 0.25,
         low="踏切足が体の後ろに残っています。踏切足を腰の真下まで踏み込んでから跳びましょう。",
         high="踏切足が体より前に出すぎています。ブレーキがかかりやすいので、腰の真下近くで踏み切りましょう。",
         draw="foot"),
    Rule("K2", "shoulder_tilt", 8, absolute=True,
         low="", high="踏切で{side}肩が下がっています。両肩を水平に保ったまま跳び上がりましょう。",
         draw="shoulder"),
    # ---- K3 回転し始め ----
    Rule("K3", "ankle_gap", 0.25,
         low="", high="跳び上がった直後に両足が開いています。踏切足をすばやく引き寄せて、早めに足を締めましょう。",
         draw="feet"),
    Rule("K3", "arm_tuck", 0.2,
         low="", high="腕を体に引き寄せるのが遅れています。踏み切ったらすぐに両腕を胸の前に締めましょう。",
         draw="arms"),
    Rule("K3", "shoulder_tilt", 8, absolute=True,
         low="", high="空中で{side}肩が下がっています。肩の高さをそろえ、回転軸をまっすぐ保ちましょう。",
         draw="shoulder"),
    Rule("K3", "head_drop", 0.12,
         low="", high="頭が下がっています。あごを引きすぎず、目線を水平に保ちましょう。"),
    Rule("K3", "axis_tilt", 6,
         low="", high="回転の始まりで軸が傾いています。頭からつま先までを一本の軸にそろえましょう。",
         draw="axis"),
    # ---- K4 空中（頂点） ----
    Rule("K4", "height_cm", 5,
         low="ジャンプの高さが足りません（滞空時間から推定）。踏切で腕と振り上げ足を同時に引き上げ、真上への力を強めましょう。",
         high=""),
    Rule("K4", "air_rotation", 45,
         low="空中での回転量が足りません。踏み切ったらすぐに腕と足を締めて、回転を速めましょう。",
         high=""),
    Rule("K4", "rotation_speed", 0.3,
         low="回転速度が遅めです。腕と足を体の中心に近づけるほど、回転は速くなります。",
         high=""),
    Rule("K4", "ankle_gap", 0.25,
         low="", high="空中で両足が開いています。足首を重ねる（クロスする）ように、しっかり締めましょう。",
         draw="feet"),
    Rule("K4", "knee_gap", 0.25,
         low="", high="空中でひざが離れています。太ももの内側を寄せて、脚全体を締めましょう。",
         draw="feet"),
    Rule("K4", "arm_tuck", 0.2,
         low="", high="空中で腕が体から離れています。両腕を胸の前でコンパクトに締めましょう。",
         draw="arms"),
    Rule("K4", "axis_tilt", 6,
         low="", high="空中で軸が傾いています。頭・肩・腰・足首を一直線にそろえましょう。",
         draw="axis"),
    # ---- K5 回転の終わり ----
    Rule("K5", "arm_open_before_landing", 0.08,
         low="腕を開くのが遅れています。着氷の少し前から腕を開き始めると、着氷が安定します。",
         high="腕を開くのが早すぎます。回転が終わる前にほどくと回転不足になりやすいので、着氷の直前まで締めておきましょう。",
         draw="arms"),
    Rule("K5", "axis_tilt_air", 5,
         low="", high="空中全体を通して軸が傾きがちです。踏切で上体が傾かないよう、まっすぐ上に跳び上がりましょう。",
         draw="axis"),
    Rule("K5", "ankle_gap", 0.25,
         low="", high="回転の終わりまで足が締まっていません。着氷の直前まで足を締めておきましょう。",
         draw="feet"),
    # ---- K6 着氷 ----
    Rule("K6", "landing_knee_min", 12,
         low="着氷でひざが深く曲がりすぎています。沈みすぎずに、すぐ滑り出せる深さで受け止めましょう。",
         high="着氷でひざのクッションが足りません。着氷足のひざを柔らかく曲げて衝撃を吸収しましょう。",
         draw="landing_knee"),
    Rule("K6", "landing_lean", 12,
         low="着氷で上体が後ろに傾いています。着氷足の上に体重をのせ、上体をやや前に保ちましょう。",
         high="着氷で上体が前に倒れています。胸を起こして、背すじを伸ばしましょう。",
         draw="trunk"),
    Rule("K6", "axis_tilt", 8,
         low="", high="着氷の瞬間に軸が傾いています。着氷足の真上に頭と肩をそろえましょう。",
         draw="axis"),
    # ---- K7 着氷後の姿勢 ----
    Rule("K7", "free_leg_extension", 15,
         low="着氷後のフリーレッグが上がっていません。左足を後ろへ大きく伸ばして、きれいな着氷姿勢を作りましょう。",
         high="", draw="free_leg"),
    Rule("K7", "arm_span", 0.5,
         low="着氷後の腕の広がりが小さいです。両腕を横へ大きく広げて、バランスを取りましょう。",
         high="", draw="arms"),
    Rule("K7", "landing_lean", 12,
         low="着氷後に上体が起きすぎています。軽く前傾して、着氷足の上で滑り出しましょう。",
         high="着氷後に上体が前に倒れすぎています。胸を起こして、姿勢よく滑り出しましょう。",
         draw="trunk"),
    Rule("K7", "shoulder_tilt", 8, absolute=True,
         low="", high="着氷後に{side}肩が下がっています。両肩を水平に保ちましょう。",
         draw="shoulder"),
]


@dataclass
class Advice:
    keyframe: str
    metric: str
    label: str
    mine: float
    ref: float
    severity: float  # |差| / しきい値
    text: str
    good: bool  # True なら「お手本に近い」という良い点
    draw: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def format_value(metric: str, value: float) -> str:
    return METRICS[metric][1](value)


def _evaluate(rule: Rule, mine: float, ref: float) -> Advice:
    label = METRICS[rule.metric][0]
    if rule.absolute:
        diff = abs(mine) - abs(ref)
    else:
        diff = mine - ref
    severity = abs(diff) / rule.threshold
    template = rule.high if diff > 0 else rule.low
    values = f"（自分 {format_value(rule.metric, mine)} / お手本 {format_value(rule.metric, ref)}）"
    if severity >= 1 and template:
        side = "右" if mine > 0 else "左"
        return Advice(rule.keyframe, rule.metric, label, mine, ref, severity,
                      template.format(side=side) + values, False, rule.draw)
    # 差が小さいか、お手本より良い向きの差
    if severity >= 1:
        return Advice(rule.keyframe, rule.metric, label, mine, ref, 0.0,
                      f"{label}は十分できています{values}", True, rule.draw)
    return Advice(rule.keyframe, rule.metric, label, mine, ref, severity,
                  f"{label}はお手本に近いです{values}", True, rule.draw)


def generate_advice(
    my_values: dict[str, dict[str, float | None]], ref_values: dict[str, dict[str, float | None]]
) -> dict[str, list[Advice]]:
    """キーフレームごとのアドバイス（重要度の高い順、最大3件）と良い点（最大1件）。

    my_values / ref_values: {キーフレーム: {測定項目: 値}}。値が None の項目は判定しない。
    """
    result: dict[str, list[Advice]] = {}
    for key in my_values:
        evaluated = []
        for rule in RULES:
            if rule.keyframe != key:
                continue
            mine, ref = my_values[key].get(rule.metric), ref_values[key].get(rule.metric)
            if mine is None or ref is None:
                continue
            evaluated.append(_evaluate(rule, mine, ref))
        problems = sorted((a for a in evaluated if not a.good), key=lambda a: -a.severity)
        goods = sorted((a for a in evaluated if a.good and a.severity < GOOD_SEVERITY), key=lambda a: a.severity)
        result[key] = problems[:MAX_ADVICE_PER_KEYFRAME] + goods[:1]
    return result
