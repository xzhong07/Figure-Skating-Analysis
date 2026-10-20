import { useSyncExternalStore } from "react"

// スマホ（タッチ操作）かどうか
export const isTouchDevice = (): boolean => window.matchMedia("(pointer: coarse)").matches

// アプリ内のカメラ（getUserMedia）を使えるか。スマホのブラウザは HTTPS でないと使えないので、
// スマホでは標準カメラアプリを使う
export const canUseInAppCamera = (): boolean =>
  !isTouchDevice() && window.isSecureContext && Boolean(navigator.mediaDevices?.getUserMedia) && "MediaRecorder" in window

// 小さな画面（スマホの縦・横）かどうか。画面の向きを変えたら切り替わる
const SMALL_QUERY = "(max-width: 640px), (max-height: 600px)"

export function useSmallScreen(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mq = window.matchMedia(SMALL_QUERY)
      mq.addEventListener("change", onChange)
      return () => mq.removeEventListener("change", onChange)
    },
    () => window.matchMedia(SMALL_QUERY).matches,
  )
}
