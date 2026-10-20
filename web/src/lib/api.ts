// サーバ（src/app.py）とのやりとり
import type { Job } from "@/types"

// 動画を送る。fetch では送信の進み具合が分からないので XMLHttpRequest を使う
export function uploadVideo(file: File, onProgress: (ratio: number) => void): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open("POST", "/api/upload")
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total)
    }
    xhr.onload = () => {
      let body: { id?: string; error?: string } = {}
      try {
        body = JSON.parse(xhr.responseText)
      } catch {
        // 413（大きすぎる）などは HTML で返る
      }
      if (xhr.status === 200 && body.id) resolve(body.id)
      else if (xhr.status === 413) reject(new Error("動画が大きすぎます。トリミングするか、画質を下げて撮ってください。"))
      else reject(new Error(body.error || "送信できませんでした。"))
    }
    xhr.onerror = () => reject(new Error("サーバに接続できません。PC で src/app.py が動いているか確認してください。"))
    const form = new FormData()
    form.append("video", file, file.name)
    xhr.send(form)
  })
}

export async function getJob(id: string): Promise<Job> {
  const res = await fetch(`/api/jobs/${id}`)
  if (!res.ok) throw new Error("この動画の情報が見つかりません。もう一度取り込んでください。")
  return res.json()
}

export async function startAnalysis(id: string, element: string, start: number, end: number): Promise<void> {
  const res = await fetch(`/api/jobs/${id}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ element, start, end }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.error || "解析を始められませんでした。")
  }
}

// ジョブが stages のどれかになるまで待つ。途中の進み具合は onProgress に知らせる
export async function waitJob(id: string, stages: string[], onProgress: (job: Job) => void): Promise<Job> {
  for (;;) {
    let job: Job
    try {
      job = await getJob(id)
    } catch {
      throw new Error("サーバに接続できません。PC で src/app.py が動いているか確認してください。")
    }
    if (job.stage === "error") throw new Error(job.error ?? "解析できませんでした。")
    if (stages.includes(job.stage)) return job
    onProgress(job)
    await new Promise((resolve) => setTimeout(resolve, 400))
  }
}

export async function getServerInfo(): Promise<{ lan: boolean; urls: string[] }> {
  try {
    return await (await fetch("/api/server")).json()
  } catch {
    return { lan: false, urls: [] }
  }
}
