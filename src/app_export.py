"""解析結果を、アプリ（ブラウザ）で表示するための JSON と画像に書き出す。

出力（out_dir の中）:
    result.json      各フレームの骨格・切り抜き枠、キーフレーム（3D 表示用の骨格つき）とアドバイス、まとめ
    ref/<n>.jpg      お手本の切り抜き画像（お手本のフレーム番号ごと）
    ref_<K>.jpg      キーフレームのお手本の画像（測定線つき）
    marks_<K>.png    キーフレームで自分の映像に重ねる測定線（透明背景、元の動画の大きさ）
"""
import json
from pathlib import Path

import cv2
import numpy as np

from advice_rules import METRICS, format_value
from advice_video import (
    GOOD_COLOR, ITEM_COLORS, SUMMARY_METRICS, THUMB_H, THUMB_W, VIEW_H, VIEW_W,
    Cropper, Renderer, annotate_advice,
)
from alignment import MIRROR_INDEX, torso_length
from analysis import AdviceResult
from keyframes import KEYFRAMES
from metrics import VIS_MIN
from overlay import MODEL_STYLE, SELF_STYLE, Comparison
from skeleton_drawer import CENTER_BONES, LEFT_BONES, LEFT_POINTS, NOSE, RIGHT_BONES, RIGHT_POINTS, SkeletonStyle
from view_align import body_yaw, mirror_world, rotate_about_vertical

PHASE_NAMES = {"approach": "踏切前", "air": "空中", "landing": "着氷後"}


