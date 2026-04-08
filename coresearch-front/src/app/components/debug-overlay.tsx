import { memo, useState, useEffect, useRef, useCallback } from 'react'
import { Wrench, X, Pause, Play, Trash2 } from 'lucide-react'

interface LogEntry {
  ts: string
  level: string
  service: string
  message: string
  request_id?: string
  [key: string]: unknown
}

const LEVEL_COLORS: Record<string, string> = {
  info: 'text-[#8b949e]',
  warn: 'text-[#d29922]',
  error: 'text-[#f85149]',
  debug: 'text-[#484f58]',
}

const LEVEL_BADGES: Record<string, string> = {
  info: 'bg-[#1f6feb]/20 text-[#58a6ff]',
  warn: 'bg-[#d29922]/20 text-[#d29922]',
  error: 'bg-[#f85149]/20 text-[#f85149]',
  debug: 'bg-[#484f58]/20 text-[#6e7681]',
}

function formatTime(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('en-US', { hour12: false, fractionalSecondDigits: 3 })
  } catch {
    return ts
  }
}

function formatContext(entry: LogEntry): string {
  const skip = new Set(['ts', 'level', 'service', 'message', 'request_id'])
  const parts: string[] = []
  for (const [k, v] of Object.entries(entry)) {
    if (skip.has(k)) continue
    parts.push(`${k}=${v}`)
  }
  return parts.join(' ')
}

function LogLine({ entry }: { entry: LogEntry }) {
  const ctx = formatContext(entry)
  return (
    <div className={`flex gap-2 text-[11px] leading-5 font-mono ${LEVEL_COLORS[entry.level] ?? 'text-[#8b949e]'}`}>
      <span className="text-[#484f58] shrink-0">{formatTime(entry.ts)}</span>
      <span className={`px-1 rounded shrink-0 ${LEVEL_BADGES[entry.level] ?? ''}`}>
        {entry.level.padEnd(5)}
      </span>
      <span className="text-[#c9d1d9]">{entry.message}</span>
      {ctx && <span className="text-[#6e7681]">{ctx}</span>}
      {entry.request_id && (
        <span className="text-[#484f58] shrink-0">[{entry.request_id}]</span>
      )}
    </div>
  )
}

function useLogStream(url: string, paused: boolean) {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const pausedRef = useRef(paused)
  pausedRef.current = paused
  const bufferRef = useRef<LogEntry[]>([])

  useEffect(() => {
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onmessage = (e) => {
      try {
        const entry = JSON.parse(e.data) as LogEntry
        if (pausedRef.current) {
          bufferRef.current.push(entry)
        } else {
          setLogs(prev => {
            const next = [...prev, entry]
            return next.length > 1000 ? next.slice(-500) : next
          })
        }
      } catch {}
    }

    ws.onclose = () => {
      wsRef.current = null
    }

    return () => {
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close()
      }
    }
  }, [url])

  // Flush buffer when unpaused
  useEffect(() => {
    if (!paused && bufferRef.current.length > 0) {
      const buffered = bufferRef.current
      bufferRef.current = []
      setLogs(prev => {
        const next = [...prev, ...buffered]
        return next.length > 1000 ? next.slice(-500) : next
      })
    }
  }, [paused])

  const clear = useCallback(() => {
    setLogs([])
    bufferRef.current = []
  }, [])

  return { logs, clear }
}

function LogPanel({ url, filter, paused }: { url: string; filter: string; paused: boolean }) {
  const { logs, clear } = useLogStream(url, paused)
  const scrollRef = useRef<HTMLDivElement>(null)
  const autoScrollRef = useRef(true)

  // Auto-scroll to bottom
  useEffect(() => {
    if (autoScrollRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logs])

  const handleScroll = useCallback(() => {
    if (!scrollRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current
    autoScrollRef.current = scrollHeight - scrollTop - clientHeight < 40
  }, [])

  const filtered = filter
    ? logs.filter(e => {
        const s = filter.toLowerCase()
        return e.message.toLowerCase().includes(s) ||
               (e.request_id ?? '').toLowerCase().includes(s) ||
               JSON.stringify(e).toLowerCase().includes(s)
      })
    : logs

  return (
    <div className="flex flex-col h-full">
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto p-2 space-y-0"
      >
        {filtered.length === 0 && (
          <div className="text-[#484f58] text-xs text-center py-4">no logs yet</div>
        )}
        {filtered.map((entry, i) => (
          <LogLine key={i} entry={entry} />
        ))}
      </div>
    </div>
  )
}

export const DebugOverlay = memo(function DebugOverlay() {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<'controlplane' | 'runner'>('controlplane')
  const [filter, setFilter] = useState('')
  const [paused, setPaused] = useState(false)

  return (
    <>
      {/* Wrench icon */}
      <button
        onClick={() => setOpen(o => !o)}
        className={`fixed bottom-3 left-3 z-50 p-2 rounded-lg transition-colors ${
          open
            ? 'bg-[#58a6ff]/20 text-[#58a6ff]'
            : 'bg-[#161b22] text-[#484f58] hover:text-[#8b949e] border border-[#30363d]'
        }`}
      >
        <Wrench className="size-4" />
      </button>

      {/* Overlay panel */}
      {open && (
        <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-40 h-[70vh] w-[720px] bg-[#0d1117] border border-[#30363d] rounded-xl flex flex-col shadow-2xl">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-[#30363d]">
            <div className="flex items-center gap-3">
              <span className="text-[#c9d1d9] text-sm font-mono">debug logs</span>
              {/* Tabs */}
              <div className="flex gap-1">
                {(['controlplane', 'runner'] as const).map(t => (
                  <button
                    key={t}
                    onClick={() => setTab(t)}
                    className={`px-2 py-0.5 text-xs font-mono rounded transition-colors ${
                      tab === t
                        ? 'bg-[#1f6feb]/20 text-[#58a6ff]'
                        : 'text-[#484f58] hover:text-[#8b949e]'
                    }`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setPaused(p => !p)}
                className="p-1.5 text-[#484f58] hover:text-[#8b949e] transition-colors"
                title={paused ? 'resume' : 'pause'}
              >
                {paused ? <Play className="size-3.5" /> : <Pause className="size-3.5" />}
              </button>
              <button
                onClick={() => setOpen(false)}
                className="p-1.5 text-[#484f58] hover:text-[#8b949e] transition-colors"
              >
                <X className="size-3.5" />
              </button>
            </div>
          </div>

          {/* Filter */}
          <div className="px-4 py-2 border-b border-[#21262d]">
            <input
              type="text"
              value={filter}
              onChange={e => setFilter(e.target.value)}
              placeholder="filter logs..."
              className="w-full bg-[#161b22] border border-[#30363d] rounded px-2 py-1 text-xs font-mono text-[#c9d1d9] placeholder-[#484f58] outline-none focus:border-[#58a6ff]"
            />
          </div>

          {/* Log panels — keep both mounted so they maintain their WebSocket connections */}
          <div className="flex-1 overflow-hidden">
            <div style={{ display: tab === 'controlplane' ? 'flex' : 'none', flexDirection: 'column', height: '100%' }}>
              <LogPanel url="/api/ws/logs/controlplane" filter={filter} paused={paused} />
            </div>
            <div style={{ display: tab === 'runner' ? 'flex' : 'none', flexDirection: 'column', height: '100%' }}>
              <LogPanel url="/api/ws/logs/runner" filter={filter} paused={paused} />
            </div>
          </div>
        </div>
      )}
    </>
  )
})
