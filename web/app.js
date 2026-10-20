// Figure Skating Lab: 自分の動画にお手本の骨格を重ねて再生し、キーフレームでアドバイスを出す。
// 解析結果（result.json）の形は src/app_export.py を参照。
"use strict";

const CIRCLED = "①②③④⑤⑥⑦";
const ZONE_COLORS = { approach: "var(--approach)", air: "var(--air)", landing: "var(--landing)" };

const $ = (id) => document.getElementById(id);
const els = {
  tabs: $("element-tabs"), fileInput: $("file-input"), btnCamera: $("btn-camera"), btnSummary: $("btn-summary"),
  stage: $("stage"), canvas: $("view"), video: $("video"), badge: $("badge"), dropzone: $("dropzone"),
  progress: $("progress"), progressTitle: $("progress-title"), progressFill: $("progress-fill"),
  progressDetail: $("progress-detail"), progressClose: $("progress-close"),
  controls: $("controls"), btnPlay: $("btn-play"), btnStop: $("btn-stop"), speed: $("speed"),
  time: $("time"), phase: $("phase"),
  timeline: $("timeline"), track: $("track"), zones: $("zones"), played: $("played"), playhead: $("playhead"),
  kfMarkers: $("kf-markers"), zoneLabels: $("zone-labels"), tooltip: $("tooltip"),
  showRef: $("show-ref"), showSelf: $("show-self"), showMarks: $("show-marks"), stopAtKf: $("stop-at-kf"),
  zoom: $("zoom"), fullRange: $("full-range"),
  panelMain: $("panel-main"), panelSummary: $("panel-summary"), panelTitle: $("panel-title"),
  panelSub: $("panel-sub"), thumbImg: $("thumb-img"), thumbEmpty: $("thumb-empty"), panelBody: $("panel-body"),
};
const ctx = els.canvas.getContext("2d");

const state = {
  element: "1A",
  data: null,
  frame: 0,
  lastFrame: -1, // 再生中に通り過ぎたキーフレームを見つけるための、前に描いたフレーム
  showSummary: false,
  images: {}, // キーフレームの測定線の画像
};

// ---------- 種目タブ ----------

async function loadElements() {
  let elements;
  try {
    elements = await (await fetch("/api/elements")).json();
  } catch {
    elements = [{ code: "1A", name: "シングルアクセル", available: true }];
  }
  els.tabs.innerHTML = "";
  for (const e of elements) {
    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = "tab";
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", String(e.code === state.element));
    tab.disabled = !e.available;
    tab.title = e.available ? e.name : `${e.name}（準備中）`;
    tab.innerHTML = `${e.code}${e.available ? "" : "<small>準備中</small>"}`;
    tab.addEventListener("click", () => {
      state.element = e.code;
      for (const t of els.tabs.children) t.setAttribute("aria-selected", String(t === tab));
    });
    els.tabs.appendChild(tab);
  }
}

// ---------- 動画の取り込みと解析 ----------

async function analyze(file) {
  stopPlayback();
  showProgress("動画を送っています", "", 0);
  const form = new FormData();
  form.append("video", file, file.name);
  form.append("element", state.element);
  let id;
  try {
    const res = await fetch("/api/analyze", { method: "POST", body: form });
    const body = await res.json();
    if (!res.ok) throw new Error(body.error || "送信できませんでした。");
    id = body.id;
  } catch (e) {
    showError(e.message);
    return;
  }
  pollJob(id);
}

async function pollJob(id) {
  let job;
  try {
    job = await (await fetch(`/api/jobs/${id}`)).json();
  } catch {
    showError("サーバに接続できません。src/app.py が動いているか確認してください。");
    return;
  }
  if (job.stage === "error") {
    showError(job.error);
    return;
  }
  if (job.stage === "done") {
    await openResult(id);
    return;
  }
  const ratio = job.total ? job.done / job.total : 0;
  showProgress(job.message, job.total ? `${job.done} / ${job.total} フレーム` : "", ratio);
  setTimeout(() => pollJob(id), 400);
}

function showProgress(title, detail, ratio) {
  els.progress.hidden = false;
  els.progress.classList.remove("error");
  els.progressClose.hidden = true;
  els.progressTitle.textContent = title;
  els.progressDetail.textContent = detail;
  els.progressFill.style.width = `${Math.round(ratio * 100)}%`;
}