def _hex(bgr: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(bgr[2], bgr[1], bgr[0])


def _pose(pts: np.ndarray, vis: np.ndarray) -> dict | None:
    """33点の骨格を {"p": [x0, y0, x1, y1, ...], "v": [0/1, ...]} にする。未検出なら None。"""
    if np.isnan(pts[:, 0]).all():
        return None
    visible = (vis >= VIS_MIN) & ~np.isnan(pts[:, 0])
    flat = np.nan_to_num(pts).round(1).reshape(-1)
    return {"p": flat.tolist(), "v": visible.astype(int).tolist()}


def _points3d(world: np.ndarray, vis: np.ndarray) -> dict | None:
    """33点の3D骨格を {"p": [[x, y, z] | None, ...], "v": [0/1, ...]} にする。未検出なら None。"""
    if np.isnan(world[:, 0]).all():
        return None
    points = [None if np.isnan(q[0]) else q.round(4).tolist() for q in world]
    visible = (vis >= VIS_MIN) & ~np.isnan(world[:, 0])
    return {"p": points, "v": visible.astype(int).tolist()}


class WorldPoses:
    """3D 表示用の骨格。world 座標（メートル、腰の中心が原点、x=右・y=下・z=奥行き）。

    お手本は、2D の重ね合わせと同じく左右反転と撮影角度の差の回転をかけ、
    フレームごとに胴体の長さを自分に合わせる。体の向き（度）は向きをそろえる表示に使う。
    """

    def __init__(self, comp: Comparison) -> None:
        me, ref = comp.me, comp.ref
        self.me, self.me_vis = me.world, me.vis
        ref_world, self.ref_vis = ref.world, ref.vis
        if comp.mirror_model:
            ref_world, self.ref_vis = mirror_world(ref_world), ref.vis[:, MIRROR_INDEX]
        self.ref = rotate_about_vertical(ref_world, comp.view_offset or 0.0)
        self.me_yaw, self.ref_yaw = body_yaw(self.me), body_yaw(self.ref)

    def keyframe(self, my_frame: int, ref_frame: int) -> dict:
        me, ref = self.me[my_frame], self.ref[ref_frame]
        scale = torso_length(me) / torso_length(ref)
        ref = ref * (scale if np.isfinite(scale) and scale > 0 else 1.0)
        return {
            "me": _points3d(me, self.me_vis[my_frame]),
            "ref": _points3d(ref, self.ref_vis[ref_frame]),
            "me_yaw": round(float(self.me_yaw[my_frame]), 1),
            "ref_yaw": round(float(self.ref_yaw[ref_frame]), 1),
        }


def _style(style: SkeletonStyle, width: int, height: int) -> dict:
    # draw_skeleton_points と同じ線の太さ（元の動画のピクセル単位）
    thickness = max(1, round(max(2, min(width, height) / 270) * style.thickness_scale))
    return {"left": _hex(style.left), "right": _hex(style.right), "center": _hex(style.center),
            "thickness": thickness}


def _write_image(path: Path, img: np.ndarray, ext: str) -> None:
    ok, data = cv2.imencode(ext, img, [cv2.IMWRITE_JPEG_QUALITY, 88] if ext == ".jpg" else [])
    if not ok:
        raise OSError(f"画像を書き出せません: {path}")
    path.write_bytes(data.tobytes())


def _marks_image(comp: Comparison, frame: int, advice, thickness: int) -> np.ndarray:
    """測定線だけを描いた透明背景の BGRA 画像。"""
    me = comp.me
    img = np.zeros((me.info.height, me.info.width, 3), np.uint8)
    annotate_advice(img, me.pts[frame], me.vis[frame], advice, thickness)
    # 黒の上に描いたので、明るさを不透明度に、色を不透明度で割り戻す（なめらかな縁を保つ）
    alpha = img.max(axis=2)
    color = np.where(alpha[..., None] > 0, img.astype(np.float32) * 255 / np.maximum(alpha, 1)[..., None], 0)
    return np.dstack([color.clip(0, 255).astype(np.uint8), alpha])


def export(comp: Comparison, result: AdviceResult, out_dir: Path, url_prefix: str, video_url: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ref").mkdir(exist_ok=True)
    me, ref = comp.me, comp.ref
    my_kf, ref_kf, advice = result.my_kf, result.ref_kf, result.advice
    renderer = Renderer(comp, my_kf, ref_kf, advice, 0.25, result.start, result.end)
    crop: Cropper = renderer.my_crop

    for index, thumb in renderer.thumbs.items():
        _write_image(out_dir / "ref" / f"{index}.jpg", thumb, ".jpg")

    frames = []
    for i in range(len(me.poses)):
        transformed = comp.aligner.transform(i)
        position = comp.aligner.ref_frame[i]
        ref_index = None if np.isnan(position) else int(round(position))
        frames.append({
            "me": _pose(me.pts[i], me.vis[i]),
            "ref": _pose(*transformed[:2]) if transformed else None,
            "crop": list(crop.box(i)),
            "thumb": ref_index if ref_index in renderer.thumbs else None,
        })

    world = WorldPoses(comp)
    keyframes = []
    for n, (key, name) in enumerate(KEYFRAMES):
        frame = my_kf[key]
        transformed = comp.aligner.transform_at(frame, ref_kf[key])
        _write_image(out_dir / f"ref_{key}.jpg", renderer.ref_thumb(ref_kf[key], advice[key]), ".jpg")
        _write_image(out_dir / f"marks_{key}.png", _marks_image(comp, frame, advice[key], crop.line_thickness()),
                     ".png")
        items, problem_no = [], 0
        for a in advice[key]:
            item = {"text": a.text, "good": a.good, "label": a.label, "severity": round(a.severity, 2)}
            if a.good:
                item.update(mark="◯", color=_hex(GOOD_COLOR))
            else:
                item.update(mark=str(problem_no + 1), color=_hex(ITEM_COLORS[problem_no % len(ITEM_COLORS)]))
                problem_no += 1
            items.append(item)
        keyframes.append({
            "key": key, "no": n + 1, "name": name, "frame": frame, "ref_frame": ref_kf[key],
            "ref_pose": _pose(*transformed[:2]) if transformed else None,
            "world": world.keyframe(frame, ref_kf[key]),
            "advice": items, "problems": problem_no,
            "ref_image": f"{url_prefix}/ref_{key}.jpg", "marks_image": f"{url_prefix}/marks_{key}.png",
        })

    names = dict(KEYFRAMES)
    problems = sorted((a for items in advice.values() for a in items if not a.good), key=lambda a: -a.severity)
    overall_me, overall_ref = result.my_values["K4"], result.ref_values["K4"]
    summary = {
        "metrics": [
            {"label": METRICS[m][0],
             "me": None if overall_me.get(m) is None else format_value(m, overall_me[m]),
             "ref": None if overall_ref.get(m) is None else format_value(m, overall_ref[m])}
            for m in SUMMARY_METRICS
        ],
        "problems": [
            {"keyframe": a.keyframe, "no": [k for k, _ in KEYFRAMES].index(a.keyframe) + 1,
             "name": names[a.keyframe], "text": a.text, "color": _hex(ITEM_COLORS[n])}
            for n, a in enumerate(problems[:3])
        ],
    }

    ev, rev = me.events, ref.events
    data = {
        "video": {"url": video_url, "fps": me.fps, "width": me.info.width, "height": me.info.height,
                  "frames": len(me.poses)},
        "view": {"width": VIEW_W, "height": VIEW_H, "thumb_width": THUMB_W, "thumb_height": THUMB_H},
        "events": {"takeoff": ev.takeoff, "apex": ev.apex, "landing": ev.landing},
        "air_time": (ev.landing - ev.takeoff) / me.fps,
        "ref_air_time": (rev.landing - rev.takeoff) / ref.fps,
        "range": {"start": result.start, "end": result.end},
        "phases": PHASE_NAMES,
        "view_offset": comp.view_offset,
        "mirror_model": comp.mirror_model,
        "thumb_url": f"{url_prefix}/ref",
        "skeleton": {
            "left_bones": LEFT_BONES, "right_bones": RIGHT_BONES, "center_bones": CENTER_BONES,
            "left_points": LEFT_POINTS, "right_points": RIGHT_POINTS, "nose": NOSE,
            "model": _style(MODEL_STYLE, me.info.width, me.info.height),
            "self": _style(SELF_STYLE, me.info.width, me.info.height),
        },
        "frames": frames,
        "keyframes": keyframes,
        "summary": summary,
    }
    (out_dir / "result.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                                         encoding="utf-8")
    return data
