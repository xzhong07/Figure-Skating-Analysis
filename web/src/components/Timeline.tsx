import { useLayoutEffect, useRef, useState, type PointerEvent } from "react"

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { CIRCLED, phaseOf, seconds } from "@/lib/analysis"
import { cn } from "@/lib/utils"
import type { Keyframe, Phase, Range, Result } from "@/types"

const ZONE_CLASS: Record<Phase, string> = {
  approach: "bg-slate-500/60",
  air: "bg-orange-500/70",
  landing: "bg-emerald-600/60",
}

const MARKER = 30 // キーフレームの印の直径（px）
const MARKER_GAP = 34 // 同じ段に並べられる印の間隔（px）
const ROW_H = 34
const STEM = 6 // いちばん下の段の印からバーまでの線の長さ

// 近くの印と重なる印は上の段に置く。段の数は重なり具合で増やす
function markerRows(keyframes: Keyframe[], x: (frame: number) => number, width: number): number[] {
  const lastX: number[] = []
  return keyframes.map((kf) => {
    const px = (x(kf.frame) / 100) * width
    let row = lastX.findIndex((last) => px - last >= MARKER_GAP)
    if (row < 0) row = lastX.length
    lastX[row] = px
    return row
  })
}

export function Timeline({
  data,
  frame,
  range,
  activeKey,
  onSeek,
  onScrubStart,
  onScrubEnd,
}: {
  data: Result
  frame: number
  range: Range
  activeKey: string | null
  onSeek: (frame: number) => void
  onScrubStart: () => void
  onScrubEnd: () => void
}) {
  const trackRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  const [hover, setHover] = useState<number | null>(null)
  const [dragging, setDragging] = useState(false)

  useLayoutEffect(() => {
    const track = trackRef.current
    if (!track) return
    const observer = new ResizeObserver(() => setWidth(track.clientWidth))
    observer.observe(track)
    return () => observer.disconnect()
  }, [])

  const x = (f: number) => Math.min(100, Math.max(0, ((f - range.start) / Math.max(1, range.end - range.start)) * 100))
  const rows = markerRows(data.keyframes, x, width)
  const rowCount = Math.max(1, ...rows.map((r) => r + 1))
  const barTop = 4 + (rowCount - 1) * ROW_H + MARKER + STEM

  const frameAt = (e: PointerEvent) => {
    const rect = trackRef.current!.getBoundingClientRect()
    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width))
    return Math.round(range.start + ratio * (range.end - range.start))
  }

  const ev = data.events
  const zones: [Phase, number, number][] = [
    ["approach", range.start, ev.takeoff],
    ["air", ev.takeoff, ev.landing],
    ["landing", ev.landing, range.end],
  ]

  return (
    <div
      className="relative mx-4 cursor-pointer touch-none select-none"
      style={{ paddingTop: barTop }}
      onPointerDown={(e) => {
        setDragging(true)
        e.currentTarget.setPointerCapture(e.pointerId)
        onScrubStart()
        onSeek(frameAt(e))
      }}
      onPointerMove={(e) => {
        const f = frameAt(e)
        setHover(f)
        if (dragging) onSeek(f)
      }}
      onPointerUp={() => {
        if (!dragging) return
        setDragging(false)
        onScrubEnd()
      }}
      onPointerLeave={() => setHover(null)}
    >
      {/* キーフレームの印（①〜⑦） */}
      {data.keyframes.map((kf, i) => {
        const top = barTop - STEM - MARKER - rows[i] * ROW_H
        const active = kf.key === activeKey
        return (
          <Tooltip key={kf.key}>
            <TooltipTrigger asChild>
              <button
                type="button"
                aria-label={`${CIRCLED[kf.no - 1]} ${kf.name}`}
                className={cn(
                  "absolute z-10 grid -translate-x-1/2 place-items-center rounded-full border-2 border-white text-sm font-bold text-neutral-950 shadow-md transition-transform hover:scale-110",
                  kf.problems ? "bg-orange-400" : "bg-emerald-400",
                  active && "scale-125 ring-4 ring-white/40 hover:scale-125",
                )}
                style={{ left: `${x(kf.frame)}%`, top, width: MARKER, height: MARKER }}
                onPointerDown={(e) => {
                  e.stopPropagation()
                  onScrubStart()
                  onSeek(kf.frame)
                }}
              >
                {kf.no}
              </button>
            </TooltipTrigger>
            <TooltipContent>
              {CIRCLED[kf.no - 1]} {kf.name}（{kf.problems ? `直したい点 ${kf.problems}件` : "お手本に近い"}）
            </TooltipContent>
          </Tooltip>
        )
      })}
      {/* 印からバーまでの線 */}
      {data.keyframes.map((kf, i) => {
        const top = barTop - STEM - rows[i] * ROW_H
        return (
          <div
            key={`stem-${kf.key}`}
            className="pointer-events-none absolute w-0.5 -translate-x-1/2 bg-white/80"
            style={{ left: `${x(kf.frame)}%`, top, height: barTop - top + 14 }}
          />
        )
      })}

      <div ref={trackRef} className="relative h-3.5 overflow-hidden rounded-full bg-muted">
        {zones.map(([key, a, b]) => (
          <div
            key={key}
            className={cn("absolute inset-y-0", ZONE_CLASS[key])}
            style={{ left: `${x(a)}%`, width: `${x(b) - x(a)}%` }}
          />
        ))}
        <div className="absolute inset-y-0 left-0 bg-white/25" style={{ width: `${x(frame)}%` }} />
      </div>
      <div
        className="pointer-events-none absolute w-1 -translate-x-1/2 rounded-full bg-red-500 shadow"
        style={{ left: `${x(frame)}%`, top: barTop - 3, height: 20 }}
      />

      <div className="relative h-5 text-xs text-muted-foreground">
        {zones.map(([key, a, b]) => (
          <span key={key} className="absolute top-1 -translate-x-1/2 whitespace-nowrap" style={{ left: `${(x(a) + x(b)) / 2}%` }}>
            {data.phases[key]}
          </span>
        ))}
      </div>

      {hover !== null && !dragging && (
        <div
          className="pointer-events-none absolute z-20 -translate-x-1/2 rounded-md bg-popover px-2 py-1 text-xs whitespace-nowrap text-popover-foreground shadow ring-1 ring-border"
          style={{ left: `${x(hover)}%`, top: barTop + 22 }}
        >
          {seconds(data, hover)}秒（{data.phases[phaseOf(data, hover)]}）
        </div>
      )}
    </div>
  )
}
