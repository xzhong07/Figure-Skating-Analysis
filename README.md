# フィギュアスケート ジャンプ骨格解析

動画から MediaPipe PoseLandmarker で人体の骨格（33点）を推定し、元動画に重ねた動画を出力します。
最終的にはお手本と自分のジャンプの骨格を比較してアドバイスを生成することを目指しています。

## セットアップ（Windows / PowerShell）

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts\download_model.py          # models/pose_landmarker_heavy.task を取得
```

> `opencv-python` は入れないでください。mediapipe が依存する `opencv-contrib-python` と `cv2` が衝突します。

## 実行

お手本動画を `input/` に置いて実行します。

```powershell
.venv\Scripts\python.exe src\main.py input\axel_model.mp4
```

出力:
- `output/axel_model_pose.mp4` … 骨格を重ねた動画（左半身=青、右半身=赤）
- `output/axel_model_landmarks.json` … 各フレームのランドマーク
  - `landmarks`: 画像に対する正規化座標 `[x, y, z]` × 33
  - `world_landmarks`: 腰中心を原点としたメートル単位の3D座標 × 33
  - `visibility`: 各関節の見えている確からしさ（0〜1）

### オプション

| オプション | 既定値 | 説明 |
|---|---|---|
| `-o, --output` | `output/<入力名>_pose.mp4` | 出力動画のパス |
| `--model` | `heavy` | `lite` / `full` / `heavy`（他のモデルは `download_model.py --model lite full` で取得） |
| `--min-visibility` | `0.5` | この値未満の関節は描画しない |
| `--min-confidence` | `0.5` | 検出・追跡の信頼度しきい値。回転中に見失う場合は下げてみる |
| `--no-json` | | ランドマークJSONを出力しない |

## 構成

```
src/
  pose_estimator.py   PoseLandmarker のラッパー（フレーム → PoseFrame）
  skeleton_drawer.py  骨格とフレーム情報の描画
  video_io.py         動画の読み込み・書き出し
  main.py             CLI
scripts/
  download_model.py   モデルファイルの取得
```
