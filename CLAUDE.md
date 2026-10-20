# CLAUDE.md

フィギュアスケートのジャンプを骨格で解析し、お手本と比べてアドバイスを作るツール。
最終目標は「お手本と自分のジャンプの骨格を重ね、定量的なアドバイスを生成するアプリ」。
現在はシングルアクセル（`input/axel_model.mp4` がお手本、`input/my_axel.mp4` が自分）で開発している。

## 環境

- Windows 11、PowerShell。Python 3.15（`.venv`）。`.venv-1` は未使用の重複
- MediaPipe 1.1.1 は旧 `mp.solutions` がない。**Tasks API の `PoseLandmarker`（VIDEO モード）** を使う。モデルファイルは `models/pose_landmarker_heavy.task`（`scripts/download_model.py` で取得）
- OpenCV は **`opencv-contrib-python` だけ** を入れる（mediapipe の依存）。`opencv-python` を併せて入れると `cv2` が衝突する
- 日本語の文字は OpenCV で描けないので、Pillow と `C:\Windows\Fonts\BIZ-UDGothicR.ttc` / `B.ttc` で描く（`src/text_render.py`）
- 実行時に出る TensorFlow Lite の INFO / WARNING は無視してよい

## コマンド

```powershell
.venv\Scripts\python.exe src\main.py input\axel_model.mp4                                          # 骨格推定＋重ね描き
.venv\Scripts\python.exe src\overlay.py input\my_axel.mp4 --reference input\axel_model.mp4        # お手本の骨格を自分に重ねる
.venv\Scripts\python.exe src\advice_video.py input\my_axel.mp4 --reference input\axel_model.mp4   # アドバイスつきスロー動画
.venv\Scripts\python.exe src\app.py                                                                # アプリ（http://localhost:8000）
```

- 踏切・着氷の自動検出が外れたら `--my-takeoff N --my-landing N --model-takeoff N --model-landing N` で指定する
- 滑る向きが逆の動画どうしは `--mirror-model`
- `output/<名前>_landmarks.json` は、同じモデルで作られていれば再利用される（推定し直したいときは削除する）

## 処理の流れ（src/）

1. `main.py` `extract_poses()` → `pose_estimator.py`: 各フレームの33点（正規化座標・world 3D・visibility）。保存と読み込みは `landmarks_io.py`
2. `camera_motion.py`: 人物の周りを除いた背景の特徴点追跡で、カメラのパン・チルト・ズームを推定して打ち消す
3. `jump_events.py`: 打ち消した座標で、腰の上昇が最大のフレームを頂点とする。足の上下の速さ（胴体の長さ/秒、しきい値 1.0）から踏切（氷に着いている最後のフレーム）と着氷を決める
4. `alignment.py` `Aligner`: 踏切・着氷を基準に区分線形で時間を対応づける（踏切前と着氷後は等速、空中は滞空時間の比）。胴体の長さで拡大縮小し、胴体の中心を重ねる。回転はさせない（傾きの差を見せるため）
5. `view_align.py`: 撮影角度の差を、踏切の0.4秒前〜踏切の体の向き（world 座標の腰と肩の線の yaw）の差の円周平均で推定する。お手本の world 骨格を y 軸まわりに回し、正射影（x, y）して `Aligner` の `ref_pts` に渡す。回転量は動画全体で一定なので、空中の回転不足などの差は残る。`--no-view-align` で以前の2Dの重ね方に戻せる
6. `overlay.py` `build_comparison()` → `Comparison(me, ref, aligner, view_offset)`: 上の 1〜5 をまとめる共通の入口。`draw_overlay()` は1フレームの重ね描き
7. `metrics.py` `Geometry`: 長さは胴体比、2D はカメラ補正済み座標、回転量だけ 3D で測る。visibility が 0.5 未満の項目は None（判定しない）
8. `keyframes.py`: K1 踏切準備 〜 K7 着氷後の姿勢。お手本と自分で、それぞれの踏切・着氷を基準に同じ定義で選ぶ
9. `advice_rules.py` `RULES`: 差 = 自分 − お手本。|差| ≥ しきい値なら low/high の文を出す。文が空ならその向きは問題にしない。1場面あたり最大3件＋良い点1件。**しきい値と文章の調整はこの表だけで行う**
10. `advice_video.py`: 0.25倍速で再生し、キーフレームで一時停止（毎秒9文字で読める長さ、3〜15秒）。測定線はアドバイスの番号と同じ色。8〜9 と再生範囲の計算は `analysis.py` `analyze()` にまとめてある

