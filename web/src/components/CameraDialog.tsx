import { Circle, RotateCcw, Square, Upload } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { cn } from "@/lib/utils"

const RECORDER_TYPES = ["video/mp4;codecs=avc1", "video/mp4", "video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"]

function recorderType(): string {
  return RECORDER_TYPES.find((t) => MediaRecorder.isTypeSupported(t)) ?? ""
}

type Phase = "live" | "recording" | "review"

export function CameraDialog({
  open,
  onOpenChange,
  onUse,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onUse: (file: File) => void
}) {
  const liveRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([])
  const [deviceId, setDeviceId] = useState<string>("")
  const [phase, setPhase] = useState<Phase>("live")
  const [file, setFile] = useState<File | null>(null)
  const [reviewUrl, setReviewUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const stopStream = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
  }

  // ダイアログを開いている間だけカメラを使う（撮った動画を見ている間は止める）
  const reviewing = phase === "review"
  useEffect(() => {
    if (!open || reviewing) return
    let cancelled = false
    const video: MediaTrackConstraints = { width: { ideal: 1920 }, height: { ideal: 1080 }, frameRate: { ideal: 60 } }
    if (deviceId) video.deviceId = { exact: deviceId }
    navigator.mediaDevices
      .getUserMedia({ video, audio: false })
      .then(async (stream) => {
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop())
          return
        }
        stopStream()
        streamRef.current = stream
        if (liveRef.current) liveRef.current.srcObject = stream
        setError(null)
        const list = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput")
        setDevices(list)
        if (!deviceId) setDeviceId(stream.getVideoTracks()[0].getSettings().deviceId ?? "")
      })
      .catch((e: Error) => setError(`カメラを使えませんでした（${e.name}）。ブラウザでカメラの使用を許可してください。`))
    return () => {
      cancelled = true
    }
  }, [open, deviceId, reviewing])

  useEffect(() => {
    if (open) return
    if (recorderRef.current?.state === "recording") {
      recorderRef.current.onstop = null
      recorderRef.current.stop()
    }
    stopStream()
    setPhase("live")
    setFile(null)
  }, [open])

  useEffect(() => () => {
    if (reviewUrl) URL.revokeObjectURL(reviewUrl)
  }, [reviewUrl])

  const startRecording = () => {
    const stream = streamRef.current
    if (!stream) return
    const type = recorderType()
    const chunks: Blob[] = []
    const recorder = new MediaRecorder(stream, type ? { mimeType: type, videoBitsPerSecond: 12_000_000 } : {})
    recorder.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data)
    }
    recorder.onstop = () => {
      const mime = recorder.mimeType || "video/webm"
      const blob = new Blob(chunks, { type: mime })
      const stamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14)
      setFile(new File([blob], `camera_${stamp}.${mime.includes("mp4") ? "mp4" : "webm"}`, { type: mime }))
      setReviewUrl(URL.createObjectURL(blob))
      stopStream()
      setPhase("review")
    }
    recorder.start(250)
    recorderRef.current = recorder
    setPhase("recording")
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>カメラで撮る</DialogTitle>
          <DialogDescription>
            {phase === "review"
              ? "撮った動画を確認して、「この動画で解析」を押してください。"
              : phase === "recording"
                ? "録画しています…"
                : "踏切の少し前から着氷の後まで、全身が写るように撮ってください。"}
          </DialogDescription>
        </DialogHeader>

        {devices.length > 1 && phase === "live" && (
          <Select value={deviceId} onValueChange={setDeviceId}>
            <SelectTrigger className="w-72">
              <SelectValue placeholder="カメラを選ぶ" />
            </SelectTrigger>
            <SelectContent>
              {devices.map((d, i) => (
                <SelectItem key={d.deviceId} value={d.deviceId}>
                  {d.label || `カメラ ${i + 1}`}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        {phase === "review" && reviewUrl ? (
          <video src={reviewUrl} controls playsInline className="aspect-video w-full rounded-lg bg-black" />
        ) : (
          <video
            ref={liveRef}
            muted
            playsInline
            autoPlay
            className={cn("aspect-video w-full rounded-lg bg-black", phase === "recording" && "ring-4 ring-red-500")}
          />
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}

        <DialogFooter>
          {phase === "live" && (
            <Button variant="destructive" onClick={startRecording} disabled={!!error}>
              <Circle className="fill-current" />
              録画開始
            </Button>
          )}
          {phase === "recording" && (
            <Button variant="destructive" onClick={() => recorderRef.current?.stop()}>
              <Square className="fill-current" />
              録画停止
            </Button>
          )}
          {phase === "review" && (
            <>
              <Button variant="outline" onClick={() => setPhase("live")}>
                <RotateCcw />
                撮り直す
              </Button>
              <Button
                onClick={() => {
                  if (file) onUse(file)
                  onOpenChange(false)
                }}
              >
                <Upload />
                この動画で解析
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
