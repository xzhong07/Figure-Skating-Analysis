"""Figure Skating Lab: お手本と自分のジャンプを比べるアプリのサーバ。

使い方（画面は web/ の React アプリ。先に一度 web/ で npm install と npm run build を実行しておく）:
    python src/app.py            # http://localhost:8000 をブラウザで開く
    python src/app.py --lan      # 同じネットワークのスマホからも開けるようにする
    python src/app.py --port 8080

流れ:
    1. POST /api/upload            動画を output/app/<ジョブID>/ に保存し、動画全体を一定フレームレートの
                                   H.264 mp4（video.mp4）に変換する（ブラウザで再生するフレームと、解析するフレームを一致させるため）
    2. 画面で前後をトリミングする範囲を選ぶ
    3. POST /api/jobs/<id>/analyze 範囲を切り出して（runs/<開始>-<終了>/clip.mp4）解析する。範囲を選び直しても送信し直さなくてよい
"""
import argparse
import json
import shutil
import socket
import subprocess
import sys
import threading
import traceback
import uuid
from pathlib import Path

import imageio_ffmpeg
from flask import Flask, abort, jsonify, request, send_from_directory

from analysis import analyze
from app_export import export
from elements import ELEMENTS, ELEMENTS_BY_CODE
from main import ROOT
from overlay import build_comparison
from video_io import VideoReader

WEB_DIR = ROOT / "web" / "dist"  # web/ で npm run build した画面
JOBS_DIR = ROOT / "output" / "app"
MAX_SIDE = 1920  # 変換後の動画の長い辺の最大ピクセル数
MAX_UPLOAD_MB = 1000
MIN_CLIP_S = 1.5  # トリミングした範囲の最短の長さ（秒）

STAGES = {
    "convert": "動画を変換しています",
    "ready": "解析する範囲を選んでください",
    "queued": "順番を待っています",
    "clip": "範囲を切り出しています",
    "pose": "骨格を推定しています",
    "camera": "カメラの動きを補正しています",
    "advice": "アドバイスを作成しています",
    "export": "表示の準備をしています",
    "done": "完了しました",
    "error": "解析できませんでした",
}

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
app.config["LAN_URLS"] = []
jobs: dict[str, dict] = {}
analysis_lock = threading.Lock()  # MediaPipe が重いので、解析は1件ずつ


# ---------- 動画の変換 ----------

def source_info(path: Path) -> tuple[float, float]:
    """ffmpeg が報告する (平均フレームレート, 長さ[秒])。fps がおかしな値（録画の webm で起こる）なら 30。"""
    reader = imageio_ffmpeg.read_frames(str(path))
    try:
        meta = next(reader)
    finally:
        reader.close()
    fps = float(meta.get("fps") or 0)
    return (fps if 10 <= fps <= 120 else 30.0), float(meta.get("duration") or 0)


def run_ffmpeg(args: list[str], total_frames: int = 0, on_progress=None) -> None:
    """ffmpeg を実行し、-progress の frame= の行から進み具合を知らせる。"""
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-nostats", "-progress", "pipe:1", *args]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace")
    for line in proc.stdout:
        if on_progress and line.startswith("frame=") and total_frames:
            on_progress(min(int(line[6:].strip() or 0), total_frames), total_frames)
    stderr = proc.stderr.read()
    if proc.wait() != 0:
        raise ValueError(f"動画を読み込めませんでした（{stderr.strip()[-200:]}）")


H264_ARGS = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]


def convert_video(src: Path, dst: Path, on_progress=None) -> None:
    """一定フレームレート・H.264・音声なしの mp4 にする。スマホの回転情報もここで映像に反映される。"""
    fps, duration = source_info(src)
    scale = f"scale=w='min(iw\\,{MAX_SIDE}*iw/max(iw\\,ih))':h=-2"
    run_ffmpeg(["-i", str(src), "-an", "-vf", scale, "-r", f"{fps:.3f}", "-fps_mode", "cfr", *H264_ARGS, str(dst)],
               round(duration * fps), on_progress)


def clip_video(src: Path, dst: Path, start: int, end: int, fps: float, on_progress=None) -> None:
    """一定フレームレートの src から、フレーム start〜end（両端を含む）を切り出す。"""
    trim = f"trim=start_frame={start}:end_frame={end + 1},setpts=PTS-STARTPTS"
    run_ffmpeg(["-i", str(src), "-an", "-vf", trim, "-r", f"{fps:.3f}", "-fps_mode", "cfr", *H264_ARGS, str(dst)],
               end - start + 1, on_progress)


