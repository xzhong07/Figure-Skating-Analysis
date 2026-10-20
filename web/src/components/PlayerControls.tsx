import { Pause, Play, Settings2, Square } from "lucide-react"
import type { ReactNode } from "react"

import { Timeline } from "@/components/Timeline"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { phaseOf, seconds } from "@/lib/analysis"
import { useSmallScreen } from "@/lib/device"
import type { Range, Result, Settings } from "@/types"

export const SPEEDS = ["0.1", "0.25", "0.5", "0.75", "1"]

function Toggle({
  id,
  label,
  checked,
  onChange,
}: {
  id: string
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <div className="flex items-center gap-2">
      <Switch id={id} checked={checked} onCheckedChange={onChange} />
      <Label htmlFor={id} className="cursor-pointer whitespace-nowrap">
        {label}
      </Label>
    </div>
  )
}

function IconButton({ label, children, ...props }: { label: string; children: ReactNode } & React.ComponentProps<typeof Button>) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button size="icon-lg" aria-label={label} className="pointer-coarse:size-11" {...props}>
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  )
}

export function PlayerControls({
  data,
  frame,
  playing,
  range,
  activeKey,
  speed,
  settings,
  onToggle,
  onStop,
  onSpeed,
  onSettings,
  onSeek,
  onKeyframe,
  onScrubStart,
  onScrubEnd,
}: {
  data: Result | null
  frame: number
  playing: boolean
  range: Range
  activeKey: string | null
  speed: string
  settings: Settings
  onToggle: () => void
  onStop: () => void
  onSpeed: (speed: string) => void
  onSettings: (settings: Partial<Settings>) => void
  onSeek: (frame: number) => void
  onKeyframe: (key: string) => void
  onScrubStart: () => void
  onScrubEnd: () => void
}) {
  const disabled = !data
  // 小さな画面では、骨格のスイッチも「表示設定」の中にまとめて、映像とアドバイスの場所を空ける
  const small = useSmallScreen()
  const skeletonToggles = (
    <>
      <Toggle id="show-ref" label="お手本の骨格" checked={settings.showRef} onChange={(v) => onSettings({ showRef: v })} />
      <Toggle id="show-self" label="自分の骨格" checked={settings.showSelf} onChange={(v) => onSettings({ showSelf: v })} />
    </>
  )
  return (
    <Card className="flex-none gap-1 px-2 py-2 lg:px-3 lg:py-2.5" aria-disabled={disabled}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-2 lg:gap-x-3">
        <IconButton label={playing ? "一時停止（スペースキー）" : "再生（スペースキー）"} onClick={onToggle} disabled={disabled}>
          {playing ? <Pause className="fill-current" /> : <Play className="fill-current" />}
        </IconButton>
        <IconButton label="停止（先頭に戻る）" variant="secondary" onClick={onStop} disabled={disabled}>
          <Square className="fill-current" />
        </IconButton>
        <Select value={speed} onValueChange={onSpeed} disabled={disabled}>
          <SelectTrigger className="w-24 pointer-coarse:h-11 lg:w-28" aria-label="再生速度">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SPEEDS.map((s) => (
              <SelectItem key={s} value={s}>
                {s}倍速
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {data && (
          <>
            <span className="font-mono text-sm tabular-nums">
              {seconds(data, frame)}秒
              {!small && (
                <span className="text-muted-foreground">
                  {" "}
                  / {seconds(data, range.start)}〜{seconds(data, range.end)}秒
                </span>
              )}
            </span>
            {!small && (
              <Badge variant="outline">
                {data.phases[phaseOf(data, frame)]}・フレーム {frame}
              </Badge>
            )}
          </>
        )}

        <div className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-2">
          {!small && skeletonToggles}
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" size="sm" className="pointer-coarse:h-9">
                <Settings2 />
                {small ? "表示" : "表示設定"}
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="flex w-60 flex-col gap-3">
              {small && skeletonToggles}
              <Toggle id="show-marks" label="測定線" checked={settings.showMarks} onChange={(v) => onSettings({ showMarks: v })} />
              <Toggle
                id="stop-at-kf"
                label="キーフレームで止める"
                checked={settings.stopAtKf}
                onChange={(v) => onSettings({ stopAtKf: v })}
              />
              <Toggle id="zoom" label="人物を拡大" checked={settings.zoom} onChange={(v) => onSettings({ zoom: v })} />
              <Toggle
                id="full-range"
                label="動画全体を表示"
                checked={settings.fullRange}
                onChange={(v) => onSettings({ fullRange: v })}
              />
            </PopoverContent>
          </Popover>
        </div>
      </div>

      {data && (
        <Timeline
          data={data}
          frame={frame}
          range={range}
          activeKey={activeKey}
          onSeek={onSeek}
          onKeyframe={onKeyframe}
          onScrubStart={onScrubStart}
          onScrubEnd={onScrubEnd}
          compact={small}
        />
      )}
    </Card>
  )
}
