import { useEffect, useLayoutEffect, useRef, type ReactNode, type RefObject } from "react"

import { drawView } from "@/lib/analysis"
import type { Keyframe, Result, Settings } from "@/types"

// 自分の映像。<video> は見えないように置き、canvas に切り抜いて骨格・測定線と一緒に描く。
// canvas は左側の空いている場所いっぱいの大きさにする
export function VideoStage({
  videoRef,
  data,
  frame,
  activeKf,
  settings,
  marks,
  badge,
  children,
}: {
  videoRef: RefObject<HTMLVideoElement | null>
  data: Result | null
  frame: number
  activeKf: Keyframe | null
  settings: Settings
  marks: Record<string, HTMLImageElement>
  badge: ReactNode
  children?: ReactNode
}) {
  const boxRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  const draw = () => {
    const canvas = canvasRef.current
    const video = videoRef.current
    if (!canvas || !video || !data) return
    drawView(canvas, {
      data,
      frame,
      video,
      marks: activeKf ? (marks[activeKf.key] ?? null) : null,
      refPose: activeKf ? activeKf.ref_pose : data.frames[frame].ref,
      settings,
    })
  }
  const drawRef = useRef(draw)
  useLayoutEffect(() => {
    drawRef.current = draw
  })

  // 表示の大きさに合わせて canvas の画素数を変える（高解像度の画面でもにじまないように）
  useLayoutEffect(() => {
    const box = boxRef.current
    const canvas = canvasRef.current
    if (!box || !canvas) return
    const resize = () => {
      const dpr = window.devicePixelRatio || 1
      canvas.width = Math.round(box.clientWidth * dpr)
      canvas.height = Math.round(box.clientHeight * dpr)
      drawRef.current()
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(box)
    return () => observer.disconnect()
  }, [])

  useEffect(draw)

  // 同じフレームへのシークなどで state が変わらなくても、映像が届いたら描き直す
  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    const redraw = () => drawRef.current()
    video.addEventListener("seeked", redraw)
    video.addEventListener("loadeddata", redraw)
    return () => {
      video.removeEventListener("seeked", redraw)
      video.removeEventListener("loadeddata", redraw)
    }
  }, [videoRef])

  // 測定線の画像が後から読み込まれたときにも描き直す
  useEffect(() => {
    const images = Object.values(marks)
    const redraw = () => drawRef.current()
    images.forEach((img) => img.addEventListener("load", redraw))
    return () => images.forEach((img) => img.removeEventListener("load", redraw))
  }, [marks])

  return (
    <div ref={boxRef} className="relative min-h-0 flex-1 overflow-hidden rounded-xl bg-black ring-1 ring-border">
      <canvas ref={canvasRef} className="absolute inset-0 size-full" />
      <video
        ref={videoRef}
        muted
        playsInline
        preload="auto"
        className="pointer-events-none absolute inset-0 size-full opacity-0"
      />
      {data && badge}
      {children}
    </div>
  )
}
