import { memo, useState, useRef, useEffect, useMemo, useCallback } from 'react'
import dagre from '@dagrejs/dagre'
import { useWorkflow } from '../context/workflow-context'
import { Seed, Branch, Iteration } from '../api/client'
import { EMPTY_ITERS, useCanvasStore, type Selection } from './canvas-store'

// ---------------------------------------------------------------------------
// BranchNode — selection-UNAWARE. Renders static SVG with data attributes.
// Highlighting is applied via CSS classes toggled by CanvasSVG, not props.
// ---------------------------------------------------------------------------

interface MetricRange { min: number; max: number }

interface BranchNodeProps {
  seed: Seed
  branch: Branch
  branchIters: Iteration[]
  layout: Record<string, { x: number; y: number }>
  mainMetricKey: string | undefined
  metricRange: MetricRange | undefined
  onSelectBranch: (seedId: number, branchId: number) => void
  onSelectIteration: (seedId: number, branchId: number, iterationId: number) => void
  onShiftClickIteration: (e: React.MouseEvent, seedId: number, branchId: number, iterationId: number) => void
  onDoubleClickNode: (branchId: number, hash: string) => void
  onContextMenu: (x: number, y: number, branchId: number) => void
}

const BranchNode = memo(function BranchNode({
  seed, branch, branchIters, layout, mainMetricKey, metricRange,
  onSelectBranch, onSelectIteration, onShiftClickIteration,
  onDoubleClickNode, onContextMenu,
}: BranchNodeProps) {
  const bp = layout[`branch:${branch.id}`]
  if (!bp) return null
  const branchX = bp.x
  const branchY = bp.y

  const isFork = !!(branch.parent_branch_id && branch.parent_iteration_hash)
  let originPos: { x: number; y: number }
  if (isFork) {
    const iterKey = `iter:${branch.parent_branch_id}:${branch.parent_iteration_hash}`
    originPos = layout[iterKey] ?? layout[`seed:${seed.id}`] ?? { x: branchX, y: branchY - 60 }
  } else {
    originPos = layout[`seed:${seed.id}`] ?? { x: branchX, y: branchY - 60 }
  }

  const selectBranch = () => onSelectBranch(seed.id, branch.id)
  const dblClickBranch = () => onDoubleClickNode(branch.id, branch.commit)

  const connectorEndY = branchY - 38
  const elbowPath = isFork
    ? `M ${originPos.x} ${originPos.y} H ${branchX} V ${connectorEndY}`
    : `M ${originPos.x} ${originPos.y} L ${branchX} ${connectorEndY}`

  return (
    <g data-branch-id={branch.id}>
      {/* Connector line */}
      <path d={elbowPath}
        stroke="transparent" strokeWidth={20} fill="none" className="cursor-pointer"
        onClick={selectBranch} />
      <path d={elbowPath} data-role="connector"
        stroke="#484f58" strokeWidth={2.5}
        fill="none" className="pointer-events-none"
        strokeDasharray={isFork ? '6 4' : undefined} />
      {/* Branch label */}
      <rect data-role="label-bg" x={branchX - 75} y={branchY - 32} width={150} height={26}
        fill="#1c2333" stroke="#3d444d" strokeWidth={1.5} rx={5}
        className="cursor-pointer"
        onClick={selectBranch} onDoubleClick={dblClickBranch} />
      <text data-role="label" x={branchX} y={branchY - 15} fill="#c9d1d9"
        fontSize="13" className="select-none font-mono cursor-pointer" textAnchor="middle"
        onClick={selectBranch} onDoubleClick={dblClickBranch}>
        {branch.name}
      </text>
      {/* Branch dot */}
      <circle data-role="dot" cx={branchX} cy={branchY} r={7}
        fill="#3d444d" stroke="#6e7681" strokeWidth={2}
        className="cursor-pointer"
        onClick={selectBranch} onDoubleClick={dblClickBranch} />

      {/* Iterations */}
      {branchIters.map((iter, i) => {
        const iterPos = layout[`iter:${branch.id}:${iter.hash}`]
        if (!iterPos) return null
        const iterX = iterPos.x
        const iterY = iterPos.y
        const prevPos = i === 0 ? { x: branchX, y: branchY } : layout[`iter:${branch.id}:${branchIters[i - 1].hash}`]
        if (!prevPos) return null

        const onClick = (e: React.MouseEvent) => {
          if (e.shiftKey) {
            onShiftClickIteration(e, seed.id, branch.id, iter.id)
          } else {
            onSelectIteration(seed.id, branch.id, iter.id)
          }
        }
        const onDblClick = () => onDoubleClickNode(branch.id, iter.hash)

        // Metric coloring (data-driven, not selection-driven)
        let metricColor: string | null = null
        if (mainMetricKey && metricRange) {
          const metricVal = iter.metrics.find(m => m.key === mainMetricKey)?.value
          if (metricVal !== undefined) {
            const { min, max } = metricRange
            const t = max > min ? (metricVal - min) / (max - min) : 0.5
            const r = Math.round(t < 0.5 ? 255 : 255 * (1 - (t - 0.5) * 2))
            const g = Math.round(t < 0.5 ? 255 * t * 2 : 255)
            metricColor = `rgb(${r},${g},60)`
          }
        }
        const baseFill = metricColor ? metricColor + '33' : iter.comments.length > 0 ? '#2d1f00' : '#1c2333'
        const baseStroke = metricColor ?? (iter.comments.length > 0 ? '#f0883e' : '#8b949e')
        const baseText = metricColor ?? (iter.comments.length > 0 ? '#f0883e' : '#8b949e')

        return (
          <g key={iter.id} data-iter-id={iter.id}>
            <line x1={prevPos.x} y1={prevPos.y} x2={iterX} y2={iterY}
              stroke="#484f58" strokeWidth={1.5} strokeDasharray="4 3" className="pointer-events-none" />
            <circle data-role="iter-dot" cx={iterX} cy={iterY} r={6}
              fill={baseFill} stroke={baseStroke} strokeWidth={2}
              className="cursor-pointer" onClick={onClick} onDoubleClick={onDblClick}
              onContextMenu={e => { e.preventDefault(); onContextMenu(e.clientX, e.clientY, branch.id) }} />
            <text data-role="iter-label" x={iterX + 14} y={iterY + 5} fill={baseText}
              fontSize="12" className="select-none font-mono cursor-pointer" onClick={onClick} onDoubleClick={onDblClick}
              onContextMenu={e => { e.preventDefault(); onContextMenu(e.clientX, e.clientY, branch.id) }}>
              {iter.name !== iter.hash ? iter.name : iter.hash.slice(0, 8)}
            </text>
            {iter.metrics.slice(0, 2).map((m, mi) => (
              <text key={m.id} x={iterX + 14} y={iterY + 19 + mi * 14} fill="#6e7681"
                fontSize="11" className="select-none font-mono pointer-events-none">
                {m.key}: {m.value}
              </text>
            ))}
          </g>
        )
      })}
    </g>
  )
})

