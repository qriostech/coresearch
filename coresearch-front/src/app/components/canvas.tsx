import { Loader2 } from 'lucide-react'
import { useWorkflow } from '../context/workflow-context'
import { CanvasHeader } from './canvas-header'
import { LeftSidebar } from './canvas-left-sidebar'
import { RightSidebar } from './canvas-right-sidebar'
import { PaneTabs } from './canvas-pane-tabs'
import { CanvasSVG } from './canvas-svg'
import { TerminalPanel } from './canvas-terminal-panel'
import { CanvasDialogs } from './canvas-dialogs'
import { CanvasOverlays } from './canvas-overlays'
import { DebugOverlay } from './debug-overlay'

export function Canvas() {
  const { loading } = useWorkflow()

  if (loading) {
    return (
      <div className="h-screen bg-[#0d1117] flex items-center justify-center">
        <Loader2 className="size-8 text-[#58a6ff] animate-spin" />
      </div>
    )
  }

  return (
    <div className="h-screen bg-[#0d1117] flex flex-col font-mono">
      <CanvasHeader />
      <div className="flex-1 flex overflow-hidden">
        <LeftSidebar />
        <div className="flex-1 flex flex-col">
          <PaneTabs />
          <CanvasSVG />
          <TerminalPanel />
        </div>
        <RightSidebar />
      </div>
      <CanvasDialogs />
      <CanvasOverlays />
      <DebugOverlay />
    </div>
  )
}
