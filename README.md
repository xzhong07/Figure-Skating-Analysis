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

## 自分の動画にお手本の骨格を重ねる

```powershell
.venv\Scripts\python.exe src\overlay.py input\my_axel.mp4 --reference input\axel_model.mp4
```

1. 両方の動画の骨格を推定する（`output/<名前>_landmarks.json` が同じモデルで作られていれば再利用）
2. 背景の動きからカメラのパン・チルト・ズームを推定して打ち消し、腰と足の上下動から踏切・頂点・着氷を自動で検出する
3. 時間を合わせる: 踏切と着氷をそろえ、空中は滞空時間の比で伸縮、踏切前と着氷後は等速で対応づける
4. 位置と大きさを合わせる: 胴体の長さで拡大縮小し、胴体の中心を重ねる（傾きの差を見せるため回転はしない）

出力:
- `output/my_axel_overlay.mp4` … お手本の骨格（太線、左半身=緑・右半身=黄）と自分の骨格（細線）を重ねた動画
- `output/my_axel_alignment.json` … 各フレームの対応先のお手本のフレーム、拡大率、検出した踏切・着氷

| オプション | 説明 |
|---|---|
| `--my-takeoff N` / `--my-landing N` | 自分の動画の踏切・着氷フレームを手動で指定する（自動検出が外れたとき） |
| `--model-takeoff N` / `--model-landing N` | お手本の踏切・着氷フレームを手動で指定する |
| `--mirror-model` | お手本を左右反転する（滑る向きが逆の動画どうしのとき） |
| `--hide-self` | 自分の骨格を描かない |
| `--model` / `--min-visibility` / `--min-confidence` | `main.py` と同じ |

## お手本との差からアドバイス動画を作る

```powershell
.venv\Scripts\python.exe src\advice_video.py input\my_axel.mp4 --reference input\axel_model.mp4
```

踏切の0.8秒前から着氷の0.8秒後までを0.25倍速で再生し、7つのキーフレームで一時停止して、お手本との差から作ったアドバイスを表示します。

| キーフレーム | 主に見る点 |
|---|---|
| ① 踏切準備 | 踏み込みのひざの深さ、上体の傾き |
| ② 踏切 | 振り上げ足の角度、腕の高さと振りの速さ、上体の傾き、踏切足の位置、肩の傾き |
| ③ 回転し始め | 足と腕の締め、肩の傾き、頭の位置、軸の傾き |
| ④ 空中（頂点） | 高さ（滞空時間から推定）、回転量・回転速度、足と腕の締め、軸の傾き |
| ⑤ 回転の終わり | 腕を開くタイミング、空中の軸の傾き、足の締め |
| ⑥ 着氷 | ひざのクッション、上体の傾き、軸の傾き |
| ⑦ 着氷後の姿勢 | フリーレッグ、腕の広がり、上体の傾き、肩の傾き |

- 一時停止中は、アドバイスの番号と同じ色の線で測った場所を示します（自分の映像とお手本の静止画の両方）
- アドバイスはルール表 `src/advice_rules.py` から作ります。しきい値と文章はこの表だけを直せば調整できます
- 一時停止の長さは文章の長さから決めます（毎秒9文字で読める長さ、3〜15秒）
- 出力: `output/my_axel_advice.mp4`、測定値とアドバイスの `output/my_axel_advice.json`、文章版の `output/my_axel_advice.md`
- `--slow 0.2` などで再生速度を変えられます。そのほかのオプションは `overlay.py` と同じです
- 数値は骨格推定によるおおよその値です。撮影の角度が違うと、画面上で測る角度にはずれが出ます

## 構成

```
src/
  pose_estimator.py   PoseLandmarker のラッパー（フレーム → PoseFrame）
  skeleton_drawer.py  骨格とフレーム情報の描画
  video_io.py         動画の読み込み・書き出し
  landmarks_io.py     ランドマークJSONの保存と読み込み
  camera_motion.py    背景の動きからカメラの動きを推定
  jump_events.py      踏切・頂点・着氷の検出
  alignment.py        お手本と自分の時間・位置の対応づけ
  metrics.py          姿勢・タイミングの測定値
  keyframes.py        比べるキーフレームの選択
  advice_rules.py     アドバイスのルール表と文章の生成
  text_render.py      日本語の文字の描画（Pillow）
  advice_video.py     CLI: アドバイスつきスロー動画を作る
  main.py             CLI: 骨格を推定して重ねる
  overlay.py          CLI: 自分の動画にお手本の骨格を重ねる
scripts/
  download_model.py   モデルファイルの取得
```
