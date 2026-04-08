import { Loader2, FileCode, Sparkles, Trash2, X } from 'lucide-react'
import { useWorkflow } from '../context/workflow-context'
import { api } from '../api/client'
import { useCanvasStore } from './canvas-store'
import { Button } from './ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from './ui/dialog'
import { Input } from './ui/input'
import { Label } from './ui/label'
import { HighlightedEditor } from './ui/highlighted-editor'

export function CanvasDialogs() {
  const { addSeed, addBranch, forkBranch, deleteBranch, deleteSeed, iterations } = useWorkflow()

  // Dialog visibility
  const seedDialog = useCanvasStore(s => s.seedDialog)
  const setSeedDialog = useCanvasStore(s => s.setSeedDialog)
  const branchDialog = useCanvasStore(s => s.branchDialog)
  const setBranchDialog = useCanvasStore(s => s.setBranchDialog)
  const forkDialog = useCanvasStore(s => s.forkDialog)
  const setForkDialog = useCanvasStore(s => s.setForkDialog)
  const deleteDialog = useCanvasStore(s => s.deleteDialog)
  const setDeleteDialog = useCanvasStore(s => s.setDeleteDialog)
  const deleteSeedDialog = useCanvasStore(s => s.deleteSeedDialog)
  const setDeleteSeedDialog = useCanvasStore(s => s.setDeleteSeedDialog)

  // Form fields
  const seedName = useCanvasStore(s => s.seedName); const setSeedName = useCanvasStore(s => s.setSeedName)
  const seedUrl = useCanvasStore(s => s.seedUrl); const setSeedUrl = useCanvasStore(s => s.setSeedUrl)
  const seedBranch = useCanvasStore(s => s.seedBranch); const setSeedBranch = useCanvasStore(s => s.setSeedBranch)
  const seedCommit = useCanvasStore(s => s.seedCommit); const setSeedCommit = useCanvasStore(s => s.setSeedCommit)
  const seedToken = useCanvasStore(s => s.seedToken); const setSeedToken = useCanvasStore(s => s.setSeedToken)
  const branchName = useCanvasStore(s => s.branchName); const setBranchName = useCanvasStore(s => s.setBranchName)
  const branchDesc = useCanvasStore(s => s.branchDesc); const setBranchDesc = useCanvasStore(s => s.setBranchDesc)
  const branchAgent = useCanvasStore(s => s.branchAgent); const setBranchAgent = useCanvasStore(s => s.setBranchAgent)
  const forkName = useCanvasStore(s => s.forkName); const setForkName = useCanvasStore(s => s.setForkName)
  const forkAgent = useCanvasStore(s => s.forkAgent); const setForkAgent = useCanvasStore(s => s.setForkAgent)
  const submitting = useCanvasStore(s => s.submitting); const setSubmitting = useCanvasStore(s => s.setSubmitting)
  const error = useCanvasStore(s => s.error); const setError = useCanvasStore(s => s.setError)

  // Fork editor
  const forkEditorBranchId = useCanvasStore(s => s.forkEditorBranchId); const setForkEditorBranchId = useCanvasStore(s => s.setForkEditorBranchId)
  const forkEditorFiles = useCanvasStore(s => s.forkEditorFiles); const setForkEditorFiles = useCanvasStore(s => s.setForkEditorFiles)
  const forkEditorSelected = useCanvasStore(s => s.forkEditorSelected); const setForkEditorSelected = useCanvasStore(s => s.setForkEditorSelected)
  const forkEditorContent = useCanvasStore(s => s.forkEditorContent); const setForkEditorContent = useCanvasStore(s => s.setForkEditorContent)
  const forkEditorDirty = useCanvasStore(s => s.forkEditorDirty); const setForkEditorDirty = useCanvasStore(s => s.setForkEditorDirty)
  const forkEditorSaving = useCanvasStore(s => s.forkEditorSaving); const setForkEditorSaving = useCanvasStore(s => s.setForkEditorSaving)

  // Selection
  const selection = useCanvasStore(s => s.getSelection())

  // Derive selected iteration for fork dialog
  const selectedIteration = selection?.type === 'iteration'
    ? (iterations[selection.branchId] ?? []).find(it => it.id === selection.iterationId)
    : undefined

  const handleAddSeed = async () => {
    if (!seedName || !seedUrl) return
    setSubmitting(true); setError(null)
    try {
      await addSeed(seedName, seedUrl, seedBranch || undefined, seedCommit || undefined, seedToken || undefined)
      setSeedName(''); setSeedUrl(''); setSeedBranch(''); setSeedCommit(''); setSeedToken(''); setSeedDialog(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create seed')
    } finally {
      setSubmitting(false)
    }
  }

  const handleAddBranch = async () => {
    if (selection?.type !== 'seed' || !branchName) return
    setSubmitting(true); setError(null)
    try {
      await addBranch(selection.seedId, branchName, 'tmux', branchAgent, branchDesc)
      setBranchName(''); setBranchDesc(''); setBranchAgent('default'); setBranchDialog(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create branch')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      {/* New seed dialog */}
      <Dialog open={seedDialog} onOpenChange={setSeedDialog}>
        <DialogContent className="bg-[#161b22] border-[#30363d] text-[#c9d1d9]">
          <DialogHeader>
            <DialogTitle className="text-[#58a6ff]">create new seed</DialogTitle>
          </DialogHeader>
          <form className="space-y-4" onSubmit={e => { e.preventDefault(); handleAddSeed() }}>
            <div>
              <Label className="text-[#c9d1d9]">name</Label>
              <Input value={seedName} onChange={e => setSeedName(e.target.value)}
                className="bg-[#0d1117] border-[#30363d] text-[#c9d1d9] font-mono"
                placeholder="my-project" />
            </div>
            <div>
              <Label className="text-[#c9d1d9]">repository url</Label>
              <Input value={seedUrl} onChange={e => setSeedUrl(e.target.value)}
                className="bg-[#0d1117] border-[#30363d] text-[#c9d1d9] font-mono"
                placeholder="https://github.com/user/repo.git" />
            </div>
            <div className="flex gap-2">
              <div className="flex-1">
                <Label className="text-[#c9d1d9]">branch <span className="text-[#6e7681]">(optional)</span></Label>
                <Input value={seedBranch} onChange={e => setSeedBranch(e.target.value)}
                  className="bg-[#0d1117] border-[#30363d] text-[#c9d1d9] font-mono"
                  placeholder="main" />
              </div>
              <div className="flex-1">
                <Label className="text-[#c9d1d9]">commit <span className="text-[#6e7681]">(optional)</span></Label>
                <Input value={seedCommit} onChange={e => setSeedCommit(e.target.value)}
                  className="bg-[#0d1117] border-[#30363d] text-[#c9d1d9] font-mono"
                  placeholder="abc1234" />
              </div>
            </div>
            <div>
              <Label className="text-[#c9d1d9]">access token <span className="text-[#6e7681]">(optional, for private repos)</span></Label>
              <Input type="password" value={seedToken} onChange={e => setSeedToken(e.target.value)}
                className="bg-[#0d1117] border-[#30363d] text-[#c9d1d9] font-mono"
                placeholder="ghp_..." />
            </div>
            {error && <p className="text-xs text-[#f85149]">{error}</p>}
            <Button type="submit" disabled={submitting}
              className="w-full bg-[#238636] hover:bg-[#2ea043] text-white">
              {submitting ? <Loader2 className="size-4 animate-spin mr-2" /> : null}
              create seed
            </Button>
          </form>
        </DialogContent>
      </Dialog>

      {/* New branch dialog */}
      <Dialog open={branchDialog} onOpenChange={setBranchDialog}>
        <DialogContent className="bg-[#161b22] border-[#30363d] text-[#c9d1d9]">
          <DialogHeader>
            <DialogTitle className="text-[#58a6ff]">create new branch</DialogTitle>
          </DialogHeader>
          <form className="space-y-4" onSubmit={e => { e.preventDefault(); handleAddBranch() }}>
            <div>
              <Label className="text-[#c9d1d9]">name</Label>
              <Input value={branchName} onChange={e => setBranchName(e.target.value)}
                className="bg-[#0d1117] border-[#30363d] text-[#c9d1d9] font-mono"
                placeholder="experiment-a" />
            </div>
            <div>
              <Label className="text-[#c9d1d9]">description <span className="text-[#6e7681]">(optional)</span></Label>
              <Input value={branchDesc} onChange={e => setBranchDesc(e.target.value)}
                className="bg-[#0d1117] border-[#30363d] text-[#c9d1d9] font-mono"
                placeholder="what this branch explores..." />
            </div>
            <div>
              <Label className="text-[#c9d1d9]">agent</Label>
              <Input value={branchAgent} onChange={e => setBranchAgent(e.target.value)}
                className="bg-[#0d1117] border-[#30363d] text-[#c9d1d9] font-mono"
                placeholder="default" />
            </div>
            {error && <p className="text-xs text-[#f85149]">{error}</p>}
            <Button type="submit" disabled={submitting}
              className="w-full bg-[#238636] hover:bg-[#2ea043] text-white">
              {submitting ? <Loader2 className="size-4 animate-spin mr-2" /> : null}
              create branch
            </Button>
          </form>
        </DialogContent>
      </Dialog>

      {/* Fork branch dialog */}
      <Dialog open={forkDialog} onOpenChange={setForkDialog}>
        <DialogContent className="bg-[#161b22] border-[#30363d] text-[#c9d1d9]">
          <DialogHeader>
            <DialogTitle className="text-[#58a6ff]">fork branch from iteration</DialogTitle>
          </DialogHeader>
          {selectedIteration && (
            <div className="text-xs font-mono text-[#8b949e] bg-[#0d1117] px-2 py-1 rounded border border-[#30363d]">
              from commit {selectedIteration.hash.slice(0, 8)}
            </div>
          )}
          <form className="space-y-4" onSubmit={async e => {
            e.preventDefault()
            if (!selection || selection.type !== 'iteration' || !selectedIteration) return
            setSubmitting(true)
            setError(null)
            try {
              const newBranch = await forkBranch(selection.branchId, selection.seedId, forkName, selectedIteration.hash, forkAgent)
              setForkDialog(false)
              const files = await api.workdir.list(newBranch.id)
              setForkEditorBranchId(newBranch.id)
              setForkEditorFiles(files)
              setForkEditorSelected(null)
              setForkEditorContent('')
              setForkEditorDirty(false)
            } catch (e: any) {
              setError(e.message)
            } finally {
              setSubmitting(false)
            }
          }}>
            <div>
              <Label className="text-[#c9d1d9]">name</Label>
              <Input value={forkName} onChange={e => setForkName(e.target.value)}
                className="bg-[#0d1117] border-[#30363d] text-[#c9d1d9] font-mono"
                placeholder="fork-experiment" />
            </div>
            <div>
              <Label className="text-[#c9d1d9]">agent</Label>
              <Input value={forkAgent} onChange={e => setForkAgent(e.target.value)}
                className="bg-[#0d1117] border-[#30363d] text-[#c9d1d9] font-mono"
                placeholder="default" />
            </div>
            {error && <p className="text-xs text-[#f85149]">{error}</p>}
            <Button type="submit" disabled={submitting}
              className="w-full bg-[#238636] hover:bg-[#2ea043] text-white">
              {submitting ? <Loader2 className="size-4 animate-spin mr-2" /> : null}
              fork branch
            </Button>
          </form>
        </DialogContent>
      </Dialog>

      {/* Delete branch confirmation */}
      <Dialog open={deleteDialog !== null} onOpenChange={open => { if (!open) setDeleteDialog(null) }}>
        <DialogContent className="bg-[#161b22] border-[#30363d] text-[#c9d1d9]">
          <DialogHeader>
            <DialogTitle className="text-[#f85149]">delete branch</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-[#8b949e]">
            Are you sure you want to delete <span className="text-[#c9d1d9] font-semibold">{deleteDialog?.branchName}</span> and
            all its child branches? Working directories will be moved to <code className="text-xs bg-[#0d1117] px-1 py-0.5 rounded">.fordeletion</code>.
          </p>
          {error && <p className="text-xs text-[#f85149]">{error}</p>}
          <div className="flex gap-2 justify-end">
            <Button
              onClick={() => setDeleteDialog(null)}
              size="sm"
              className="bg-[#21262d] hover:bg-[#30363d] text-[#c9d1d9] border border-[#30363d]"
            >
              cancel
            </Button>
            <Button
              disabled={submitting}
              onClick={async () => {
                if (!deleteDialog) return
                setSubmitting(true); setError(null)
                try {
                  await deleteBranch(deleteDialog.seedId, deleteDialog.branchId)
                  setDeleteDialog(null)
                } catch (e) {
                  setError(e instanceof Error ? e.message : 'Failed to delete branch')
                } finally {
                  setSubmitting(false)
                }
              }}
              size="sm"
              className="bg-[#da3633] hover:bg-[#f85149] text-white gap-2"
            >
              {submitting ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
              delete
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Delete seed confirmation */}
      <Dialog open={deleteSeedDialog !== null} onOpenChange={open => { if (!open) setDeleteSeedDialog(null) }}>
        <DialogContent className="bg-[#161b22] border-[#30363d] text-[#c9d1d9]">
          <DialogHeader>
            <DialogTitle className="text-[#f85149]">delete seed</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-[#8b949e]">
            Are you sure you want to delete <span className="text-[#c9d1d9] font-semibold">{deleteSeedDialog?.seedName}</span> and
            all its branches? Working directories will be moved to <code className="text-xs bg-[#0d1117] px-1 py-0.5 rounded">.fordeletion</code>.
          </p>
          {error && <p className="text-xs text-[#f85149]">{error}</p>}
          <div className="flex gap-2 justify-end">
            <Button onClick={() => setDeleteSeedDialog(null)} size="sm"
              className="bg-[#21262d] hover:bg-[#30363d] text-[#c9d1d9] border border-[#30363d]">
              cancel
            </Button>
            <Button disabled={submitting} size="sm"
              className="bg-[#da3633] hover:bg-[#f85149] text-white gap-2"
              onClick={async () => {
                if (!deleteSeedDialog) return
                setSubmitting(true); setError(null)
                try {
                  await deleteSeed(deleteSeedDialog.seedId)
                  setDeleteSeedDialog(null)
                } catch (e) {
                  setError(e instanceof Error ? e.message : 'Failed to delete seed')
                } finally {
                  setSubmitting(false)
                }
              }}>
              {submitting ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
              delete
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Post-fork file editor */}
      {forkEditorBranchId !== null && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6" onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation() } }}>
          <div className="bg-[#161b22] border border-[#30363d] rounded-lg w-full max-w-5xl h-[80vh] flex flex-col">
            <div className="flex items-center justify-between px-4 py-3 border-b border-[#30363d]">
              <div className="flex items-center gap-2">
                <FileCode className="size-4 text-[#58a6ff]" />
                <span className="text-[#c9d1d9] text-sm font-semibold">edit working tree</span>
                {forkEditorDirty && <span className="text-xs text-[#f0883e]">unsaved changes</span>}
              </div>
              <Button
                disabled={forkEditorSaving}
                onClick={async () => {
                  setForkEditorSaving(true)
                  try {
                    if (forkEditorDirty && forkEditorSelected) {
                      await api.workdir.writeFile(forkEditorBranchId, forkEditorSelected, forkEditorContent)
                    }
                    await api.workdir.commit(forkEditorBranchId)
                    setForkEditorBranchId(null)
                  } finally {
                    setForkEditorSaving(false)
                  }
                }}
                size="sm"
                className="bg-[#238636] hover:bg-[#2ea043] text-white gap-2"
              >
                {forkEditorSaving ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
                done editing
              </Button>
            </div>
            <div className="flex flex-1 overflow-hidden">
              {/* File tree */}
              <div className="w-56 border-r border-[#30363d] overflow-y-auto p-2 space-y-0.5">
                {forkEditorFiles.map(f => (
                  <div key={f}
                    onClick={async () => {
                      if (forkEditorDirty && forkEditorSelected) {
                        await api.workdir.writeFile(forkEditorBranchId, forkEditorSelected, forkEditorContent)
                      }
                      const content = await api.workdir.readFile(forkEditorBranchId, f)
                      setForkEditorSelected(f)
                      setForkEditorContent(content)
                      setForkEditorDirty(false)
                    }}
                    className={`px-2 py-1 rounded text-xs font-mono cursor-pointer truncate transition-colors ${
                      forkEditorSelected === f
                        ? 'bg-[#58a6ff]/20 text-[#58a6ff]'
                        : 'text-[#8b949e] hover:text-[#c9d1d9] hover:bg-[#0d1117]'
                    }`}>
                    {f}
                  </div>
                ))}
              </div>
              {/* Editor */}
              <div className="flex-1 flex flex-col overflow-hidden bg-[#0d1117]">
                {forkEditorSelected ? (
                  <HighlightedEditor
                    content={forkEditorContent}
                    filePath={forkEditorSelected}
                    onChange={v => { setForkEditorContent(v); setForkEditorDirty(true) }}
                  />
                ) : (
                  <div className="flex-1 flex items-center justify-center text-[#6e7681] text-sm">
                    select a file to edit
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
