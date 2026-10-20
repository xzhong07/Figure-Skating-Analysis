import { useLayoutEffect, useRef, type ReactNode } from "react"

import { cn } from "@/lib/utils"

// 中身が枠に収まるまで文字を小さくする（スクロールしなくても全文が読めるように）。
// 中の文字の大きさは em で指定すること。min でも収まらないときだけスクロールさせる
export function FitBox({
  children,
  fitKey,
  max = 19,
  min = 12,
  className,
}: {
  children: ReactNode
  fitKey: unknown // 中身が変わったら測り直すための値
  max?: number
  min?: number
  className?: string
}) {
  const ref = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const fit = () => {
      let size = max
      el.style.fontSize = `${size}px`
      while (size > min && el.scrollHeight > el.clientHeight + 1) {
        size -= 0.5
        el.style.fontSize = `${size}px`
      }
    }
    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(el)
    return () => observer.disconnect()
  }, [fitKey, max, min])

  return (
    <div ref={ref} className={cn("min-h-0 flex-1 overflow-y-auto", className)}>
      {children}
    </div>
  )
}
