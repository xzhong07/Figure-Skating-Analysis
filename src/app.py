"""Figure Skating Lab: お手本と自分のジャンプを比べるアプリのサーバ。

使い方:
    python src/app.py            # http://localhost:8000 をブラウザで開く
    python src/app.py --port 8080

アップロードされた動画は output/app/<ジョブID>/ に保存し、一定フレームレートの H.264 mp4 に
変換してから解析する（ブラウザで再生するフレームと、解析したフレームを一致させるため）。
"""
import argparse
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

WEB_DIR = ROOT / "web"
JOBS_DIR = ROOT / "output" / "app"
MAX_SIDE = 1920  # 変換後の動画の長い辺の最大ピクセル数
MAX_UPLOAD_MB = 500

STAGES = {
    "queued": "順番を待っています",
    "convert": "動画を変換しています",
    "pose": "骨格を推定しています",
    "camera": "カメラの動きを補正しています",
    "advice": "アドバイスを作成しています",
    "export": "表示の準備をしています",
    "done": "完了しました",
    "error": "解析できませんでした",
}

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
jobs: dict[str, dict] = {}
analysis_lock = threading.Lock()  # MediaPipe が重いので、解析は1件ずつ


def source_fps(path: Path) -> float:
    """ffmpeg が報告する平均フレームレート。おかしな値（録画の webm で起こる）なら 30。"""
    reader = imageio_ffmpeg.read_frames(str(path))
    try:
        fps = float(next(reader).get("fps") or 0)
    finally:
        reader.close()
    return fps if 10 <= fps <= 120 else 30.0


def convert_video(src: Path, dst: Path) -> None:
    """一定フレームレート・H.264・音声なしの mp4 にする。スマホの回転情報もここで映像に反映される。"""
    fps = source_fps(src)
    scale = f"scale=w='min(iw\\,{MAX_SIDE}*iw/max(iw\\,ih))':h=-2"
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(src),
        "-an", "-vf", scale, "-r", f"{fps:.3f}", "-fps_mode", "cfr",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(dst),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise ValueError(f"動画を読み込めませんでした（{proc.stderr.strip()[-200:]}）")


def set_stage(job: dict, stage: str, done: int = 0, total: int = 0) -> None:
    job.update(stage=stage, message=STAGES[stage], done=done, total=total)


def run_job(job_id: str, upload: Path, element_code: str) -> None:
    job = jobs[job_id]
    job_dir = upload.parent
    element = ELEMENTS_BY_CODE[element_code]
    try:
        with analysis_lock:
            set_stage(job, "convert")
            video = job_dir / "video.mp4"
            convert_video(upload, video)

            set_stage(job, "pose")
            comp = build_comparison(
                video, element.reference,
                my_landmarks_path=job_dir / "landmarks.json",
                on_progress=lambda stage, done, total: set_stage(job, stage, done, total),
            )
            set_stage(job, "advice")
            result = analyze(comp)
            set_stage(job, "export")
            prefix = f"/files/{job_id}"
            export(comp, result, job_dir, prefix, f"{prefix}/video.mp4")
            set_stage(job, "done")
    except Exception as e:  # 解析の失敗は画面に理由を出す
        traceback.print_exc()
        set_stage(job, "error")
        job["error"] = str(e) or e.__class__.__name__


# ---------- 画面 ----------

@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/static/<path:path>")
def static_files(path: str):
    response = send_from_directory(WEB_DIR, path)
    # 画面のファイルを直したらすぐ反映されるよう、キャッシュさせない
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/files/<job_id>/<path:path>")
def job_files(job_id: str, path: str):
    if job_id not in jobs and not (JOBS_DIR / job_id / "result.json").exists():
        abort(404)
    # send_from_directory は Range 要求に対応するので、動画のシークができる
    return send_from_directory(JOBS_DIR / job_id, path)


# ---------- API ----------

@app.get("/api/elements")
def api_elements():
    return jsonify([{"code": e.code, "name": e.name, "available": e.available} for e in ELEMENTS])


@app.post("/api/analyze")
def api_analyze():
    file = request.files.get("video")
    element_code = request.form.get("element", "1A")
    element = ELEMENTS_BY_CODE.get(element_code)
    if file is None or not file.filename:
        return jsonify(error="動画ファイルがありません。"), 400
    if element is None or not element.available:
        return jsonify(error=f"{element_code} の解析はまだ準備中です。"), 400

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True)
    suffix = Path(file.filename).suffix.lower() or ".webm"
    upload = job_dir / f"upload{suffix}"
    file.save(upload)

    jobs[job_id] = {"id": job_id, "element": element_code, "name": file.filename}
    set_stage(jobs[job_id], "queued")
    threading.Thread(target=run_job, args=(job_id, upload, element_code), daemon=True).start()
    return jsonify(id=job_id)


@app.get("/api/jobs/<job_id>")
def api_job(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        abort(404)
    return jsonify(job)


@app.get("/api/jobs/<job_id>/result")
def api_result(job_id: str):
    path = JOBS_DIR / job_id / "result.json"
    if not path.exists():
        abort(404)
    return send_from_directory(path.parent, path.name, mimetype="application/json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Figure Skating Lab のサーバを起動します。")
    parser.add_argument("--port", type=int, default=8000, help="ポート番号")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(f"Figure Skating Lab: http://localhost:{args.port} をブラウザで開いてください（終了は Ctrl+C）")
    # カメラはブラウザの安全な接続（localhost）でしか使えないので、この PC からだけ受け付ける
    app.run(host="127.0.0.1", port=args.port, threaded=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
