import { Camera, ClipboardList, Pause, Play, QrCode, Scissors, Square, Upload, Video } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { CameraDialog } from "@/components/CameraDialog"
import { PhoneDialog } from "@/components/PhoneDialog"
import { PlayerControls } from "@/components/PlayerControls"
import { SidePanel } from "@/components/SidePanel"
import { SummaryDialog } from "@/components/SummaryDialog"
import { TrimDialog } from "@/components/TrimDialog"
import { VideoStage } from "@/components/VideoStage"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { CIRCLED, playRange } from "@/lib/analysis"
import { getJob, getServerInfo, startAnalysis, uploadVideo, waitJob } from "@/lib/api"
import { canUseInAppCamera, isTouchDevice } from "@/lib/device"
import { Player } from "@/lib/player"
import { cn } from "@/lib/utils"
import type { Element, Job, Result, Settings } from "@/types"

const FALLBACK_ELEMENTS: Element[] = [{ code: "1A", name: "シングルアクセル", available: true }]
const RETRIM_HINT = "踏切の約1秒前から着氷の約1秒後までが入るように、範囲を選び直してみてください。"

type Status =
  | { kind: "idle" }
  | { kind: "progress"; title: string; detail: string; ratio: number }
  | { kind: "error"; message: string; canRetrim: boolean }

const progressOf = (job: Job): Status => ({
  kind: "progress",
  title: job.message,
  detail: job.total ? `${job.done} / ${job.total} フレーム` : "",
  ratio: job.total ? job.done / job.total : 0,
})

