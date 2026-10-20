// 解析結果を扱う小さな関数と、canvas への描画
import type { Phase, Pose, Range, Result, Settings, SkeletonStyle } from "@/types"

export const CIRCLED = "①②③④⑤⑥⑦"

export function playRange(data: Result, fullRange: boolean): Range {
  return fullRange ? { start: 0, end: data.video.frames - 1 } : data.range
}

export function seconds(data: Result, frame: number): string {
  return (frame / data.video.fps).toFixed(2)
}

export function phaseOf(data: Result, frame: number): Phase {
  const ev = data.events
  return frame < ev.takeoff ? "approach" : frame <= ev.landing ? "air" : "landing"
}

// 元の動画のピクセル座標 → canvas の座標。拡大表示では、切り抜き枠の高さを canvas に合わせ、
// 横は canvas の縦横比まで広げて人物を中心に置く（大きな画面いっぱいに映すため）
export function viewTransform(data: Result, frame: number, cw: number, ch: number, zoom: boolean) {
  if (zoom) {
    const [x0, y0, w, h] = data.frames[frame].crop
    const k = Math.min(ch / h, cw / w)
    const { width, height } = data.video
    // 映像が canvas より大きいときは、映像の外（黒い余白）が見えないように寄せる
    const clamp = (d: number, size: number, view: number) => (size >= view ? Math.min(0, Math.max(view - size, d)) : d)
    return {
      k,
      dx: clamp(cw / 2 - (x0 + w / 2) * k, width * k, cw),
      dy: clamp(ch / 2 - (y0 + h / 2) * k, height * k, ch),
    }
  }
  const { width, height } = data.video
  const k = Math.min(cw / width, ch / height)
  return { k, dx: (cw - width * k) / 2, dy: (ch - height * k) / 2 }
}

const L_SHOULDER = 11
const R_SHOULDER = 12

function drawSkeleton(ctx: CanvasRenderingContext2D, data: Result, pose: Pose, style: SkeletonStyle, k: number) {
  if (!pose) return
  const sk = data.skeleton
  const { p, v } = pose
  const x = (i: number) => p[2 * i]
  const y = (i: number) => p[2 * i + 1]
  ctx.lineCap = "round"

  const line = (color: string, segments: [number, number, number, number][]) => {
    ctx.strokeStyle = color
    ctx.lineWidth = style.thickness
    ctx.beginPath()
    for (const [ax, ay, bx, by] of segments) {
      ctx.moveTo(ax, ay)
      ctx.lineTo(bx, by)
    }
    ctx.stroke()
  }
  const bones = (pairs: [number, number][]) =>
    pairs.filter(([a, b]) => v[a] && v[b]).map(([a, b]) => [x(a), y(a), x(b), y(b)] as [number, number, number, number])
  const joints = (indices: number[], color: string) => {
    for (const i of indices) {
      if (!v[i]) continue
      ctx.beginPath()
      ctx.arc(x(i), y(i), style.thickness + 2, 0, Math.PI * 2)
      ctx.fillStyle = color
      ctx.fill()
      ctx.lineWidth = 1 / k
      ctx.strokeStyle = "#000"
      ctx.stroke()
    }
  }

  const center = bones(sk.center_bones)
  // 首: 両肩の中点 → 鼻
  if (v[L_SHOULDER] && v[R_SHOULDER] && v[sk.nose]) {
    center.push([(x(L_SHOULDER) + x(R_SHOULDER)) / 2, (y(L_SHOULDER) + y(R_SHOULDER)) / 2, x(sk.nose), y(sk.nose)])
  }
  line(style.center, center)
  line(style.left, bones(sk.left_bones))
  line(style.right, bones(sk.right_bones))
  joints(sk.left_points, style.left)
  joints(sk.right_points, style.right)
  joints([sk.nose], style.center)
}

export interface DrawInput {
  data: Result
  frame: number
  video: HTMLVideoElement
  marks: HTMLImageElement | null // 一時停止中のキーフレームの測定線
  refPose: Pose
  settings: Settings
}

export function drawView(canvas: HTMLCanvasElement, input: DrawInput) {
  const ctx = canvas.getContext("2d")
  if (!ctx) return
  const { data, frame, video, marks, refPose, settings } = input
  const { k, dx, dy } = viewTransform(data, frame, canvas.width, canvas.height, settings.zoom)
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.fillStyle = "#000"
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.setTransform(k, 0, 0, k, dx, dy)
  const { width, height } = data.video
  if (video.readyState >= 2) ctx.drawImage(video, 0, 0, width, height)
  if (settings.showSelf) drawSkeleton(ctx, data, data.frames[frame].me, data.skeleton.self, k)
  if (settings.showRef) drawSkeleton(ctx, data, refPose, data.skeleton.model, k)
  if (marks && settings.showMarks && marks.complete && marks.naturalWidth) ctx.drawImage(marks, 0, 0, width, height)
  ctx.setTransform(1, 0, 0, 1, 0, 0)
}
