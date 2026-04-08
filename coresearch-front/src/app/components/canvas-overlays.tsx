import React from 'react'
import { GitCompare, FolderTree, FileCode, Folder, ChevronRight, ChevronDown, X, Sparkles, MessageSquare } from 'lucide-react'
import { useWorkflow } from '../context/workflow-context'
import { api } from '../api/client'
import { useCanvasStore } from './canvas-store'
import { Input } from './ui/input'
import { HighlightedCode } from './ui/highlighted-code'

export function CanvasOverlays() {
  const { iterations } = useWorkflow()

  // Overlays
  const diffOverlay = useCanvasStore(s => s.diffOverlay); const setDiffOverlay = useCanvasStore(s => s.setDiffOverlay)
  const contextMenu = useCanvasStore(s => s.contextMenu); const setContextMenu = useCanvasStore(s => s.setContextMenu)
  const fileBrowser = useCanvasStore(s => s.fileBrowser); const setFileBrowser = useCanvasStore(s => s.setFileBrowser)
  const expandedDirs = useCanvasStore(s => s.expandedDirs); const setExpandedDirs = useCanvasStore(s => s.setExpandedDirs)
  const viewingFile = useCanvasStore(s => s.viewingFile); const setViewingFile = useCanvasStore(s => s.setViewingFile)
  const textOverlay = useCanvasStore(s => s.textOverlay); const setTextOverlay = useCanvasStore(s => s.setTextOverlay)
  const lightbox = useCanvasStore(s => s.lightbox); const setLightbox = useCanvasStore(s => s.setLightbox)
  const panes = useCanvasStore(s => s.panes)
  const activePaneId = useCanvasStore(s => s.activePaneId)
  const sendBranchToPane = useCanvasStore(s => s.sendBranchToPane)

  return (
    <>
      {/* Diff overlay */}
      {diffOverlay && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
          onClick={() => setDiffOverlay(null)}
          onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); setDiffOverlay(null) } }}
          tabIndex={0}
          ref={el => el?.focus()}>
          <div className="bg-[#0d1117] border border-[#30363d] rounded-lg shadow-2xl w-[80vw] h-[80vh] flex flex-col"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-[#30363d]">
              <div className="flex items-center gap-2 text-sm">
                <GitCompare className="size-4 text-[#58a6ff]" />
                <span className="text-[#8b949e]">diff</span>
                <span className="font-mono text-[#f0883e]">{diffOverlay.from}</span>
                <span className="text-[#8b949e]">..</span>
                <span className="font-mono text-[#3fb950]">{diffOverlay.to}</span>
              </div>
              <button onClick={() => setDiffOverlay(null)} className="text-[#8b949e] hover:text-[#c9d1d9]">
                <X className="size-5" />
              </button>
            </div>
            <pre className="flex-1 overflow-auto p-4 text-xs font-mono leading-5">
              {diffOverlay.content.split('\n').map((line, i) => (
                <div key={i} className={
                  line.startsWith('+++') || line.startsWith('---') ? 'text-[#c9d1d9] font-bold'
                  : line.startsWith('+') ? 'text-[#3fb950] bg-[#0d2818]'
                  : line.startsWith('-') ? 'text-[#f85149] bg-[#3d1117]'
                  : line.startsWith('@@') ? 'text-[#79c0ff]'
                  : line.startsWith('diff ') ? 'text-[#c9d1d9] font-bold mt-4'
                  : 'text-[#8b949e]'
                }>{line}</div>
              ))}
            </pre>
          </div>
        </div>
      )}

      {/* Context menu */}
      {contextMenu && (
        <div className="fixed inset-0 z-50" onClick={() => setContextMenu(null)}>
          <div
            className="absolute bg-[#161b22] border border-[#30363d] rounded shadow-lg py-1 min-w-[160px]"
            style={{ left: contextMenu.x, top: contextMenu.y }}
            onClick={e => e.stopPropagation()}
          >
            <div className="px-3 py-1.5 text-xs text-[#8b949e] border-b border-[#30363d]">send to pane</div>
            {panes.filter(p => p.id !== activePaneId).map(p => (
              <button key={p.id}
                onClick={() => sendBranchToPane(contextMenu.branchId, p.id)}
                className="w-full text-left px-3 py-1.5 text-xs text-[#c9d1d9] hover:bg-[#30363d] transition-colors"
              >
                {p.name}
              </button>
            ))}
            {panes.length < 2 && (
              <div className="px-3 py-1.5 text-xs text-[#6e7681] italic">create another pane first</div>
            )}
          </div>
        </div>
      )}

      {/* File browser overlay */}
      {fileBrowser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
          onClick={() => { setFileBrowser(null); setViewingFile(null) }}
          onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); setFileBrowser(null); setViewingFile(null) } }}
          tabIndex={0}
          ref={el => el?.focus()}>
          <div className="bg-[#0d1117] border border-[#30363d] rounded-lg shadow-2xl w-[80vw] h-[80vh] flex flex-col"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-[#30363d]">
              <div className="flex items-center gap-2 text-sm">
                <FolderTree className="size-4 text-[#58a6ff]" />
                <span className="text-[#8b949e]">{fileBrowser.mode === 'workdir' ? 'working tree' : 'files at'}</span>
                {fileBrowser.mode === 'git' && <span className="font-mono text-[#f0883e]">{fileBrowser.hash.slice(0, 8)}</span>}
              </div>
              <button onClick={() => { setFileBrowser(null); setViewingFile(null) }} className="text-[#8b949e] hover:text-[#c9d1d9]">
                <X className="size-5" />
              </button>
            </div>
            <div className="flex flex-1 overflow-hidden">
              {/* File tree */}
              <div className="w-64 border-r border-[#30363d] overflow-y-auto p-2">
                {(() => {
                  type TreeNode = { name: string; path: string; children: Record<string, TreeNode>; isFile: boolean }
                  const root: TreeNode = { name: '', path: '', children: {}, isFile: false }
                  for (const filepath of fileBrowser.files) {
                    const parts = filepath.split('/')
                    let node = root
                    for (let i = 0; i < parts.length; i++) {
                      const part = parts[i]
                      if (!node.children[part]) {
                        node.children[part] = {
                          name: part,
                          path: parts.slice(0, i + 1).join('/'),
                          children: {},
                          isFile: i === parts.length - 1,
                        }
                      }
                      node = node.children[part]
                    }
                  }
                  const renderNode = (node: TreeNode, depth: number): React.ReactNode[] => {
                    const sorted = Object.values(node.children).sort((a, b) => {
                      if (a.isFile !== b.isFile) return a.isFile ? 1 : -1
                      return a.name.localeCompare(b.name)
                    })
                    return sorted.map(child => {
                      if (child.isFile) {
                        return (
                          <div key={child.path}
                            onClick={async () => {
                              try {
                                const content = fileBrowser.mode === 'workdir'
                                  ? await api.workdir.readFile(fileBrowser.branchId, child.path)
                                  : await api.tree.file(fileBrowser.branchId, fileBrowser.hash, child.path)
                                setViewingFile({ path: child.path, content })
                              } catch {}
                            }}
                            className={`flex items-center gap-1 px-2 py-0.5 rounded cursor-pointer text-xs font-mono truncate ${
                              viewingFile?.path === child.path
                                ? 'bg-[#58a6ff]/20 text-[#58a6ff]'
                                : 'text-[#c9d1d9] hover:bg-[#161b22]'
                            }`}
                            style={{ paddingLeft: depth * 12 + 8 }}>
                            <FileCode className="size-3 shrink-0 text-[#8b949e]" />
                            {child.name}
                          </div>
                        )
                      }
                      const isExpanded = expandedDirs.has(child.path)
                      return (
                        <div key={child.path}>
                          <div
                            onClick={() => {
                              const next = new Set(expandedDirs)
                              if (next.has(child.path)) next.delete(child.path)
                              else next.add(child.path)
                              setExpandedDirs(next)
                            }}
                            className="flex items-center gap-1 px-2 py-0.5 rounded cursor-pointer text-xs font-mono text-[#c9d1d9] hover:bg-[#161b22] truncate"
                            style={{ paddingLeft: depth * 12 + 8 }}>
                            {isExpanded ? <ChevronDown className="size-3 shrink-0" /> : <ChevronRight className="size-3 shrink-0" />}
                            <Folder className="size-3 shrink-0 text-[#58a6ff]" />
                            {child.name}
                          </div>
                          {isExpanded && renderNode(child, depth + 1)}
                        </div>
                      )
                    })
                  }
                  return renderNode(root, 0)
                })()}
              </div>
              {/* File content */}
              <div className="flex-1 overflow-auto">
                {viewingFile ? (
                  <div>
                    <div className="sticky top-0 bg-[#161b22] border-b border-[#30363d] px-4 py-2 text-xs font-mono text-[#8b949e]">
                      {viewingFile.path}
                    </div>
                    <HighlightedCode content={viewingFile.content} filePath={viewingFile.path} />
                  </div>
                ) : (
                  <div className="flex items-center justify-center h-full text-[#484f58] text-sm">
                    select a file to view
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Text overlay for descriptions and comments */}
      {textOverlay && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6"
          onClick={e => { if (e.target === e.currentTarget) setTextOverlay(null) }}
          onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); setTextOverlay(null) } }}>
          <div className={`bg-[#161b22] border border-[#30363d] rounded-lg w-full ${textOverlay.type === 'metric-chart' ? 'max-w-3xl' : 'max-w-xl'} max-h-[70vh] flex flex-col`}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-[#30363d]">
              <div className="flex items-center gap-2">
                {textOverlay.type === 'branch-description' && <FileCode className="size-4 text-[#58a6ff]" />}
                {textOverlay.type === 'iteration-comments' && <MessageSquare className="size-4 text-[#f0883e]" />}
                {textOverlay.type === 'metric-chart' && <Sparkles className="size-4 text-[#58a6ff]" />}
                <span className="text-[#c9d1d9] text-sm font-semibold">
                  {textOverlay.type === 'branch-description' ? 'branch description'
                    : textOverlay.type === 'iteration-comments' ? 'iteration comments'
                    : textOverlay.metricKey}
                </span>
              </div>
              <button onClick={() => setTextOverlay(null)} className="text-[#8b949e] hover:text-[#c9d1d9]">
                <X className="size-4" />
              </button>
            </div>

            {textOverlay.type === 'branch-description' && (
              <div className="p-4 space-y-3">
                <textarea
                  autoFocus
                  defaultValue={textOverlay.value}
                  onChange={e => setTextOverlay({ ...textOverlay, value: e.target.value })}
                  onKeyDown={async e => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      await api.branches.update((textOverlay as any).branchId, (textOverlay as any).value)
                      setTextOverlay(null)
                    }
                  }}
                  className="w-full bg-[#0d1117] text-[#c9d1d9] font-mono text-sm p-3 rounded border border-[#30363d] resize-none outline-none focus:border-[#58a6ff] min-h-[120px]"
                  placeholder="describe what this branch explores... (Enter to save, Shift+Enter for newline)"
                />
              </div>
            )}

            {textOverlay.type === 'iteration-comments' && (() => {
              const iter = Object.values(iterations).flat().find(it => it.id === textOverlay.iterationId)
              if (!iter) return null
              return (
                <div className="flex flex-col overflow-hidden">
                  <div className="flex-1 overflow-y-auto p-4 space-y-3">
                    {iter.comments.length === 0 && (
                      <p className="text-[#6e7681] text-sm text-center py-4">no comments yet</p>
                    )}
                    {iter.comments.map(c => (
                      <div key={c.id} className="bg-[#0d1117] p-3 rounded border border-[#30363d] group">
                        <div className="flex justify-between items-start">
                          <div className="text-[#c9d1d9] text-sm whitespace-pre-wrap break-all">{c.body}</div>
                          <button
                            onClick={() => api.iterations.deleteComment(iter.id, c.id)}
                            className="text-[#6e7681] hover:text-[#f85149] opacity-0 group-hover:opacity-100 ml-2 shrink-0"
                          >
                            <X className="size-3" />
                          </button>
                        </div>
                        <div className="text-[#6e7681] text-xs mt-2">{c.user_name} &middot; {new Date(c.created_at).toLocaleString()}</div>
                      </div>
                    ))}
                  </div>
                  <div className="border-t border-[#30363d] p-4">
                    <Input
                      autoFocus
                      onKeyDown={async e => {
                        if (e.key === 'Enter') {
                          const input = e.target as HTMLInputElement
                          const val = input.value.trim()
                          if (!val) return
                          await api.iterations.addComment(iter.id, val)
                          input.value = ''
                        }
                      }}
                      className="bg-[#0d1117] border-[#30363d] text-[#c9d1d9] font-mono text-sm"
                      placeholder="type a comment and press Enter..."
                    />
                  </div>
                </div>
              )
            })()}

            {textOverlay.type === 'metric-chart' && (() => {
              const branchIters = iterations[textOverlay.branchId] ?? []
              const points = branchIters
                .map(it => ({
                  hash: it.hash,
                  name: it.name !== it.hash ? it.name : it.hash.slice(0, 8),
                  value: it.metrics.find(m => m.key === textOverlay.metricKey)?.value,
                }))
                .filter((p): p is { hash: string; name: string; value: number } => p.value !== undefined)
              if (points.length < 2) return (
                <div className="p-8 text-center text-[#6e7681] text-sm">not enough data points</div>
              )

              const cW = 700
              const cH = 320
              const pad = { top: 20, right: 20, bottom: 50, left: 55 }
              const w = cW - pad.left - pad.right
              const h = cH - pad.top - pad.bottom
              const minV = Math.min(...points.map(p => p.value))
              const maxV = Math.max(...points.map(p => p.value))
              const rangeV = maxV > minV ? maxV - minV : 1
              const midV = (minV + maxV) / 2
              const yTicks = [minV, midV, maxV]

              return (
                <div className="p-4">
                  <svg viewBox={`0 0 ${cW} ${cH}`} className="w-full">
                    {/* Background */}
                    <rect x={pad.left} y={pad.top} width={w} height={h} fill="#0d1117" rx={4} />

                    {/* Y grid + labels */}
                    {yTicks.map((v, i) => {
                      const y = pad.top + h - ((v - minV) / rangeV) * h
                      return (
                        <g key={i}>
                          <line x1={pad.left} y1={y} x2={pad.left + w} y2={y}
                            stroke="#21262d" strokeWidth={1} strokeDasharray={i === 1 ? '4 4' : undefined} />
                          <text x={pad.left - 8} y={y + 3} fill="#8b949e" fontSize="11" textAnchor="end" className="font-mono">
                            {v % 1 === 0 ? v : v.toFixed(3)}
                          </text>
                        </g>
                      )
                    })}

                    {/* Area fill */}
                    <polygon
                      fill="#58a6ff" fillOpacity={0.08}
                      points={[
                        `${pad.left},${pad.top + h}`,
                        ...points.map((p, i) => {
                          const x = pad.left + (i / (points.length - 1)) * w
                          const y = pad.top + h - ((p.value - minV) / rangeV) * h
                          return `${x},${y}`
                        }),
                        `${pad.left + w},${pad.top + h}`,
                      ].join(' ')}
                    />

                    {/* Line */}
                    <polyline
                      fill="none" stroke="#58a6ff" strokeWidth={2} strokeLinejoin="round"
                      points={points.map((p, i) => {
                        const x = pad.left + (i / (points.length - 1)) * w
                        const y = pad.top + h - ((p.value - minV) / rangeV) * h
                        return `${x},${y}`
                      }).join(' ')}
                    />

                    {/* Dots + labels */}
                    {points.map((p, i) => {
                      const x = pad.left + (i / (points.length - 1)) * w
                      const y = pad.top + h - ((p.value - minV) / rangeV) * h
                      return (
                        <g key={i}>
                          <circle cx={x} cy={y} r={4} fill="#161b22" stroke="#58a6ff" strokeWidth={2} />
                          {/* Value on hover area */}
                          <title>{p.name}: {p.value}</title>
                          <circle cx={x} cy={y} r={12} fill="transparent" />
                          {/* X label */}
                          <text x={x} y={pad.top + h + 16} fill="#8b949e" fontSize="10" textAnchor="middle" className="font-mono"
                            transform={points.length > 8 ? `rotate(-45 ${x} ${pad.top + h + 16})` : undefined}>
                            {p.name}
                          </text>
                          {/* Value above dot */}
                          <text x={x} y={y - 10} fill="#c9d1d9" fontSize="10" textAnchor="middle" className="font-mono">
                            {p.value % 1 === 0 ? p.value : p.value.toFixed(3)}
                          </text>
                        </g>
                      )
                    })}
                  </svg>
                </div>
              )
            })()}
          </div>
        </div>
      )}

      {/* Lightbox */}
      {lightbox && (() => {
        const iter = Object.values(iterations).flat().find(it => it.id === lightbox.iterationId)
        const imageVisuals = iter?.visuals.filter(v => v.format !== 'html') ?? []
        const current = imageVisuals[lightbox.index]
        if (!current || !iter) return null
        const hasPrev = lightbox.index > 0
        const hasNext = lightbox.index < imageVisuals.length - 1
        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
            onClick={() => setLightbox(null)}
            onKeyDown={e => {
              if (e.key === 'Escape') { e.preventDefault(); setLightbox(null) }
              if (e.key === 'ArrowLeft' && hasPrev) setLightbox({ ...lightbox, index: lightbox.index - 1 })
              if (e.key === 'ArrowRight' && hasNext) setLightbox({ ...lightbox, index: lightbox.index + 1 })
            }}
            tabIndex={0}
            ref={el => el?.focus()}>
            <button onClick={() => setLightbox(null)}
              className="absolute top-4 right-4 text-white/70 hover:text-white">
              <X className="size-6" />
            </button>
            {hasPrev && (
              <button onClick={e => { e.stopPropagation(); setLightbox({ ...lightbox, index: lightbox.index - 1 }) }}
                className="absolute left-4 top-1/2 -translate-y-1/2 text-white/50 hover:text-white text-3xl px-2 py-4">
                &#8249;
              </button>
            )}
            {hasNext && (
              <button onClick={e => { e.stopPropagation(); setLightbox({ ...lightbox, index: lightbox.index + 1 }) }}
                className="absolute right-4 top-1/2 -translate-y-1/2 text-white/50 hover:text-white text-3xl px-2 py-4">
                &#8250;
              </button>
            )}
            <img src={api.iterations.visualUrl(iter.id, current.filename)} alt={current.filename}
              onClick={e => e.stopPropagation()}
              className="max-w-[90vw] max-h-[90vh] object-contain rounded shadow-2xl" />
            {imageVisuals.length > 1 && (
              <div className="absolute bottom-4 text-white/50 text-xs font-mono">
                {lightbox.index + 1} / {imageVisuals.length}
              </div>
            )}
          </div>
        )
      })()}
    </>
  )
}
