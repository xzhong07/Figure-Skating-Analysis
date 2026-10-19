"""お手本との差からアドバイスを作り、キーフレームで一時停止して文章を表示するスロー動画を出力する。

使い方:
    python src/advice_video.py input/my_axel.mp4 --reference input/axel_model.mp4
    python src/advice_video.py input/my_axel.mp4 --reference input/axel_model.mp4 --slow 0.2

出力:
    output/<入力名>_advice.mp4   スロー動画（1920x1080, 30fps）
    output/<入力名>_advice.json  キーフレームごとの測定値とアドバイス
    output/<入力名>_advice.md    同じ内容の文章版
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from advice_rules import Advice, format_value, generate_advice, METRICS
from alignment import torso_center
from jump_events import body_series, fill_missing, rolling
from keyframes import KEYFRAME_NAMES, KEYFRAMES, select_keyframes
from main import ROOT
from metrics import FRAME_METRICS, VIS_MIN, Geometry
from overlay import MODEL_STYLE, Comparison, Subject, add_comparison_args, comparison_from_args, draw_overlay
from skeleton_drawer import (
    L_ANKLE, L_HIP, L_KNEE, L_SHOULDER, L_WRIST,
    R_ANKLE, R_HIP, R_KNEE, R_SHOULDER, R_WRIST,
    draw_skeleton_points,
)
from text_render import Canvas, font
from video_io import VideoReader, VideoWriter

OUT_W, OUT_H, OUT_FPS = 1920, 1080, 30
VIEW_W, VIEW_H = 1280, 960  # 左: 人物を切り抜いた映像
PANEL_X, PANEL_W = VIEW_W, OUT_W - VIEW_W  # 右: 情報パネル
PAD = 24
THUMB_W = PANEL_W - 2 * PAD
THUMB_H = THUMB_W * 3 // 4
CROP_BODY = 7.0  # 切り抜きの高さ（胴体の長さの何倍か）
LEAD_S = 0.8  # 踏切の前・着氷の後に再生する秒数
READ_CHARS_PER_S = 9  # 一時停止の長さを決める読む速さ
MAX_FREEZE_S = 15.0
INTRO_S, SUMMARY_S = 5.0, 14.0
CIRCLED = "①②③④⑤⑥⑦"

# アドバイスの番号ごとの色（測定線と同じ色）。BGR
ITEM_COLORS = [(0, 150, 255), (255, 210, 0), (230, 80, 255)]
GOOD_COLOR = (90, 220, 90)
PANEL_BG = (34, 30, 28)

# 全体の比較としてまとめ画面に出す項目
SUMMARY_METRICS = [
    "height_cm", "air_time", "air_rotation", "rotation_speed",
    "free_thigh_peak", "arm_open_before_landing", "landing_knee_min",
]


def rgb(bgr: tuple[int, int, int]) -> tuple[int, int, int]:
    return bgr[2], bgr[1], bgr[0]


# ---------- 測定値 ----------

def collect_values(geom: Geometry, keyframes: dict[str, int]) -> dict[str, dict[str, float | None]]:
    overall = geom.overall()
    return {
        key: {**{m: geom.frame_metric(m, frame) for m in FRAME_METRICS}, **overall}
        for key, frame in keyframes.items()
    }


# ---------- 切り抜き ----------

class Cropper:
    """人物を中心に、一定の大きさで切り抜く。中心はなめらかに追従させる。"""

    def __init__(self, subject: Subject, start: int, end: int, aspect: float) -> None:
        self.frame_w, self.frame_h = subject.info.width, subject.info.height
        pts = subject.pts
        center = torso_center(pts)
        cx = rolling(fill_missing(center[:, 0]), 4, np.mean)
        cy = rolling(fill_missing(center[:, 1]), 4, np.mean)
        _, _, torso = body_series(pts)
        size = float(np.median(torso[start : end + 1]))
        self.h = min(subject.info.height, size * CROP_BODY)
        self.w = self.h * aspect
        # 脚が胴体より下に長いので、中心を少し下げる
        self.cx, self.cy = cx, cy + 0.6 * size

    def box(self, index: int) -> tuple[int, int, int, int]:
        w, h = int(round(self.w)), int(round(self.h))
        x0 = int(round(self.cx[index] - w / 2))
        y0 = int(round(self.cy[index] - h / 2))
        # 枠が映像からはみ出さないよう内側にずらす（映像より大きい枠のときだけ黒い余白が出る）
        if w <= self.frame_w:
            x0 = min(max(0, x0), self.frame_w - w)
        if h <= self.frame_h:
            y0 = min(max(0, y0), self.frame_h - h)
        return x0, y0, w, h

    def crop(self, frame: np.ndarray, index: int, out_size: tuple[int, int]) -> np.ndarray:
        x0, y0, w, h = self.box(index)
        canvas = np.zeros((h, w, 3), np.uint8)
        fh, fw = frame.shape[:2]
        sx0, sy0, sx1, sy1 = max(0, x0), max(0, y0), min(fw, x0 + w), min(fh, y0 + h)
        if sx1 > sx0 and sy1 > sy0:
            canvas[sy0 - y0 : sy1 - y0, sx0 - x0 : sx1 - x0] = frame[sy0:sy1, sx0:sx1]
        return cv2.resize(canvas, out_size, interpolation=cv2.INTER_AREA)

    def line_thickness(self) -> int:
        return max(2, round(self.h / 160))


# ---------- 測定線 ----------

def _p(pts: np.ndarray, i: int) -> tuple[int, int]:
    return int(round(pts[i, 0])), int(round(pts[i, 1]))


def _mid(pts: np.ndarray, a: int, b: int) -> np.ndarray:
    return (pts[a] + pts[b]) / 2


def _dashed(img: np.ndarray, a: np.ndarray, b: np.ndarray, color, thickness: int, dash: int = 14) -> None:
    length = float(np.linalg.norm(b - a))
    if length < 1:
        return
    steps = int(length // dash)
    for k in range(0, steps, 2):
        p0 = a + (b - a) * (k / steps)
        p1 = a + (b - a) * (min(k + 1, steps) / steps)
        cv2.line(img, tuple(p0.astype(int)), tuple(p1.astype(int)), color, thickness, cv2.LINE_AA)


def _line(img, a, b, color, thickness) -> None:
    cv2.line(img, tuple(np.asarray(a).astype(int)), tuple(np.asarray(b).astype(int)), color, thickness, cv2.LINE_AA)


def annotate(img: np.ndarray, pts: np.ndarray, vis: np.ndarray, tag: str, color, thickness: int) -> None:
    """測定している線や点を描く。必要な関節が見えていなければ何もしない。"""

    def ok(*idx: int) -> bool:
        return all(vis[i] >= VIS_MIN and not np.isnan(pts[i, 0]) for i in idx)

    t = thickness
    dot = t * 3
    if tag in ("trunk", "axis"):
        if not ok(L_SHOULDER, R_SHOULDER, L_HIP, R_HIP) or (tag == "axis" and not ok(L_ANKLE, R_ANKLE)):
            return
        bottom = _mid(pts, L_HIP, R_HIP) if tag == "trunk" else _mid(pts, L_ANKLE, R_ANKLE)
        top = _mid(pts, L_SHOULDER, R_SHOULDER)
        top = bottom + (top - bottom) * 1.3
        length = float(np.linalg.norm(top - bottom))
        _dashed(img, bottom, bottom - np.array([0, length]), (255, 255, 255), max(1, t // 2))
        _line(img, bottom, top, color, t)
        cv2.circle(img, tuple(bottom.astype(int)), dot, color, -1, cv2.LINE_AA)
    elif tag == "shoulder":
        if not ok(L_SHOULDER, R_SHOULDER):
            return
        a, b = pts[L_SHOULDER], pts[R_SHOULDER]
        center = (a + b) / 2
        half = np.linalg.norm(b - a) * 0.8
        _dashed(img, center - np.array([half, 0]), center + np.array([half, 0]), (255, 255, 255), max(1, t // 2))
        _line(img, a - (b - a) * 0.3, b + (b - a) * 0.3, color, t)
    elif tag in ("thigh", "free_leg"):
        hip, end = (R_HIP, R_KNEE) if tag == "thigh" else (L_HIP, L_ANKLE)
        if not ok(hip, end):
            return
        a, b = pts[hip], pts[end]
        length = float(np.linalg.norm(b - a))
        _dashed(img, a, a + np.array([0, length]), (255, 255, 255), max(1, t // 2))
        _line(img, a, a + (b - a) * 1.2, color, t)
        cv2.circle(img, _p(pts, hip), dot, color, -1, cv2.LINE_AA)
    elif tag in ("takeoff_knee", "landing_knee"):
        hip, knee, ankle = (L_HIP, L_KNEE, L_ANKLE) if tag == "takeoff_knee" else (R_HIP, R_KNEE, R_ANKLE)
        if not ok(hip, knee, ankle):
            return
        poly = np.array([_p(pts, hip), _p(pts, knee), _p(pts, ankle)], np.int32)
        cv2.polylines(img, [poly], False, color, t + 1, cv2.LINE_AA)
        cv2.circle(img, _p(pts, knee), dot + 2, color, t, cv2.LINE_AA)
    elif tag == "arms":
        if not ok(L_SHOULDER, R_SHOULDER, L_HIP, R_HIP):
            return
        center = torso_center(pts)
        for w in (L_WRIST, R_WRIST):
            if ok(w):
                _dashed(img, center, pts[w], color, max(1, t // 2 + 1))
                cv2.circle(img, _p(pts, w), dot, color, t, cv2.LINE_AA)
    elif tag == "feet":
        for a, b in ((L_ANKLE, R_ANKLE), (L_KNEE, R_KNEE)):
            if ok(a, b):
                _line(img, pts[a], pts[b], color, t)
                cv2.circle(img, _p(pts, a), dot, color, -1, cv2.LINE_AA)
                cv2.circle(img, _p(pts, b), dot, color, -1, cv2.LINE_AA)
    elif tag == "foot":
        if not ok(L_HIP, R_HIP, L_ANKLE):
            return
        hip = _mid(pts, L_HIP, R_HIP)
        _dashed(img, hip, np.array([hip[0], pts[L_ANKLE, 1]]), (255, 255, 255), max(1, t // 2))
        _line(img, np.array([hip[0], pts[L_ANKLE, 1]]), pts[L_ANKLE], color, t)
        cv2.circle(img, _p(pts, L_ANKLE), dot + 2, color, t, cv2.LINE_AA)


def annotate_advice(img: np.ndarray, pts: np.ndarray, vis: np.ndarray, advice: list[Advice], thickness: int) -> None:
    for n, a in enumerate(x for x in advice if not x.good):
        if a.draw:
            annotate(img, pts, vis, a.draw, ITEM_COLORS[n % len(ITEM_COLORS)], thickness)


# ---------- 画面の組み立て ----------

class Renderer:
    def __init__(self, comp: Comparison, my_kf: dict[str, int], ref_kf: dict[str, int],
                 advice: dict[str, list[Advice]], slow: float, start: int, end: int) -> None:
        self.comp, self.my_kf, self.ref_kf, self.advice = comp, my_kf, ref_kf, advice
        self.slow, self.start, self.end = slow, start, end
        me, ref = comp.me, comp.ref
        self.my_crop = Cropper(me, start, end, VIEW_W / VIEW_H)
        self.ref_start = max(0, ref.events.takeoff - round(1.0 * ref.fps))
        self.ref_end = min(len(ref.poses) - 1, ref.events.landing + round(1.0 * ref.fps))
        self.ref_crop = Cropper(ref, self.ref_start, self.ref_end, THUMB_W / THUMB_H)
        self.ref_frames = self._load_ref_frames()
        self.thumbs = {i: self.ref_thumb(i, []) for i in self.ref_frames}

    def _load_ref_frames(self) -> dict[int, np.ndarray]:
        frames = {}
        with VideoReader(self.comp.ref.video) as reader:
            for index, _, frame in reader.frames():
                if index > self.ref_end:
                    break
                if index >= self.ref_start:
                    frames[index] = frame
        return frames

    def ref_thumb(self, index: int, advice: list[Advice]) -> np.ndarray:
        ref = self.comp.ref
        img = self.ref_frames[index].copy()
        if ref.poses[index].detected:
            draw_skeleton_points(img, ref.pts[index], ref.vis[index] >= VIS_MIN, MODEL_STYLE)
            annotate_advice(img, ref.pts[index], ref.vis[index], advice, self.ref_crop.line_thickness())
        thumb = self.ref_crop.crop(img, index, (THUMB_W, THUMB_H))
        return cv2.flip(thumb, 1) if self.comp.mirror_model else thumb

    def view(self, frame: np.ndarray, index: int, key: str | None = None) -> np.ndarray:
        """自分の映像（骨格と、一時停止中は測定線つき）を切り抜く。"""
        img = frame.copy()
        if key is None:
            draw_overlay(img, self.comp, index)
        else:
            draw_overlay(img, self.comp, index, ref_position=self.ref_kf[key])
            me = self.comp.me
            annotate_advice(img, me.pts[index], me.vis[index], self.advice[key], self.my_crop.line_thickness())
        return self.my_crop.crop(img, index, (VIEW_W, VIEW_H))

    TIMELINE_X0, TIMELINE_X1 = 48, VIEW_W - 48
    TIMELINE_Y0, TIMELINE_Y1 = VIEW_H + 52, VIEW_H + 80

    def _x_of(self, frame: float) -> int:
        span = self.end - self.start
        return int(self.TIMELINE_X0 + (self.TIMELINE_X1 - self.TIMELINE_X0) * (frame - self.start) / span)

    def _zones(self):
        ev = self.comp.me.events
        return [
            (self.start, ev.takeoff, (120, 100, 80), "踏切前"),
            (ev.takeoff, ev.landing, (40, 140, 230), "空中"),
            (ev.landing, self.end, (90, 150, 90), "着氷後"),
        ]

    def _timeline_shapes(self, base: np.ndarray, index: float) -> None:
        """時間の帯（踏切前 / 空中 / 着氷後）、キーフレームの印、今の位置。"""
        y0, y1 = self.TIMELINE_Y0, self.TIMELINE_Y1
        for a, b, color, _ in self._zones():
            cv2.rectangle(base, (self._x_of(a), y0), (self._x_of(b), y1), color, -1)
        for key, _ in KEYFRAMES:
            x = self._x_of(self.my_kf[key])
            cv2.line(base, (x, y0 - 6), (x, y1), (255, 255, 255), 2)
        x = self._x_of(index)
        cv2.rectangle(base, (x - 3, y0 - 4), (x + 3, y1 + 4), (0, 0, 255), -1)

    def _timeline_labels(self, canvas: Canvas) -> None:
        for a, b, _, label in self._zones():
            canvas.text(((self._x_of(a) + self._x_of(b)) // 2, self.TIMELINE_Y1 + 6), label, 18,
                        (220, 220, 220), anchor="ma")
        for n, (key, _) in enumerate(KEYFRAMES):
            canvas.text((self._x_of(self.my_kf[key]), self.TIMELINE_Y0 - 10), CIRCLED[n], 26,
                        bold=True, anchor="mb")

    def compose(self, view: np.ndarray, index: int, key: str | None) -> np.ndarray:
        base = np.full((OUT_H, OUT_W, 3), PANEL_BG, np.uint8)
        base[:VIEW_H, :VIEW_W] = view
        me = self.comp.me

        if key is None:
            position = self.comp.aligner.ref_frame[index] if index < len(me.poses) else np.nan
            ref_index = None if np.isnan(position) else int(round(position))
            thumb = self.thumbs.get(ref_index) if ref_index is not None else None
        else:
            thumb = self.ref_thumb(self.ref_kf[key], self.advice[key])
        ty = PAD + 96
        if thumb is not None:
            base[ty : ty + THUMB_H, PANEL_X + PAD : PANEL_X + PAD + THUMB_W] = thumb
        else:
            cv2.rectangle(base, (PANEL_X + PAD, ty), (PANEL_X + PAD + THUMB_W, ty + THUMB_H), (60, 60, 60), -1)

        self._timeline_shapes(base, index)
        canvas = Canvas(base)
        self._timeline_labels(canvas)
        label = "お手本（元の映像）"
        canvas.rect((PANEL_X + PAD, ty, PANEL_X + PAD + 24 + int(font(24, bold=True).getlength(label)), ty + 40),
                    (0, 0, 0, 170), radius=6)
        canvas.text((PANEL_X + PAD + 12, ty + 6), label, 24, rgb(MODEL_STYLE.left), bold=True)
        if thumb is None:
            canvas.text((PANEL_X + PAD + THUMB_W // 2, ty + THUMB_H // 2), "（対応する場面なし）", 24,
                        (180, 180, 180), anchor="mm")

        phase = {"approach": "踏切前", "air": "空中", "landing": "着氷後"}[me.events.phase(index)]
        if key is None:
            canvas.text((PANEL_X + PAD, PAD), f"▶ スロー再生（{self.slow:g}倍速）", 38, bold=True)
            canvas.text((PANEL_X + PAD, PAD + 52), f"自分 {index / me.fps:.2f}秒 ・ {phase}", 24, (190, 190, 190))
            self._legend(canvas, ty + THUMB_H + 28, index)
            badge = f"▶ {self.slow:g}倍速"
        else:
            n = [k for k, _ in KEYFRAMES].index(key)
            canvas.text((PANEL_X + PAD, PAD), f"{CIRCLED[n]} {KEYFRAME_NAMES[key]}", 42, bold=True)
            canvas.text((PANEL_X + PAD, PAD + 54), f"一時停止中 ・ 自分 {index / me.fps:.2f}秒", 24, (190, 190, 190))
            self._advice_list(canvas, ty + THUMB_H + 24, self.advice[key])
            badge = f"■ 一時停止　{CIRCLED[n]} {KEYFRAME_NAMES[key]}"
        canvas.rect((16, 16, 48 + int(font(32, bold=True).getlength(badge)), 70), (0, 0, 0, 170), radius=8)
        canvas.text((32, 24), badge, 32, bold=True)
        return canvas.to_bgr()

    def _legend(self, canvas: Canvas, y: int, index: int) -> None:
        x, width = PANEL_X + PAD, THUMB_W
        lines = [
            ("太線（緑・黄）＝お手本の骨格", rgb(MODEL_STYLE.right)),
            ("細線（水色・桃色）＝自分の骨格", (200, 200, 230)),
            ("緑・水色が左半身、黄・桃色が右半身", (190, 190, 190)),
        ]
        for text, color in lines:
            y = canvas.paragraph((x, y), text, 26, width, color) + 6
        upcoming = [(n, k) for n, (k, _) in enumerate(KEYFRAMES) if self.my_kf[k] >= index]
        if upcoming:
            n, k = upcoming[0]
            canvas.paragraph((x, y + 18), f"次の一時停止：{CIRCLED[n]} {KEYFRAME_NAMES[k]}", 28, width, bold=True)

    def _advice_list(self, canvas: Canvas, y: int, advice: list[Advice]) -> None:
        x, width = PANEL_X + PAD, THUMB_W
        bottom = OUT_H - PAD
        indent = 40
        for size in (26, 24, 22, 20):
            total = sum(Canvas.paragraph_height(a.text, size, width - indent) + 14 for a in advice)
            if y + total <= bottom:
                break
        if not advice:
            canvas.paragraph((x, y), "この場面で比べられる項目がありませんでした（関節が隠れているなど）。", size, width,
                             (200, 200, 200))
            return
        problem_no = 0
        for a in advice:
            if a.good:
                mark, color = "◯", rgb(GOOD_COLOR)
            else:
                mark, color = str(problem_no + 1), rgb(ITEM_COLORS[problem_no % len(ITEM_COLORS)])
                problem_no += 1
            canvas.rect((x, y + 2, x + 30, y + 32), color + (255,), radius=15)
            canvas.text((x + 15, y + 17), mark, 20, (20, 20, 20), bold=True, anchor="mm")
            y = canvas.paragraph((x + indent, y), a.text, size, width - indent,
                                 (235, 235, 235) if not a.good else (200, 235, 200)) + 14


def freeze_seconds(advice: list[Advice]) -> float:
    chars = sum(len(a.text) for a in advice)
    return float(min(MAX_FREEZE_S, max(3.0, 1.5 + chars / READ_CHARS_PER_S)))


def intro_screen(view: np.ndarray, comp: Comparison, slow: float) -> np.ndarray:
    base = np.full((OUT_H, OUT_W, 3), PANEL_BG, np.uint8)
    base[:VIEW_H, :VIEW_W] = (view * 0.35).astype(np.uint8)
    canvas = Canvas(base)
    me, ref = comp.me, comp.ref
    x, y, width = 80, 120, OUT_W - 160
    canvas.text((x, y), "シングルアクセル　お手本との比較アドバイス", 56, bold=True)
    y += 110
    lines = [
        f"・{slow:g}倍速で再生し、{len(KEYFRAMES)}つの場面で一時停止してアドバイスを表示します。",
        "・太線（緑・黄）がお手本、細線（水色・桃色）が自分の骨格です。お手本は自分の体の位置と大きさに合わせています。",
        (f"・お手本の骨格は、撮影角度の差（約{abs(comp.view_offset):.0f}°）を3Dで回して補正し、自分のカメラから見た形で重ねています。"
         "右上のお手本の映像は元の撮影角度のままです。")
        if comp.view_offset is not None else "・お手本の骨格は、お手本の撮影角度のまま重ねています。",
        "・一時停止中は、アドバイスの番号と同じ色の線で、測った場所を示します（白い点線は水平・鉛直の目安）。",
        f"・踏切と着氷：自分 {me.events.takeoff / me.fps:.2f}秒 → {me.events.landing / me.fps:.2f}秒"
        f"（滞空 {(me.events.landing - me.events.takeoff) / me.fps:.2f}秒）／ お手本の滞空 "
        f"{(ref.events.landing - ref.events.takeoff) / ref.fps:.2f}秒",
        "・数値は骨格推定によるおおよその値です。撮影の角度が違うと、角度などにずれが出ることがあります。",
    ]
    for line in lines:
        y = canvas.paragraph((x, y), line, 32, width) + 22
    return canvas.to_bgr()


def summary_screen(my_values, ref_values, advice: dict[str, list[Advice]]) -> np.ndarray:
    base = np.full((OUT_H, OUT_W, 3), PANEL_BG, np.uint8)
    canvas = Canvas(base)
    canvas.text((80, 60), "まとめ", 56, bold=True)

    x, y = 80, 170
    col = [x, x + 470, x + 690]
    canvas.text((col[1], y), "自分", 30, bold=True)
    canvas.text((col[2], y), "お手本", 30, rgb(MODEL_STYLE.left), bold=True)
    y += 56
    overall_me, overall_ref = my_values["K4"], ref_values["K4"]
    for metric in SUMMARY_METRICS:
        mine, ref = overall_me.get(metric), overall_ref.get(metric)
        canvas.text((col[0], y), METRICS[metric][0], 28)
        canvas.text((col[1], y), "—" if mine is None else format_value(metric, mine), 28)
        canvas.text((col[2], y), "—" if ref is None else format_value(metric, ref), 28, (200, 230, 200))
        y += 54

    x2, width = 1000, OUT_W - 1000 - 80
    canvas.text((x2, 170), "特に直したいポイント", 34, bold=True)
    problems = sorted((a for items in advice.values() for a in items if not a.good), key=lambda a: -a.severity)
    y = 236
    for n, a in enumerate(problems[:3]):
        color = rgb(ITEM_COLORS[n])
        canvas.rect((x2, y + 2, x2 + 34, y + 36), color + (255,), radius=17)
        canvas.text((x2 + 17, y + 19), str(n + 1), 22, (20, 20, 20), bold=True, anchor="mm")
        idx = [k for k, _ in KEYFRAMES].index(a.keyframe)
        canvas.text((x2 + 48, y), f"{CIRCLED[idx]} {KEYFRAME_NAMES[a.keyframe]}", 26, (190, 190, 190))
        y = canvas.paragraph((x2 + 48, y + 38), a.text, 28, width - 48) + 30
    if not problems:
        canvas.paragraph((x2, y), "大きな差は見つかりませんでした。", 28, width)
    return canvas.to_bgr()


# ---------- 出力 ----------

def write_reports(path_json: Path, path_md: Path, comp: Comparison, my_kf, ref_kf, my_values, ref_values,
                  advice: dict[str, list[Advice]]) -> None:
    me, ref = comp.me, comp.ref
    data = {
        "input": str(me.video),
        "reference": str(ref.video),
        "events": {"me": vars(me.events), "reference": vars(ref.events)},
        "keyframes": {
            key: {
                "name": name,
                "frame": my_kf[key],
                "reference_frame": ref_kf[key],
                "values": {m: {"me": my_values[key].get(m), "reference": ref_values[key].get(m)}
                           for m in my_values[key]},
                "advice": [a.to_dict() for a in advice[key]],
            }
            for key, name in KEYFRAMES
        },
    }
    path_json.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = [
        f"# アドバイス：{me.video.name}（お手本：{ref.video.name}）",
        "",
        f"- 自分：踏切 {me.events.takeoff / me.fps:.2f}秒、着氷 {me.events.landing / me.fps:.2f}秒"
        f"（滞空 {(me.events.landing - me.events.takeoff) / me.fps:.2f}秒）",
        f"- お手本：滞空 {(ref.events.landing - ref.events.takeoff) / ref.fps:.2f}秒",
        "- 数値は骨格推定によるおおよその値です。撮影角度の差で、角度などにずれが出ることがあります。",
        "",
        "## 全体の比較",
        "",
        "| 項目 | 自分 | お手本 |",
        "|---|---|---|",
    ]
    for metric in SUMMARY_METRICS:
        mine, r = my_values["K4"].get(metric), ref_values["K4"].get(metric)
        lines.append(f"| {METRICS[metric][0]} | {'—' if mine is None else format_value(metric, mine)} | "
                     f"{'—' if r is None else format_value(metric, r)} |")
    for n, (key, name) in enumerate(KEYFRAMES):
        lines += ["", f"## {CIRCLED[n]} {name}（自分 {my_kf[key]}フレーム / お手本 {ref_kf[key]}フレーム）", ""]
        if not advice[key]:
            lines.append("- 比べられる項目がありませんでした。")
        for a in advice[key]:
            lines.append(f"- {'◯ ' if a.good else ''}{a.text}")
    path_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="お手本との差からアドバイスを作り、スロー動画で表示します。")
    add_comparison_args(parser)
    parser.add_argument("-o", "--output", type=Path, help="出力動画（既定: output/<入力名>_advice.mp4）")
    parser.add_argument("--slow", type=float, default=0.25, help="再生速度（0.25 = 4倍スロー）")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output or ROOT / "output" / f"{args.input.stem}_advice.mp4"

    comp = comparison_from_args(args)
    my_geom, ref_geom = Geometry(comp.me), Geometry(comp.ref)
    my_kf, ref_kf = select_keyframes(my_geom), select_keyframes(ref_geom)
    my_values, ref_values = collect_values(my_geom, my_kf), collect_values(ref_geom, ref_kf)
    advice = generate_advice(my_values, ref_values)

    write_reports(output.with_suffix(".json"), output.with_suffix(".md"), comp, my_kf, ref_kf,
                  my_values, ref_values, advice)
    for n, (key, name) in enumerate(KEYFRAMES):
        print(f"{CIRCLED[n]} {name}（自分 {my_kf[key]} / お手本 {ref_kf[key]}）")
        for a in advice[key]:
            print(f"   {'◯' if a.good else '・'} {a.text}")

    me = comp.me
    start = max(0, me.events.takeoff - round(LEAD_S * me.fps))
    # 着氷後のキーフレーム（K7）が LEAD_S より後になる場合もそこまで再生する
    end = min(len(me.poses) - 1, max(me.events.landing + round(LEAD_S * me.fps), max(my_kf.values())))
    renderer = Renderer(comp, my_kf, ref_kf, advice, args.slow, start, end)

    out_per_source = OUT_FPS / (me.fps * args.slow)
    pending = 0.0
    written = 0
    with VideoReader(args.input) as reader, VideoWriter(output, OUT_FPS, OUT_W, OUT_H) as writer:

        def emit(img: np.ndarray, count: int) -> None:
            nonlocal written
            for _ in range(count):
                writer.write(img)
            written += count

        last_view = None
        for index, _, frame in reader.frames():
            if index < start:
                continue
            if index > end:
                break
            view = renderer.view(frame, index)
            if index == start:
                emit(intro_screen(view, comp, args.slow), round(INTRO_S * OUT_FPS))
            pending += out_per_source
            count = int(pending)
            pending -= count
            if count:
                emit(renderer.compose(view, index, None), count)
            for key, _ in KEYFRAMES:
                if my_kf[key] == index:
                    still = renderer.compose(renderer.view(frame, index, key), index, key)
                    emit(still, round(freeze_seconds(advice[key]) * OUT_FPS))
            last_view = view
            print(f"\r動画を作成中: {index - start + 1}/{end - start + 1}", end="", flush=True)
        if last_view is not None:
            emit(summary_screen(my_values, ref_values, advice), round(SUMMARY_S * OUT_FPS))

    print(f"\r出力動画: {output}（{written / OUT_FPS:.1f}秒）")
    print(f"アドバイス: {output.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
