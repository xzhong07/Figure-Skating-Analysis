"""アプリで選べる種目の一覧。

今はシングルアクセル（1A）だけ解析できる。2S・CSp はタブだけ用意しておき、
お手本の動画と、種目ごとのキーフレーム・ルール表ができたら available を True にする。
"""
from dataclasses import dataclass
from pathlib import Path

from main import ROOT


@dataclass(frozen=True)
class Element:
    code: str  # タブに出す表記
    name: str
    reference: Path | None  # お手本の動画
    available: bool


ELEMENTS = [
    Element("1A", "シングルアクセル", ROOT / "input" / "axel_model.mp4", True),
    Element("2S", "ダブルサルコウ", None, False),
    Element("CSp", "キャメルスピン", None, False),
]
ELEMENTS_BY_CODE = {e.code: e for e in ELEMENTS}
