import { Pause, Play } from "lucide-react"

import { FitBox } from "@/components/FitBox"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { CIRCLED, phaseOf, seconds } from "@/lib/analysis"
import type { AdviceItem, Keyframe, Result } from "@/types"

// 右側: お手本の映像と、一時停止中のキーフレームではその場面のアドバイス（my_axel_advice.mp4 と同じ並び）
export function SidePanel({
  data,
  frame,
  playing,
  speed,
  activeKf,
}: {
  data: Result | null
  frame: number
  playing: boolean
  speed: number
  activeKf: Keyframe | null
}) {
  if (!data) {
    return (
      <Card className="flex h-full items-center justify-center p-8 text-center text-muted-foreground">
        自分のジャンプの動画を取り込むと、ここにお手本の映像とアドバイスが表示されます。
      </Card>
    )
  }

  const time = `自分 ${seconds(data, frame)}秒`
  const phase = data.phases[phaseOf(data, frame)]
  const thumb = data.frames[frame].thumb
  const image = activeKf ? activeKf.ref_image : thumb === null ? null : `${data.thumb_url}/${thumb}.jpg`

  return (
    <Card className="flex h-full min-h-0 flex-col gap-3 p-5">
      <div className="flex-none">
        {activeKf ? (
          <h2 className="text-2xl font-bold tracking-tight">
            {CIRCLED[activeKf.no - 1]} {activeKf.name}
          </h2>
        ) : (
          <h2 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            {playing ? <Play className="size-6 fill-current" /> : <Pause className="size-6 fill-current" />}
            {playing ? `スロー再生（${speed}倍速）` : "一時停止中"}
          </h2>
        )}
        <div className="mt-1.5 flex items-center gap-2 text-sm text-muted-foreground">
          {activeKf && <Badge variant="secondary">一時停止中</Badge>}
          <span>{time}</span>
          <Badge variant="outline">{phase}</Badge>
        </div>
      </div>

      {/* お手本の映像は、アドバイスの場所を残すため高さを抑える */}
      <div className="flex h-[40%] flex-none justify-center">
      <div className="relative aspect-[4/3] h-full max-w-full overflow-hidden rounded-lg bg-muted">
        {image ? (
          <img src={image} alt="お手本の映像" className="size-full object-contain" />
        ) : (
          <div className="grid size-full place-items-center text-sm text-muted-foreground">（対応する場面なし）</div>
        )}
        <span className="absolute top-2 left-2 rounded-md bg-black/70 px-2 py-0.5 text-xs font-bold text-green-400">
          お手本（元の映像）
        </span>
      </div>
      </div>

      <FitBox
        fitKey={activeKf ? activeKf.key : `legend-${frame < data.keyframes[0].frame}`}
        max={activeKf ? 20 : 16}
      >
        {activeKf ? <AdviceList items={activeKf.advice} /> : <Legend data={data} frame={frame} />}
      </FitBox>
    </Card>
  )
}

export function AdviceList({ items }: { items: AdviceItem[] }) {
  if (!items.length) {
    return <p className="text-muted-foreground">この場面で比べられる項目がありませんでした（関節が隠れているなど）。</p>
  }
  return (
    <ul className="flex flex-col gap-[0.8em]">
      {items.map((a, i) => (
        <li key={i} className="flex gap-[0.6em] leading-relaxed">
          <span
            className="grid size-[1.6em] flex-none place-items-center rounded-full text-[0.85em] font-bold text-neutral-950"
            style={{ background: a.color }}
          >
            {a.mark}
          </span>
          <span className={a.good ? "text-emerald-200" : undefined}>{a.text}</span>
        </li>
      ))}
    </ul>
  )
}

function Legend({ data, frame }: { data: Result; frame: number }) {
  const sk = data.skeleton
  // 説明書きは最初のキーフレームより前にいる間だけ出す
  const showInfo = frame < data.keyframes[0].frame
  const view =
    data.view_offset === null
      ? "お手本の骨格は、お手本の撮影角度のまま重ねています。"
      : `お手本の骨格は、撮影角度の差（約${Math.abs(data.view_offset).toFixed(0)}°）を3Dで回して補正し、自分のカメラから見た形で重ねています。上のお手本の映像は元の撮影角度のままです。`
  const swatch = (color: string, thick: boolean) => (
    <span className="inline-block w-[1.4em] rounded-full align-middle" style={{ background: color, height: thick ? 6 : 3 }} />
  )
  return (
    <div className="flex flex-col gap-[0.5em]">
      <p className="flex items-center gap-2">
        {swatch(sk.model.left, true)}
        {swatch(sk.model.right, true)}太線（緑・黄）＝お手本の骨格
      </p>
      <p className="flex items-center gap-2">
        {swatch(sk.self.left, false)}
        {swatch(sk.self.right, false)}細線（水色・桃色）＝自分の骨格
      </p>
      <p className="text-muted-foreground">緑・水色が左半身、黄・桃色が右半身</p>
      {showInfo && (
        <>
          <Separator className="my-[0.4em]" />
          <div className="flex flex-col gap-[0.3em] text-[0.85em] leading-relaxed text-muted-foreground">
            <p>
              踏切と着氷：自分 {seconds(data, data.events.takeoff)}秒 → {seconds(data, data.events.landing)}秒（滞空{" "}
              {data.air_time.toFixed(2)}秒）／ お手本の滞空 {data.ref_air_time.toFixed(2)}秒
            </p>
            <p>{view}</p>
            <p>一時停止中は、アドバイスの番号と同じ色の線で、測った場所を示します（白い点線は水平・鉛直の目安）。</p>
            <p>数値は骨格推定によるおおよその値です。撮影の角度が違うと、角度などにずれが出ることがあります。</p>
          </div>
        </>
      )}
    </div>
  )
}
