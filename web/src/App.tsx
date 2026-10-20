import { Camera, ClipboardList, Pause, Play, Square, Upload, Video } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { CameraDialog, cameraSupported } from "@/components/CameraDialog"
import { PlayerControls } from "@/components/PlayerControls"
import { SidePanel } from "@/components/SidePanel"
import { SummaryDialog } from "@/components/SummaryDialog"
import { VideoStage } from "@/components/VideoStage"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { CIRCLED, playRange } from "@/lib/analysis"
import { Player } from "@/lib/player"
import { cn } from "@/lib/utils"
import type { Element, Job, Result, Settings } from "@/types"

const FALLBACK_ELEMENTS: Element[] = [{ code: "1A", name: "シングルアクセル", available: true }]

type Status =
  | { kind: "idle" }
  | { kind: "progress"; title: string; detail: string; ratio: number }
  | { kind: "error"; message: string }

export default function App() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const playerRef = useRef<Player | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const scrubWasPlaying = useRef(false)

  const [elements, setElements] = useState<Element[]>(FALLBACK_ELEMENTS)
  const [element, setElement] = useState("1A")
  const [data, setData] = useState<Result | null>(null)
  const [status, setStatus] = useState<Status>({ kind: "idle" })
  const [frame, setFrame] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState("0.25")
  const [settings, setSettings] = useState<Settings>({
    showRef: true,
    showSelf: true,
    showMarks: true,
    stopAtKf: true,
    zoom: true,
    fullRange: false,
  })
  const [summaryOpen, setSummaryOpen] = useState(false)
  const [cameraOpen, setCameraOpen] = useState(false)
  const [dragOver, setDragOver] = useState(false)

  const range = useMemo(() => (data ? playRange(data, settings.fullRange) : { start: 0, end: 0 }), [data, settings.fullRange])
  // 一時停止中で、ちょうどキーフレームの上にいるときはその場面のアドバイスを出す
  const activeKf = data && !playing ? (data.keyframes.find((k) => k.frame === frame) ?? null) : null

  // キーフレームの測定線の画像
  const marks = useMemo(() => {
    const images: Record<string, HTMLImageElement> = {}
    for (const kf of data?.keyframes ?? []) {
      const img = new Image()
      img.src = kf.marks_image
      images[kf.key] = img
      new Image().src = kf.ref_image
    }
    return images
  }, [data])

  useEffect(() => {
    const video = videoRef.current
    // StrictMode では2回呼ばれるので、作るのは1回だけ
    if (!video || playerRef.current) return
    playerRef.current = new Player(
      video,
      (s) => {
        setFrame(s.frame)
        setPlaying(s.playing)
      },
      () => setSummaryOpen(true),
    )
  }, [])

  useEffect(() => {
    const player = playerRef.current
    if (!player) return
    player.range = range
    player.stopAtKeyframes = settings.stopAtKf
  }, [range, settings.stopAtKf])

  useEffect(() => {
    playerRef.current?.setRate(Number(speed))
  }, [speed])

  const openResult = useCallback(async (id: string) => {
    let result: Result
    try {
      const res = await fetch(`/api/jobs/${id}/result`)
      if (!res.ok) throw new Error()
      result = await res.json()
    } catch {
      setStatus({ kind: "error", message: "解析結果を読み込めませんでした。" })
      return
    }
    history.replaceState(null, "", `#job=${id}`)
    // お手本の画像は再生中に切り替えるので、先に読み込んでおく
    for (const f of result.frames) if (f.thumb !== null) new Image().src = `${result.thumb_url}/${f.thumb}.jpg`
    const player = playerRef.current!
    player.pause()
    await player.load(result)
    player.setRate(Number(speed))
    const r = playRange(result, settings.fullRange)
    player.range = r
    setData(result)
    setSummaryOpen(false)
    setStatus({ kind: "idle" })
    player.seek(r.start)
  }, [speed, settings.fullRange])

  // 解析が終わるまで進み具合を表示する
  const watchJob = useCallback(
    async (id: string) => {
      for (;;) {
        let job: Job
        try {
          job = await (await fetch(`/api/jobs/${id}`)).json()
        } catch {
          setStatus({ kind: "error", message: "サーバに接続できません。src/app.py が動いているか確認してください。" })
          return
        }
        if (job.stage === "error") {
          setStatus({ kind: "error", message: job.error ?? "解析できませんでした。" })
          return
        }
        if (job.stage === "done") {
          await openResult(id)
          return
        }
        setStatus({
          kind: "progress",
          title: job.message,
          detail: job.total ? `${job.done} / ${job.total} フレーム` : "",
          ratio: job.total ? job.done / job.total : 0,
        })
        await new Promise((resolve) => setTimeout(resolve, 400))
      }
    },
    [openResult],
  )

  const analyze = useCallback(
    async (file: File) => {
      playerRef.current?.pause()
      setStatus({ kind: "progress", title: "動画を送っています", detail: "", ratio: 0 })
      const form = new FormData()
      form.append("video", file, file.name)
      form.append("element", element)
      try {
        const res = await fetch("/api/analyze", { method: "POST", body: form })
        const body = await res.json()
        if (!res.ok) throw new Error(body.error || "送信できませんでした。")
        void watchJob(body.id)
      } catch (e) {
        setStatus({ kind: "error", message: (e as Error).message })
      }
    },
    [element, watchJob],
  )

  useEffect(() => {
    fetch("/api/elements")
      .then((r) => r.json())
      .then(setElements)
      .catch(() => {})
    const match = location.hash.match(/job=([0-9a-f]+)/)
    if (match) {
      setStatus({ kind: "progress", title: "前回の解析結果を開いています", detail: "", ratio: 1 })
      void openResult(match[1])
    }
    // 最初の1回だけ
  }, [])

  // スペースキーで再生・一時停止、← → で1フレームずつ
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const player = playerRef.current
      if (!data || !player || cameraOpen || summaryOpen) return
      const target = e.target as HTMLElement
      if (target.closest("input, select, textarea, [role=combobox], [role=switch], [role=tab]")) return
      if (e.code === "Space") {
        e.preventDefault()
        player.toggle()
      } else if (e.code === "ArrowLeft" || e.code === "ArrowRight") {
        e.preventDefault()
        player.pause()
        player.seek(player.frame + (e.code === "ArrowLeft" ? -1 : 1))
      }
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [data, cameraOpen, summaryOpen])

  const pickFile = () => fileRef.current?.click()
  const openCamera = () => {
    if (!cameraSupported()) {
      setStatus({
        kind: "error",
        message: "このブラウザではカメラ撮影を使えません。Chrome または Edge で http://localhost から開いてください。",
      })
      return
    }
    playerRef.current?.pause()
    setCameraOpen(true)
  }

  const badge = activeKf ? (
    <>
      <Square className="size-4 fill-current" />
      一時停止　{CIRCLED[activeKf.no - 1]} {activeKf.name}
    </>
  ) : playing ? (
    <>
      <Play className="size-4 fill-current" />
      {speed}倍速
    </>
  ) : (
    <>
      <Pause className="size-4 fill-current" />
      一時停止
    </>
  )

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <header className="flex h-14 flex-none items-center gap-6 border-b bg-card/60 px-4 backdrop-blur">
        <div className="flex items-center gap-2">
          <div className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground">
            <Video className="size-4" />
          </div>
          <h1 className="text-lg font-bold tracking-tight whitespace-nowrap">Figure Skating Lab</h1>
        </div>

        <Tabs value={element} onValueChange={setElement}>
          <TabsList>
            {elements.map((e) => (
              <TabsTrigger
                key={e.code}
                value={e.code}
                disabled={!e.available}
                title={e.available ? e.name : `${e.name}（準備中）`}
                className="px-4 font-bold"
              >
                {e.code}
                {!e.available && <span className="text-[10px] font-normal text-muted-foreground">準備中</span>}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        <div className="ml-auto flex items-center gap-2">
          {data && (
            <Button variant="outline" onClick={() => setSummaryOpen(true)}>
              <ClipboardList />
              まとめ
            </Button>
          )}
          <Button onClick={pickFile}>
            <Upload />
            動画を選ぶ
          </Button>
          <Button variant="secondary" onClick={openCamera}>
            <Camera />
            カメラで撮る
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept="video/*"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0]
              e.target.value = ""
              if (file) void analyze(file)
            }}
          />
        </div>
      </header>

      {/* my_axel_advice.mp4 と同じく、左 2/3 に自分の映像、右 1/3 にお手本とアドバイス */}
      <main className="grid min-h-0 flex-1 grid-cols-[minmax(0,2fr)_minmax(380px,1fr)] gap-3 p-3">
        <section
          className="flex min-h-0 flex-col gap-3"
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragOver(false)
            const files = [...e.dataTransfer.files]
            const file = files.find((f) => f.type.startsWith("video/")) ?? files[0]
            if (file) void analyze(file)
          }}
        >
          <VideoStage
            videoRef={videoRef}
            data={data}
            frame={frame}
            activeKf={activeKf}
            settings={settings}
            marks={marks}
            badge={
              <div className="absolute top-3 left-3 flex items-center gap-2 rounded-lg bg-black/65 px-3 py-1.5 text-lg font-bold text-white backdrop-blur">
                {badge}
              </div>
            }
          >
            {!data && status.kind === "idle" && (
              <div
                className={cn(
                  "absolute inset-3 flex flex-col items-center justify-center gap-4 rounded-lg border-2 border-dashed text-center",
                  dragOver ? "border-primary bg-primary/10" : "border-border bg-card",
                )}
              >
                <Upload className="size-10 text-muted-foreground" />
                <div>
                  <p className="text-xl font-bold">自分のジャンプの動画を取り込みます</p>
                  <p className="mt-2 text-muted-foreground">ここに動画をドロップするか、下のボタンを押してください。</p>
                  <p className="text-sm text-muted-foreground">踏切の少し前から着氷の後まで、全身が写っている動画を使ってください。</p>
                </div>
                <div className="flex gap-2">
                  <Button size="lg" onClick={pickFile}>
                    <Upload />
                    動画を選ぶ
                  </Button>
                  <Button size="lg" variant="secondary" onClick={openCamera}>
                    <Camera />
                    カメラで撮る
                  </Button>
                </div>
              </div>
            )}
            {status.kind !== "idle" && (
              <div className="absolute inset-0 grid place-items-center bg-background/80 backdrop-blur-sm">
                <Card className="w-[min(460px,90%)] gap-4 p-6">
                  {status.kind === "progress" ? (
                    <>
                      <p className="text-lg font-bold">{status.title}</p>
                      <Progress value={status.ratio * 100} className="h-2" />
                      <p className="text-sm text-muted-foreground">{status.detail || " "}</p>
                    </>
                  ) : (
                    <>
                      <Alert variant="destructive">
                        <AlertTitle>解析できませんでした</AlertTitle>
                        <AlertDescription>
                          {status.message}
                          踏切の少し前から着氷の後まで、全身が写っている動画でもう一度試してください。
                        </AlertDescription>
                      </Alert>
                      <Button variant="outline" className="self-end" onClick={() => setStatus({ kind: "idle" })}>
                        閉じる
                      </Button>
                    </>
                  )}
                </Card>
              </div>
            )}
          </VideoStage>

          <PlayerControls
            data={data}
            frame={frame}
            playing={playing}
            range={range}
            activeKey={activeKf?.key ?? null}
            speed={speed}
            settings={settings}
            onToggle={() => playerRef.current?.toggle()}
            onStop={() => playerRef.current?.stop()}
            onSpeed={setSpeed}
            onSettings={(s) => {
              setSettings((prev) => ({ ...prev, ...s }))
              // 範囲を切り替えて今の位置が外れたら先頭へ
              if (data && s.fullRange !== undefined) {
                const r = playRange(data, s.fullRange)
                if (frame < r.start || frame > r.end) {
                  playerRef.current!.range = r
                  playerRef.current?.seek(r.start)
                }
              }
            }}
            onSeek={(f) => playerRef.current?.seek(f)}
            onScrubStart={() => {
              const player = playerRef.current
              scrubWasPlaying.current = !!player?.playing
              player?.pause()
            }}
            onScrubEnd={() => {
              if (scrubWasPlaying.current) playerRef.current?.play()
            }}
          />
        </section>

        <aside className="min-h-0">
          <SidePanel data={data} frame={frame} playing={playing} speed={Number(speed)} activeKf={activeKf} />
        </aside>
      </main>

      <SummaryDialog data={data} open={summaryOpen} onOpenChange={setSummaryOpen} />
      <CameraDialog open={cameraOpen} onOpenChange={setCameraOpen} onUse={(file) => void analyze(file)} />
    </div>
  )
}