// ---------------------------------------------------------------------------
// CSS-based selection highlight styles (injected once)
// ---------------------------------------------------------------------------
const HIGHLIGHT_STYLE_ID = 'canvas-selection-styles'
function ensureHighlightStyles() {
  if (document.getElementById(HIGHLIGHT_STYLE_ID)) return
  const style = document.createElement('style')
  style.id = HIGHLIGHT_STYLE_ID
  style.textContent = `
    /* Branch selected */
    [data-branch-id].node-selected > [data-role="connector"] { stroke: #58a6ff; stroke-width: 3.5; }
    [data-branch-id].node-selected > [data-role="label-bg"] { stroke: #58a6ff; stroke-width: 2; }
    [data-branch-id].node-selected > [data-role="label"] { fill: #79c0ff; }
    [data-branch-id].node-selected > [data-role="dot"] { fill: #58a6ff; stroke: #58a6ff; r: 9; }
    /* Iteration selected */
    [data-iter-id].iter-selected > [data-role="iter-dot"] { fill: #388bfd; stroke: #58a6ff; r: 8; }
    [data-iter-id].iter-selected > [data-role="iter-label"] { fill: #58a6ff; }
  `
  document.head.appendChild(style)
}

// ---------------------------------------------------------------------------
// CanvasSVG — the main SVG graph area
// ---------------------------------------------------------------------------