# ---------- ジョブ ----------

def save_job(job: dict) -> None:
    """サーバを起動し直しても、範囲を選び直したり結果を開いたりできるよう保存しておく。"""
    (JOBS_DIR / job["id"] / "job.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")


def get_job(job_id: str) -> dict | None:
    if job_id in jobs:
        return jobs[job_id]
    path = JOBS_DIR / job_id / "job.json"
    if not job_id.isalnum() or not path.exists():
        return None
    jobs[job_id] = json.loads(path.read_text(encoding="utf-8"))
    return jobs[job_id]


def set_stage(job: dict, stage: str, done: int = 0, total: int = 0) -> None:
    job.update(stage=stage, message=STAGES[stage], done=done, total=total)
    if stage in ("ready", "done", "error"):
        save_job(job)


def fail(job: dict, e: Exception) -> None:
    traceback.print_exc()
    job["error"] = str(e) or e.__class__.__name__
    set_stage(job, "error")


def run_convert(job: dict, upload: Path) -> None:
    job_dir = upload.parent
    try:
        set_stage(job, "convert")
        video = job_dir / "video.mp4"
        convert_video(upload, video, lambda done, total: set_stage(job, "convert", done, total))
        with VideoReader(video) as reader:
            info = reader.info
        job["video"] = {"url": f"/files/{job['id']}/video.mp4", "fps": info.fps, "frames": info.frame_count,
                        "width": info.width, "height": info.height}
        job.pop("error", None)
        set_stage(job, "ready")
    except Exception as e:  # 失敗の理由は画面に出す
        fail(job, e)


def run_analysis(job: dict, element_code: str, start: int, end: int) -> None:
    job_dir = JOBS_DIR / job["id"]
    element = ELEMENTS_BY_CODE[element_code]
    name = f"{start}-{end}"
    run_dir = job_dir / "runs" / name
    try:
        with analysis_lock:
            # 前の範囲の結果は消す（同じ範囲を選び直したときは、骨格の推定結果を使い回す）
            for old in (job_dir / "runs").glob("*"):
                if old.name != name:
                    shutil.rmtree(old, ignore_errors=True)
            run_dir.mkdir(parents=True, exist_ok=True)
            prefix = f"/files/{job['id']}/runs/{name}"
            video_info = job["video"]
            if start == 0 and end == video_info["frames"] - 1:
                clip, clip_url = job_dir / "video.mp4", f"/files/{job['id']}/video.mp4"  # トリミングしていない
            else:
                clip, clip_url = run_dir / "clip.mp4", f"{prefix}/clip.mp4"
                if not clip.exists():
                    set_stage(job, "clip")
                    clip_video(job_dir / "video.mp4", clip, start, end, video_info["fps"],
                               lambda done, total: set_stage(job, "clip", done, total))

            set_stage(job, "pose")
            comp = build_comparison(
                clip, element.reference,
                my_landmarks_path=run_dir / "landmarks.json",
                on_progress=lambda stage, done, total: set_stage(job, stage, done, total),
            )
            set_stage(job, "advice")
            result = analyze(comp)
            set_stage(job, "export")
            export(comp, result, run_dir, prefix, clip_url)
            job["run"] = name
            job.pop("error", None)
            set_stage(job, "done")
    except Exception as e:  # 失敗の理由は画面に出す
        fail(job, e)


# ---------- 画面 ----------

@app.get("/")
def index():
    response = send_from_directory(WEB_DIR, "index.html")
    # 画面を作り直したらすぐ反映されるよう、index.html はキャッシュさせない（ほかのファイルは名前が変わる）
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/<path:path>")
def web_files(path: str):
    return send_from_directory(WEB_DIR, path)


@app.get("/files/<job_id>/<path:path>")
def job_files(job_id: str, path: str):
    if get_job(job_id) is None and not (JOBS_DIR / job_id / "result.json").exists():
        abort(404)
    # send_from_directory は Range 要求に対応するので、動画のシークができる
    return send_from_directory(JOBS_DIR / job_id, path)


# ---------- API ----------

@app.get("/api/elements")
def api_elements():
    return jsonify([{"code": e.code, "name": e.name, "available": e.available} for e in ELEMENTS])


