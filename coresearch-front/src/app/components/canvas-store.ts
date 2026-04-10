import { create } from 'zustand'
import { Iteration, api } from '../api/client'

export type LightboxState = { iterationId: number; index: number } | null

export type Selection =
  | { type: 'seed'; seedId: number }
  | { type: 'branch'; seedId: number; branchId: number }
  | { type: 'iteration'; seedId: number; branchId: number; iterationId: number }
  | null

export interface Pane {
  id: number
  name: string
  selection: Selection
  pan: { x: number; y: number }
  zoom: number
  focusBranchIds: number[] | null
}

export type TextOverlay =
  | { type: 'branch-description'; branchId: number; value: string }
  | { type: 'iteration-comments'; iterationId: number }
  | { type: 'metric-chart'; branchId: number; metricKey: string }
  | null

export interface FileBrowserState {
  branchId: number
  hash: string
  files: string[]
  mode: 'git' | 'workdir'
}

export interface DiffState {
  content: string
  from: string
  to: string
}

let paneIdCounter = 1

const EMPTY_SET = new Set<number>()
const EMPTY_ITERS: Iteration[] = []

export { EMPTY_SET, EMPTY_ITERS }

interface CanvasStore {
  // Panes
  panes: Pane[]
  activePaneId: number

  // Derived helpers
  getActivePane: () => Pane
  getSelection: () => Selection
  getPan: () => { x: number; y: number }
  getZoom: () => number

  // Pane actions
  setActivePaneId: (id: number) => void
  updateActivePane: (updates: Partial<Pane>) => void
  setSelection: (sel: Selection) => void
  setPan: (p: { x: number; y: number }) => void
  setZoom: (z: number) => void
  addPane: () => void
  closePane: (id: number) => void
  renamePane: (id: number, name: string) => void
  sendBranchToPane: (branchId: number, paneId: number) => void

  // Multi-select
  selectedIterationIds: Set<number>
  setSelectedIterationIds: (ids: Set<number>) => void
  shiftClickIteration: (iterationId: number, anchorId: number) => void

  // Terminal
  // attachedBranchId and attachedCorySessionId are mutually exclusive — at
  // most one is non-null at a time. The terminal panel renders whichever is
  // set, and the setter for either kind clears the other before attaching.
  attachedBranchId: number | null
  attachedCorySessionId: number | null
  openedTerminals: number[]
  openedCoryTerminals: number[]
  terminalHeight: number
  terminalResizing: boolean
  setAttachedBranchId: (id: number | null) => void
  setAttachedCorySessionId: (id: number | null) => void
  setTerminalHeight: (h: number) => void
  setTerminalResizing: (v: boolean) => void

  // Cory UI highlights — ephemeral, broadcast over WS by the cory_ui MCP
  // server. Map iteration_id → reason chip text. Lost on reload by design.
  highlightedIterations: Map<number, string>
  addIterationHighlight: (iteration_id: number, reason: string) => void
  removeIterationHighlight: (iteration_id: number) => void
  clearIterationHighlights: () => void

  // Pan target — branch ID to center the canvas on (consumed & cleared by CanvasSVG)
  panTarget: number | null
  setPanTarget: (id: number | null) => void

  // Pan target keyed by a specific iteration (branchId + hash). Set when the
  // user wants to navigate to one iteration node, e.g. clicking an entry in
  // the cory highlights pill. Consumed & cleared by CanvasSVG, just like
  // panTarget. Lives as a parallel field rather than a union on panTarget so
  // existing branch-only callers don't change shape.
  panTargetIteration: { branchId: number; iterationHash: string } | null
  setPanTargetIteration: (target: { branchId: number; iterationHash: string } | null) => void

  // Seed pan target — seed ID to center the canvas on after creation
  seedPanTarget: number | null
  setSeedPanTarget: (id: number | null) => void

  // Dialogs
  seedDialog: boolean
  setSeedDialog: (open: boolean) => void
  branchDialog: boolean
  setBranchDialog: (open: boolean) => void
  forkDialog: boolean
  setForkDialog: (open: boolean) => void
  deleteDialog: { seedId: number; branchId: number; branchName: string } | null
  setDeleteDialog: (v: { seedId: number; branchId: number; branchName: string } | null) => void
  deleteSeedDialog: { seedId: number; seedName: string } | null
  setDeleteSeedDialog: (v: { seedId: number; seedName: string } | null) => void

