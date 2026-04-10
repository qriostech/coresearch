import { createContext, useContext, useState, useEffect, useCallback, useMemo, useRef, ReactNode } from 'react'
import { api, Project, Seed, Branch, Iteration, Runner, CorySession } from '../api/client'
import { useCanvasStore } from '../components/canvas-store'

interface WorkflowState {
  projects: Project[]
  currentProject: Project | null
  runners: Runner[]
  seeds: Seed[]
  branches: Record<number, Branch[]>
  iterations: Record<number, Iteration[]>
  aliveBranches: Set<number>
  corySessions: CorySession[]
  loading: boolean
  selectProject: (project: Project) => void
  addSeed: (name: string, repository_url: string, branch?: string, commit?: string, access_token?: string) => Promise<Seed>
  addBranch: (seed_id: number, name: string, kind?: string, agent?: string, description?: string) => Promise<Branch>
  renewBranch: (seed_id: number, branch_id: number) => Promise<Branch>
  forkBranch: (branch_id: number, seed_id: number, name: string, iteration_hash: string, agent?: string) => Promise<Branch>
  deleteBranch: (seed_id: number, branch_id: number) => Promise<void>
  deleteSeed: (seed_id: number) => Promise<void>
  addCorySession: (name?: string, agent?: string) => Promise<CorySession>
  killCorySession: (cory_session_id: number) => Promise<void>
  deleteCorySession: (cory_session_id: number) => Promise<void>
  seedPositions: Record<number, { x: number; y: number }>
}

const WorkflowContext = createContext<WorkflowState | undefined>(undefined)