export default function App() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const playerRef = useRef<Player | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const captureRef = useRef<HTMLInputElement>(null)
  const scrubWasPlaying = useRef(false)
  const touch = useMemo(() => isTouchDevice(), [])

  const [elements, setElements] = useState<Element[]>(FALLBACK_ELEMENTS)
  const [element, setElement] = useState("1A")
  const [job, setJob] = useState<Job | null>(null) // 取り込んだ動画（範囲を選び直すときに使う）
  const [data, setData] = useState<Result | null>(null)
  const [status, setStatus] = useState<Status>({ kind: "idle" })
  const [frame, setFrame] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [pausedKey, setPausedKey] = useState<string | null>(null)
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
  const [trimOpen, setTrimOpen] = useState(false)
  const [phoneUrls, setPhoneUrls] = useState<string[]>([])
  const [phoneOpen, setPhoneOpen] = useState(false)
  const [dragOver, setDragOver] = useState(false)

  const range = useMemo(() => (data ? playRange(data, settings.fullRange) : { start: 0, end: 0 }), [data, settings.fullRange])
  // 一時停止中で、ちょうどキーフレームの上にいるときはその場面のアドバイスを出す
  // （同じフレームにキーフレームが2つあるときは、選んだ／止まったほうを出す）
  const activeKf =
    data && !playing
      ? (data.keyframes.find((k) => k.key === pausedKey && k.frame === frame) ??
        data.keyframes.find((k) => k.frame === frame) ??
        null)
      : null
  const canRetrim = Boolean(job?.video)

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
        setPausedKey(s.keyframe)
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
      setStatus({ kind: "error", message: "解析結果を読み込めませんでした。", canRetrim: false })
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

  // 1. 送信 → 2. 変換 → 3. 範囲を選ぶ（TrimDialog）
  const importVideo = useCallback(async (file: File) => {
    playerRef.current?.pause()
    setStatus({ kind: "progress", title: "動画を送っています", detail: file.name, ratio: 0 })
    try {
      const id = await uploadVideo(file, (ratio) =>
        setStatus({ kind: "progress", title: "動画を送っています", detail: `${Math.round(ratio * 100)}%`, ratio }),
      )
      // 読み込み直しても、範囲を選ぶところから続けられるようにする
      history.replaceState(null, "", `#job=${id}`)
      const ready = await waitJob(id, ["ready"], (j) => setStatus(progressOf(j)))
      setJob(ready)
      setStatus({ kind: "idle" })
      setTrimOpen(true)
    } catch (e) {
      setStatus({ kind: "error", message: (e as Error).message, canRetrim: false })
    }
  }, [])

  // 4. 選んだ範囲を解析 → 結果を開く
  const analyzeRange = useCallback(
    async (start: number, end: number) => {
      if (!job) return
      setTrimOpen(false)
      playerRef.current?.pause()
      setStatus({ kind: "progress", title: "解析を始めています", detail: "", ratio: 0 })
      try {
        await startAnalysis(job.id, element, start, end)
        const done = await waitJob(job.id, ["done"], (j) => setStatus(progressOf(j)))
        setJob(done)
        await openResult(job.id)
      } catch (e) {
        setStatus({ kind: "error", message: (e as Error).message, canRetrim: true })
      }
    },
    [job, element, openResult],
  )

  useEffect(() => {
    fetch("/api/elements")
      .then((r) => r.json())
      .then(setElements)
      .catch(() => {})
    if (!isTouchDevice()) getServerInfo().then((s) => setPhoneUrls(s.urls))
    // 前回の続きを開く（解析が済んでいれば結果、まだなら範囲を選ぶところから）
    const match = location.hash.match(/job=([0-9a-f]+)/)
    if (match) {
      const id = match[1]
      setStatus({ kind: "progress", title: "前回の続きを開いています", detail: "", ratio: 1 })
      getJob(id)
        .then((j) => {
          setJob(j)
          if (j.stage === "ready" || (j.stage === "error" && j.video && !j.trim)) {
            setStatus({ kind: "idle" })
            setTrimOpen(true)
          } else if (j.stage === "error") {
            setStatus({ kind: "error", message: j.error ?? "解析できませんでした。", canRetrim: Boolean(j.video) })
          } else if (j.stage === "done") {
            void openResult(id)
          } else {
            // 変換中・解析中なら、終わるまで待つ
            const target = j.video ? "done" : "ready"
            waitJob(id, [target], (p) => setStatus(progressOf(p)))
              .then((r) => {
                setJob(r)
                if (target === "done") return openResult(id)
                setStatus({ kind: "idle" })
                setTrimOpen(true)
              })
              .catch((e: Error) => setStatus({ kind: "error", message: e.message, canRetrim: Boolean(j.video) }))
          }
        })
        // 範囲を選ぶ機能より前に作った結果には、ジョブの情報がない
        .catch(() => void openResult(id))
    }
    // 最初の1回だけ
  }, [])

  // スペースキーで再生・一時停止、← → で1フレームずつ
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const player = playerRef.current
      if (!data || !player || cameraOpen || summaryOpen || trimOpen) return
      const target = e.target as HTMLElement
      if (target.closest("input, select, textarea, [role=combobox], [role=switch], [role=tab], [role=slider]")) return
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
  }, [data, cameraOpen, summaryOpen, trimOpen])

  const pickFile = () => fileRef.current?.click()
  // PC はアプリ内のカメラ、スマホ（と HTTPS でない接続）は標準カメラアプリで撮る
  const openCamera = () => {
    playerRef.current?.pause()
    if (canUseInAppCamera()) setCameraOpen(true)
    else captureRef.current?.click()
  }
  const openTrim = () => {
    playerRef.current?.pause()
    setStatus({ kind: "idle" })
    setTrimOpen(true)
  }

  const onFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ""
    if (file) void importVideo(file)
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

  // 画面が狭いとき（スマホ）は、ボタンの文字を隠してアイコンだけにする
  const label = (text: string) => <span className="hidden lg:inline">{text}</span>

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <header className="flex h-12 flex-none items-center gap-2 border-b bg-card/60 px-2 backdrop-blur lg:h-14 lg:gap-6 lg:px-4">
        <div className="flex items-center gap-2">
          <div className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground">
            <Video className="size-4" />
          </div>
          <h1 className="hidden text-lg font-bold tracking-tight whitespace-nowrap md:block">Figure Skating Lab</h1>
        </div>

        <Tabs value={element} onValueChange={setElement}>
          <TabsList>
            {elements.map((e) => (
              <TabsTrigger
                key={e.code}
                value={e.code}
                disabled={!e.available}
                title={e.available ? e.name : `${e.name}（準備中）`}
                className="px-2 font-bold lg:px-4"
              >
                {e.code}
                {!e.available && <span className="hidden text-[10px] font-normal text-muted-foreground sm:inline">準備中</span>}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        <div className="ml-auto flex items-center gap-1.5 lg:gap-2">
          {phoneUrls.length > 0 && (
            <Button variant="ghost" onClick={() => setPhoneOpen(true)} aria-label="スマホで開く">
              <QrCode />
              {label("スマホで開く")}
            </Button>
          )}
          {canRetrim && data && (
            <Button variant="outline" onClick={openTrim} aria-label="範囲を選び直す">
              <Scissors />
              {label("範囲を選び直す")}
            </Button>
          )}
          {data && (
            <Button variant="outline" onClick={() => setSummaryOpen(true)} aria-label="まとめ">
              <ClipboardList />
              {label("まとめ")}
            </Button>
          )}
          <Button onClick={pickFile} aria-label="動画を選ぶ">
            <Upload />
            {label("動画を選ぶ")}
          </Button>
          <Button variant="secondary" onClick={openCamera} aria-label="カメラで撮る">
            <Camera />
            {label("カメラで撮る")}
          </Button>
          <input ref={fileRef} type="file" accept="video/*" hidden onChange={onFileInput} />
          {/* スマホでは標準カメラアプリ（背面カメラ）が開く */}
          <input ref={captureRef} type="file" accept="video/*" capture="environment" hidden onChange={onFileInput} />
        </div>
      </header>

      {/* my_axel_advice.mp4 と同じく、横長の画面では左 2/3 に自分の映像、右 1/3 にお手本とアドバイス。
          縦長の画面（スマホ）では上から 映像 → 操作 → お手本とアドバイス */}
      <main className="grid min-h-0 flex-1 gap-2 p-2 portrait:grid-cols-1 portrait:grid-rows-[auto_minmax(0,1fr)] landscape:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)] lg:gap-3 lg:p-3">
        <section
          className="flex min-h-0 flex-col gap-2 lg:gap-3"
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
            if (file) void importVideo(file)
          }}
        >
          <VideoStage
            videoRef={videoRef}
            data={data}
            frame={frame}
            activeKf={activeKf}
            settings={settings}
            marks={marks}
            className="portrait:h-[36dvh] portrait:flex-none"
            badge={
              <div className="absolute top-2 left-2 flex items-center gap-2 rounded-lg bg-black/65 px-2.5 py-1 text-sm font-bold text-white backdrop-blur lg:top-3 lg:left-3 lg:px-3 lg:py-1.5 lg:text-lg">
                {badge}
              </div>
            }
          >
            {!data && status.kind === "idle" && (
              <div
                className={cn(
                  "absolute inset-2 flex flex-col items-center justify-center gap-3 overflow-y-auto rounded-lg border-2 border-dashed p-4 text-center lg:inset-3 lg:gap-4",
                  dragOver ? "border-primary bg-primary/10" : "border-border bg-card",
                )}
              >
                <Upload className="size-8 text-muted-foreground lg:size-10" />
                <div>
                  <p className="text-lg font-bold lg:text-xl">自分のジャンプの動画を取り込みます</p>
                  <p className="mt-2 text-sm text-muted-foreground lg:text-base">
                    {touch ? "下のボタンを押してください。" : "ここに動画をドロップするか、下のボタンを押してください。"}
                  </p>
                  <p className="text-sm text-muted-foreground">取り込んだあとに、前後の余分なところを切り落とせます。</p>
                </div>
                <div className="flex flex-wrap justify-center gap-2">
                  <Button size="lg" onClick={pickFile}>
                    <Upload />
                    動画を選ぶ
                  </Button>
                  <Button size="lg" variant="secondary" onClick={openCamera}>
                    <Camera />
                    カメラで撮る
                  </Button>
                  {job?.video && (
                    <Button size="lg" variant="outline" onClick={openTrim}>
                      <Scissors />
                      範囲を選んで解析を続ける
                    </Button>
                  )}
                </div>
              </div>
            )}
            {status.kind !== "idle" && (
              <div className="absolute inset-0 grid place-items-center bg-background/80 p-2 backdrop-blur-sm">
                <Card className="w-[min(460px,100%)] gap-4 p-5 lg:p-6">
                  {status.kind === "progress" ? (
                    <>
                      <p className="text-lg font-bold">{status.title}</p>
                      <Progress value={status.ratio * 100} className="h-2" />
                      <p className="truncate text-sm text-muted-foreground">{status.detail || " "}</p>
                    </>
                  ) : (
                    <>
                      <Alert variant="destructive">
                        <AlertTitle>解析できませんでした</AlertTitle>
                        <AlertDescription>
                          {status.message}
                          {status.canRetrim ? RETRIM_HINT : "踏切の少し前から着氷の後まで、全身が写っている動画でもう一度試してください。"}
                        </AlertDescription>
                      </Alert>
                      <div className="flex justify-end gap-2">
                        {status.canRetrim && canRetrim && (
                          <Button onClick={openTrim}>
                            <Scissors />
                            範囲を選び直す
                          </Button>
                        )}
                        <Button variant="outline" onClick={() => setStatus({ kind: "idle" })}>
                          閉じる
                        </Button>
                      </div>
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
            onKeyframe={(key) => playerRef.current?.seekKeyframe(key)}
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
      <CameraDialog open={cameraOpen} onOpenChange={setCameraOpen} onUse={(file) => void importVideo(file)} />
      <TrimDialog
        video={job?.video ?? null}
        initial={job?.trim}
        open={trimOpen}
        onOpenChange={setTrimOpen}
        onConfirm={(start, end) => void analyzeRange(start, end)}
      />
      <PhoneDialog urls={phoneUrls} open={phoneOpen} onOpenChange={setPhoneOpen} />
    </div>
  )
}