  // Form fields
  seedName: string; setSeedName: (v: string) => void
  seedUrl: string; setSeedUrl: (v: string) => void
  seedBranch: string; setSeedBranch: (v: string) => void
  seedCommit: string; setSeedCommit: (v: string) => void
  seedToken: string; setSeedToken: (v: string) => void
  branchName: string; setBranchName: (v: string) => void
  branchDesc: string; setBranchDesc: (v: string) => void
  branchAgent: string; setBranchAgent: (v: string) => void
  forkName: string; setForkName: (v: string) => void
  forkAgent: string; setForkAgent: (v: string) => void
  submitting: boolean; setSubmitting: (v: boolean) => void
  error: string | null; setError: (v: string | null) => void
  pushing: boolean; setPushing: (v: boolean) => void
  pushResult: string | null; setPushResult: (v: string | null) => void

  // Overlays
  lightbox: LightboxState; setLightbox: (v: LightboxState) => void
  diffOverlay: DiffState | null; setDiffOverlay: (v: DiffState | null) => void
  diffLoading: boolean; setDiffLoading: (v: boolean) => void
  fileBrowser: FileBrowserState | null; setFileBrowser: (v: FileBrowserState | null) => void
  fileBrowserLoading: boolean; setFileBrowserLoading: (v: boolean) => void
  expandedDirs: Set<string>; setExpandedDirs: (v: Set<string>) => void
  viewingFile: { path: string; content: string } | null; setViewingFile: (v: { path: string; content: string } | null) => void
  textOverlay: TextOverlay; setTextOverlay: (v: TextOverlay) => void
  contextMenu: { x: number; y: number; branchId: number } | null; setContextMenu: (v: { x: number; y: number; branchId: number } | null) => void
  mainMetric: Record<number, string>; setMainMetric: (v: Record<number, string>) => void

  // Fork editor
  forkEditorBranchId: number | null; setForkEditorBranchId: (v: number | null) => void
  forkEditorFiles: string[]; setForkEditorFiles: (v: string[]) => void
  forkEditorSelected: string | null; setForkEditorSelected: (v: string | null) => void
  forkEditorContent: string; setForkEditorContent: (v: string) => void
  forkEditorDirty: boolean; setForkEditorDirty: (v: boolean) => void
  forkEditorSaving: boolean; setForkEditorSaving: (v: boolean) => void

  // Pane rename
  renamingPaneId: number | null; setRenamingPaneId: (v: number | null) => void

  // Session reset
  resetProject: () => void

  // Compound actions
  openFileBrowser: (branchId: number, hash: string) => Promise<void>
}