export function CanvasSVG() {
  const { seeds, branches, iterations } = useWorkflow()

  // Only subscribe to action functions (stable references) — NOT selection
  const setSelection = useCanvasStore(s => s.setSelection)
  const shiftClickIteration = useCanvasStore(s => s.shiftClickIteration)
  const openFileBrowser = useCanvasStore(s => s.openFileBrowser)
  const setContextMenu = useCanvasStore(s => s.setContextMenu)
  const setPan = useCanvasStore(s => s.setPan)
  const setZoom = useCanvasStore(s => s.setZoom)
  const setLightbox = useCanvasStore(s => s.setLightbox)
  const mainMetric = useCanvasStore(s => s.mainMetric)

  // Read pan/zoom/focus from active pane for initial render & pane switching
  const activePane = useCanvasStore(s => s.getActivePane())
  const pan = activePane.pan
  const zoom = activePane.zoom

  // DOM refs
  const canvasRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const svgGroupRef = useRef<SVGGElement>(null)
  const isPanningRef = useRef(false)
  const lastMouseRef = useRef({ x: 0, y: 0 })
  const panRef = useRef(pan)
  const zoomRef = useRef(zoom)
  const activePaneIdRef = useRef(activePane.id)

  // Sync refs when switching panes
  if (activePane.id !== activePaneIdRef.current) {
    activePaneIdRef.current = activePane.id
    panRef.current = pan
    zoomRef.current = zoom
  }

  // Refs for arrow key navigation
  const iterationsRef = useRef(iterations)
  iterationsRef.current = iterations
  const branchesRef = useRef(branches)
  branchesRef.current = branches
  const layoutRef = useRef<Record<string, { x: number; y: number }>>({})

  // Inject CSS once
  useEffect(() => { ensureHighlightStyles() }, [])

  // ---------------------------------------------------------------------------
  // Selection highlighting via direct DOM class toggling — zero React re-renders
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return

    let prevSelection: Selection = null
    let prevMultiIds: Set<number> = new Set()

    // Apply initial state
    const initState = useCanvasStore.getState()
    prevSelection = initState.getSelection()
    prevMultiIds = initState.selectedIterationIds
    applySelectionHighlight(svg, prevSelection, prevMultiIds)

    // Subscribe to full store, compare relevant slices manually
    const unsub = useCanvasStore.subscribe((state) => {
      const sel = state.getSelection()
      const multiIds = state.selectedIterationIds
      if (sel === prevSelection && multiIds === prevMultiIds) return
      prevSelection = sel
      prevMultiIds = multiIds
      applySelectionHighlight(svg, sel, multiIds)
    })

    return unsub
  }, [])

  // ---------------------------------------------------------------------------
  // applyTransform — mutates SVG group directly
  // ---------------------------------------------------------------------------
  const applyTransform = useCallback(() => {
    const g = svgGroupRef.current
    if (!g) return
    const { x, y } = panRef.current
    g.setAttribute('transform', `translate(${x}, ${y}) scale(${zoomRef.current})`)
  }, [])

  // Apply transform on mount and pane switch
  useEffect(() => { applyTransform() }, [activePane.id, applyTransform])

  // ---------------------------------------------------------------------------
  // Viewport size tracking
  // ---------------------------------------------------------------------------
  const [viewportSize, setViewportSize] = useState({ w: 2000, h: 1200 })
  useEffect(() => {
    const el = canvasRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      setViewportSize(prev => prev.w === Math.round(width) && prev.h === Math.round(height) ? prev : { w: Math.round(width), h: Math.round(height) })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // ---------------------------------------------------------------------------
  // Viewport culling — only re-render when the set of visible branch IDs changes,
  // not on every pan/zoom sync to React state.
  // ---------------------------------------------------------------------------
  const computeVisibleBranches = useCallback((l: Record<string, { x: number; y: number }>) => {
    const p = panRef.current
    const z = zoomRef.current
    const margin = 300
    const vLeft = (-p.x / z) - margin
    const vTop = (-p.y / z) - margin
    const vRight = ((viewportSize.w - p.x) / z) + margin
    const vBottom = ((viewportSize.h - p.y) / z) + margin

    const result: Set<number> = new Set()
    for (const [key, pos] of Object.entries(l)) {
      if (!key.startsWith('branch:') && !key.startsWith('iter:')) continue
      if (pos.x >= vLeft && pos.x <= vRight && pos.y >= vTop && pos.y <= vBottom) {
        if (key.startsWith('branch:')) {
          result.add(Number(key.slice(7)))
        } else {
          const branchId = Number(key.slice(5).split(':')[0])
          result.add(branchId)
        }
      }
    }
    return result
  }, [viewportSize])

  const [visibleBranches, setVisibleBranches] = useState<Set<number>>(() => computeVisibleBranches(layoutRef.current))
  const visibleBranchesRef = useRef(visibleBranches)

  const syncVisibleBranches = useCallback(() => {
    const next = computeVisibleBranches(layoutRef.current)
    const prev = visibleBranchesRef.current
    if (next.size !== prev.size || [...next].some(id => !prev.has(id))) {
      visibleBranchesRef.current = next
      setVisibleBranches(next)
    }
  }, [computeVisibleBranches])


  // ---------------------------------------------------------------------------
  // Mouse pan handlers — native events to bypass React's synthetic event overhead
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const el = canvasRef.current
    if (!el) return

    const onDown = (e: MouseEvent) => {
      if (e.target === el || (e.target as HTMLElement).closest('.canvas-bg')) {
        isPanningRef.current = true
        lastMouseRef.current = { x: e.clientX, y: e.clientY }
      }
    }
    const onMove = (e: MouseEvent) => {
      if (!isPanningRef.current) return
      const last = lastMouseRef.current
      const p = panRef.current
      panRef.current = { x: p.x + e.clientX - last.x, y: p.y + e.clientY - last.y }
      lastMouseRef.current = { x: e.clientX, y: e.clientY }
      applyTransform()
      syncVisibleBranches()
    }
    const onUp = () => {
      if (!isPanningRef.current) return
      isPanningRef.current = false
      setPan(panRef.current)
      syncVisibleBranches()
    }

    el.addEventListener('mousedown', onDown)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      el.removeEventListener('mousedown', onDown)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [applyTransform, setPan, syncVisibleBranches])

  // ---------------------------------------------------------------------------
  // Cmd+scroll zoom
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const el = canvasRef.current
    if (!el) return
    let syncTimer: ReturnType<typeof setTimeout> | null = null
    let targetZoom = zoomRef.current
    let animId: number | null = null

    const animate = () => {
      animId = null
      const cur = zoomRef.current
      const diff = targetZoom - cur
      if (Math.abs(diff) < 0.001) {
        zoomRef.current = targetZoom
      } else {
        zoomRef.current = cur + diff * 0.3
        animId = requestAnimationFrame(animate)
      }
      // Recompute pan to keep the mouse anchor point stable
      const mx = lastAnchor.mx
      const my = lastAnchor.my
      const oldZoom = lastAnchor.prevZoom
      const newZoom = zoomRef.current
      panRef.current = {
        x: mx - (mx - lastAnchor.basePan.x) * (newZoom / oldZoom),
        y: my - (my - lastAnchor.basePan.y) * (newZoom / oldZoom),
      }
      applyTransform()
      syncVisibleBranches()
    }

    const lastAnchor = { mx: 0, my: 0, prevZoom: 1, basePan: { x: 0, y: 0 } }

    const handler = (e: WheelEvent) => {
      if (!e.metaKey && !e.ctrlKey) return
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      // Capture anchor on first scroll or when target matches current (fresh gesture)
      if (animId === null) {
        lastAnchor.mx = e.clientX - rect.left
        lastAnchor.my = e.clientY - rect.top
        lastAnchor.prevZoom = zoomRef.current
        lastAnchor.basePan = { ...panRef.current }
      }
      const factor = e.deltaY > 0 ? 0.94 : 1.06
      targetZoom = Math.min(Math.max(targetZoom * factor, 0.1), 5)
      if (animId === null) {
        animId = requestAnimationFrame(animate)
      }
      if (syncTimer) clearTimeout(syncTimer)
      syncTimer = setTimeout(() => {
        setPan(panRef.current)
        setZoom(zoomRef.current)
        syncVisibleBranches()
      }, 250)
    }
    el.addEventListener('wheel', handler, { passive: false })
    return () => {
      el.removeEventListener('wheel', handler)
      if (syncTimer) clearTimeout(syncTimer)
      if (animId !== null) cancelAnimationFrame(animId)
    }
  }, [applyTransform, setPan, setZoom, syncVisibleBranches])

  // ---------------------------------------------------------------------------
  // Arrow key navigation (uses refs to avoid re-registering)
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const el = document.activeElement
      const tag = (el?.tagName ?? '').toLowerCase()
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return
      if (el instanceof HTMLElement && el.isContentEditable) return
      const sel = useCanvasStore.getState().getSelection()
      if (!sel || sel.type === 'seed') return

      if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        const branchIters = iterationsRef.current[sel.branchId] ?? []
        if (branchIters.length === 0) return
        e.preventDefault()
        const currentIdx = sel.type === 'iteration'
          ? branchIters.findIndex(it => it.id === sel.iterationId)
          : -1
        const nextIdx = e.key === 'ArrowDown'
          ? Math.min(currentIdx + 1, branchIters.length - 1)
          : currentIdx - 1
        if (nextIdx < 0) {
          setSelection({ type: 'branch', seedId: sel.seedId, branchId: sel.branchId })
          return
        }
        if (nextIdx === currentIdx && sel.type === 'iteration') return
        setSelection({ type: 'iteration', seedId: sel.seedId, branchId: sel.branchId, iterationId: branchIters[nextIdx].id })
        return
      }

      if (e.key === ' ') {
        if (sel.type !== 'iteration') return
        const branchIters = iterationsRef.current[sel.branchId] ?? []
        const iter = branchIters.find(it => it.id === sel.iterationId)
        if (!iter) return
        const imageVisuals = iter.visuals.filter(v => v.format !== 'html')
        if (imageVisuals.length === 0) return
        e.preventDefault()
        setLightbox({ iterationId: iter.id, index: 0 })
        return
      }

      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        const layout = layoutRef.current
        const sorted = Object.values(branchesRef.current).flat()
          .filter(b => layout[`branch:${b.id}`])
          .sort((a, b) => {
            const dx = layout[`branch:${a.id}`].x - layout[`branch:${b.id}`].x
            return dx !== 0 ? dx : layout[`branch:${a.id}`].y - layout[`branch:${b.id}`].y
          })
        const idx = sorted.findIndex(b => b.id === sel.branchId)
        if (idx === -1) return
        e.preventDefault()
        const target = sorted[e.key === 'ArrowRight' ? idx + 1 : idx - 1]
        if (!target) return
        const curY = sel.type === 'iteration'
          ? (layout[`iter:${sel.branchId}:${iterationsRef.current[sel.branchId]?.find(i => i.id === sel.iterationId)?.hash}`]?.y ?? layout[`branch:${sel.branchId}`]!.y)
          : layout[`branch:${sel.branchId}`]!.y
        const targetIters = iterationsRef.current[target.id] ?? []
        if (targetIters.length === 0) {
          setSelection({ type: 'branch', seedId: target.seed_id, branchId: target.id })
        } else {
          const nearest = targetIters.reduce((best, it) => {
            const itY = layout[`iter:${target.id}:${it.hash}`]?.y ?? Infinity
            const bestY = layout[`iter:${target.id}:${best.hash}`]?.y ?? Infinity
            return Math.abs(itY - curY) < Math.abs(bestY - curY) ? it : best
          })
          setSelection({ type: 'iteration', seedId: target.seed_id, branchId: target.id, iterationId: nearest.id })
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [setSelection, setLightbox])

  // ---------------------------------------------------------------------------
  // Dagre layout
  // ---------------------------------------------------------------------------
  const focusKey = activePane.focusBranchIds === null ? 'all' : JSON.stringify(activePane.focusBranchIds)

  // Structural key: only re-layout when the graph topology changes (new/removed nodes),
  // not when metric values or comments change within existing iterations.
  const layoutStructureKey = useMemo(() => {
    const parts: string[] = []
    seeds.forEach(seed => {
      parts.push(`s${seed.id}`)
      ;(branches[seed.id] ?? []).forEach(branch => {
        parts.push(`b${branch.id}:${branch.parent_branch_id ?? ''}:${branch.parent_iteration_hash ?? ''}`)
        ;(iterations[branch.id] ?? []).forEach(iter => parts.push(`i${iter.hash}`))
      })
    })
    return parts.join(',')
  }, [seeds, branches, iterations])

  const layout = useMemo(() => {
    const g = new dagre.graphlib.Graph()
    g.setGraph({ rankdir: 'TB', nodesep: 80, ranksep: 70 })
    g.setDefaultEdgeLabel(() => ({}))
    const filter = activePane.focusBranchIds
    const visibleBranchIds = filter === null ? null : new Set(filter)
    seeds.forEach(seed => {
      const seedBranches = (branches[seed.id] ?? []).filter(b => visibleBranchIds === null || visibleBranchIds.has(b.id))
      if (seedBranches.length === 0 && visibleBranchIds !== null) return
      g.setNode(`seed:${seed.id}`, { width: 60, height: 60 })
      seedBranches.forEach(branch => {
        g.setNode(`branch:${branch.id}`, { width: 160, height: 42 })
        if (branch.parent_branch_id && branch.parent_iteration_hash) {
          const parentKey = `iter:${branch.parent_branch_id}:${branch.parent_iteration_hash}`
          if (visibleBranchIds === null || visibleBranchIds.has(branch.parent_branch_id)) {
            g.setEdge(parentKey, `branch:${branch.id}`)
          } else {
            g.setEdge(`seed:${seed.id}`, `branch:${branch.id}`)
          }
        } else {
          g.setEdge(`seed:${seed.id}`, `branch:${branch.id}`)
        }
        const branchIters = iterations[branch.id] ?? []
        branchIters.forEach((iter, i) => {
          g.setNode(`iter:${branch.id}:${iter.hash}`, { width: 300, height: 56 })
          const parent = i === 0 ? `branch:${branch.id}` : `iter:${branch.id}:${branchIters[i - 1].hash}`
          g.setEdge(parent, `iter:${branch.id}:${iter.hash}`)
        })
      })
    })
    dagre.layout(g)
    const positions: Record<string, { x: number; y: number }> = {}
    g.nodes().forEach(id => {
      const node = g.node(id)
      if (node) positions[id] = { x: node.x, y: node.y }
    })
    layoutRef.current = positions
    return positions
  }, [layoutStructureKey, focusKey])

  // Recompute visible branches when layout changes (new nodes added/removed)
  useEffect(() => { syncVisibleBranches() }, [layout, syncVisibleBranches])

  // ---------------------------------------------------------------------------
  // Stable callbacks for BranchNode
  // ---------------------------------------------------------------------------
  const handleSelectBranch = useCallback((seedId: number, branchId: number) => {
    setSelection({ type: 'branch', seedId, branchId })
  }, [setSelection])

  const handleSelectIteration = useCallback((seedId: number, branchId: number, iterationId: number) => {
    setSelection({ type: 'iteration', seedId, branchId, iterationId })
  }, [setSelection])

  const handleShiftClickIteration = useCallback((_e: React.MouseEvent, seedId: number, branchId: number, iterationId: number) => {
    // Read current selection from store at click time
    const sel = useCanvasStore.getState().getSelection()
    if (sel?.type === 'iteration' && sel.branchId === branchId) {
      shiftClickIteration(iterationId, sel.iterationId)
    } else {
      setSelection({ type: 'iteration', seedId, branchId, iterationId })
    }
  }, [shiftClickIteration, setSelection])

  const handleDoubleClickNode = useCallback((branchId: number, hash: string) => {
    openFileBrowser(branchId, hash)
  }, [openFileBrowser])

  const handleNodeContextMenu = useCallback((x: number, y: number, branchId: number) => {
    setContextMenu({ x, y, branchId })
  }, [setContextMenu])

  // ---------------------------------------------------------------------------
  // Pan-to-branch: when panTarget is set, center on the latest iteration
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const unsub = useCanvasStore.subscribe((state, prev) => {
      if (state.panTarget === null || state.panTarget === prev.panTarget) return
      const branchId = state.panTarget
      useCanvasStore.getState().setPanTarget(null)

      // Find the latest iteration position, or fall back to the branch node
      const branchIters = iterations[branchId] ?? []
      const latest = branchIters[branchIters.length - 1]
      const key = latest
        ? `iter:${branchId}:${latest.hash}`
        : `branch:${branchId}`
      const pos = layoutRef.current[key]
      if (!pos) return

      const z = Math.min(zoomRef.current, 0.90)
      zoomRef.current = z

      // Find the branch node position (not the latest iteration)
      const branchPos = layoutRef.current[`branch:${branchId}`]
      const targetPos = branchPos ?? pos
      const newPan = {
        x: viewportSize.w / 2 - targetPos.x * z,
        y: viewportSize.h / 2 - targetPos.y * z,
      }
      panRef.current = newPan
      applyTransform()
      setPan(newPan)
      setZoom(z)

      // Re-apply selection highlight after React renders the newly visible nodes
      requestAnimationFrame(() => {
        const svg = svgRef.current
        if (!svg) return
        const s = useCanvasStore.getState()
        applySelectionHighlight(svg, s.getSelection(), s.selectedIterationIds)
      })
    })
    return unsub
  }, [iterations, viewportSize, applyTransform, setPan, setZoom])

  // ---------------------------------------------------------------------------
  // Pan-to-seed: after layout recomputes, center on the seed if seedPanTarget is set
  // ---------------------------------------------------------------------------
  useEffect(() => {
    const seedId = useCanvasStore.getState().seedPanTarget
    if (seedId === null) return

    const pos = layout[`seed:${seedId}`]
    if (!pos) return

    useCanvasStore.getState().setSeedPanTarget(null)

    const z = zoomRef.current
    const newPan = {
      x: viewportSize.w / 2 - pos.x * z,
      y: viewportSize.h / 2 - pos.y * z,
    }
    panRef.current = newPan
    applyTransform()
    setPan(newPan)
  }, [layout, viewportSize, applyTransform, setPan])

  // Pre-compute metric ranges per branch (O(n) instead of O(n²) per iteration)
  const metricRanges = useMemo(() => {
    const ranges: Record<number, MetricRange> = {}
    for (const [branchIdStr, key] of Object.entries(mainMetric)) {
      const branchId = Number(branchIdStr)
      if (!key) continue
      const iters = iterations[branchId] ?? []
      let min = Infinity, max = -Infinity
      for (const it of iters) {
        const m = it.metrics.find(m => m.key === key)
        if (m !== undefined) { min = Math.min(min, m.value); max = Math.max(max, m.value) }
      }
      if (min !== Infinity) ranges[branchId] = { min, max }
    }
    return ranges
  }, [iterations, mainMetric])

  // ---------------------------------------------------------------------------
  // Render — selection state is NOT read here, only data + layout
  // ---------------------------------------------------------------------------
  return (
    <div
      ref={canvasRef}
      className="flex-1 overflow-hidden cursor-move relative canvas-bg bg-[#141a23]"
    >
      <svg ref={svgRef} className="w-full h-full" style={{ willChange: 'transform' }}>
        <defs>
          <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1c2331" strokeWidth="1" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#grid)" />
        <g ref={svgGroupRef}>

          {seeds.map(seed =>
            (branches[seed.id] ?? [])
              .filter(branch =>
                (activePane.focusBranchIds === null || activePane.focusBranchIds.includes(branch.id))
                && visibleBranches.has(branch.id)
              )
              .map(branch => (
                <BranchNode
                  key={branch.id}
                  seed={seed}
                  branch={branch}
                  branchIters={iterations[branch.id] ?? EMPTY_ITERS}
                  layout={layout}
                  mainMetricKey={mainMetric[branch.id]}
                  metricRange={metricRanges[branch.id]}
                  onSelectBranch={handleSelectBranch}
                  onSelectIteration={handleSelectIteration}
                  onShiftClickIteration={handleShiftClickIteration}
                  onDoubleClickNode={handleDoubleClickNode}
                  onContextMenu={handleNodeContextMenu}
                />
              ))
          )}

          {seeds.map(seed => {
            if (activePane.focusBranchIds !== null) {
              const hasFocused = (branches[seed.id] ?? []).some(b => activePane.focusBranchIds!.includes(b.id))
              if (!hasFocused) return null
            }
            const pos = layout[`seed:${seed.id}`]
            if (!pos) return null
            // Viewport cull seeds too
            const p = panRef.current, z = zoomRef.current
            const screenX = pos.x * z + p.x, screenY = pos.y * z + p.y
            if (screenX < -100 || screenX > viewportSize.w + 100 || screenY < -100 || screenY > viewportSize.h + 100) return null
            return (
              <g key={seed.id} data-seed-id={seed.id}>
                <circle data-role="seed-dot" cx={pos.x} cy={pos.y} r={22}
                  fill="#2ea043" stroke="#3fb950" strokeWidth={2.5}
                  onClick={() => setSelection({ type: 'seed', seedId: seed.id })}
                  className="cursor-pointer hover:fill-[#2ea043] transition-colors" />
                <text x={pos.x} y={pos.y - 32} fill="#c9d1d9" fontSize="15"
                  fontWeight="bold" className="select-none" textAnchor="middle">
                  {seed.name}
                </text>
              </g>
            )
          })}
        </g>
      </svg>
    </div>
  )
}

