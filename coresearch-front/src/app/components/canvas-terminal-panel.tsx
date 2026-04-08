import { memo, useRef, useState, useCallback } from 'react'
import { Terminal as TerminalIcon, X } from 'lucide-react'
import { useWorkflow } from '../context/workflow-context'
import { useCanvasStore } from './canvas-store'
import { BranchTerminal } from './terminal'

export const TerminalPanel = memo(function TerminalPanel() {
  const { branches } = useWorkflow()
  const attachedBranchId = useCanvasStore(s => s.attachedBranchId)
  const openedTerminals = useCanvasStore(s => s.openedTerminals)
  const terminalHeight = useCanvasStore(s => s.terminalHeight)
  const setTerminalHeight = useCanvasStore(s => s.setTerminalHeight)
  const setAttachedBranchId = useCanvasStore(s => s.setAttachedBranchId)

  const [dragging, setDragging] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{ startY: number; startHeight: number } | null>(null)

  const startDrag = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    const currentHeight = useCanvasStore.getState().terminalHeight
    dragRef.current = { startY: e.clientY, startHeight: currentHeight }

    document.body.style.cursor = 'ns-resize'
    document.body.style.userSelect = 'none'
    setDragging(true)

    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current || !panelRef.current) return
      const delta = dragRef.current.startY - ev.clientY
      const newHeight = Math.max(120, Math.min(dragRef.current.startHeight + delta, window.innerHeight * 0.8))
      // DOM mutation only — no store updates, xterm is frozen behind blur
      panelRef.current.style.height = `${newHeight}px`
    }

    const onUp = (ev: MouseEvent) => {
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      if (!dragRef.current) return
      const delta = dragRef.current.startY - ev.clientY
      const finalHeight = Math.max(120, Math.min(dragRef.current.startHeight + delta, window.innerHeight * 0.8))
      dragRef.current = null

      // Commit new height
      setTerminalHeight(finalHeight)
      setDragging(false)

      // Detach and reattach — this destroys and recreates the terminal
      // at the new dimensions, exactly like the user manually closing
      // and reopening the panel.
      const branchId = useCanvasStore.getState().attachedBranchId
      if (branchId !== null) {
        setAttachedBranchId(null)
        requestAnimationFrame(() => {
          setAttachedBranchId(branchId)
        })
      }
    }

    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [setTerminalHeight, setAttachedBranchId])

  if (attachedBranchId === null) return null

  const branchName = Object.values(branches).flat().find(b => b.id === attachedBranchId)?.name ?? String(attachedBranchId)

  return (
    <div ref={panelRef} className="border-t border-[#30363d] bg-[#0d1117] flex flex-col" style={{ height: terminalHeight }}>
      <div
        className="h-2 cursor-ns-resize bg-[#161b22] hover:bg-[#58a6ff]/30 transition-colors shrink-0 flex items-center justify-center"
        onMouseDown={startDrag}
      >
        <div className="w-8 h-0.5 rounded-full bg-[#30363d]" />
      </div>
      <div className="flex items-center justify-between px-4 py-2 bg-[#161b22] border-b border-[#30363d]">
        <div className="flex items-center gap-2">
          <TerminalIcon className="size-4 text-[#58a6ff]" />
          <span className="text-xs text-[#8b949e] font-mono">
            branch terminal — {branchName}
          </span>
        </div>
        <button onClick={() => setAttachedBranchId(null)}
          className="text-[#8b949e] hover:text-[#c9d1d9] transition-colors">
          <X className="size-4" />
        </button>
      </div>
      <div className="flex-1 p-2 overflow-hidden relative">
        {dragging && (
          <div className="absolute inset-0 z-10 backdrop-blur-sm bg-[#0d1117]/50 flex items-center justify-center">
            <span className="text-xs text-[#8b949e] font-mono">resizing...</span>
          </div>
        )}
        {openedTerminals.map(id => (
          <BranchTerminal key={id} branchId={id} visible={id === attachedBranchId} />
        ))}
      </div>
    </div>
  )
})
