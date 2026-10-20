import { ChevronLeft, ChevronRight, Pause, Play, Repeat, Scissors } from "lucide-react"
import { useEffect, useRef, useState, type PointerEvent } from "react"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Slider } from "@/components/ui/slider"
import { cn } from "@/lib/utils"
import type { SourceVideo } from "@/types"

const MIN_LENGTH_S = 1.5 // サーバ（src/app.py の MIN_CLIP_S）と同じ
const THUMBS = 8
const STEP_S = 0.1

// 秒 → フレーム番号（lib/player.ts と同じ式）
const frameAt = (video: SourceVideo, t: number) => Math.min(video.frames - 1, Math.max(0, Math.floor(t * video.fps + 0.05)))
// 範囲の終わり（秒）は最後のフレームの終わりなので、その1つ前のフレームまでを含める
const lastFrameBefore = (video: SourceVideo, t: number) => Math.min(video.frames - 1, Math.floor(t * video.fps + 0.05) - 1)

// 動画から等間隔に小さな画像を取り出す（どこで跳んでいるか分かるように）
async function makeThumbs(url: string, count: number, signal: { cancelled: boolean }): Promise<string[]> {
  const video = document.createElement("video")
  video.muted = true
  video.playsInline = true
  video.preload = "auto"
  video.src = url
  await new Promise((resolve, reject) => {
    video.onloadeddata = resolve
    video.onerror = reject
  })
  const canvas = document.createElement("canvas")
  canvas.height = 90
  canvas.width = Math.round((90 * video.videoWidth) / video.videoHeight)
  const ctx = canvas.getContext("2d")!
  const thumbs: string[] = []
  for (let i = 0; i < count && !signal.cancelled; i++) {
    video.currentTime = ((i + 0.5) / count) * video.duration
    await new Promise((resolve) => (video.onseeked = resolve))
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
    thumbs.push(canvas.toDataURL("image/jpeg", 0.7))
  }
  video.removeAttribute("src")
  video.load()
  return thumbs
}