export const useCanvasStore = create<CanvasStore>((set, get) => ({
  // Panes
  panes: [{ id: paneIdCounter, name: 'main', selection: null, pan: { x: 400, y: 300 }, zoom: 1, focusBranchIds: null }],
  activePaneId: 1,

  getActivePane: () => {
    const { panes, activePaneId } = get()
    return panes.find(p => p.id === activePaneId) ?? panes[0]
  },
  getSelection: () => get().getActivePane().selection,
  getPan: () => get().getActivePane().pan,
  getZoom: () => get().getActivePane().zoom,

  setActivePaneId: (id) => set({ activePaneId: id }),
  updateActivePane: (updates) => set(s => ({
    panes: s.panes.map(p => p.id === s.activePaneId ? { ...p, ...updates } : p),
  })),
  setSelection: (sel) => {
    const s = get()
    set({
      panes: s.panes.map(p => p.id === s.activePaneId ? { ...p, selection: sel } : p),
      selectedIterationIds: EMPTY_SET,
    })
  },
  setPan: (p) => get().updateActivePane({ pan: p }),
  setZoom: (z) => get().updateActivePane({ zoom: z }),

  addPane: () => {
    paneIdCounter += 1
    const newPane: Pane = { id: paneIdCounter, name: `pane ${paneIdCounter}`, selection: null, pan: { x: 400, y: 300 }, zoom: 1, focusBranchIds: [] }
    set(s => ({ panes: [...s.panes, newPane], activePaneId: paneIdCounter }))
  },
  closePane: (id) => set(s => {
    const next = s.panes.filter(p => p.id !== id)
    if (next.length === 0) return s
    return { panes: next, activePaneId: s.activePaneId === id ? next[0].id : s.activePaneId }
  }),
  renamePane: (id, name) => set(s => ({
    panes: s.panes.map(p => p.id === id ? { ...p, name } : p),
  })),
  sendBranchToPane: (branchId, paneId) => {
    set(s => ({
      panes: s.panes.map(p => {
        if (p.id !== paneId) return p
        if (p.focusBranchIds?.includes(branchId)) return p
        return { ...p, focusBranchIds: [...(p.focusBranchIds ?? []), branchId] }
      }),
      contextMenu: null,
    }))
  },

  // Multi-select
  selectedIterationIds: EMPTY_SET,
  setSelectedIterationIds: (ids) => set({ selectedIterationIds: ids }),
  shiftClickIteration: (iterationId, anchorId) => set(s => {
    const next = new Set(s.selectedIterationIds)
    if (!next.has(anchorId)) next.add(anchorId)
    if (next.has(iterationId)) next.delete(iterationId)
    else next.add(iterationId)
    return { selectedIterationIds: next }
  }),

  // Terminal
  attachedBranchId: null,
  attachedCorySessionId: null,
  openedTerminals: [],
  openedCoryTerminals: [],
  terminalHeight: 320,
  terminalResizing: false,
  setAttachedBranchId: (id) => {
    const s = get()
    const prevBranch = s.attachedBranchId
    const prevCory = s.attachedCorySessionId
    // Switching: detach first, reattach next frame so the terminal is fully
    // destroyed and recreated. Covers both branch→branch and cory→branch.
    if ((prevBranch !== null || prevCory !== null) && id !== null && prevBranch !== id) {
      set(st => ({
        attachedBranchId: null,
        attachedCorySessionId: null,
        openedTerminals: !st.openedTerminals.includes(id)
          ? [...st.openedTerminals, id]
          : st.openedTerminals,
      }))
      requestAnimationFrame(() => {
        set({ attachedBranchId: id })
      })
    } else {
      set(st => ({
        attachedBranchId: id,
        attachedCorySessionId: id !== null ? null : st.attachedCorySessionId,
        openedTerminals: id !== null && !st.openedTerminals.includes(id)
          ? [...st.openedTerminals, id]
          : st.openedTerminals,
      }))
    }
  },
  setAttachedCorySessionId: (id) => {
    const s = get()
    const prevBranch = s.attachedBranchId
    const prevCory = s.attachedCorySessionId
    if ((prevBranch !== null || prevCory !== null) && id !== null && prevCory !== id) {
      set(st => ({
        attachedBranchId: null,
        attachedCorySessionId: null,
        openedCoryTerminals: !st.openedCoryTerminals.includes(id)
          ? [...st.openedCoryTerminals, id]
          : st.openedCoryTerminals,
      }))
      requestAnimationFrame(() => {
        set({ attachedCorySessionId: id })
      })
    } else {
      set(st => ({
        attachedCorySessionId: id,
        attachedBranchId: id !== null ? null : st.attachedBranchId,
        openedCoryTerminals: id !== null && !st.openedCoryTerminals.includes(id)
          ? [...st.openedCoryTerminals, id]
          : st.openedCoryTerminals,
      }))
    }
  },
  setTerminalHeight: (h) => set({ terminalHeight: h }),
  setTerminalResizing: (v) => set({ terminalResizing: v }),

  // Cory UI highlights — see interface comment. Each mutation returns a new
  // Map so React/Zustand selectors notice the change.
  highlightedIterations: new Map<number, string>(),
  addIterationHighlight: (iteration_id, reason) => set(s => {
    const next = new Map(s.highlightedIterations)
    next.set(iteration_id, reason)
    return { highlightedIterations: next }
  }),
  removeIterationHighlight: (iteration_id) => set(s => {
    if (!s.highlightedIterations.has(iteration_id)) return s
    const next = new Map(s.highlightedIterations)
    next.delete(iteration_id)
    return { highlightedIterations: next }
  }),
  clearIterationHighlights: () => set(s => {
    if (s.highlightedIterations.size === 0) return s
    return { highlightedIterations: new Map() }
  }),

  // Pan target
  panTarget: null, setPanTarget: (id) => set({ panTarget: id }),
  panTargetIteration: null, setPanTargetIteration: (target) => set({ panTargetIteration: target }),
  seedPanTarget: null, setSeedPanTarget: (id) => set({ seedPanTarget: id }),

  // Dialogs
  seedDialog: false, setSeedDialog: (v) => set({ seedDialog: v }),
  branchDialog: false, setBranchDialog: (v) => set({ branchDialog: v }),
  forkDialog: false, setForkDialog: (v) => set({ forkDialog: v }),
  deleteDialog: null, setDeleteDialog: (v) => set({ deleteDialog: v }),
  deleteSeedDialog: null, setDeleteSeedDialog: (v) => set({ deleteSeedDialog: v }),

  // Form fields
  seedName: '', setSeedName: (v) => set({ seedName: v }),
  seedUrl: '', setSeedUrl: (v) => set({ seedUrl: v }),
  seedBranch: '', setSeedBranch: (v) => set({ seedBranch: v }),
  seedCommit: '', setSeedCommit: (v) => set({ seedCommit: v }),
  seedToken: '', setSeedToken: (v) => set({ seedToken: v }),
  branchName: '', setBranchName: (v) => set({ branchName: v }),
  branchDesc: '', setBranchDesc: (v) => set({ branchDesc: v }),
  branchAgent: '', setBranchAgent: (v) => set({ branchAgent: v }),
  forkName: '', setForkName: (v) => set({ forkName: v }),
  forkAgent: 'default', setForkAgent: (v) => set({ forkAgent: v }),
  submitting: false, setSubmitting: (v) => set({ submitting: v }),
  error: null, setError: (v) => set({ error: v }),
  pushing: false, setPushing: (v) => set({ pushing: v }),
  pushResult: null, setPushResult: (v) => set({ pushResult: v }),

  // Overlays
  lightbox: null, setLightbox: (v) => set({ lightbox: v }),
  diffOverlay: null, setDiffOverlay: (v) => set({ diffOverlay: v }),
  diffLoading: false, setDiffLoading: (v) => set({ diffLoading: v }),
  fileBrowser: null, setFileBrowser: (v) => set({ fileBrowser: v }),
  fileBrowserLoading: false, setFileBrowserLoading: (v) => set({ fileBrowserLoading: v }),
  expandedDirs: new Set(), setExpandedDirs: (v) => set({ expandedDirs: v }),
  viewingFile: null, setViewingFile: (v) => set({ viewingFile: v }),
  textOverlay: null, setTextOverlay: (v) => set({ textOverlay: v }),
  contextMenu: null, setContextMenu: (v) => set({ contextMenu: v }),
  mainMetric: {}, setMainMetric: (v) => set({ mainMetric: v }),

  // Fork editor
  forkEditorBranchId: null, setForkEditorBranchId: (v) => set({ forkEditorBranchId: v }),
  forkEditorFiles: [], setForkEditorFiles: (v) => set({ forkEditorFiles: v }),
  forkEditorSelected: null, setForkEditorSelected: (v) => set({ forkEditorSelected: v }),
  forkEditorContent: '', setForkEditorContent: (v) => set({ forkEditorContent: v }),
  forkEditorDirty: false, setForkEditorDirty: (v) => set({ forkEditorDirty: v }),
  forkEditorSaving: false, setForkEditorSaving: (v) => set({ forkEditorSaving: v }),

  // Pane rename
  renamingPaneId: null, setRenamingPaneId: (v) => set({ renamingPaneId: v }),

  // Session reset — clears all state that references session-specific IDs
  resetProject: () => {
    paneIdCounter = 1
    set({
      panes: [{ id: 1, name: 'main', selection: null, pan: { x: 400, y: 300 }, zoom: 1, focusBranchIds: null }],
      activePaneId: 1,
      selectedIterationIds: EMPTY_SET,
      attachedBranchId: null,
      attachedCorySessionId: null,
      openedTerminals: [],
      openedCoryTerminals: [],
      highlightedIterations: new Map(),
      lightbox: null,
      diffOverlay: null,
      diffLoading: false,
      fileBrowser: null,
      fileBrowserLoading: false,
      expandedDirs: new Set(),
      viewingFile: null,
      textOverlay: null,
      contextMenu: null,
      mainMetric: {},
      seedPanTarget: null,
      forkEditorBranchId: null,
      forkEditorFiles: [],
      forkEditorSelected: null,
      forkEditorContent: '',
      forkEditorDirty: false,
      forkEditorSaving: false,
      renamingPaneId: null,
      error: null,
      pushResult: null,
    })
  },

  // Compound actions
  openFileBrowser: async (branchId, hash) => {
    set({ fileBrowserLoading: true })
    try {
      const files = await api.tree.list(branchId, hash)
      set({ fileBrowser: { branchId, hash, files, mode: 'git' as const }, expandedDirs: new Set(), viewingFile: null })
    } catch {
      set({ fileBrowser: null })
    } finally {
      set({ fileBrowserLoading: false })
    }
  },
}))