## アプリ（Figure Skating Lab）

- `app.py`（Flask）: アップロード → `output/app/<ジョブID>/` に保存 → imageio-ffmpeg で一定フレームレートの H.264 mp4 に変換 → `build_comparison`（自分のランドマークはジョブのフォルダに保存）→ `analyze` → `app_export.export`。解析は別スレッドで1件ずつ
- `app_export.py`: `result.json`（各フレームの骨格・写したお手本の骨格・切り抜き枠・お手本の画像番号、キーフレームとアドバイス、まとめ、骨の組と色）、お手本の切り抜き画像、測定線の透明 PNG。描画は `advice_video.py` の `Renderer` / `Cropper` / `annotate_advice` を再利用している
- `web/`（素の HTML/JS/CSS、ビルド不要）: `<video>` を canvas に切り抜いて描き、骨格は JS で描く。フレーム番号 = `floor(mediaTime × fps + 0.05)`。一時停止中にキーフレームのフレームにいるときだけ、その場面のアドバイスと測定線を出す
- 種目は `elements.py`。2S・CSp は `available=False`（タブだけ）
- 変換した動画で推定し直すので、元の動画での結果と1〜3フレームずれることがある（例: my_axel の頂点 84 → 81。お手本どうしでも撮影角度の差 約9°、直す点1件が出る）
- 画面の確認: ヘッドレス Edge を DevTools プロトコルで操作してスクリーンショットを撮った（Claude in Chrome が使えないとき）

## これまでに分かったこと

- 撮影者がカメラを振る・ズームするので、**画面内の座標をそのまま使って判定しない**。必ず `Subject.stable`（カメラ補正済み）を使う
- 氷の高さもスケーターの移動やズームで変わるため、踏切・着氷は高さではなく足の速度で判定している
- 見えている手首が左右で入れ替わると平均値が飛ぶ。速度などは手首ごとに求める
- 着氷後は後ろ向きに滑るので、上体の傾きは `landing_lean`（着氷足の上への前傾を正）を使う
- 2D の角度は撮影角度の影響を受ける（お手本と自分で角度が違うとずれる）。真横から見ているときは肩の傾きを判定しない
- 現在の検出結果: お手本 踏切49・頂点59・着氷63（30fps）、自分 踏切76・頂点84・着氷94（51.8fps）
- world 座標は x=右、y=下、z=奥行き（カメラ基準）。(x, y) を正射影すると、画面上の2D骨格とのずれは胴体の約0.07倍で、重ね合わせに使える精度
- 撮影角度の差は約61°（ばらつき13°）。3Dで回す重ね方にすると、踏切±0.15秒のずれが胴体の0.30倍から0.18倍に減った。着氷付近でずれが増えるのは回転不足（体の向きの差 約150°）が正しく表れているため
- アドバイスの測定（metrics.py）は、まだお手本自身の撮影角度の2D座標で測っている（回した骨格では測っていない）

## 検証のしかた

- **お手本どうしの比較**（入力と `--reference` の両方を `axel_model.mp4` にする）で、直す点が0件になり、撮影角度の差が0°になること
- リファクタ後は `overlay.py --no-view-align` を実行し、`output/my_axel_alignment.json` が2D方式の基準と同じであること
- 出力動画から一時停止の画面を切り出して目視で確認する（測定線の位置、文章の量、映像との矛盾）
- テストコードはまだない。検証用の一時スクリプトや画像はプロジェクトの外に置く

## 決まりごと

- コメント・docstring・CLI のメッセージ・コミットメッセージは日本語
- `input/` と `output/` の中身（動画・解析結果）と `models/*.task` はコミットしない（`.gitignore` で除外済み。お手本動画は第三者の著作物）
- リポジトリ: https://github.com/xzhong07/Figure-Skating-Analysis （public、`main` ブランチ）
- アドバイス文は今はルール＋テンプレート方式。Claude API での文章化は、後からオプションとして追加する予定（API は月額プランとは別料金）

## 今後の候補

- 複数の練習動画でしきい値を調整する
- 腕を開いたとみなす基準（`metrics.ARM_OPEN_DISTANCE` = 胴体の0.8倍）の見直し
- Claude API による文章化のオプション
- お手本の2D測定を、撮影角度に合わせて回した骨格で行う（重ね合わせと同じ補正を測定にも使う）
- 撮影角度の差に強い 3D ベースの測定を増やす
- カメラの上下の角度（見下ろし・見上げ）の差の補正
