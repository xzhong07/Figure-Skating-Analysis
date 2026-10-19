"""自分の動画に、お手本の骨格を踏切のタイミングと体の大きさ・位置をそろえて重ねる。

使い方:
    python src/overlay.py input/my_axel.mp4 --reference input/axel_model.mp4
    python src/overlay.py input/my_axel.mp4 --reference input/axel_model.mp4 --my-takeoff 52 --my-landing 67
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

from alignment import Aligner, to_pixels
from camera_motion import estimate_camera_motion, stabilize_points
from jump_events import JumpEvents, detect_jump
from landmarks_io import load_landmarks, save_landmarks
from main import ROOT, extract_poses, model_path_for
from pose_estimator import PoseFrame
from skeleton_drawer import SkeletonStyle, draw_skeleton, draw_skeleton_points, draw_text_lines
from video_io import VideoInfo, VideoReader, VideoWriter

# お手本: 太め・はっきりした色（左=緑、右=黄）。自分: 細め・薄い色（左=水色、右=桃色）
MODEL_STYLE = SkeletonStyle(left=(60, 220, 60), right=(0, 220, 255), center=(255, 255, 255), thickness_scale=1.3)
SELF_STYLE = SkeletonStyle(left=(230, 190, 140), right=(170, 150, 255), center=(200, 200, 200), thickness_scale=0.5)


def load_or_extract(video: Path, model_name: str, min_confidence: float) -> tuple[VideoInfo, list[PoseFrame]]:
    """output/<名前>_landmarks.json が同じモデルで作られていれば読み込み、なければ推定して保存する。"""
    json_path = ROOT / "output" / f"{video.stem}_landmarks.json"
    model_path = model_path_for(model_name)
    with VideoReader(video) as reader:
        info = reader.info
        if json_path.exists():
            meta, poses = load_landmarks(json_path)
            if meta.get("model") == model_path.name:
                print(f"既存のランドマークを使用: {json_path}")
                return info, poses
        print(f"骨格を推定: {video}")
        poses = extract_poses(reader, model_path, min_confidence)
    save_landmarks(json_path, video, model_path.name, info, poses)
    print(f"ランドマーク: {json_path}")
    return info, poses


def describe(name: str, events: JumpEvents, fps: float) -> str:
    air = (events.landing - events.takeoff) / fps
    return f"{name}: 踏切={events.takeoff} 頂点={events.apex} 着氷={events.landing}（滞空 {air:.2f}秒）"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="自分の動画にお手本の骨格を重ねて出力します。")
    parser.add_argument("input", type=Path, help="自分の動画")
    parser.add_argument("--reference", type=Path, required=True, help="お手本の動画")
    parser.add_argument("-o", "--output", type=Path, help="出力動画（既定: output/<入力名>_overlay.mp4）")
    parser.add_argument("--model", choices=["lite", "full", "heavy"], default="heavy", help="使用するモデル")
    parser.add_argument("--min-visibility", type=float, default=0.5, help="この値未満の関節は描画しない")
    parser.add_argument("--min-confidence", type=float, default=0.5, help="検出・追跡の信頼度しきい値")
    parser.add_argument("--my-takeoff", type=int, help="自分の動画の踏切フレーム（自動検出を上書き）")
    parser.add_argument("--my-landing", type=int, help="自分の動画の着氷フレーム（自動検出を上書き）")
    parser.add_argument("--model-takeoff", type=int, help="お手本の踏切フレーム（自動検出を上書き）")
    parser.add_argument("--model-landing", type=int, help="お手本の着氷フレーム（自動検出を上書き）")
    parser.add_argument("--mirror-model", action="store_true", help="お手本を左右反転する（滑る向きが逆の動画どうしのとき）")
    parser.add_argument("--hide-self", action="store_true", help="自分の骨格を描かない")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output or ROOT / "output" / f"{args.input.stem}_overlay.mp4"
    alignment_path = output.with_name(f"{args.input.stem}_alignment.json")

    ref_info, ref_poses = load_or_extract(args.reference, args.model, args.min_confidence)
    my_info, my_poses = load_or_extract(args.input, args.model, args.min_confidence)

    ref_pts, _ = to_pixels(ref_poses, ref_info.width, ref_info.height)
    my_pts, _ = to_pixels(my_poses, my_info.width, my_info.height)

    print("カメラの動きを推定中...")
    ref_events = detect_jump(
        stabilize_points(ref_pts, estimate_camera_motion(args.reference, ref_poses)),
        ref_info.fps, args.model_takeoff, args.model_landing,
    )
    my_events = detect_jump(
        stabilize_points(my_pts, estimate_camera_motion(args.input, my_poses)),
        my_info.fps, args.my_takeoff, args.my_landing,
    )
    print(describe("お手本", ref_events, ref_info.fps))
    print(describe("自分  ", my_events, my_info.fps))

    ref_pts, ref_vis = to_pixels(ref_poses, ref_info.width, ref_info.height, mirror=args.mirror_model)
    aligner = Aligner(my_pts, my_info.fps, my_events, ref_pts, ref_vis, ref_info.fps, ref_events)

    records = []
    drawn = 0
    with VideoReader(args.input) as reader, VideoWriter(output, my_info.fps, my_info.width, my_info.height) as writer:
        for index, _, frame in reader.frames():
            pose = my_poses[index] if index < len(my_poses) else None
            if pose is not None and not args.hide_self:
                draw_skeleton(frame, pose, args.min_visibility, SELF_STYLE)

            result = aligner.transform(index) if index < len(my_poses) else None
            ref_frame = aligner.ref_frame[index] if index < len(my_poses) else np.nan
            record = {"frame": index, "phase": my_events.phase(index), "ref_frame": None}
            if result is not None:
                mapped, vis, info = result
                draw_skeleton_points(frame, mapped, vis >= args.min_visibility, MODEL_STYLE)
                record.update(ref_frame=round(float(ref_frame), 3), **info)
                drawn += 1
            records.append(record)

            ref_text = f"model {ref_frame:.1f}" if result is not None else "model -"
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
        "events": {"me": vars(my_events), "reference": vars(ref_events)},
        "frames": records,
    }
    alignment_path.write_text(json.dumps(alignment, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"対応づけ: {alignment_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
