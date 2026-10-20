// 解析結果（result.json）の形。書き出しは src/app_export.py
export type Pose = { p: number[]; v: number[] } | null

export interface FrameData {
  me: Pose
  ref: Pose
  crop: [number, number, number, number] // 人物を中心にした切り抜き枠 x0, y0, w, h（元の動画のピクセル）
  thumb: number | null // 対応するお手本の画像番号
}

export interface AdviceItem {
  text: string
  good: boolean
  label: string
  severity: number
  mark: string
  color: string
}

export interface Keyframe {
  key: string
  no: number
  name: string
  frame: number
  ref_frame: number
  ref_pose: Pose
  advice: AdviceItem[]
  problems: number
  ref_image: string
  marks_image: string
}

export interface SkeletonStyle {
  left: string
  right: string
  center: string
  thickness: number
}

export type Phase = "approach" | "air" | "landing"

export interface Result {
  video: { url: string; fps: number; width: number; height: number; frames: number }
  events: { takeoff: number; apex: number; landing: number }
  air_time: number
  ref_air_time: number
  range: { start: number; end: number }
  phases: Record<Phase, string>
  view_offset: number | null
  thumb_url: string
  skeleton: {
    left_bones: [number, number][]
    right_bones: [number, number][]
    center_bones: [number, number][]
    left_points: number[]
    right_points: number[]
    nose: number
    model: SkeletonStyle
    self: SkeletonStyle
  }
  frames: FrameData[]
  keyframes: Keyframe[]
  summary: {
    metrics: { label: string; me: string | null; ref: string | null }[]
    problems: { keyframe: string; no: number; name: string; text: string; color: string }[]
  }
}

export interface Element {
  code: string
  name: string
  available: boolean
}

export interface Job {
  id: string
  stage: string
  message: string
  done: number
  total: number
  error?: string
}

export interface Settings {
  showRef: boolean
  showSelf: boolean
  showMarks: boolean
  stopAtKf: boolean
  zoom: boolean
  fullRange: boolean
}

export interface Range {
  start: number
  end: number
}
