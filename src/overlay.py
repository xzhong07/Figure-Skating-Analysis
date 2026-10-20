"""自分の動画に、お手本の骨格を踏切のタイミングと体の大きさ・位置をそろえて重ねる。

使い方:
    python src/overlay.py input/my_axel.mp4 --reference input/axel_model.mp4
    python src/overlay.py input/my_axel.mp4 --reference input/axel_model.mp4 --my-takeoff 52 --my-landing 67
"""
import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from alignment import Aligner, map_time, to_pixels, to_world
from camera_motion import estimate_camera_motion, stabilize_points
from jump_events import JumpEvents, detect_jump
from landmarks_io import load_landmarks, save_landmarks
from main import ROOT, extract_poses, model_path_for
from pose_estimator import PoseFrame
from skeleton_drawer import SkeletonStyle, draw_skeleton, draw_skeleton_points, draw_text_lines
from video_io import VideoInfo, VideoReader, VideoWriter
from view_align import SPREAD_WARNING_DEG, estimate_view_offset, mirror_world, project, rotate_about_vertical

# お手本: 太め・はっきりした色（左=緑、右=黄）。自分: 細め・薄い色（左=水色、右=桃色）
MODEL_STYLE = SkeletonStyle(left=(60, 220, 60), right=(0, 220, 255), center=(255, 255, 255), thickness_scale=1.3)
SELF_STYLE = SkeletonStyle(left=(230, 190, 140), right=(170, 150, 255), center=(200, 200, 200), thickness_scale=0.5)


# 進み具合の通知: (段階の名前, 済んだ数, 全体の数)
Progress = Callable[[str, int, int], None]


def load_or_extract(
    video: Path, model_name: str, min_confidence: float,
    json_path: Path | None = None, on_progress: Progress | None = None,
) -> tuple[VideoInfo, list[PoseFrame]]:
    """ランドマークJSON（既定: output/<名前>_landmarks.json）が同じモデルで作られていれば読み込み、
    なければ推定して保存する。"""
    json_path = json_path or ROOT / "output" / f"{video.stem}_landmarks.json"
    model_path = model_path_for(model_name)
    with VideoReader(video) as reader:
        info = reader.info
        if json_path.exists():
            meta, poses = load_landmarks(json_path)
            if meta.get("model") == model_path.name:
                print(f"既存のランドマークを使用: {json_path}")
                return info, poses
        print(f"骨格を推定: {video}")
        on_frame = None
        if on_progress:
            total = max(1, info.frame_count)

            def on_frame(_frame, pose: PoseFrame) -> None:
                on_progress("pose", min(pose.frame_index + 1, total), total)
        poses = extract_poses(reader, model_path, min_confidence, on_frame)
    save_landmarks(json_path, video, model_path.name, info, poses)
    print(f"ランドマーク: {json_path}")
    return info, poses


def describe(name: str, events: JumpEvents, fps: float) -> str:
    air = (events.landing - events.takeoff) / fps
    return f"{name}: 踏切={events.takeoff} 頂点={events.apex} 着氷={events.landing}（滞空 {air:.2f}秒）"


@dataclass
class Subject:
    """1本の動画の解析結果。座標はすべて左右反転していない元の向き。"""

    video: Path
    info: VideoInfo
    poses: list[PoseFrame]
    pts: np.ndarray  # (N, 33, 2) ピクセル座標。未検出は NaN
    vis: np.ndarray  # (N, 33)
    world: np.ndarray  # (N, 33, 3) メートル単位の3D座標。未検出は NaN
    stable: np.ndarray  # (N, 33, 2) カメラの動きを打ち消したピクセル座標
    events: JumpEvents

    @property
    def fps(self) -> float:
        return self.info.fps


@dataclass
class Comparison:
    me: Subject
    ref: Subject
    aligner: Aligner
    mirror_model: bool
    view_offset: float | None = None  # お手本の3D骨格を回した角度（度）。None なら2Dのまま重ねている
    view_spread: float | None = None  # 撮影角度の差の推定のばらつき（度）。手動指定のときは None


