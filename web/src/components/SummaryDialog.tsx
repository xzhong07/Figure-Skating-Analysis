import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { CIRCLED } from "@/lib/analysis"
import type { Result } from "@/types"

// まとめ（my_axel_advice.mp4 の最後の画面と同じ内容）
export function SummaryDialog({
  data,
  open,
  onOpenChange,
}: {
  data: Result | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  if (!data) return null
  const s = data.summary
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle className="text-2xl">まとめ</DialogTitle>
          <DialogDescription>ジャンプ全体の比較と、特に直したいポイントです。</DialogDescription>
        </DialogHeader>
        <div className="grid gap-8 md:grid-cols-[1fr_1.1fr]">
          <Table className="text-base">
            <TableHeader>
              <TableRow>
                <TableHead>項目</TableHead>
                <TableHead>自分</TableHead>
                <TableHead className="text-green-400">お手本</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {s.metrics.map((m) => (
                <TableRow key={m.label}>
                  <TableCell className="whitespace-normal">{m.label}</TableCell>
                  <TableCell>{m.me ?? "—"}</TableCell>
                  <TableCell className="text-green-200">{m.ref ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <div>
            <h3 className="mb-3 text-lg font-bold">特に直したいポイント</h3>
            {s.problems.length ? (
              <ul className="flex flex-col gap-4">
                {s.problems.map((p, n) => (
                  <li key={n} className="flex gap-3 leading-relaxed">
                    <span
                      className="grid size-8 flex-none place-items-center rounded-full font-bold text-neutral-950"
                      style={{ background: p.color }}
                    >
                      {n + 1}
                    </span>
                    <span>
                      <span className="text-sm text-muted-foreground">
                        {CIRCLED[p.no - 1]} {p.name}
                      </span>
                      <br />
                      {p.text}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p>大きな差は見つかりませんでした。</p>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
