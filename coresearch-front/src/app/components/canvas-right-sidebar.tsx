import { memo, useMemo, useState } from 'react'
import { GitBranch, GitCompare, FileCode, Loader2, Sparkles, Terminal as TerminalIcon, Trash2, Upload, X } from 'lucide-react'
import Markdown from 'react-markdown'
import { useWorkflow } from '../context/workflow-context'
import { useCanvasStore } from './canvas-store'
import { api } from '../api/client'
import { Button } from './ui/button'

const mdComponents = {
  h1: (p: any) => <h1 className="text-sm font-semibold text-[#c9d1d9] mb-1" {...p} />,
  h2: (p: any) => <h2 className="text-xs font-semibold text-[#c9d1d9] mb-1" {...p} />,
  h3: (p: any) => <h3 className="text-xs font-semibold text-[#c9d1d9] mb-1" {...p} />,
  p: (p: any) => <p className="text-xs text-[#c9d1d9] mb-2 leading-relaxed" {...p} />,
  ul: (p: any) => <ul className="text-xs text-[#c9d1d9] list-disc pl-4 mb-2 space-y-0.5" {...p} />,
  ol: (p: any) => <ol className="text-xs text-[#c9d1d9] list-decimal pl-4 mb-2 space-y-0.5" {...p} />,
  li: (p: any) => <li className="text-xs text-[#c9d1d9]" {...p} />,
  code: (p: any) => <code className="text-xs font-mono bg-[#161b22] px-1 rounded text-[#79c0ff]" {...p} />,
  pre: (p: any) => <pre className="text-xs font-mono bg-[#161b22] p-2 rounded mb-2 overflow-x-auto" {...p} />,
  strong: (p: any) => <strong className="text-[#c9d1d9] font-semibold" {...p} />,
  em: (p: any) => <em className="text-[#8b949e]" {...p} />,
}

function MdPreview({ label, content, onExpand }: { label: string; content: string; onExpand: () => void }) {
  const truncated = content.length > 200

  return (
    <div
      onClick={onExpand}
      className="p-2 rounded cursor-pointer bg-[#0d1117] border border-[#30363d] hover:border-[#8b949e] transition-colors"
    >
      <div className="text-xs text-[#8b949e] mb-1">{label}</div>
      <div className="max-h-24 overflow-hidden relative">
        <Markdown components={mdComponents}>{truncated ? content.slice(0, 200) + '...' : content}</Markdown>
        {truncated && (
          <div className="absolute bottom-0 left-0 right-0 h-6 bg-gradient-to-t from-[#0d1117] to-transparent" />
        )}
      </div>
    </div>
  )
}