@app.get("/api/server")
def api_server():
    """スマホで開くための URL（--lan で起動したときだけ）。"""
    return jsonify(lan=bool(app.config["LAN_URLS"]), urls=app.config["LAN_URLS"])


@app.post("/api/upload")
def api_upload():
    file = request.files.get("video")
    if file is None or not file.filename:
        return jsonify(error="動画ファイルがありません。"), 400
    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True)
    suffix = Path(file.filename).suffix.lower() or ".mp4"
    upload = job_dir / f"upload{suffix}"
    file.save(upload)

    job = {"id": job_id, "name": file.filename}
    jobs[job_id] = job
    set_stage(job, "convert")
    threading.Thread(target=run_convert, args=(job, upload), daemon=True).start()
    return jsonify(id=job_id)


@app.post("/api/jobs/<job_id>/analyze")
def api_analyze(job_id: str):
    job = get_job(job_id)
    if job is None or "video" not in job:
        return jsonify(error="動画が見つかりません。もう一度取り込んでください。"), 404
    if job["stage"] not in ("ready", "done", "error"):
        return jsonify(error="この動画は今、処理中です。"), 409
    body = request.get_json(silent=True) or {}
    element_code = body.get("element", "1A")
    element = ELEMENTS_BY_CODE.get(element_code)
    if element is None or not element.available:
        return jsonify(error=f"{element_code} の解析はまだ準備中です。"), 400
    video = job["video"]
    try:
        start = max(0, int(body.get("start", 0)))
        end = min(video["frames"] - 1, int(body.get("end", video["frames"] - 1)))
    except (TypeError, ValueError):
        return jsonify(error="範囲の指定が正しくありません。"), 400
    if (end - start + 1) / video["fps"] < MIN_CLIP_S:
        return jsonify(error=f"範囲が短すぎます。{MIN_CLIP_S}秒以上を選んでください。"), 400

    job.update(element=element_code, trim={"start": start, "end": end})
    set_stage(job, "queued")
    threading.Thread(target=run_analysis, args=(job, element_code, start, end), daemon=True).start()
    return jsonify(id=job_id)


@app.get("/api/jobs/<job_id>")
def api_job(job_id: str):
    job = get_job(job_id)
    if job is None:
        abort(404)
    return jsonify(job)


@app.get("/api/jobs/<job_id>/result")
def api_result(job_id: str):
    job = get_job(job_id)
    run = (job or {}).get("run")
    # 範囲を選ぶ前の版で作った結果は、ジョブのフォルダに直接ある
    path = JOBS_DIR / job_id / "runs" / run / "result.json" if run else JOBS_DIR / job_id / "result.json"
    if not path.exists():
        abort(404)
    response = send_from_directory(path.parent, path.name, mimetype="application/json")
    response.headers["Cache-Control"] = "no-cache"
    return response


# ---------- 起動 ----------

def lan_addresses() -> list[str]:
    """この PC の IPv4 アドレス（モバイルホットスポットの 192.168.137.1 なども含む）。"""
    addresses = {info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    try:
        # 外への経路に使うアドレス（実際には送信しない）
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            addresses.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(a for a in addresses if not a.startswith("127."))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Figure Skating Lab のサーバを起動します。")
    parser.add_argument("--port", type=int, default=8000, help="ポート番号")
    parser.add_argument("--lan", action="store_true",
                        help="同じネットワーク（Wi-Fi・ホットスポット・テザリング）のスマホからも開けるようにする")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not (WEB_DIR / "index.html").exists():
        print("画面がまだ作られていません。web フォルダで npm install と npm run build を実行してください。")
        return 1
    print(f"Figure Skating Lab: http://localhost:{args.port} をブラウザで開いてください（終了は Ctrl+C）")
    if args.lan:
        urls = [f"http://{a}:{args.port}" for a in lan_addresses()]
        app.config["LAN_URLS"] = urls
        print("スマホからは、同じネットワークにつないで次のどれかを開いてください（PC の画面の「スマホで開く」に QR コードも出ます）:")
        for url in urls:
            print(f"  {url}")
        print("※ 同じネットワークにいる人は誰でも開けます。Windows のファイアウォールの確認が出たら「プライベート ネットワーク」を許可してください。")
    app.run(host="0.0.0.0" if args.lan else "127.0.0.1", port=args.port, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
