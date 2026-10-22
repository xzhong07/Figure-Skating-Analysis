import { Box, Settings2 } from "lucide-react"
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react"
import * as THREE from "three"
import { OrbitControls } from "three/addons/controls/OrbitControls.js"

import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Switch } from "@/components/ui/switch"
import { CIRCLED } from "@/lib/analysis"
import { isTouchDevice } from "@/lib/device"
import { cn } from "@/lib/utils"
import type { Keyframe, Pose3D, Result, Settings, SkeletonStyle } from "@/types"

// お手本と自分のキーフレームの骨格を3D空間で重ねて、ドラッグ（スマホは指）で回して見る。
// 骨格は world 座標なので、腰の中心が原点になる（跳んだ高さや滑った距離は表せない）

const L_SHOULDER = 11
const R_SHOULDER = 12
const FOOT_POINTS = [27, 28, 29, 30, 31, 32] // 足首・かかと・つま先（床の高さに使う）
const TARGET = new THREE.Vector3(0, -0.1, 0)
const DISTANCE = 2.6
// 視点の向き（注視点からカメラへの向き）。「カメラ」は自分の動画を撮った向き
const VIEWS = {
  camera: { label: "カメラ", dir: new THREE.Vector3(0, 0, 1) },
  side: { label: "横", dir: new THREE.Vector3(1, 0, 0) },
  top: { label: "上", dir: new THREE.Vector3(0, 1, 0.001) },
} as const
type ViewName = keyof typeof VIEWS

// 骨の太さ（メートル）。2D と同じく、お手本を太く、自分を細くして、重なっても両方見えるようにする
const RADIUS = { ref: 0.022, me: 0.012 }
const JOINT = { ref: 0.032, me: 0.022 }
const HIDDEN_OPACITY = 0.3 // visibility が低い（見えていない）点と骨
const REF_OPACITY = 0.8

// world 座標（y=下、z=奥）を three.js の座標（y=上、z=手前）にする。rotate は鉛直軸まわりの回転（度）。
// 回す向きは src/view_align.py の rotate_about_vertical と同じ
function toVector([x, y, z]: [number, number, number], rotate: number): THREE.Vector3 {
  if (rotate) {
    const t = (rotate * Math.PI) / 180
    ;[x, z] = [x * Math.cos(t) - z * Math.sin(t), x * Math.sin(t) + z * Math.cos(t)]
  }
  return new THREE.Vector3(x, -y, -z)
}

type Points = (THREE.Vector3 | null)[]

function toPoints(pose: Pose3D, rotate: number): Points {
  return pose ? pose.p.map((p) => (p ? toVector(p, rotate) : null)) : []
}

const UNIT_CYLINDER = new THREE.CylinderGeometry(1, 1, 1, 12)
const UNIT_SPHERE = new THREE.SphereGeometry(1, 16, 12)
const UP = new THREE.Vector3(0, 1, 0)

function addSkeleton(
  group: THREE.Group,
  data: Result,
  points: Points,
  visible: number[],
  style: SkeletonStyle,
  who: "me" | "ref",
) {
  const sk = data.skeleton
  const materials = new Map<string, THREE.Material>()
  const material = (color: string, shown: boolean) => {
    const key = `${color}${shown}`
    let m = materials.get(key)
    if (!m) {
      const opacity = (shown ? 1 : HIDDEN_OPACITY) * (who === "ref" ? REF_OPACITY : 1)
      m = new THREE.MeshLambertMaterial({ color, transparent: opacity < 1, opacity, depthWrite: opacity === 1 })
      materials.set(key, m)
    }
    return m
  }
  const bone = (a: THREE.Vector3, b: THREE.Vector3, color: string, shown: boolean) => {
    const length = a.distanceTo(b)
    if (length < 1e-4) return
    const mesh = new THREE.Mesh(UNIT_CYLINDER, material(color, shown))
    mesh.position.copy(a).add(b).multiplyScalar(0.5)
    mesh.quaternion.setFromUnitVectors(UP, b.clone().sub(a).normalize())
    mesh.scale.set(RADIUS[who], length, RADIUS[who])
    group.add(mesh)
  }
  const joint = (i: number, color: string) => {
    const p = points[i]
    if (!p) return
    const mesh = new THREE.Mesh(UNIT_SPHERE, material(color, Boolean(visible[i])))
    mesh.position.copy(p)
    mesh.scale.setScalar(JOINT[who])
    group.add(mesh)
  }

  const used = new Set<number>([sk.nose])
  const groups: [[number, number][], string][] = [
    [sk.left_bones, style.left],
    [sk.right_bones, style.right],
    [sk.center_bones, style.center],
  ]
  for (const [bones, color] of groups) {
    for (const [i, j] of bones) {
      const a = points[i]
      const b = points[j]
      if (!a || !b) continue
      bone(a, b, color, Boolean(visible[i] && visible[j]))
      used.add(i).add(j)
    }
  }
  // 首（肩の中点〜鼻）は 2D の表示と同じく1本の線で描く
  const ls = points[L_SHOULDER]
  const rs = points[R_SHOULDER]
  const nose = points[sk.nose]
  if (ls && rs && nose) {
    bone(ls.clone().add(rs).multiplyScalar(0.5), nose, style.center, Boolean(visible[L_SHOULDER] && visible[R_SHOULDER] && visible[sk.nose]))
  }
  for (const i of used) {
    joint(i, sk.left_points.includes(i) ? style.left : sk.right_points.includes(i) ? style.right : style.center)
  }
}