function MdOverlay({ panels, onClose }: { panels: { label: string; content: string }[]; onClose: () => void }) {
  const sideBySide = panels.length > 1

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onClose}
      onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); onClose() } }}
      tabIndex={0}
      ref={el => el?.focus()}
    >
      <div
        className={`bg-[#0d1117] border border-[#30363d] rounded-xl max-h-[80vh] overflow-hidden m-4 shadow-2xl flex flex-col ${
          sideBySide ? 'max-w-5xl w-full' : 'max-w-2xl w-full'
        }`}
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 pt-4 pb-2 shrink-0">
          <div className="flex items-center gap-3">
            {panels.map((p, i) => (
              <span key={i} className="text-sm text-[#8b949e] font-semibold">
                {p.label}{i < panels.length - 1 && <span className="ml-3 text-[#30363d]">|</span>}
              </span>
            ))}
          </div>
          <button onClick={onClose} className="text-[#484f58] hover:text-[#c9d1d9] transition-colors">
            <X className="size-4" />
          </button>
        </div>
        <div className={`flex-1 overflow-hidden flex ${sideBySide ? 'divide-x divide-[#30363d]' : ''}`}>
          {panels.map((p, i) => (
            <div key={i} className="flex-1 overflow-y-auto p-6">
              {sideBySide && (
                <div className="text-xs text-[#58a6ff] font-semibold mb-3 uppercase tracking-wide">{p.label}</div>
              )}
              <Markdown components={mdComponents}>{p.content}</Markdown>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function IterationDocs({ hypothesis, analysis }: { hypothesis: string | null; analysis: string | null }) {
  const [overlayOpen, setOverlayOpen] = useState(false)

  const panels: { label: string; content: string }[] = []
  if (hypothesis) panels.push({ label: 'hypothesis', content: hypothesis })
  if (analysis) panels.push({ label: 'analysis', content: analysis })

  return (
    <>
      {hypothesis && (
        <MdPreview label="hypothesis" content={hypothesis} onExpand={() => setOverlayOpen(true)} />
      )}
      {analysis && (
        <MdPreview label="analysis" content={analysis} onExpand={() => setOverlayOpen(true)} />
      )}
      {overlayOpen && (
        <MdOverlay panels={panels} onClose={() => setOverlayOpen(false)} />
      )}
    </>
  )
}

export const RightSidebar = memo(function RightSidebar() {
  const { seeds, branches, iterations, aliveBranches, currentProject, selectProject, renewBranch, forkBranch, deleteBranch } = useWorkflow()

  const selection = useCanvasStore(s => s.getSelection())
  const setSelection = useCanvasStore(s => s.setSelection)
  const selectedIterationIds = useCanvasStore(s => s.selectedIterationIds)
  const mainMetric = useCanvasStore(s => s.mainMetric)
  const setMainMetric = useCanvasStore(s => s.setMainMetric)
  const attachedBranchId = useCanvasStore(s => s.attachedBranchId)
  const setAttachedBranchId = useCanvasStore(s => s.setAttachedBranchId)
  const setTextOverlay = useCanvasStore(s => s.setTextOverlay)
  const setLightbox = useCanvasStore(s => s.setLightbox)
  const openFileBrowser = useCanvasStore(s => s.openFileBrowser)
  const fileBrowserLoading = useCanvasStore(s => s.fileBrowserLoading)
  const setForkName = useCanvasStore(s => s.setForkName)
  const setForkAgent = useCanvasStore(s => s.setForkAgent)
  const setForkDialog = useCanvasStore(s => s.setForkDialog)
  const pushing = useCanvasStore(s => s.pushing)
  const setPushing = useCanvasStore(s => s.setPushing)
  const pushResult = useCanvasStore(s => s.pushResult)
  const setPushResult = useCanvasStore(s => s.setPushResult)
  const submitting = useCanvasStore(s => s.submitting)
  const setSubmitting = useCanvasStore(s => s.setSubmitting)
  const error = useCanvasStore(s => s.error)
  const setError = useCanvasStore(s => s.setError)
  const diffLoading = useCanvasStore(s => s.diffLoading)
  const setDiffLoading = useCanvasStore(s => s.setDiffLoading)
  const setDiffOverlay = useCanvasStore(s => s.setDiffOverlay)

  const selectedSeed = seeds.find(s => s.id === selection?.seedId)
  const selectedBranch = selection?.type === 'branch' || selection?.type === 'iteration'
    ? (branches[selection.seedId] ?? []).find(b => b.id === selection.branchId)
    : undefined
  const selectedIteration = selection?.type === 'iteration'
    ? (iterations[selection.branchId] ?? []).find(it => it.id === selection.iterationId)
    : undefined

  const sessionAlive = selection?.type === 'branch' ? aliveBranches.has(selection.branchId) : false

  if (!selectedSeed && !selectedBranch && !selectedIteration) return null

  return (
    <div className="w-80 border-l border-[#30363d] bg-[#161b22] p-6 overflow-y-auto">
      <div className="space-y-4">
        <div className="flex justify-end">
          <button
            onClick={() => setSelection(null)}
            className="text-[#484f58] hover:text-[#c9d1d9] transition-colors"
          >
            <X className="size-4" />
          </button>
        </div>

        {/* === SEED === */}
        {selectedSeed && selection?.type === 'seed' && (
          <>
            <div>
              <div className="text-xs text-[#8b949e] mb-1">name</div>
              <div className="text-[#c9d1d9]">{selectedSeed.name}</div>
            </div>
            <div>
              <div className="text-xs text-[#8b949e] mb-1">repository</div>
              <div className="text-[#c9d1d9] text-sm font-mono bg-[#0d1117] p-2 rounded border border-[#30363d] break-all">
                {selectedSeed.repository_url}
              </div>
            </div>
            <div className="flex gap-2">
              <div className="flex-1">
                <div className="text-xs text-[#8b949e] mb-1">branch</div>
                <div className="text-[#c9d1d9] text-sm font-mono">{selectedSeed.branch}</div>
              </div>
              <div className="flex-1">
                <div className="text-xs text-[#8b949e] mb-1">commit</div>
                <div className="text-[#6e7681] text-xs font-mono">{selectedSeed.commit.slice(0, 12)}</div>
              </div>
            </div>
            <Button
              onClick={() => useCanvasStore.getState().setDeleteSeedDialog({
                seedId: selectedSeed.id,
                seedName: selectedSeed.name,
              })}
              size="sm"
              className="w-full bg-[#1f2937] hover:bg-[#374151] text-[#f85149] hover:text-[#ff7b72] gap-2 border border-[#30363d]"
            >
              <Trash2 className="size-4" />
              delete seed
            </Button>
          </>
        )}

        {/* === BRANCH === */}
        {selectedBranch && selection?.type === 'branch' && (
          <>
            <div>
              <div className="text-xs text-[#8b949e] mb-1">branch</div>
              <div className="text-[#c9d1d9]">{selectedBranch.name}</div>
            </div>
            <div
              onClick={() => setTextOverlay({ type: 'branch-description', branchId: selectedBranch.id, value: selectedBranch.description })}
              className="p-2 rounded cursor-pointer bg-[#0d1117] border border-[#30363d] hover:border-[#8b949e] transition-colors"
            >
              <div className="text-xs text-[#8b949e] mb-1">description</div>
              <div className="text-[#c9d1d9] text-xs">
                {selectedBranch.description || <span className="text-[#6e7681] italic">click to add...</span>}
              </div>
            </div>
            {selectedBranch.git_branch && (
              <div>
                <div className="text-xs text-[#8b949e] mb-1">git branch</div>
                <div className="text-[#c9d1d9] text-xs font-mono bg-[#0d1117] p-2 rounded border border-[#30363d] break-all">
                  {selectedBranch.git_branch}
                </div>
              </div>
            )}
            <div className="flex gap-2">
              <div className="flex-1">
                <div className="text-xs text-[#8b949e] mb-1">commit</div>
                <div className="text-[#6e7681] text-xs font-mono">{selectedBranch.commit.slice(0, 12)}</div>
              </div>
              {selectedBranch.session && (
                <div className="flex-1">
                  <div className="text-xs text-[#8b949e] mb-1">agent</div>
                  <div className="text-[#c9d1d9] text-sm">{selectedBranch.session.agent}</div>
                </div>
              )}
            </div>
            {(() => {
              const branchIters = iterations[selectedBranch.id] ?? []
              const allKeys = [...new Set(branchIters.flatMap(it => it.metrics.map(m => m.key)))]
              if (allKeys.length === 0) return null
              const current = mainMetric[selectedBranch.id] ?? ''
              const points = current
                ? branchIters
                    .map(it => ({ hash: it.hash, value: it.metrics.find(m => m.key === current)?.value }))
                    .filter((p): p is { hash: string; value: number } => p.value !== undefined)
                : []

              const chartW = 240
              const chartH = 100
              const pad = { top: 10, right: 10, bottom: 20, left: 35 }
              const w = chartW - pad.left - pad.right
              const h = chartH - pad.top - pad.bottom
              const minV = points.length ? Math.min(...points.map(p => p.value)) : 0
              const maxV = points.length ? Math.max(...points.map(p => p.value)) : 1
              const rangeV = maxV > minV ? maxV - minV : 1

              return (
                <div className="space-y-2">
                  <div>
                    <div className="text-xs text-[#8b949e] mb-1">main metric</div>
                    <select
                      value={current}
                      onChange={e => setMainMetric({ ...mainMetric, [selectedBranch.id]: e.target.value })}
                      className="w-full bg-[#0d1117] border border-[#30363d] text-[#c9d1d9] text-xs font-mono rounded px-2 py-1.5 outline-none"
                    >
                      <option value="">none</option>
                      {allKeys.map(k => <option key={k} value={k}>{k}</option>)}
                    </select>
                  </div>
                  {points.length >= 2 && (
                    <div
                      className="bg-[#0d1117] rounded border border-[#30363d] p-2 cursor-pointer hover:border-[#8b949e] transition-colors"
                      onClick={() => setTextOverlay({ type: 'metric-chart', branchId: selectedBranch.id, metricKey: current })}
                    >
                      <svg width={chartW} height={chartH} className="w-full">
                        <text x={pad.left - 4} y={pad.top + 3} fill="#6e7681" fontSize="8" textAnchor="end" className="font-mono">
                          {maxV % 1 === 0 ? maxV : maxV.toFixed(2)}
                        </text>
                        <text x={pad.left - 4} y={pad.top + h + 3} fill="#6e7681" fontSize="8" textAnchor="end" className="font-mono">
                          {minV % 1 === 0 ? minV : minV.toFixed(2)}
                        </text>
                        <line x1={pad.left} y1={pad.top} x2={pad.left + w} y2={pad.top} stroke="#21262d" strokeWidth={0.5} />
                        <line x1={pad.left} y1={pad.top + h} x2={pad.left + w} y2={pad.top + h} stroke="#21262d" strokeWidth={0.5} />
                        <line x1={pad.left} y1={pad.top + h / 2} x2={pad.left + w} y2={pad.top + h / 2} stroke="#21262d" strokeWidth={0.5} strokeDasharray="3 3" />
                        <polyline
                          fill="none" stroke="#58a6ff" strokeWidth={1.5}
                          points={points.map((p, i) => {
                            const x = pad.left + (i / (points.length - 1)) * w
                            const y = pad.top + h - ((p.value - minV) / rangeV) * h
                            return `${x},${y}`
                          }).join(' ')}
                        />
                        {points.map((p, i) => {
                          const x = pad.left + (i / (points.length - 1)) * w
                          const y = pad.top + h - ((p.value - minV) / rangeV) * h
                          return (
                            <g key={i}>
                              <circle cx={x} cy={y} r={2.5} fill="#58a6ff" />
                              {points.length <= 10 && (
                                <text x={x} y={chartH - 4} fill="#6e7681" fontSize="7" textAnchor="middle" className="font-mono">
                                  {p.hash.slice(0, 4)}
                                </text>
                              )}
                            </g>
                          )
                        })}
                      </svg>
                    </div>
                  )}
                </div>
              )
            })()}

            <Button
              onClick={async () => {
                if (attachedBranchId === selectedBranch.id) {
                  setAttachedBranchId(null)
                } else {
                  // Auto-renew if session is dead
                  if (!sessionAlive) {
                    await renewBranch(selectedBranch.seed_id, selectedBranch.id)
                  }
                  setAttachedBranchId(selectedBranch.id)
                }
              }}
              size="sm"
              className={attachedBranchId === selectedBranch.id
                ? 'w-full bg-[#da3633] hover:bg-[#f85149] text-white gap-2'
                : 'w-full bg-[#238636] hover:bg-[#2ea043] text-white gap-2'}
            >
              <TerminalIcon className="size-4" />
              {attachedBranchId === selectedBranch.id ? 'detach' : 'attach terminal'}
            </Button>
            {sessionAlive && (
              <Button
                onClick={async () => {
                  await api.branches.kill(selectedBranch.id)
                  if (attachedBranchId === selectedBranch.id) setAttachedBranchId(null)
                }}
                size="sm"
                className="w-full bg-[#1f2937] hover:bg-[#374151] text-[#f85149] hover:text-[#ff7b72] gap-2 border border-[#30363d]"
              >
                <X className="size-4" />
                kill session
              </Button>
            )}
            {selectedBranch.git_branch && (
              <Button
                disabled={pushing}
                onClick={async () => {
                  setPushing(true)
                  setPushResult(null)
                  try {
                    const res = await api.branches.push(selectedBranch.id)
                    setPushResult(res.message)
                  } catch (e: any) {
                    setPushResult(`error: ${e.message}`)
                  } finally {
                    setPushing(false)
                  }
                }}
                size="sm"
                className="w-full bg-[#1f2937] hover:bg-[#374151] text-[#c9d1d9] gap-2 border border-[#30363d]"
              >
                {pushing ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
                push to remote
              </Button>
            )}
            {pushResult && (
              <p className={`text-xs font-mono break-all ${pushResult.startsWith('error') ? 'text-[#f85149]' : 'text-[#3fb950]'}`}>
                {pushResult}
              </p>
            )}
            <Button
              onClick={() => useCanvasStore.getState().setDeleteDialog({
                seedId: selectedBranch.seed_id,
                branchId: selectedBranch.id,
                branchName: selectedBranch.name,
              })}
              size="sm"
              className="w-full bg-[#1f2937] hover:bg-[#374151] text-[#f85149] hover:text-[#ff7b72] gap-2 border border-[#30363d]"
            >
              <Trash2 className="size-4" />
              delete branch
            </Button>
          </>
        )}

        {/* === ITERATION === */}
        {selectedIteration && (
          <>
            <div>
              <div className="text-xs text-[#8b949e] mb-1">commit</div>
              <div className="text-[#6e7681] text-xs font-mono">{selectedIteration.hash.slice(0, 12)}</div>
            </div>
            {(selectedIteration.hypothesis || selectedIteration.analysis) && (
              <IterationDocs
                hypothesis={selectedIteration.hypothesis}
                analysis={selectedIteration.analysis}
              />
            )}
            <div
              onClick={() => setTextOverlay({ type: 'iteration-comments', iterationId: selectedIteration.id })}
              className="p-2 rounded cursor-pointer bg-[#0d1117] border border-[#30363d] hover:border-[#8b949e] transition-colors"
            >
              <div className="text-xs text-[#8b949e] mb-1">comments</div>
              <div className="text-[#c9d1d9] text-xs">
                {selectedIteration.comments.length > 0
                  ? `${selectedIteration.comments.length} comment${selectedIteration.comments.length > 1 ? 's' : ''}`
                  : <span className="text-[#6e7681] italic">click to add...</span>}
              </div>
            </div>
            {selectedIteration.metrics.length > 0 && (
              <div>
                <div className="text-xs text-[#8b949e] mb-2">metrics</div>
                <div className="space-y-1">
                  {selectedIteration.metrics.map(m => (
                    <div key={m.id} className="flex justify-between text-xs bg-[#0d1117] px-2 py-1 rounded border border-[#30363d]">
                      <span className="text-[#8b949e]">{m.key}</span>
                      <span className="text-[#c9d1d9] font-mono">{m.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {selectedIteration.visuals.length > 0 && (
              <div>
                <div className="text-xs text-[#8b949e] mb-2">visuals</div>
                <div className="space-y-2">
                  {selectedIteration.visuals.map((v) => (
                    v.format === 'html' ? (
                      <a key={v.id}
                        href={api.iterations.visualUrl(selectedIteration.id, v.filename)}
                        target="_blank" rel="noreferrer"
                        className="block text-xs text-[#58a6ff] underline font-mono truncate">
                        {v.filename}
                      </a>
                    ) : (
                      <img key={v.id}
                        src={api.iterations.visualUrl(selectedIteration.id, v.filename)}
                        alt={v.filename}
                        onClick={() => setLightbox({ iterationId: selectedIteration.id, index: selectedIteration.visuals.filter(x => x.format !== 'html').indexOf(v) })}
                        className="w-full rounded border border-[#30363d] cursor-pointer hover:border-[#58a6ff] transition-colors" />
                    )
                  ))}
                </div>
              </div>
            )}
            <Button
              onClick={() => {
                if (!selection || selection.type !== 'iteration') return
                openFileBrowser(selection.branchId, selectedIteration.hash)
              }}
              disabled={fileBrowserLoading}
              size="sm"
              className="w-full bg-[#1f2937] hover:bg-[#374151] text-[#c9d1d9] gap-2 border border-[#30363d]"
            >
              {fileBrowserLoading ? <Loader2 className="size-4 animate-spin" /> : <FileCode className="size-4" />}
              browse files
            </Button>
            <Button
              onClick={() => { setForkName(''); setForkAgent('default'); setForkDialog(true) }}
              size="sm"
              className="w-full bg-[#238636] hover:bg-[#2ea043] text-white gap-2"
            >
              <GitBranch className="size-4" />
              fork branch
            </Button>
            {selectedBranch?.git_branch && selection?.type === 'iteration' && (
              <>
                <Button
                  disabled={pushing}
                  onClick={async () => {
                    setPushing(true)
                    setPushResult(null)
                    try {
                      const res = await api.branches.push(selection.branchId, selectedIteration.hash)
                      setPushResult(res.message)
                    } catch (e: any) {
                      setPushResult(`error: ${e.message}`)
                    } finally {
                      setPushing(false)
                    }
                  }}
                  size="sm"
                  className="w-full bg-[#1f2937] hover:bg-[#374151] text-[#c9d1d9] gap-2 border border-[#30363d]"
                >
                  {pushing ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
                  push to remote
                </Button>
                {pushResult && (
                  <p className={`text-xs font-mono break-all ${pushResult.startsWith('error') ? 'text-[#f85149]' : 'text-[#3fb950]'}`}>
                    {pushResult}
                  </p>
                )}
                <Button
                  disabled={submitting}
                  onClick={async () => {
                    setSubmitting(true)
                    setError(null)
                    try {
                      const seedName = selectedIteration.name !== selectedIteration.hash
                        ? selectedIteration.name
                        : `${selectedBranch!.name}-${selectedIteration.hash.slice(0, 6)}`
                      await api.seeds.fromIteration(
                        currentProject!.id, seedName, selection.branchId, selectedIteration.hash,
                      )
                      await selectProject(currentProject!)
                    } catch (e: any) {
                      setError(e.message)
                    } finally {
                      setSubmitting(false)
                    }
                  }}
                  size="sm"
                  className="w-full bg-[#1f2937] hover:bg-[#374151] text-[#c9d1d9] gap-2 border border-[#30363d]"
                >
                  {submitting ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
                  seed from iteration
                </Button>
              </>
            )}
            {error && <p className="text-xs text-[#f85149] break-all">{error}</p>}
          </>
        )}

        {/* === MULTI-SELECT DIFF === */}
        {selectedIterationIds.size >= 2 && selection?.type === 'iteration' && (
          <div className="pt-2 border-t border-[#30363d]">
            <div className="text-xs text-[#8b949e] mb-2">
              {selectedIterationIds.size} iterations selected
            </div>
            <Button
              onClick={async () => {
                const branchIters = iterations[selection.branchId] ?? []
                const selected = branchIters.filter(it => selectedIterationIds.has(it.id))
                if (selected.length < 2) return
                selected.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
                const from = selected[0]
                const to = selected[selected.length - 1]
                setDiffLoading(true)
                try {
                  const content = await api.diff.get(selection.branchId, from.hash, to.hash)
                  setDiffOverlay({ content, from: from.hash.slice(0, 8), to: to.hash.slice(0, 8) })
                } catch (e: any) {
                  setDiffOverlay({ content: `Error: ${e.message}`, from: from.hash.slice(0, 8), to: to.hash.slice(0, 8) })
                } finally {
                  setDiffLoading(false)
                }
              }}
              disabled={diffLoading}
              size="sm"
              className="w-full bg-[#1f2937] hover:bg-[#374151] text-[#c9d1d9] gap-2 border border-[#30363d]"
            >
              {diffLoading ? <Loader2 className="size-4 animate-spin" /> : <GitCompare className="size-4" />}
              show diff
            </Button>
          </div>
        )}
      </div>
    </div>
  )
})
