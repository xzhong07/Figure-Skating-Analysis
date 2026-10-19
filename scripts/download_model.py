"""MediaPipe PoseLandmarker のモデルファイルを models/ にダウンロードする。

使い方:
    python scripts/download_model.py            # heavy（既定）
    python scripts/download_model.py --model lite full heavy
"""
import argparse
import urllib.request
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
URL_TEMPLATE = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_{name}/float16/latest/pose_landmarker_{name}.task"
)


def download(name: str, force: bool = False) -> Path:
    dest = MODELS_DIR / f"pose_landmarker_{name}.task"
    if dest.exists() and not force:
        print(f"既に存在します: {dest}")
        return dest
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    url = URL_TEMPLATE.format(name=name)
    print(f"ダウンロード中: {url}")
    tmp = dest.with_suffix(".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dest)
    print(f"保存しました: {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", nargs="+", default=["heavy"], choices=["lite", "full", "heavy"])
    parser.add_argument("--force", action="store_true", help="既存ファイルを上書きする")
    args = parser.parse_args()
    for name in args.model:
        download(name, args.force)


if __name__ == "__main__":
    main()