def load_subject(
    video: Path, model_name: str, min_confidence: float, takeoff: int | None, landing: int | None,
    landmarks_path: Path | None = None, on_progress: Progress | None = None,
) -> Subject:
    info, poses = load_or_extract(video, model_name, min_confidence, landmarks_path, on_progress)
    if on_progress:
        on_progress("camera", 0, 1)
    pts, vis = to_pixels(poses, info.width, info.height)
    stable = stabilize_points(pts, estimate_camera_motion(video, poses))
    events = detect_jump(stable, info.fps, takeoff, landing)
    return Subject(video, info, poses, pts, vis, to_world(poses), stable, events)


def build_comparison(
    my_video: Path,
    ref_video: Path,
    model_name: str = "heavy",
    min_confidence: float = 0.5,
    mirror_model: bool = False,
    my_takeoff: int | None = None,
    my_landing: int | None = None,
    model_takeoff: int | None = None,
    model_landing: int | None = None,
    view_align: bool = True,
    view_offset: float | None = None,
    my_landmarks_path: Path | None = None,
    on_progress: Progress | None = None,
) -> Comparison:
    """両方の動画の骨格を用意し、踏切・着氷を検出して、時間と位置の対応づけを作る。

    view_align=True のときは、お手本の3D骨格を撮影角度の差だけ回してから写して重ねる
    （view_offset を渡すとその角度を使う）。False ならお手本の画面上の2D骨格をそのまま重ねる。
    my_landmarks_path を渡すと、自分の動画のランドマークJSONをそこに保存・再利用する。
    on_progress には自分の動画の処理の進み具合を知らせる。
    """
    ref = load_subject(ref_video, model_name, min_confidence, model_takeoff, model_landing)
    me = load_subject(my_video, model_name, min_confidence, my_takeoff, my_landing, my_landmarks_path, on_progress)
    print(describe("お手本", ref.events, ref.fps))
    print(describe("自分  ", me.events, me.fps))

    ref_pts, ref_vis = to_pixels(ref.poses, ref.info.width, ref.info.height, mirror=mirror_model)
    spread = None
    if view_align:
        ref_world = mirror_world(ref.world) if mirror_model else ref.world
        if view_offset is None:
            ref_frame = map_time(me.events, me.fps, len(me.poses), ref.events, ref.fps, len(ref.poses))
            view_offset, spread = estimate_view_offset(me.world, me.events, me.fps, ref_world, ref_frame)
            print(f"撮影角度の差: {view_offset:.0f}°（ばらつき {spread:.0f}°）")
            if spread > SPREAD_WARNING_DEG:
                print("  ※ ばらつきが大きく、推定が不安定です。--view-offset で角度を指定することもできます。")
        else:
            print(f"撮影角度の差: {view_offset:.0f}°（手動指定）")
        # Aligner は胴体の長さの比で拡大するので、メートル単位の座標をそのまま渡せる
        ref_pts = project(rotate_about_vertical(ref_world, view_offset))
    else:
        view_offset = None
    aligner = Aligner(me.pts, me.fps, me.events, ref_pts, ref_vis, ref.fps, ref.events)
    return Comparison(me, ref, aligner, mirror_model, view_offset, spread)


def draw_overlay(
    frame: np.ndarray,
    comp: Comparison,
    index: int,
    min_visibility: float = 0.5,
    hide_self: bool = False,
    ref_position: float | None = None,
) -> dict | None:
    """自分の動画のフレームに、自分の骨格（細線）とお手本の骨格（太線）を描く。

    ref_position を渡すと、時間の対応づけの代わりにそのお手本のフレーム位置の骨格を描く。
    お手本の骨格を描いたときは変換の情報を返す。
    """
    if index >= len(comp.me.poses):
        return None
    if not hide_self:
        draw_skeleton(frame, comp.me.poses[index], min_visibility, SELF_STYLE)
    if ref_position is None:
        result = comp.aligner.transform(index)
    else:
        result = comp.aligner.transform_at(index, ref_position)
    if result is None:
        return None
    mapped, vis, info = result
    draw_skeleton_points(frame, mapped, vis >= min_visibility, MODEL_STYLE)
    return info


