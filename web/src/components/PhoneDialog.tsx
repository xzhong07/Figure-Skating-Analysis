import QRCode from "qrcode"
import { useEffect, useState } from "react"

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"

// PC の画面に、スマホで開くための URL を QR コードで出す（src/app.py を --lan で起動したとき）
export function PhoneDialog({ urls, open, onOpenChange }: { urls: string[]; open: boolean; onOpenChange: (open: boolean) => void }) {
  const [codes, setCodes] = useState<Record<string, string>>({})

  useEffect(() => {
    if (!open) return
    let cancelled = false
    Promise.all(urls.map((u) => QRCode.toDataURL(u, { margin: 1, width: 220 }))).then((images) => {
      if (!cancelled) setCodes(Object.fromEntries(urls.map((u, i) => [u, images[i]])))
    })
    return () => {
      cancelled = true
    }
  }, [open, urls])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>スマホで開く</DialogTitle>
          <DialogDescription>
            スマホをこの PC と同じネットワーク（Wi-Fi、PC のモバイルホットスポット、スマホのテザリング）につないで、カメラで QR コードを読み取ってください。
            開けないときは、別の QR コードを試してください。
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-wrap justify-center gap-6">
          {urls.map((u) => (
            <figure key={u} className="flex flex-col items-center gap-2">
              {codes[u] ? <img src={codes[u]} alt={u} className="size-44 rounded-md bg-white" /> : <div className="size-44" />}
              <figcaption className="font-mono text-xs text-muted-foreground">{u}</figcaption>
            </figure>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