// 動画の前後を切り落とす範囲を選ぶ（PC・スマホ共通）
export function TrimDialog({
  video,
  initial,
  open,
  onOpenChange,
  onConfirm,
}: {
  video: SourceVideo | null
  initial?: { start: number; end: number } // 前に解析した範囲（フレーム番号）
  open: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: (start: number, end: number) => void
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const stripRef = useRef<HTMLDivElement>(null)
  const duration = video ? video.frames / video.fps : 0
  const [range, setRange] = useState<[number, number]>([0, duration])
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [loop, setLoop] = useState(false)
  const [thumbs, setThumbs] = useState<string[]>([])
  const loopRef = useRef({ loop, range })
  useEffect(() => {
    loopRef.current = { loop, range }
  }, [loop, range])

  // 開くたびに、前の範囲（なければ全体）から始める
  useEffect(() => {
    if (!open || !video) return
    const d = video.frames / video.fps
    setRange(initial ? [initial.start / video.fps, (initial.end + 1) / video.fps] : [0, d])
    setTime(0)
    setLoop(false)
    setThumbs([])
    const signal = { cancelled: false }
    makeThumbs(video.url, THUMBS, signal)
      .then((t) => !signal.cancelled && setThumbs(t))
      .catch(() => {})
    return () => {
      signal.cancelled = true
    }
  }, [open, video, initial])

  // 再生位置を追う。「選んだ範囲を再生」のときは範囲の終わりで始めに戻す。
  // ダイアログの中身は開いたあとに作られるので、video は毎回 ref から読む
  useEffect(() => {
    if (!open) return
    let raf = 0
    const tick = () => {
      const el = videoRef.current
      if (el) {
        const { loop, range } = loopRef.current
        if (loop && !el.paused && el.currentTime >= range[1]) el.currentTime = range[0]
        setTime(el.currentTime)
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [open])

  if (!video) return null

  const seek = (t: number) => {
    const el = videoRef.current
    if (!el) return
    el.currentTime = Math.min(duration, Math.max(0, t))
    setTime(el.currentTime)
  }
  const togglePlay = () => {
    const el = videoRef.current
    if (!el) return
    if (el.paused) {
      if (loop && (el.currentTime < range[0] || el.currentTime >= range[1])) el.currentTime = range[0]
      void el.play()
    } else el.pause()
  }
  const toggleLoop = () => {
    const next = !loop
    setLoop(next)
    if (next) {
      seek(range[0])
      void videoRef.current?.play()
    }
  }
  const setStart = () => setRange(([, b]) => [Math.min(time, b - MIN_LENGTH_S / 2), b])
  const setEnd = () => setRange(([a]) => [a, Math.max(time, a + MIN_LENGTH_S / 2)])
  const seekStrip = (e: PointerEvent<HTMLDivElement>) => {
    const rect = stripRef.current!.getBoundingClientRect()
    seek(((e.clientX - rect.left) / rect.width) * duration)
  }

  const length = range[1] - range[0]
  const tooShort = length < MIN_LENGTH_S
  const pct = (t: number) => `${(t / duration) * 100}%`

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-dvh flex-col overflow-y-auto sm:max-w-4xl max-sm:h-dvh max-sm:max-w-none max-sm:rounded-none">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-lg">
            <Scissors className="size-5" />
            解析する範囲を選ぶ
          </DialogTitle>
          <DialogDescription>
            撮り始めと撮り終わりの余分なところを切り落とします。踏切の約1秒前から着氷の約1秒後までを残すと、うまく解析できます。
          </DialogDescription>
        </DialogHeader>

        <video
          ref={videoRef}
          src={video.url}
          muted
          playsInline
          preload="auto"
          className="max-h-[45dvh] w-full rounded-lg bg-black object-contain"
          onClick={togglePlay}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
        />

        {/* サムネイルの帯。範囲の外は暗くし、今の位置に線を出す。押すとその位置へ */}
        <div
          ref={stripRef}
          className="relative h-14 cursor-pointer touch-none overflow-hidden rounded-md bg-muted select-none"
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture(e.pointerId)
            seekStrip(e)
          }}
          onPointerMove={(e) => {
            if (e.buttons) seekStrip(e)
          }}
        >
          <div className="flex h-full">
            {thumbs.map((src, i) => (
              <img key={i} src={src} alt="" className="h-full min-w-0 flex-1 object-cover" draggable={false} />
            ))}
          </div>
          <div className="absolute inset-y-0 left-0 bg-black/65" style={{ width: pct(range[0]) }} />
          <div className="absolute inset-y-0 right-0 bg-black/65" style={{ left: pct(range[1]) }} />
          <div
            className="absolute inset-y-0 border-y-2 border-primary"
            style={{ left: pct(range[0]), width: pct(length) }}
          />
          <div className="absolute inset-y-0 w-0.5 -translate-x-1/2 bg-red-500" style={{ left: pct(time) }} />
        </div>

        <Slider
          min={0}
          max={duration}
          step={1 / video.fps}
          minStepsBetweenThumbs={Math.round((MIN_LENGTH_S / 2) * video.fps)}
          value={range}
          onValueChange={(v) => {
            const [a, b] = v as [number, number]
            // 動かした取っ手の位置を映像で見られるようにする
            seek(a !== range[0] ? a : b)
            setRange([a, b])
          }}
          aria-label="解析する範囲"
          className="py-2 [&_[data-slot=slider-thumb]]:size-6 [&_[data-slot=slider-track]]:h-2"
        />

        <div className="flex flex-wrap items-center gap-2">
          <Button size="icon-lg" onClick={togglePlay} aria-label={playing ? "一時停止" : "再生"}>
            {playing ? <Pause className="fill-current" /> : <Play className="fill-current" />}
          </Button>
          <Button size="icon-lg" variant="secondary" onClick={() => seek(time - STEP_S)} aria-label="0.1秒戻る">
            <ChevronLeft />
          </Button>
          <Button size="icon-lg" variant="secondary" onClick={() => seek(time + STEP_S)} aria-label="0.1秒進む">
            <ChevronRight />
          </Button>
          <span className="font-mono text-sm tabular-nums">{time.toFixed(2)}秒</span>
          <div className="ml-auto flex flex-wrap gap-2">
            <Button variant="outline" onClick={setStart}>
              今の位置を開始にする
            </Button>
            <Button variant="outline" onClick={setEnd}>
              今の位置を終了にする
            </Button>
            <Button variant={loop ? "default" : "outline"} onClick={toggleLoop}>
              <Repeat />
              選んだ範囲を再生
            </Button>
          </div>
        </div>

        <p className={cn("text-sm tabular-nums", tooShort ? "text-destructive" : "text-muted-foreground")}>
          開始 {range[0].toFixed(2)}秒 ／ 終了 {range[1].toFixed(2)}秒 ／ 長さ {length.toFixed(2)}秒
          {tooShort && `（${MIN_LENGTH_S}秒以上にしてください）`}
        </p>

        <DialogFooter className="mt-auto gap-2">
          <Button variant="outline" onClick={() => onConfirm(0, video.frames - 1)}>
            トリミングせずに解析
          </Button>
          <Button
            disabled={tooShort}
            onClick={() => onConfirm(frameAt(video, range[0]), lastFrameBefore(video, range[1]))}
          >
            <Scissors />
            この範囲で解析
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
