import { memo, useState, useEffect } from 'react'
import { Bot, FolderGit2, FolderTree, GitBranch, Plus, Server, ChevronRight, ChevronDown, Terminal as TerminalIcon, X } from 'lucide-react'
import { useWorkflow } from '../context/workflow-context'
import { useCanvasStore } from './canvas-store'
import { api, Branch } from '../api/client'

export const LeftSidebar = memo(function LeftSidebar() {
  const {
    projects, currentProject, selectProject, runners, seeds, branches, iterations, aliveBranches,
    corySessions, addCorySession, killCorySession,
  } = useWorkflow()
  const selection = useCanvasStore(s => s.getSelection())
  const setSelection = useCanvasStore(s => s.setSelection)
  const attachedBranchId = useCanvasStore(s => s.attachedBranchId)
  const setAttachedBranchId = useCanvasStore(s => s.setAttachedBranchId)
  const attachedCorySessionId = useCanvasStore(s => s.attachedCorySessionId)
  const setAttachedCorySessionId = useCanvasStore(s => s.setAttachedCorySessionId)

  return (
    <div className="w-64 border-r border-[#30363d] bg-[#161b22] p-4 overflow-y-auto flex flex-col gap-6">
      {/* Projects section */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <FolderGit2 className="size-4 text-[#58a6ff]" />
          <h2 className="text-sm text-[#c9d1d9] font-semibold">projects</h2>
        </div>
        <div className="space-y-1">
          {projects.map(project => (
            <div key={project.id}
              onClick={() => selectProject(project)}
              className={`px-2 py-1.5 rounded cursor-pointer transition-colors text-sm ${
                currentProject?.id === project.id
                  ? 'bg-[#58a6ff]/20 text-[#58a6ff]'
                  : 'text-[#8b949e] hover:text-[#c9d1d9] hover:bg-[#0d1117]'
              }`}>
              {project.name}
            </div>
          ))}
          {projects.length === 0 && (
            <p className="text-xs text-[#6e7681]">no projects yet</p>
          )}
        </div>
      </div>

      {/* Runners section */}
      <RunnersSection runners={runners} />

      {/* Seeds section */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <FolderTree className="size-4 text-[#58a6ff]" />
          <h2 className="text-sm text-[#c9d1d9] font-semibold">seeds</h2>
        </div>
        <div className="space-y-2">
          {seeds.map(seed => (
            <div key={seed.id}
              onClick={() => setSelection({ type: 'seed', seedId: seed.id })}
              className={`p-2 rounded cursor-pointer transition-colors ${
                selection?.type === 'seed' && selection.seedId === seed.id
                  ? 'bg-[#58a6ff]/20 border border-[#58a6ff]'
                  : 'bg-[#0d1117] border border-[#30363d] hover:border-[#8b949e]'
              }`}>
              <div className="text-[#c9d1d9] text-sm mb-1">{seed.name}</div>
              <div className="text-[#6e7681] text-xs flex items-center gap-1">
                <GitBranch className="size-3" />
                {(branches[seed.id] ?? []).length} branches
              </div>
            </div>
          ))}
          {seeds.length === 0 && (
            <p className="text-xs text-[#6e7681]">no seeds yet</p>
          )}
        </div>
      </div>

      {/* Cory section */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Bot className="size-4 text-[#58a6ff]" />
            <h2 className="text-sm text-[#c9d1d9] font-semibold">cory</h2>
          </div>
          <button
            onClick={async () => {
              try {
                await addCorySession()
              } catch (e) {
                console.error('[coresearch] failed to create cory session:', e)
              }
            }}
            className="p-0.5 rounded hover:bg-[#0d1117] text-[#6e7681] hover:text-[#c9d1d9] transition-colors"
            title="New cory session"
          >
            <Plus className="size-3.5" />
          </button>
        </div>
        <div className="space-y-1">
          {corySessions.filter(s => s.status === 'active').map(session => {
            const isAttached = attachedCorySessionId === session.id
            return (
              <div key={session.id}
                onClick={() => setAttachedCorySessionId(isAttached ? null : session.id)}
                className={`group px-2 py-1.5 rounded cursor-pointer transition-colors flex items-center gap-2 ${
                  isAttached
                    ? 'bg-[#238636]/20 border border-[#238636]'
                    : 'hover:bg-[#0d1117] border border-transparent hover:border-[#30363d]'
                }`}>
                <Bot className={`size-3 shrink-0 ${isAttached ? 'text-[#3fb950]' : 'text-[#6e7681]'}`} />
                <div className="min-w-0 flex-1">
                  <div className="text-[#c9d1d9] text-xs truncate">{session.name || `cory-${session.uuid.slice(0, 8)}`}</div>
                  <div className="text-[#6e7681] text-xs truncate">{session.agent}</div>
                </div>
                <button
                  onClick={async (e) => {
                    e.stopPropagation()
                    try {
                      await killCorySession(session.id)
                      if (attachedCorySessionId === session.id) setAttachedCorySessionId(null)
                    } catch (err) {
                      console.error('[coresearch] failed to kill cory session:', err)
                    }
                  }}
                  className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity p-0.5 rounded hover:bg-[#da3633]/20"
                  title="Kill cory session"
                >
                  <X className="size-3 text-[#6e7681] hover:text-[#f85149]" />
                </button>
              </div>
            )
          })}
          {corySessions.filter(s => s.status === 'active').length === 0 && (
            <p className="text-xs text-[#6e7681]">no cory sessions</p>
          )}
        </div>
      </div>

      {/* Sessions section */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <TerminalIcon className="size-4 text-[#58a6ff]" />
          <h2 className="text-sm text-[#c9d1d9] font-semibold">sessions</h2>
        </div>
        <div className="space-y-1">
          {seeds.flatMap(seed =>
            (branches[seed.id] ?? [])
              .filter(branch => aliveBranches.has(branch.id))
              .map(branch => {
                const isAttached = attachedBranchId === branch.id
                return (
                  <div key={branch.id}
                    onClick={() => {
                      setAttachedBranchId(isAttached ? null : branch.id)
                      const branchIters = iterations[branch.id] ?? []
                      const latest = branchIters[branchIters.length - 1]
                      if (latest) {
                        setSelection({ type: 'iteration', seedId: seed.id, branchId: branch.id, iterationId: latest.id })
                      } else {
                        setSelection({ type: 'branch', seedId: seed.id, branchId: branch.id })
                      }
                      if (!isAttached) {
                        useCanvasStore.getState().setPanTarget(branch.id)
                      }
                    }}
                    className={`group px-2 py-1.5 rounded cursor-pointer transition-colors flex items-center gap-2 ${
                      isAttached
                        ? 'bg-[#238636]/20 border border-[#238636]'
                        : 'hover:bg-[#0d1117] border border-transparent hover:border-[#30363d]'
                    }`}>
                    <TerminalIcon className={`size-3 shrink-0 ${isAttached ? 'text-[#3fb950]' : 'text-[#6e7681]'}`} />
                    <div className="min-w-0 flex-1">
                      <div className="text-[#c9d1d9] text-xs truncate">{branch.name}</div>
                      <div className="text-[#6e7681] text-xs truncate">{seed.name}</div>
                    </div>
                    <button
                      onClick={async (e) => {
                        e.stopPropagation()
                        await api.branches.kill(branch.id)
                        if (attachedBranchId === branch.id) setAttachedBranchId(null)
                      }}
                      className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity p-0.5 rounded hover:bg-[#da3633]/20"
                      title="Kill session"
                    >
                      <X className="size-3 text-[#6e7681] hover:text-[#f85149]" />
                    </button>
                  </div>
                )
              })
          )}
          {aliveBranches.size === 0 && (
            <p className="text-xs text-[#6e7681]">no active sessions</p>
          )}
        </div>
      </div>
    </div>
  )
})

function RunnersSection({ runners }: { runners: { id: number; name: string; status: string }[] }) {
  const aliveBranches = useWorkflow().aliveBranches
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [runnerBranches, setRunnerBranches] = useState<Branch[]>([])
  const [loadingBranches, setLoadingBranches] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editName, setEditName] = useState('')

  useEffect(() => {
    if (expandedId === null) {
      setRunnerBranches([])
      return
    }
    setLoadingBranches(true)
    api.runners.branches(expandedId)
      .then(setRunnerBranches)
      .catch(() => setRunnerBranches([]))
      .finally(() => setLoadingBranches(false))
  }, [expandedId])

  const STATUS_COLORS: Record<string, string> = {
    active: 'bg-[#3fb950]',
    offline: 'bg-[#f85149]',
    draining: 'bg-[#d29922]',
  }

  const submitRename = async (runnerId: number) => {
    const trimmed = editName.trim()
    if (trimmed && trimmed !== runners.find(r => r.id === runnerId)?.name) {
      try {
        await api.runners.rename(runnerId, trimmed)
      } catch {}
    }
    setEditingId(null)
  }

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <Server className="size-4 text-[#58a6ff]" />
        <h2 className="text-sm text-[#c9d1d9] font-semibold">runners</h2>
      </div>
      <div className="space-y-1">
        {runners.map(runner => {
          const expanded = expandedId === runner.id
          const editing = editingId === runner.id
          return (
            <div key={runner.id}>
              <div
                onClick={() => { if (!editing) setExpandedId(expanded ? null : runner.id) }}
                onDoubleClick={(e) => {
                  e.stopPropagation()
                  setEditingId(runner.id)
                  setEditName(runner.name)
                }}
                className={`px-2 py-1.5 rounded cursor-pointer transition-colors flex items-center gap-2 ${
                  expanded
                    ? 'bg-[#58a6ff]/10 text-[#c9d1d9]'
                    : 'text-[#8b949e] hover:text-[#c9d1d9] hover:bg-[#0d1117]'
                }`}
              >
                {expanded
                  ? <ChevronDown className="size-3 shrink-0 text-[#484f58]" />
                  : <ChevronRight className="size-3 shrink-0 text-[#484f58]" />
                }
                <div className={`size-2 rounded-full shrink-0 ${STATUS_COLORS[runner.status] ?? 'bg-[#484f58]'}`} />
                {editing ? (
                  <input
                    autoFocus
                    value={editName}
                    onChange={e => setEditName(e.target.value)}
                    onBlur={() => submitRename(runner.id)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') submitRename(runner.id)
                      if (e.key === 'Escape') { e.preventDefault(); setEditingId(null) }
                    }}
                    onClick={e => e.stopPropagation()}
                    className="text-sm bg-[#0d1117] border border-[#58a6ff] rounded px-1 py-0 text-[#c9d1d9] outline-none w-full font-mono"
                  />
                ) : (
                  <span className="text-sm truncate">{runner.name}</span>
                )}
              </div>
              {expanded && (
                <div className="ml-5 mt-1 space-y-0.5">
                  {loadingBranches && (
                    <div className="text-[#484f58] text-xs py-1">loading...</div>
                  )}
                  {!loadingBranches && runnerBranches.length === 0 && (
                    <div className="text-[#484f58] text-xs py-1">no branches</div>
                  )}
                  {!loadingBranches && runnerBranches.map(branch => (
                    <div
                      key={branch.id}
                      onClick={() => {
                        useCanvasStore.getState().setSelection({
                          type: 'branch',
                          seedId: branch.seed_id,
                          branchId: branch.id,
                        })
                        useCanvasStore.getState().setPanTarget(branch.id)
                      }}
                      className="flex items-center gap-1.5 px-2 py-1 rounded text-xs cursor-pointer hover:bg-[#0d1117] transition-colors"
                    >
                      <GitBranch className="size-3 shrink-0 text-[#484f58]" />
                      <span className="text-[#c9d1d9] truncate">{branch.name}</span>
                      <div className={`size-1.5 rounded-full shrink-0 ml-auto ${
                        aliveBranches.has(branch.id) ? 'bg-[#3fb950]' : 'bg-[#484f58]'
                      }`} />
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
        {runners.length === 0 && (
          <p className="text-xs text-[#6e7681]">no runners registered</p>
        )}
      </div>
    </div>
  )
}