def add_comparison_args(parser: argparse.ArgumentParser) -> None:
    """お手本と比べる CLI に共通の引数。"""
    parser.add_argument("input", type=Path, help="自分の動画")
    parser.add_argument("--reference", type=Path, required=True, help="お手本の動画")
    parser.add_argument("--model", choices=["lite", "full", "heavy"], default="heavy", help="使用するモデル")
    parser.add_argument("--min-visibility", type=float, default=0.5, help="この値未満の関節は描画しない")
    parser.add_argument("--min-confidence", type=float, default=0.5, help="検出・追跡の信頼度しきい値")
    parser.add_argument("--my-takeoff", type=int, help="自分の動画の踏切フレーム（自動検出を上書き）")
    parser.add_argument("--my-landing", type=int, help="自分の動画の着氷フレーム（自動検出を上書き）")
    parser.add_argument("--model-takeoff", type=int, help="お手本の踏切フレーム（自動検出を上書き）")
    parser.add_argument("--model-landing", type=int, help="お手本の着氷フレーム（自動検出を上書き）")
    parser.add_argument("--mirror-model", action="store_true",
                        help="お手本を左右反転する（撮影角度の補正を使うときは通常不要）")
    parser.add_argument("--no-view-align", action="store_true",
                        help="撮影角度の補正をせず、お手本の画面上の骨格をそのまま重ねる")
    parser.add_argument("--view-offset", type=float, help="撮影角度の差（度）を手動で指定する（自動推定を上書き）")


def comparison_from_args(args: argparse.Namespace) -> Comparison:
    return build_comparison(
        args.input, args.reference, args.model, args.min_confidence, args.mirror_model,
        args.my_takeoff, args.my_landing, args.model_takeoff, args.model_landing,
        view_align=not args.no_view_align, view_offset=args.view_offset,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="自分の動画にお手本の骨格を重ねて出力します。")
    add_comparison_args(parser)
    parser.add_argument("-o", "--output", type=Path, help="出力動画（既定: output/<入力名>_overlay.mp4）")
    parser.add_argument("--hide-self", action="store_true", help="自分の骨格を描かない")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output or ROOT / "output" / f"{args.input.stem}_overlay.mp4"
    alignment_path = output.with_name(f"{args.input.stem}_alignment.json")

    comp = comparison_from_args(args)
    my_info, ref_info = comp.me.info, comp.ref.info
    my_events, ref_events = comp.me.events, comp.ref.events

    records = []
    drawn = 0
    with VideoReader(args.input) as reader, VideoWriter(output, my_info.fps, my_info.width, my_info.height) as writer:
        for index, _, frame in reader.frames():
            info = draw_overlay(frame, comp, index, args.min_visibility, args.hide_self)
            ref_frame = comp.aligner.ref_frame[index] if index < len(comp.me.poses) else np.nan
            record = {"frame": index, "phase": my_events.phase(index), "ref_frame": None}
            if info is not None:
                record.update(ref_frame=round(float(ref_frame), 3), **info)
                drawn += 1
            records.append(record)

            ref_text = f"model {ref_frame:.1f}" if info is not None else "model -"
            draw_text_lines(frame, [
                f"frame {index}  {index / my_info.fps:.2f}s  {ref_text}  [{my_events.phase(index)}]",
                "green/yellow: model   thin: me",
            ])
            writer.write(frame)

    print(f"お手本の骨格を描いたフレーム: {drawn}/{len(records)}")
    print(f"出力動画: {output}")

    alignment = {
        "input": str(args.input),
        "reference": str(args.reference),
        "fps": my_info.fps,
        "reference_fps": ref_info.fps,
        "mirror_model": args.mirror_model,
        **({"view_offset": comp.view_offset} if comp.view_offset is not None else {}),
        "events": {"me": vars(my_events), "reference": vars(ref_events)},
        "frames": records,
    }
    alignment_path.write_text(json.dumps(alignment, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"対応づけ: {alignment_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