function showError(message) {
  els.progress.hidden = false;
  els.progress.classList.add("error");
  els.progressTitle.textContent = "解析できませんでした";
  els.progressDetail.textContent = `${message} 踏切の少し前から着氷の後まで、全身が写っている動画でもう一度試してください。`;
  els.progressClose.hidden = false;
}

async function openResult(id) {
  let data;
  try {
    const res = await fetch(`/api/jobs/${id}/result`);
    if (!res.ok) throw new Error();
    data = await res.json();
  } catch {
    showError("解析結果を読み込めませんでした。");
    return;
  }
  history.replaceState(null, "", `#job=${id}`);
  state.data = data;
  state.images = {};
  for (const kf of data.keyframes) {
    const img = new Image();
    img.src = kf.marks_image;
    img.onload = render;
    state.images[kf.key] = img;
    new Image().src = kf.ref_image;
  }
  // お手本の画像は再生中に切り替えるので、先に読み込んでおく
  for (const f of data.frames) if (f.thumb !== null) new Image().src = `${data.thumb_url}/${f.thumb}.jpg`;

  els.video.src = data.video.url;
  await new Promise((resolve) => els.video.addEventListener("loadeddata", resolve, { once: true }));
  applySpeed();
  els.progress.hidden = true;
  els.dropzone.hidden = true;
  els.controls.setAttribute("aria-disabled", "false");
  els.btnSummary.hidden = false;
  state.showSummary = false;
  buildTimeline();
  seekFrame(range().start);
}

// ---------- 再生 ----------

const fps = () => state.data.video.fps;
const frameCount = () => state.data.video.frames;

function range() {
  const d = state.data;
  return els.fullRange.checked ? { start: 0, end: frameCount() - 1 } : d.range;
}

function frameOf(time) {
  return Math.min(frameCount() - 1, Math.max(0, Math.floor(time * fps() + 0.05)));
}

function seekFrame(frame) {
  const f = Math.min(frameCount() - 1, Math.max(0, Math.round(frame)));
  state.frame = f;
  state.lastFrame = f;
  // フレームの表示時刻ちょうどだと前のフレームになることがあるので、少し後ろを指す
  els.video.currentTime = (f + 0.3) / fps();
  render();
}

function isPlaying() {
  return !els.video.paused && !els.video.ended;
}

function play() {
  if (!state.data) return;
  const r = range();
  if (state.frame >= r.end || state.frame < r.start) seekFrame(r.start);
  state.showSummary = false;
  applySpeed();
  els.video.play();
}

function pause() {
  els.video.pause();
}

function stopPlayback() {
  if (!state.data) return;
  pause();
  state.showSummary = false;
  seekFrame(range().start);
}

function applySpeed() {
  const rate = Number(els.speed.value);
  els.video.defaultPlaybackRate = rate;
  els.video.playbackRate = rate;
}

// 再生中の各フレームで、キーフレームと再生範囲の終わりを調べる
function onFrame(frame) {
  if (!state.data) return;
  const prev = state.lastFrame;
  state.frame = frame;
  state.lastFrame = frame;
  if (isPlaying()) {
    if (els.stopAtKf.checked) {
      const kf = state.data.keyframes.find((k) => prev < k.frame && k.frame <= frame);
      if (kf) {
        pause();
        seekFrame(kf.frame);
        return;
      }
    }
    if (frame >= range().end) {
      pause();
      seekFrame(range().end);
      state.showSummary = true;
    }
  }
  render();
}

