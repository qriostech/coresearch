import { Plus, GitBranch } from 'lucide-react'
import { useCanvasStore } from './canvas-store'
import { Button } from './ui/button'
import coresearchLogo from './coresearch.png'

export function CanvasHeader() {
  const selection = useCanvasStore(s => s.getSelection())
  const setBranchDialog = useCanvasStore(s => s.setBranchDialog)
  const setSeedDialog = useCanvasStore(s => s.setSeedDialog)

  return (
    <div className="border-b border-[#30363d] bg-[#161b22] px-6 py-3 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <img src={coresearchLogo} alt="coresearch" className="h-15 -my-3" />
        <h1 className="text-lg text-[#c9d1d9]">co.research</h1>
      </div>
      <div className="flex gap-2">
        {selection?.type === 'seed' && (
          <Button onClick={() => setBranchDialog(true)} size="sm"
            className="bg-[#238636] hover:bg-[#2ea043] text-white gap-2">
            <GitBranch className="size-4" /> add branch
          </Button>
        )}
        <Button onClick={() => setSeedDialog(true)} size="sm"
          className="bg-[#238636] hover:bg-[#2ea043] text-white gap-2">
          <Plus className="size-4" /> new seed
        </Button>
      </div>
    </div>
  )
}
