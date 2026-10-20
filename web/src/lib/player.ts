// <video> の再生を管理し、フレームごとにキーフレームでの一時停止と再生範囲の終わりを調べる
import type { Range, Result } from "@/types"

export interface PlayerState {
  frame: number
  playing: boolean
  keyframe: string | null // 一時停止しているキーフレーム（同じフレームに2つあるときに見分けるため）
}

export class Player {
  data: Result | null = null
  frame = 0
  stopAtKeyframes = true
  range: Range = { start: 0, end: 0 }
  keyframe: string | null = null
  private lastFrame = -1 // 再生中に通り過ぎたキーフレームを見つけるための、前のフレーム
  private readonly video: HTMLVideoElement
  private readonly onChange: (state: PlayerState) => void
  private readonly onEnd: () => void

  constructor(video: HTMLVideoElement, onChange: (state: PlayerState) => void, onEnd: () => void) {
    this.video = video
    this.onChange = onChange
    this.onEnd = onEnd
    video.addEventListener("play", () => this.emit())
    video.addEventListener("pause", () => this.emit())
    this.startFrameLoop()
  }

  get playing(): boolean {
    return !this.video.paused && !this.video.ended
  }

  private get fps(): number {
    return this.data?.video.fps ?? 30
  }

  private frameOf(time: number): number {
    const last = (this.data?.video.frames ?? 1) - 1
    return Math.min(last, Math.max(0, Math.floor(time * this.fps + 0.05)))
  }

  private emit() {
    this.onChange({ frame: this.frame, playing: this.playing, keyframe: this.keyframe })
  }

  async load(data: Result) {
    this.data = data
    this.video.src = data.video.url
    await new Promise((resolve) => this.video.addEventListener("loadeddata", resolve, { once: true }))
  }

  seek(frame: number, keyframe: string | null = null) {
    if (!this.data) return
    this.keyframe = keyframe
    const f = Math.min(this.data.video.frames - 1, Math.max(0, Math.round(frame)))
    this.frame = f
    this.lastFrame = f
    // フレームの表示時刻ちょうどだと前のフレームになることがあるので、少し後ろを指す
    this.video.currentTime = (f + 0.3) / this.fps
    this.emit()
  }

  // キーフレームへ移動して一時停止する
  seekKeyframe(key: string) {
    const kf = this.data?.keyframes.find((k) => k.key === key)
    if (!kf) return
    this.pause()
    this.seek(kf.frame, key)
  }

  play() {
    if (!this.data) return
    // 同じフレームに次のキーフレームがあれば、再生せずにそちらのアドバイスを出す
    const kfs = this.data.keyframes
    const i = kfs.findIndex((k) => k.key === this.keyframe)
    if (i >= 0 && kfs[i + 1]?.frame === kfs[i].frame) {
      this.keyframe = kfs[i + 1].key
      this.emit()
      return
    }
    this.keyframe = null
    if (this.frame >= this.range.end || this.frame < this.range.start) this.seek(this.range.start)
    void this.video.play()
  }

  pause() {
    this.video.pause()
  }

  toggle() {
    if (this.playing) this.pause()
    else this.play()
  }

  stop() {
    this.pause()
    this.seek(this.range.start)
  }

  setRate(rate: number) {
    this.video.defaultPlaybackRate = rate
    this.video.playbackRate = rate
  }

  private onFrame(frame: number) {
    if (!this.data) return
    const prev = this.lastFrame
    this.frame = frame
    this.lastFrame = frame
    if (this.playing) {
      const kf = this.stopAtKeyframes && this.data.keyframes.find((k) => prev < k.frame && k.frame <= frame)
      if (kf) {
        this.pause()
        this.seek(kf.frame, kf.key)
        return
      }
      if (frame >= this.range.end) {
        this.pause()
        this.seek(this.range.end)
        this.onEnd()
        return
      }
    }
    this.emit()
  }

  private startFrameLoop() {
    const video = this.video
    if ("requestVideoFrameCallback" in HTMLVideoElement.prototype) {
      const step: VideoFrameRequestCallback = (_now, meta) => {
        this.onFrame(this.frameOf(meta.mediaTime))
        video.requestVideoFrameCallback(step)
      }
      video.requestVideoFrameCallback(step)
    } else {
      const step = () => {
        if (this.playing) this.onFrame(this.frameOf(video.currentTime))
        requestAnimationFrame(step)
      }
      requestAnimationFrame(step)
    }
  }
}