function startFrameLoop() {
  const video = els.video;
  if ("requestVideoFrameCallback" in HTMLVideoElement.prototype) {
    const step = (_now, meta) => {
      onFrame(frameOf(meta.mediaTime));
      video.requestVideoFrameCallback(step);
    };
    video.requestVideoFrameCallback(step);
  } else {
    const step = () => {
      if (isPlaying()) onFrame(frameOf(video.currentTime));
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
}

// 一時停止中で、ちょうどキーフレームの上にいるときはその場面
function activeKeyframe() {
  if (!state.data || isPlaying()) return null;
  return state.data.keyframes.find((k) => k.frame === state.frame) || null;
}

// ---------- 描画 ----------

function viewTransform() {
  const d = state.data;
  const cw = els.canvas.width, ch = els.canvas.height;
  if (els.zoom.checked) {
    const [x0, y0, w] = d.frames[state.frame].crop;
    const k = cw / w;
    return { k, dx: -x0 * k, dy: -y0 * k };
  }
  const k = Math.min(cw / d.video.width, ch / d.video.height);
  return { k, dx: (cw - d.video.width * k) / 2, dy: (ch - d.video.height * k) / 2 };
}

function drawSkeleton(pose, style, k) {
  if (!pose) return;
  const sk = state.data.skeleton;
  const p = pose.p, v = pose.v;
  const x = (i) => p[2 * i], y = (i) => p[2 * i + 1];
  ctx.lineCap = "round";
  ctx.lineWidth = style.thickness;
  const bones = (pairs, color) => {
    ctx.strokeStyle = color;
    ctx.beginPath();
    for (const [a, b] of pairs) {
      if (!v[a] || !v[b]) continue;
      ctx.moveTo(x(a), y(a));
      ctx.lineTo(x(b), y(b));
    }
    ctx.stroke();
  };
  const joints = (indices, color) => {
    const r = style.thickness + 2;
    for (const i of indices) {
      if (!v[i]) continue;
      ctx.beginPath();
      ctx.arc(x(i), y(i), r, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.lineWidth = 1 / k;
      ctx.strokeStyle = "#000";
      ctx.stroke();
    }
    ctx.lineWidth = style.thickness;
  };
  const [ls, rs] = [11, 12];
  bones(sk.center_bones, style.center);
  if (v[ls] && v[rs] && v[sk.nose]) {
    ctx.strokeStyle = style.center;
    ctx.beginPath();
    ctx.moveTo((x(ls) + x(rs)) / 2, (y(ls) + y(rs)) / 2);
    ctx.lineTo(x(sk.nose), y(sk.nose));
    ctx.stroke();
  }
  bones(sk.left_bones, style.left);
  bones(sk.right_bones, style.right);
  joints(sk.left_points, style.left);
  joints(sk.right_points, style.right);
  joints([sk.nose], style.center);
}

function drawView(kf) {
  const d = state.data;
  const frame = d.frames[state.frame];
  const { k, dx, dy } = viewTransform();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, els.canvas.width, els.canvas.height);
  ctx.setTransform(k, 0, 0, k, dx, dy);
  ctx.drawImage(els.video, 0, 0, d.video.width, d.video.height);
  if (els.showSelf.checked) drawSkeleton(frame.me, d.skeleton.self, k);
  if (els.showRef.checked) drawSkeleton(kf ? kf.ref_pose : frame.ref, d.skeleton.model, k);
  if (kf && els.showMarks.checked) {
    const img = state.images[kf.key];
    if (img && img.complete && img.naturalWidth) ctx.drawImage(img, 0, 0, d.video.width, d.video.height);
  }
  ctx.setTransform(1, 0, 0, 1, 0, 0);
}

function render() {
  const d = state.data;
  if (!d) return;
  const kf = activeKeyframe();
  drawView(kf);
  renderControls(kf);
  renderPanel(kf);
}

function seconds(frame) {
  return (frame / fps()).toFixed(2);
}

function phaseOf(frame) {
  const ev = state.data.events;
  const key = frame < ev.takeoff ? "approach" : frame <= ev.landing ? "air" : "landing";
  return state.data.phases[key];
}

function renderControls(kf) {
  const playing = isPlaying();
  els.btnPlay.textContent = playing ? "❚❚" : "▶";
  els.btnPlay.setAttribute("aria-label", playing ? "一時停止" : "再生");
  els.btnPlay.title = playing ? "一時停止（スペースキー）" : "再生（スペースキー）";
  const r = range();
  els.time.textContent = `${seconds(state.frame)}秒（${seconds(r.start)}〜${seconds(r.end)}秒）`;
  els.phase.textContent = `${phaseOf(state.frame)}（フレーム ${state.frame}）`;

  const pos = `${xPercent(state.frame)}%`;
  els.playhead.style.left = pos;
  els.played.style.width = pos;
  for (const m of els.kfMarkers.children) m.classList.toggle("active", kf !== null && m.dataset.key === kf.key);

  els.badge.hidden = false;
  if (kf) els.badge.textContent = `■ 一時停止　${CIRCLED[kf.no - 1]} ${kf.name}`;
  else els.badge.textContent = playing ? `▶ ${Number(els.speed.value)}倍速` : "❚❚ 一時停止";
}

// ---------- シークバー ----------

function xPercent(frame) {
  const r = range();
  return Math.min(100, Math.max(0, ((frame - r.start) / Math.max(1, r.end - r.start)) * 100));
}

function buildTimeline() {
  const d = state.data;
  const r = range();
  const ev = d.events;
  const zones = [
    ["approach", r.start, ev.takeoff],
    ["air", ev.takeoff, ev.landing],
    ["landing", ev.landing, r.end],
  ];
  els.zones.innerHTML = "";
  els.zoneLabels.innerHTML = "";
  for (const [key, a, b] of zones) {
    const zone = document.createElement("div");
    zone.className = "zone";
    zone.style.left = `${xPercent(a)}%`;
    zone.style.width = `${xPercent(b) - xPercent(a)}%`;
    zone.style.background = ZONE_COLORS[key];
    els.zones.appendChild(zone);
    const label = document.createElement("span");
    label.className = "zone-label";
    label.style.left = `${(xPercent(a) + xPercent(b)) / 2}%`;
    label.textContent = d.phases[key];
    els.zoneLabels.appendChild(label);
  }

  els.kfMarkers.innerHTML = "";
  for (const kf of d.keyframes) {
    const m = document.createElement("button");
    m.type = "button";
    m.className = kf.problems ? "kf" : "kf ok";
    m.dataset.key = kf.key;
    m.style.left = `${xPercent(kf.frame)}%`;
    m.textContent = String(kf.no);
    m.setAttribute("aria-label", `${CIRCLED[kf.no - 1]} ${kf.name}`);
    const tip = kf.problems ? `直したい点 ${kf.problems}件` : "お手本に近い";
    m.addEventListener("pointerenter", () => showTooltip(m, `${CIRCLED[kf.no - 1]} ${kf.name}（${tip}）`));
    m.addEventListener("pointerleave", hideTooltip);
    m.addEventListener("pointerdown", (e) => e.stopPropagation());
    m.addEventListener("click", () => {
      pause();
      state.showSummary = false;
      seekFrame(kf.frame);
    });
    els.kfMarkers.appendChild(m);
  }
  layoutMarkers();
}

// 前の印と重なる印は上の段に置く（段の数は重なり具合で増やす）
const MARKER_SIZE = 32;
const MARKER_GAP = 36; // 同じ段に並べられる印の間隔（px）
const MARKER_ROW_H = 36;
const MARKER_STEM = 8; // いちばん下の段の印からバーまでの線の長さ

function layoutMarkers() {
  const width = els.track.getBoundingClientRect().width;
  const lastX = [];
  const rows = [];
  for (const m of els.kfMarkers.children) {
    const x = (parseFloat(m.style.left) / 100) * width;
    let row = lastX.findIndex((last) => x - last >= MARKER_GAP);
    if (row < 0) row = lastX.length;
    lastX[row] = x;
    rows.push(row);
  }
  const top = 4 + (lastX.length - 1) * MARKER_ROW_H + MARKER_SIZE + MARKER_STEM; // バーの上端
  els.timeline.style.paddingTop = `${top}px`;
  els.kfMarkers.style.height = `${top}px`;
  [...els.kfMarkers.children].forEach((m, i) => {
    const y = top - MARKER_STEM - MARKER_SIZE - rows[i] * MARKER_ROW_H;
    m.style.top = `${y}px`;
    m.style.setProperty("--stem", `${top - y - MARKER_SIZE + 2}px`);
  });
}

function showTooltip(anchor, text) {
  els.tooltip.textContent = text;
  els.tooltip.style.left = anchor.style.left;
  els.tooltip.hidden = false;
}

function hideTooltip() {
  els.tooltip.hidden = true;
}

function frameAtPointer(e) {
  const rect = els.track.getBoundingClientRect();
  const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
  const r = range();
  return Math.round(r.start + ratio * (r.end - r.start));
}

function setupTimeline() {
  let dragging = false;
  let wasPlaying = false;
  els.timeline.addEventListener("pointerdown", (e) => {
    if (!state.data) return;
    dragging = true;
    wasPlaying = isPlaying();
    pause();
    state.showSummary = false;
    els.timeline.setPointerCapture(e.pointerId);
    seekFrame(frameAtPointer(e));
  });
  els.timeline.addEventListener("pointermove", (e) => {
    if (!state.data) return;
    const f = frameAtPointer(e);
    if (dragging) seekFrame(f);
    else if (!e.target.classList.contains("kf")) {
      els.tooltip.textContent = `${seconds(f - range().start)}秒（${phaseOf(f)}）`;
      els.tooltip.style.left = `${xPercent(f)}%`;
      els.tooltip.hidden = false;
    }
  });
  const end = () => {
    if (!dragging) return;
    dragging = false;
    if (wasPlaying) play();
  };
  els.timeline.addEventListener("pointerup", end);
  els.timeline.addEventListener("pointercancel", end);
  els.timeline.addEventListener("pointerleave", () => { if (!dragging) hideTooltip(); });
}

// ---------- 右側の情報 ----------

function adviceList(items) {
  if (!items.length) {
    return `<p class="muted">この場面で比べられる項目がありませんでした（関節が隠れているなど）。</p>`;
  }
  return `<ul class="advice">${items.map((a) => `
    <li class="${a.good ? "good" : ""}">
      <span class="mark" style="background:${a.color}">${a.mark}</span>
      <span>${escapeHtml(a.text)}</span>
    </li>`).join("")}</ul>`;
}

function legend() {
  const sk = state.data.skeleton;
  const next = state.data.keyframes.find((k) => k.frame > state.frame);
  const d = state.data;
  const view = d.view_offset === null
    ? "お手本の骨格は、お手本の撮影角度のまま重ねています。"
    : `お手本の骨格は、撮影角度の差（約${Math.abs(d.view_offset).toFixed(0)}°）を3Dで回して補正し、自分のカメラから見た形で重ねています。上のお手本の映像は元の撮影角度のままです。`;
  return `
    <ul class="legend">
      <li><span class="swatch thick" style="background:${sk.model.left}"></span><span class="swatch thick" style="background:${sk.model.right}"></span>太線（緑・黄）＝お手本の骨格</li>
      <li><span class="swatch" style="background:${sk.self.left}"></span><span class="swatch" style="background:${sk.self.right}"></span>細線（水色・桃色）＝自分の骨格</li>
      <li class="muted">緑・水色が左半身、黄・桃色が右半身</li>
    </ul>
    ${next ? `<p class="next">次の一時停止：${CIRCLED[next.no - 1]} ${next.name}</p>` : ""}
    <div class="info">
      <p>踏切と着氷：自分 ${seconds(d.events.takeoff)}秒 → ${seconds(d.events.landing)}秒（滞空 ${d.air_time.toFixed(2)}秒）／ お手本の滞空 ${d.ref_air_time.toFixed(2)}秒</p>
      <p>${view}</p>
      <p>一時停止中は、アドバイスの番号と同じ色の線で、測った場所を示します（白い点線は水平・鉛直の目安）。</p>
      <p>数値は骨格推定によるおおよその値です。撮影の角度が違うと、角度などにずれが出ることがあります。</p>
    </div>`;
}

function setThumb(src) {
  if (src) {
    if (!els.thumbImg.src.endsWith(src)) els.thumbImg.src = src;
    els.thumbImg.hidden = false;
    els.thumbEmpty.hidden = true;
  } else {
    els.thumbImg.hidden = true;
    els.thumbEmpty.hidden = false;
  }
}

function renderPanel(kf) {
  const d = state.data;
  els.panelSummary.hidden = !state.showSummary;
  els.panelMain.hidden = state.showSummary;
  if (state.showSummary) {
    renderSummary();
    return;
  }
  const t = `自分 ${seconds(state.frame)}秒 ・ ${phaseOf(state.frame)}`;
  if (kf) {
    els.panelTitle.textContent = `${CIRCLED[kf.no - 1]} ${kf.name}`;
    els.panelSub.textContent = `一時停止中 ・ ${t}`;
    setThumb(kf.ref_image);
    const body = adviceList(kf.advice);
    if (els.panelBody.dataset.key !== kf.key) {
      els.panelBody.innerHTML = body;
      els.panelBody.dataset.key = kf.key;
    }
    return;
  }
  els.panelTitle.textContent = isPlaying()
    ? `▶ スロー再生（${Number(els.speed.value)}倍速）`
    : "❚❚ 一時停止中";
  els.panelSub.textContent = t;
  const thumb = d.frames[state.frame].thumb;
  setThumb(thumb === null ? null : `${d.thumb_url}/${thumb}.jpg`);
  const html = legend();
  if (els.panelBody.innerHTML !== html) {
    els.panelBody.innerHTML = html;
    delete els.panelBody.dataset.key;
  }
}

function renderSummary() {
  const s = state.data.summary;
  const rows = s.metrics.map((m) => `
    <tr><td>${m.label}</td><td>${m.me ?? "—"}</td><td class="ref">${m.ref ?? "—"}</td></tr>`).join("");
  const problems = s.problems.length
    ? `<ul class="advice">${s.problems.map((p, n) => `
        <li><span class="mark" style="background:${p.color}">${n + 1}</span>
          <span><span class="scene">${CIRCLED[p.no - 1]} ${p.name}</span><br>${escapeHtml(p.text)}</span></li>`).join("")}</ul>`
    : `<p>大きな差は見つかりませんでした。</p>`;
  const html = `
    <div class="summary">
      <h2>まとめ</h2>
      <table>
        <thead><tr><th>項目</th><th>自分</th><th>お手本</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <h3>特に直したいポイント</h3>
      ${problems}
      <button type="button" class="btn" id="summary-close">再生画面に戻る</button>
    </div>`;
  if (els.panelSummary.innerHTML !== html) {
    els.panelSummary.innerHTML = html;
    $("summary-close").addEventListener("click", () => {
      state.showSummary = false;
      render();
    });
  }
}

function escapeHtml(text) {
  return text.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

// ---------- カメラ ----------

const camera = {
  dialog: $("camera"), live: $("camera-live"), review: $("camera-review"), select: $("camera-select"),
  status: $("camera-status"), record: $("cam-record"), use: $("cam-use"), retake: $("cam-retake"),
  close: $("cam-close"),
  stream: null, recorder: null, chunks: [], file: null,
};

function recorderType() {
  const types = ["video/mp4;codecs=avc1", "video/mp4", "video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"];
  return types.find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
}

async function startCamera(deviceId) {
  stopStream();
  const video = { width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 60 } };
  if (deviceId) video.deviceId = { exact: deviceId };
  try {
    camera.stream = await navigator.mediaDevices.getUserMedia({ video, audio: false });
  } catch (e) {
    camera.status.textContent = `カメラを使えませんでした（${e.name}）。ブラウザでカメラの使用を許可してください。`;
    camera.record.disabled = true;
    return;
  }
  camera.record.disabled = false;
  camera.live.srcObject = camera.stream;
  const devices = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput");
  const current = camera.stream.getVideoTracks()[0].getSettings().deviceId;
  camera.select.innerHTML = devices
    .map((d, i) => `<option value="${d.deviceId}" ${d.deviceId === current ? "selected" : ""}>${escapeHtml(d.label || `カメラ ${i + 1}`)}</option>`)
    .join("");
  camera.select.hidden = devices.length < 2;
}

function stopStream() {
  if (camera.stream) camera.stream.getTracks().forEach((t) => t.stop());
  camera.stream = null;
}

function resetCameraView() {
  camera.file = null;
  camera.review.hidden = true;
  camera.review.removeAttribute("src");
  camera.live.hidden = false;
  camera.record.hidden = false;
  camera.record.textContent = "● 録画開始";
  camera.use.hidden = true;
  camera.retake.hidden = true;
  camera.status.textContent = "踏切の少し前から着氷の後まで、全身が写るように撮ってください。";
}

function setupCamera() {
  els.btnCamera.addEventListener("click", async () => {
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      alert("このブラウザではカメラ撮影を使えません。Chrome または Edge で http://localhost から開いてください。");
      return;
    }
    stopPlayback();
    resetCameraView();
    camera.dialog.showModal();
    await startCamera();
  });
  camera.select.addEventListener("change", () => startCamera(camera.select.value));
  camera.record.addEventListener("click", () => {
    if (camera.recorder && camera.recorder.state === "recording") {
      camera.recorder.stop();
      return;
    }
    if (!camera.stream) return;
    const type = recorderType();
    camera.chunks = [];
    camera.recorder = new MediaRecorder(camera.stream, type ? { mimeType: type, videoBitsPerSecond: 12_000_000 } : {});
    camera.recorder.ondataavailable = (e) => { if (e.data.size) camera.chunks.push(e.data); };
    camera.recorder.onstop = () => {
      camera.dialog.classList.remove("recording");
      const mime = camera.recorder.mimeType || "video/webm";
      const blob = new Blob(camera.chunks, { type: mime });
      const ext = mime.includes("mp4") ? "mp4" : "webm";
      const stamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
      camera.file = new File([blob], `camera_${stamp}.${ext}`, { type: mime });
      camera.review.src = URL.createObjectURL(blob);
      camera.review.hidden = false;
      camera.live.hidden = true;
      camera.record.hidden = true;
      camera.use.hidden = false;
      camera.retake.hidden = false;
      camera.status.textContent = "撮った動画を確認して、「この動画で解析」を押してください。";
    };
    camera.recorder.start(250);
    camera.dialog.classList.add("recording");
    camera.record.textContent = "■ 録画停止";
    camera.status.textContent = "録画しています…";
  });
  camera.retake.addEventListener("click", resetCameraView);
  camera.use.addEventListener("click", () => {
    const file = camera.file;
    camera.dialog.close();
    if (file) analyze(file);
  });
  camera.close.addEventListener("click", () => camera.dialog.close());
  camera.dialog.addEventListener("close", () => {
    if (camera.recorder && camera.recorder.state === "recording") {
      camera.recorder.onstop = null;
      camera.recorder.stop();
    }
    camera.dialog.classList.remove("recording");
    stopStream();
  });
}

// ---------- 操作 ----------

function setup() {
  els.fileInput.addEventListener("change", () => {
    const file = els.fileInput.files[0];
    els.fileInput.value = "";
    if (file) analyze(file);
  });
  for (const target of [els.stage, els.dropzone]) {
    target.addEventListener("dragover", (e) => {
      e.preventDefault();
      els.dropzone.classList.add("drag");
    });
    target.addEventListener("dragleave", () => els.dropzone.classList.remove("drag"));
    target.addEventListener("drop", (e) => {
      e.preventDefault();
      els.dropzone.classList.remove("drag");
      const file = [...e.dataTransfer.files].find((f) => f.type.startsWith("video/")) || e.dataTransfer.files[0];
      if (file) analyze(file);
    });
  }
  els.progressClose.addEventListener("click", () => {
    els.progress.hidden = true;
  });

  els.btnPlay.addEventListener("click", () => (isPlaying() ? pause() : play()));
  els.btnStop.addEventListener("click", stopPlayback);
  els.speed.addEventListener("change", () => {
    applySpeed();
    render();
  });
  els.btnSummary.addEventListener("click", () => {
    pause();
    state.showSummary = !state.showSummary;
    render();
  });
  for (const input of [els.showRef, els.showSelf, els.showMarks, els.stopAtKf, els.zoom]) {
    input.addEventListener("change", render);
  }
  els.fullRange.addEventListener("change", () => {
    if (!state.data) return;
    buildTimeline();
    const r = range();
    if (state.frame < r.start || state.frame > r.end) seekFrame(r.start);
    else render();
  });
  els.video.addEventListener("play", render);
  els.video.addEventListener("pause", render);
  els.video.addEventListener("seeked", render);

  document.addEventListener("keydown", (e) => {
    if (!state.data || camera.dialog.open) return;
    if (["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName) && e.target.type !== "checkbox") return;
    if (e.code === "Space") {
      e.preventDefault();
      isPlaying() ? pause() : play();
    } else if (e.code === "ArrowLeft" || e.code === "ArrowRight") {
      e.preventDefault();
      pause();
      state.showSummary = false;
      seekFrame(state.frame + (e.code === "ArrowLeft" ? -1 : 1));
    }
  });

  window.addEventListener("resize", () => { if (state.data) layoutMarkers(); });

  setupTimeline();
  setupCamera();
  startFrameLoop();
}

async function init() {
  setup();
  await loadElements();
  const match = location.hash.match(/job=([0-9a-f]+)/);
  if (match) {
    showProgress("前回の解析結果を開いています", "", 1);
    await openResult(match[1]);
  }
}

init();
