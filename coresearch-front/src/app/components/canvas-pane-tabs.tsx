import { Plus, X } from 'lucide-react'
import { useCanvasStore } from './canvas-store'

export function PaneTabs() {
  const panes = useCanvasStore(s => s.panes)
  const activePaneId = useCanvasStore(s => s.activePaneId)
  const setActivePaneId = useCanvasStore(s => s.setActivePaneId)
  const addPane = useCanvasStore(s => s.addPane)
  const closePane = useCanvasStore(s => s.closePane)
  const renamePane = useCanvasStore(s => s.renamePane)
  const renamingPaneId = useCanvasStore(s => s.renamingPaneId)
  const setRenamingPaneId = useCanvasStore(s => s.setRenamingPaneId)

  return (
    <div className="flex items-center border-b border-[#30363d] bg-[#161b22] shrink-0">
      {panes.map(p => (
        <div key={p.id}
          className={`flex items-center gap-1 px-3 py-1.5 text-xs cursor-pointer border-r border-[#30363d] group ${
            p.id === activePaneId ? 'bg-[#141a23] text-[#c9d1d9]' : 'text-[#6e7681] hover:text-[#8b949e]'
          }`}
          onClick={() => setActivePaneId(p.id)}
          onDoubleClick={() => setRenamingPaneId(p.id)}
        >
          {renamingPaneId === p.id ? (
            <input
              autoFocus
              defaultValue={p.name}
              className="bg-transparent text-[#c9d1d9] font-mono text-xs outline-none border-b border-[#58a6ff] w-20"
              onBlur={e => { renamePane(p.id, e.target.value || p.name); setRenamingPaneId(null) }}
              onKeyDown={e => {
                if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
                if (e.key === 'Escape') { e.preventDefault(); setRenamingPaneId(null) }
                e.stopPropagation()
              }}
              onClick={e => e.stopPropagation()}
            />
          ) : (
            <span className="font-mono">{p.name}</span>
          )}
          {panes.length > 1 && (
            <button
              onClick={e => { e.stopPropagation(); closePane(p.id) }}
              className="opacity-0 group-hover:opacity-100 text-[#6e7681] hover:text-[#f85149] ml-1"
            >
              <X className="size-3" />
            </button>
          )}
        </div>
      ))}
      <button onClick={addPane} className="px-2 py-1.5 text-[#6e7681] hover:text-[#c9d1d9]">
        <Plus className="size-3.5" />
      </button>
    </div>
  )
}
