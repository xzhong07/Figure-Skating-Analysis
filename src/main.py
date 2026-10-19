"""動画から骨格を推定し、元動画に重ねた動画とランドマークJSONを出力する。

使い方:
    python src/main.py input/axel_model.mp4
    python src/main.py input/axel_model.mp4 -o output/axel_model_pose.mp4 --model full
"""
import argparse
import json
import sys
import time
from pathlib import Path

from pose_estimator import NUM_LANDMARKS, PoseEstimator, PoseFrame
from skeleton_drawer import draw_info, draw_skeleton
from video_io import VideoReader, VideoWriter

ROOT = Path(__file__).resolve().parent.parent


def pose_to_dict(pose: PoseFrame) -> dict:
    d = {"frame": pose.frame_index, "timestamp_ms": pose.timestamp_ms, "detected": pose.detected}
    if pose.detected:
        d["landmarks"] = pose.landmarks.round(5).tolist()
        d["world_landmarks"] = pose.world_landmarks.round(5).tolist()
        d["visibility"] = pose.visibility.round(4).tolist()
    return d


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
    model_path = ROOT / "models" / f"pose_landmarker_{args.model}.task"

    with VideoReader(args.input) as reader:
        info = reader.info
        print(f"入力: {args.input} ({info.width}x{info.height}, {info.fps:.2f}fps, 約{info.frame_count}フレーム)")
        print(f"モデル: {model_path.name}")

        poses: list[PoseFrame] = []
        start = time.perf_counter()
        with (
            PoseEstimator(
                model_path,
                min_detection_confidence=args.min_confidence,
                min_presence_confidence=args.min_confidence,
                min_tracking_confidence=args.min_confidence,
            ) as estimator,
            VideoWriter(output, info.fps, info.width, info.height) as writer,
        ):
            for index, timestamp_ms, frame in reader.frames():
                pose = estimator.process(frame, index, timestamp_ms)
                poses.append(pose)
                draw_skeleton(frame, pose, args.min_visibility)
                draw_info(frame, pose)
                writer.write(frame)
                if index % 10 == 0:
                    print(f"\r処理中: {index + 1}/{info.frame_count}", end="", flush=True)
        elapsed = time.perf_counter() - start

    total = len(poses)
    missed = sum(not p.detected for p in poses)
    print(f"\r処理完了: {total}フレーム / {elapsed:.1f}秒 ({total / max(elapsed, 1e-9):.1f}fps)")
    print(f"未検出フレーム: {missed}/{total}")
    print(f"出力動画: {output}")

    if not args.no_json:
        data = {
            "source": str(args.input),
            "model": model_path.name,
            "fps": info.fps,
            "width": info.width,
            "height": info.height,
            "num_landmarks": NUM_LANDMARKS,
            "frames": [pose_to_dict(p) for p in poses],
        }
        json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        print(f"ランドマーク: {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
