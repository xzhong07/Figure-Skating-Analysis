"""動画の読み込みと書き出し。"""
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class VideoInfo:
    fps: float
    width: int
    height: int
    frame_count: int  # コンテナが報告する値。実際のフレーム数とずれることがある


class VideoReader:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"動画ファイルが見つかりません: {self.path}")
        self._cap = cv2.VideoCapture(str(self.path))
        if not self._cap.isOpened():
            raise OSError(f"動画を開けません: {self.path}")
        fps = self._cap.get(cv2.CAP_PROP_FPS)
        self.info = VideoInfo(
            fps=fps if fps and fps > 0 else 30.0,
            width=int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            frame_count=int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        )

    def frames(self) -> Iterator[tuple[int, int, np.ndarray]]:
        """(フレーム番号, タイムスタンプ[ms], BGR画像) を順に返す。"""
        index = 0
        while True:
            ok, frame = self._cap.read()
            if not ok:
                break
            # 可変フレームレートの動画でも fps から計算した時刻を使い、等間隔に扱う
            yield index, int(round(index * 1000 / self.info.fps)), frame
            index += 1

    def close(self) -> None:
        self._cap.release()

    def __enter__(self) -> "VideoReader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class VideoWriter:
    def __init__(self, path: str | Path, fps: float, width: int, height: int) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self._writer = cv2.VideoWriter(str(self.path), fourcc, fps, (width, height))
        if not self._writer.isOpened():
            raise OSError(f"出力動画を作成できません: {self.path}")

    def write(self, frame: np.ndarray) -> None:
        self._writer.write(frame)

    def close(self) -> None:
        self._writer.release()

    def __enter__(self) -> "VideoWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