function disposeGroup(group: THREE.Group) {
  const materials = new Set<THREE.Material>()
  group.traverse((o) => {
    if (o instanceof THREE.Mesh) materials.add(o.material as THREE.Material)
    if (o instanceof THREE.GridHelper) {
      o.geometry.dispose()
      materials.add(o.material as THREE.Material)
    }
  })
  materials.forEach((m) => m.dispose())
  group.clear()
}

interface Scene3D {
  renderer: THREE.WebGLRenderer
  scene: THREE.Scene
  camera: THREE.PerspectiveCamera
  controls: OrbitControls
  skeletons: THREE.Group
  render: () => void
}

function Toggle({ id, label, checked, onChange }: { id: string; label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center gap-2">
      <Switch id={id} checked={checked} onCheckedChange={onChange} />
      <Label htmlFor={id} className="cursor-pointer whitespace-nowrap">
        {label}
      </Label>
    </div>
  )
}

export function SkeletonStage3D({
  data,
  activeKf,
  settings,
  onSettings,
  onKeyframe,
  className,
  children,
}: {
  data: Result
  activeKf: Keyframe | null
  settings: Settings
  onSettings: (settings: Partial<Settings>) => void
  onKeyframe: (key: string) => void
  className?: string
  children?: ReactNode
}) {
  const boxRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const sceneRef = useRef<Scene3D | null>(null)
  const [failed, setFailed] = useState(false)
  // オンにすると、お手本を自分と同じ体の向きに回し、姿勢の形だけを比べる
  const [alignYaw, setAlignYaw] = useState(false)

  const setView = (name: ViewName) => {
    const s = sceneRef.current
    if (!s) return
    s.controls.target.copy(TARGET)
    s.camera.position.copy(TARGET).addScaledVector(VIEWS[name].dir.clone().normalize(), DISTANCE)
    s.controls.update()
    s.render()
  }

  // three.js の準備（1回だけ）。描くのは視点や骨格が変わったときだけ
  useLayoutEffect(() => {
    const box = boxRef.current
    const canvas = canvasRef.current
    if (!box || !canvas) return
    let renderer: THREE.WebGLRenderer
    try {
      renderer = new THREE.WebGLRenderer({ canvas, antialias: true })
    } catch {
      setFailed(true)
      return
    }
    renderer.setClearColor(0x0a0a0a)
    const scene = new THREE.Scene()
    scene.add(new THREE.HemisphereLight(0xffffff, 0x404040, 2.2))
    const light = new THREE.DirectionalLight(0xffffff, 1.2)
    light.position.set(2, 4, 3)
    scene.add(light)
    const skeletons = new THREE.Group()
    scene.add(skeletons)
    const camera = new THREE.PerspectiveCamera(40, 1, 0.05, 50)
    const controls = new OrbitControls(camera, canvas)
    controls.minDistance = 1
    controls.maxDistance = 8
    const render = () => renderer.render(scene, camera)
    controls.addEventListener("change", render)
    sceneRef.current = { renderer, scene, camera, controls, skeletons, render }
    setView("camera")

    const resize = () => {
      // スマホの高い画素密度では描画が重くなるので 2 倍までにする
      renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1))
      renderer.setSize(box.clientWidth, box.clientHeight, false)
      camera.aspect = box.clientWidth / Math.max(1, box.clientHeight)
      camera.updateProjectionMatrix()
      render()
    }
    resize()
    const observer = new ResizeObserver(resize)
    observer.observe(box)
    return () => {
      observer.disconnect()
      controls.dispose()
      disposeGroup(skeletons)
      renderer.dispose()
      sceneRef.current = null
    }
    // 最初の1回だけ
  }, [])

  const world = activeKf?.world
  useEffect(() => {
    const s = sceneRef.current
    if (!s) return
    disposeGroup(s.skeletons)
    if (world) {
      const me = toPoints(world.me, 0)
      const ref = toPoints(world.ref, alignYaw ? world.me_yaw - world.ref_yaw : 0)
      // 床は2人の足のうち低いほうの高さに置く
      const feet = [me, ref].flatMap((pts) => FOOT_POINTS.map((i) => pts[i]?.y ?? Infinity))
      const floor = Math.min(...feet)
      const grid = new THREE.GridHelper(4, 16, 0x555555, 0x2a2a2a)
      grid.position.y = Number.isFinite(floor) ? floor : -0.9
      s.skeletons.add(grid)
      if (settings.showRef && world.ref) addSkeleton(s.skeletons, data, ref, world.ref.v, data.skeleton.model, "ref")
      if (settings.showSelf && world.me) addSkeleton(s.skeletons, data, me, world.me.v, data.skeleton.self, "me")
    }
    s.render()
  }, [data, world, alignYaw, settings.showRef, settings.showSelf])

  const legend = (style: SkeletonStyle, text: string) => (
    <span className="flex items-center gap-1.5">
      <span className="h-1 w-5 rounded-full" style={{ background: `linear-gradient(90deg, ${style.left} 50%, ${style.right} 50%)` }} />
      {text}
    </span>
  )

  return (
    <>
      <div ref={boxRef} className={cn("relative min-h-0 flex-1 overflow-hidden rounded-xl bg-black ring-1 ring-border", className)}>
        <canvas ref={canvasRef} className="absolute inset-0 size-full cursor-grab touch-none active:cursor-grabbing" />
        <div className="pointer-events-none absolute top-2 left-2 flex flex-col items-start gap-1.5 lg:top-3 lg:left-3">
          <div className="flex items-center gap-2 rounded-lg bg-black/65 px-2.5 py-1 text-sm font-bold text-white backdrop-blur lg:px-3 lg:py-1.5 lg:text-lg">
            <Box className="size-4" />
            {activeKf ? `3D　${CIRCLED[activeKf.no - 1]} ${activeKf.name}` : "3D"}
          </div>
          <div className="flex gap-3 rounded-md bg-black/55 px-2 py-0.5 text-xs text-white/90">
            {legend(data.skeleton.model, "お手本")}
            {legend(data.skeleton.self, "自分")}
          </div>
        </div>
        {(failed || (activeKf && !world)) && (
          <div className="absolute inset-0 grid place-items-center p-4 text-center text-sm text-white/80">
            {failed
              ? "この端末では3D表示を使えません（WebGL に対応していません）。"
              : "この解析結果には3Dの骨格がありません。「範囲を選び直す」から解析し直すと表示できます。"}
          </div>
        )}
        <p className="pointer-events-none absolute bottom-1.5 left-2 text-[11px] text-white/55 lg:bottom-2 lg:left-3 lg:text-xs">
          {isTouchDevice() ? "1本指で回転・2本指で拡大と移動" : "ドラッグで回転・ホイールで拡大・右ドラッグで移動"}
        </p>
        {children}
      </div>

      <Card className="flex-none gap-2 px-2 py-2 lg:px-3 lg:py-2.5">
        <div className="flex justify-between gap-1 sm:justify-start sm:gap-2">
          {data.keyframes.map((kf) => (
            <button
              key={kf.key}
              type="button"
              aria-label={`${CIRCLED[kf.no - 1]} ${kf.name}`}
              title={`${CIRCLED[kf.no - 1]} ${kf.name}`}
              className={cn(
                "grid size-9 place-items-center rounded-full border-2 border-white text-sm font-bold text-neutral-950 shadow-md transition-transform hover:scale-110",
                kf.problems ? "bg-orange-400" : "bg-emerald-400",
                kf.key === activeKf?.key && "scale-110 ring-4 ring-white/40",
              )}
              onClick={() => onKeyframe(kf.key)}
            >
              {kf.no}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-2">
          <span className="text-sm text-muted-foreground">視点</span>
          {(Object.keys(VIEWS) as ViewName[]).map((name) => (
            <Button key={name} variant="outline" size="sm" className="pointer-coarse:h-9" onClick={() => setView(name)}>
              {VIEWS[name].label}
            </Button>
          ))}
          <div className="ml-auto">
            <Popover>
              <PopoverTrigger asChild>
                <Button variant="outline" size="sm" className="pointer-coarse:h-9">
                  <Settings2 />
                  表示
                </Button>
              </PopoverTrigger>
              <PopoverContent align="end" className="flex w-64 flex-col gap-3">
                <Toggle id="show-ref-3d" label="お手本の骨格" checked={settings.showRef} onChange={(v) => onSettings({ showRef: v })} />
                <Toggle id="show-self-3d" label="自分の骨格" checked={settings.showSelf} onChange={(v) => onSettings({ showSelf: v })} />
                <Toggle id="align-yaw" label="体の向きをそろえる" checked={alignYaw} onChange={setAlignYaw} />
                <p className="text-xs leading-relaxed text-muted-foreground">
                  オフでは撮影角度の差だけを補正するので、回転の遅れも見えます。オンにすると姿勢の形だけを比べられます。
                  腰の位置を重ねているため、跳んだ高さは表せません。奥行きは推定なので、手足が重なる場面ではずれることがあります。
                </p>
              </PopoverContent>
            </Popover>
          </div>
        </div>
      </Card>
    </>
  )
}
