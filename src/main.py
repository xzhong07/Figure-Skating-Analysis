"""動画から骨格を推定し、元動画に重ねた動画とランドマークJSONを出力する。

使い方:
    python src/main.py input/axel_model.mp4
    python src/main.py input/axel_model.mp4 -o output/axel_model_pose.mp4 --model full
"""
import argparse
import sys
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

from landmarks_io import save_landmarks
from pose_estimator import PoseEstimator, PoseFrame
from skeleton_drawer import draw_info, draw_skeleton
from video_io import VideoReader, VideoWriter

ROOT = Path(__file__).resolve().parent.parent


def model_path_for(name: str) -> Path:
    return ROOT / "models" / f"pose_landmarker_{name}.task"


def extract_poses(
    reader: VideoReader,
    model_path: Path,
    min_confidence: float = 0.5,
    on_frame: Callable[[np.ndarray, PoseFrame], None] | None = None,
) -> list[PoseFrame]:
    """動画の全フレームの骨格を推定する。on_frame があれば各フレームで呼ぶ。"""
    info = reader.info
    poses: list[PoseFrame] = []
    start = time.perf_counter()
    with PoseEstimator(
        model_path,
        min_detection_confidence=min_confidence,
        min_presence_confidence=min_confidence,
        min_tracking_confidence=min_confidence,
    ) as estimator:
        for index, timestamp_ms, frame in reader.frames():
            pose = estimator.process(frame, index, timestamp_ms)
            poses.append(pose)
            if on_frame:
                on_frame(frame, pose)
            if index % 10 == 0:
                print(f"\r処理中: {index + 1}/{info.frame_count}", end="", flush=True)
    elapsed = time.perf_counter() - start

    total = len(poses)
    missed = sum(not p.detected for p in poses)
    print(f"\r処理完了: {total}フレーム / {elapsed:.1f}秒 ({total / max(elapsed, 1e-9):.1f}fps)")
    print(f"未検出フレーム: {missed}/{total}")
    return poses


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="動画に骨格を重ねて出力します。")
    parser.add_argument("input", type=Path, help="入力動画ファイル")
    parser.add_argument("-o", "--output", type=Path, help="出力動画（既定: output/<入力名>_pose.mp4）")
    parser.add_argument("--model", choices=["lite", "full", "heavy"], default="heavy", help="使用するモデル")
    parser.add_argument("--min-visibility", type=float, default=0.5, help="この値未満の関節は描画しない")
    parser.add_argument("--min-confidence", type=float, default=0.5, help="検出・追跡の信頼度しきい値")
    parser.add_argument("--no-json", action="store_true", help="ランドマークJSONを出力しない")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output or ROOT / "output" / f"{args.input.stem}_pose.mp4"
    json_path = output.with_name(f"{args.input.stem}_landmarks.json")
    model_path = model_path_for(args.model)

    with VideoReader(args.input) as reader:
        info = reader.info
        print(f"入力: {args.input} ({info.width}x{info.height}, {info.fps:.2f}fps, 約{info.frame_count}フレーム)")
        print(f"モデル: {model_path.name}")

        with VideoWriter(output, info.fps, info.width, info.height) as writer:

            def draw_and_write(frame: np.ndarray, pose: PoseFrame) -> None:
                draw_skeleton(frame, pose, args.min_visibility)
                draw_info(frame, pose)
                writer.write(frame)

            poses = extract_poses(reader, model_path, args.min_confidence, draw_and_write)

    print(f"出力動画: {output}")
    if not args.no_json:
        save_landmarks(json_path, args.input, model_path.name, info, poses)
        print(f"ランドマーク: {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