// ---------------------------------------------------------------------------
// applySelectionHighlight — toggles CSS classes on SVG elements directly
// ---------------------------------------------------------------------------
function applySelectionHighlight(svg: SVGSVGElement, selection: Selection, multiIds: Set<number>) {
  // Clear previous highlights
  svg.querySelectorAll('.node-selected').forEach(el => el.classList.remove('node-selected'))
  svg.querySelectorAll('.iter-selected').forEach(el => el.classList.remove('iter-selected'))
  svg.querySelectorAll('.seed-selected').forEach(el => el.classList.remove('seed-selected'))

  if (!selection) return

  if (selection.type === 'seed') {
    const el = svg.querySelector(`[data-seed-id="${selection.seedId}"]`)
    if (el) {
      el.classList.add('seed-selected')
      const dot = el.querySelector('[data-role="seed-dot"]')
      if (dot) { dot.setAttribute('r', '25'); dot.setAttribute('stroke', '#58a6ff'); dot.setAttribute('stroke-width', '3') }
    }
  } else if (selection.type === 'branch') {
    const el = svg.querySelector(`[data-branch-id="${selection.branchId}"]`)
    if (el) el.classList.add('node-selected')
  } else if (selection.type === 'iteration') {
    // Highlight the parent branch
    const branchEl = svg.querySelector(`[data-branch-id="${selection.branchId}"]`)
    if (branchEl) branchEl.classList.add('node-selected')
    // Highlight the iteration
    const iterEl = svg.querySelector(`[data-iter-id="${selection.iterationId}"]`)
    if (iterEl) iterEl.classList.add('iter-selected')
  }

  // Multi-select highlights
  multiIds.forEach(id => {
    const el = svg.querySelector(`[data-iter-id="${id}"]`)
    if (el) el.classList.add('iter-selected')
  })

  // Reset seed dots that lost selection
  svg.querySelectorAll('[data-seed-id]:not(.seed-selected) [data-role="seed-dot"]').forEach(dot => {
    dot.setAttribute('r', '22')
    dot.setAttribute('stroke', '#3fb950')
    dot.setAttribute('stroke-width', '2')
  })
}