export function WorkflowProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<Project[]>([])
  const [currentProject, setCurrentProject] = useState<Project | null>(null)
  const [runners, setRunners] = useState<Runner[]>([])
  const [seeds, setSeeds] = useState<Seed[]>([])
  const [branches, setBranches] = useState<Record<number, Branch[]>>({})
  const [iterations, setIterations] = useState<Record<number, Iteration[]>>({})
  const [loading, setLoading] = useState(true)
  const [aliveBranches, setAliveBranches] = useState<Set<number>>(new Set())
  const [corySessions, setCorySessions] = useState<CorySession[]>([])

  // Compute canvas positions from seed order (memoized to stabilize context value)
  const seedPositions = useMemo(() => {
    const positions: Record<number, { x: number; y: number }> = {}
    seeds.forEach((seed, i) => {
      const SPACING = 220
      const prev = seeds.slice(0, i)
      const xOffset = prev.reduce((acc, s) => {
        return acc + Math.max(1, (branches[s.id] ?? []).length) * SPACING
      }, 200)
      positions[seed.id] = { x: xOffset, y: 120 }
    })
    return positions
  }, [seeds, branches])

  const loadBranchesForSeeds = useCallback(async (seedList: Seed[]) => {
    const entries = await Promise.all(
      seedList.map(async (s) => {
        const bs = await api.branches.list(s.id)
        return [s.id, bs] as const
      })
    )
    const fetched = Object.fromEntries(entries)
    setBranches(fetched)
    // Populate aliveBranches from session status
    const alive = new Set<number>()
    for (const bs of Object.values(fetched)) {
      for (const b of bs) {
        if (b.session?.status === 'active') alive.add(b.id)
      }
    }
    setAliveBranches(alive)
  }, [])

  const selectProject = useCallback(async (project: Project) => {
    setCurrentProject(project)
    setLoading(true)
    // Clear stale data from the previous project immediately so it doesn't
    // bleed into the new project's rendering or get picked up by polls.
    setSeeds([])
    setBranches({})
    setIterations({})
    setAliveBranches(new Set())
    // Reset canvas UI state (selections, terminals, overlays) tied to old project IDs
    useCanvasStore.getState().resetProject()
    const seedList = await api.seeds.list(project.id)
    setSeeds(seedList)
    await loadBranchesForSeeds(seedList)
    setLoading(false)
  }, [loadBranchesForSeeds])

  useEffect(() => {
    Promise.all([
      api.projects.list(),
      api.runners.list(),
      api.corySessions.list(),
    ])
      .then(async ([projectList, runnerList, coryList]) => {
        setProjects(projectList)
        setRunners(runnerList)
        setCorySessions(coryList)
        if (projectList.length > 0) {
          await selectProject(projectList[0])
        } else {
          setLoading(false)
        }
      })
      .catch((e) => {
        console.error('[coresearch] failed to load:', e)
        setLoading(false)
      })
  }, [])

  // --- Cory session mutations ---

  const addCorySession = useCallback(async (name?: string, agent?: string) => {
    const session = await api.corySessions.create(name, agent)
    setCorySessions(prev => [session, ...prev])
    return session
  }, [])

  const killCorySession = useCallback(async (cory_session_id: number) => {
    await api.corySessions.kill(cory_session_id)
    setCorySessions(prev => prev.map(s =>
      s.id === cory_session_id ? { ...s, status: 'killed', ended_at: new Date().toISOString() } : s
    ))
  }, [])

  const deleteCorySession = useCallback(async (cory_session_id: number) => {
    await api.corySessions.delete(cory_session_id)
    setCorySessions(prev => prev.filter(s => s.id !== cory_session_id))
  }, [])

  const refreshCorySessions = useCallback(async () => {
    try {
      const list = await api.corySessions.list()
      setCorySessions(list)
    } catch {}
  }, [])

  const addSeed = useCallback(async (name: string, repository_url: string, branch?: string, commit?: string, access_token?: string) => {
    if (!currentProject) throw new Error('No project selected')
    const seed = await api.seeds.create(currentProject.id, name, repository_url, branch, commit, access_token)
    setSeeds((prev) => [...prev, seed])
    setBranches((prev) => ({ ...prev, [seed.id]: [] }))
    useCanvasStore.getState().setSeedPanTarget(seed.id)
    return seed
  }, [currentProject])

  const addBranch = useCallback(async (seed_id: number, name: string, kind?: string, agent?: string, description?: string) => {
    const branch = await api.branches.create(seed_id, name, kind, agent, description)
    setBranches((prev) => ({
      ...prev,
      [seed_id]: [...(prev[seed_id] ?? []), branch],
    }))
    return branch
  }, [])

  const renewBranch = useCallback(async (seed_id: number, branch_id: number) => {
    const branch = await api.branches.renew(branch_id)
    setBranches((prev) => ({
      ...prev,
      [seed_id]: (prev[seed_id] ?? []).map(b => b.id === branch_id ? branch : b),
    }))
    return branch
  }, [])

  const forkBranch = useCallback(async (branch_id: number, seed_id: number, name: string, iteration_hash: string, agent?: string) => {
    const branch = await api.branches.fork(branch_id, name, iteration_hash, agent)
    setBranches((prev) => ({
      ...prev,
      [seed_id]: [...(prev[seed_id] ?? []), branch],
    }))
    return branch
  }, [])

  const deleteBranch = useCallback(async (seed_id: number, branch_id: number) => {
    // Collect the branch and all its descendants before the API call
    const allBranches = Object.values(branches).flat()
    const idsToRemove = new Set<number>()
    const collect = (id: number) => {
      idsToRemove.add(id)
      for (const b of allBranches) {
        if (b.parent_branch_id === id && !idsToRemove.has(b.id)) {
          collect(b.id)
        }
      }
    }
    collect(branch_id)

    await api.branches.delete(branch_id)

    // Remove from branches state
    setBranches((prev) => {
      const next: Record<number, Branch[]> = {}
      for (const [sid, list] of Object.entries(prev)) {
        const filtered = list.filter(b => !idsToRemove.has(b.id))
        next[Number(sid)] = filtered
      }
      return next
    })
    // Remove from iterations state
    setIterations((prev) => {
      const next = { ...prev }
      for (const id of idsToRemove) delete next[id]
      return next
    })
    // Remove from alive set
    setAliveBranches((prev) => {
      const next = new Set(prev)
      for (const id of idsToRemove) next.delete(id)
      return next
    })
    // Clean up canvas store
    const store = useCanvasStore.getState()
    if (store.attachedBranchId !== null && idsToRemove.has(store.attachedBranchId)) {
      store.setAttachedBranchId(null)
    }
    const openTerminalsToRemove = store.openedTerminals.filter(id => idsToRemove.has(id))
    if (openTerminalsToRemove.length > 0) {
      useCanvasStore.setState({
        openedTerminals: store.openedTerminals.filter(id => !idsToRemove.has(id)),
      })
    }
    const sel = store.getSelection()
    if (sel && 'branchId' in sel && idsToRemove.has(sel.branchId)) {
      store.setSelection(null)
    }
  }, [branches])

  const deleteSeed = useCallback(async (seed_id: number) => {
    await api.seeds.delete(seed_id)
    setSeeds(prev => prev.filter(s => s.id !== seed_id))
    const branchIds = (branches[seed_id] ?? []).map(b => b.id)
    setBranches(prev => { const next = { ...prev }; delete next[seed_id]; return next })
    setIterations(prev => { const next = { ...prev }; for (const id of branchIds) delete next[id]; return next })
    setAliveBranches(prev => { const next = new Set(prev); for (const id of branchIds) next.delete(id); return next })
    const store = useCanvasStore.getState()
    if (store.attachedBranchId !== null && branchIds.includes(store.attachedBranchId)) store.setAttachedBranchId(null)
    const openToRemove = store.openedTerminals.filter(id => branchIds.includes(id))
    if (openToRemove.length > 0) useCanvasStore.setState({ openedTerminals: store.openedTerminals.filter(id => !branchIds.includes(id)) })
    const sel = store.getSelection()
    if (sel && sel.seedId === seed_id) store.setSelection(null)
  }, [branches])

  // --- Event-driven updates via WebSocket ---

  const branchesRef = useRef(branches)
  branchesRef.current = branches
  const currentProjectRef = useRef(currentProject)
  currentProjectRef.current = currentProject

  // Fetch branches for a single seed and merge into state
  const refreshBranches = useCallback(async (seedId: number) => {
    try {
      const bs = await api.branches.list(seedId)
      setBranches(prev => ({ ...prev, [seedId]: bs }))
      // Update alive set from session status
      setAliveBranches(prev => {
        const next = new Set(prev)
        for (const b of bs) {
          if (b.session?.status === 'active') next.add(b.id)
          else next.delete(b.id)
        }
        return next
      })
    } catch {}
  }, [])

  // Fetch iterations for a single branch and merge into state
  const refreshIterations = useCallback(async (branchId: number) => {
    try {
      const iters = await api.iterations.list(branchId)
      setIterations(prev => ({ ...prev, [branchId]: iters }))
    } catch {}
  }, [])

  // Load initial iterations when branches change
  const allBranchIds = Object.values(branches).flat().map(b => b.id)
  const allBranchIdsKey = JSON.stringify(allBranchIds)

  useEffect(() => {
    for (const id of allBranchIds) {
      if (!iterations[id]) {
        refreshIterations(id)
      }
    }
  }, [allBranchIdsKey])

  // WebSocket event listener — stable deps, uses refs for mutable state
  const [wsRetry, setWsRetry] = useState(0)

  useEffect(() => {
    const ws = new WebSocket('/api/ws/events')

    ws.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data)
        switch (event.type) {
          case 'branch.created':
          case 'branch.deleted':
            if (event.seed_id) refreshBranches(event.seed_id)
            break
          case 'session.status': {
            const br = branchesRef.current
            for (const [seedId, bs] of Object.entries(br)) {
              if ((bs as Branch[]).some(b => b.id === event.branch_id)) {
                refreshBranches(Number(seedId))
                break
              }
            }
            break
          }
          case 'iteration.created':
          case 'iteration.metrics':
          case 'iteration.visuals':
          case 'iteration.doc':
            if (event.branch_id) refreshIterations(event.branch_id)
            break
          case 'seed.created':
          case 'seed.deleted': {
            const proj = currentProjectRef.current
            if (proj) {
              api.seeds.list(proj.id).then(setSeeds).catch(() => {})
            }
            break
          }
          case 'runner.registered':
          case 'runner.offline':
            api.runners.list().then(setRunners).catch(() => {})
            break
          case 'cory_session.created':
          case 'cory_session.status':
          case 'cory_session.deleted':
            refreshCorySessions()
            break
        }
      } catch {}
    }

    ws.onclose = () => {
      setTimeout(() => setWsRetry(n => n + 1), 3000)
    }

    return () => {
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close()
      }
    }
  }, [wsRetry, refreshBranches, refreshIterations, refreshCorySessions])

  const contextValue = useMemo(() => ({
    projects, currentProject, runners, seeds, branches, iterations, aliveBranches, corySessions, loading,
    selectProject, addSeed, addBranch, renewBranch, forkBranch, deleteBranch, deleteSeed,
    addCorySession, killCorySession, deleteCorySession, seedPositions,
  }), [projects, currentProject, runners, seeds, branches, iterations, aliveBranches, corySessions, loading,
    selectProject, addSeed, addBranch, renewBranch, forkBranch, deleteBranch, deleteSeed,
    addCorySession, killCorySession, deleteCorySession, seedPositions])

  return (
    <WorkflowContext.Provider value={contextValue}>
      {children}
    </WorkflowContext.Provider>
  )
}

export function useWorkflow() {
  const ctx = useContext(WorkflowContext)
  if (!ctx) throw new Error('useWorkflow must be used within WorkflowProvider')
  return ctx
}
