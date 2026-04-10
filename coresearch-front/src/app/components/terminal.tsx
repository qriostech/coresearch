import { useEffect, useRef } from 'react'
import { init, Terminal, FitAddon } from 'ghostty-web'

// Initialize WASM once — all terminal instances share this promise
const ghosttyReady = init()

interface Props {
  // Stable identifier used as the React key and as the useEffect dep — the
  // same id may be reused across kinds (branch 5 vs cory_session 5), but
  // wsPath disambiguates so this collision is harmless.
  id: number
  // Full path under /api, e.g. `/api/ws/branch/5` or `/api/ws/cory-session/5`.
  // Changing wsPath remounts the websocket; the parent panel rebuilds the
  // component on attachment changes anyway.
  wsPath: string
  visible: boolean
}

export function WsTerminal({ id: _id, wsPath, visible }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const termRef = useRef<Terminal | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const fitRef = useRef<FitAddon | null>(null)
  const visibleRef = useRef(visible)
  visibleRef.current = visible

  useEffect(() => {
    if (!containerRef.current) return
    let cancelled = false

    ghosttyReady.then(async () => {
      if (cancelled || !containerRef.current) return

      const term = new Terminal({
        theme: {
          background: '#0d1117',
          foreground: '#c9d1d9',
          cursor: '#58a6ff',
          selectionBackground: '#58a6ff44',
        },
        fontFamily: 'monospace',
        fontSize: 13,
        scrollback: 10000,
      })
      const fit = new FitAddon()
      term.loadAddon(fit)
      await term.open(containerRef.current!)
      fit.fit()
      term.focus()

      // Suppress contenteditable visual artifacts
      const el = containerRef.current!
      el.style.caretColor = 'transparent'
      el.style.color = 'transparent'

      // Replace built-in link detection with one that handles wrapped URLs.
      // The built-in provider scans one row at a time so wrapped URLs never match.
      // We clear it and register our own via the public API.
      const ld = (term as any).linkDetector
      if (ld) ld.providers = []

      term.registerLinkProvider({
        provideLinks(absRow: number, cb: (links?: any[]) => void) {
          const buf = term.buffer.active
          const cols = term.cols

          const getLineText = (row: number): string => {
            const line = buf.getLine(row)
            if (!line) return ''
            const chars: string[] = []
            for (let c = 0; c < line.length; c++) {
              const cell = line.getCell(c)
              if (!cell) { chars.push(' '); continue }
              const cp = cell.getCodepoint()
              cp === 0 || cp < 32 ? chars.push(' ') : chars.push(String.fromCodePoint(cp))
            }
            return chars.join('')
          }

          const curText = getLineText(absRow)
          if (!curText.trim()) { cb(undefined); return }

          // Walk backward through all consecutive full-width (wrapped) rows
          const segments: { row: number; text: string; offset: number }[] = []
          let r = absRow - 1
          const prefixRows: { row: number; text: string }[] = []
          while (r >= 0) {
            const t = getLineText(r)
            if (t.length < cols) break
            prefixRows.push({ row: r, text: t })
            r--
          }
          prefixRows.reverse()

          // Walk forward through all consecutive full-width rows after current
          const suffixRows: { row: number; text: string }[] = []
          r = absRow
          while (getLineText(r).length >= cols) {
            const nextRow = r + 1
            const t = getLineText(nextRow)
            if (!t) break
            suffixRows.push({ row: nextRow, text: t })
            r = nextRow
          }

          // Build combined string with segment tracking
          let combined = ''
          for (const s of prefixRows) {
            segments.push({ row: s.row, text: s.text, offset: combined.length })
            combined += s.text
          }
          segments.push({ row: absRow, text: curText, offset: combined.length })
          combined += curText
          for (const s of suffixRows) {
            segments.push({ row: s.row, text: s.text, offset: combined.length })
            combined += s.text
          }

          const curSeg = segments.find(s => s.row === absRow)!
          const URL_RE = /(?:https?:\/\/|mailto:|ftp:\/\/|ssh:\/\/|git:\/\/|tel:|magnet:|gemini:\/\/|gopher:\/\/|news:)[\w\-.~:\/?#@!$&*+,;=%]+/gi
          const TRAILING_PUNCT = /[.,;!?)\]]+$/
          const links: any[] = []
          let m: RegExpExecArray | null

          while ((m = URL_RE.exec(combined)) !== null) {
            const url = m[0].replace(TRAILING_PUNCT, '')
            const mStart = m.index
            const mEnd = m.index + url.length - 1

            // Skip if the URL doesn't touch the current row
            if (mEnd < curSeg.offset || mStart >= curSeg.offset + curText.length) continue

            const toRowCol = (pos: number) => {
              for (let i = segments.length - 1; i >= 0; i--) {
                if (pos >= segments[i].offset)
                  return { x: pos - segments[i].offset, y: segments[i].row }
              }
              return { x: 0, y: absRow }
            }

            links.push({
              text: url,
              range: { start: toRowCol(mStart), end: toRowCol(mEnd) },
              activate: (ev: MouseEvent) => {
                if (ev.ctrlKey || ev.metaKey) window.open(url, '_blank', 'noopener,noreferrer')
              },
            })
          }
          cb(links.length > 0 ? links : undefined)
        }
      })

      if (cancelled) { term.dispose(); return }
      termRef.current = term
      fitRef.current = fit

      const ws = new WebSocket(wsPath)
      ws.binaryType = 'arraybuffer'
      wsRef.current = ws

      ws.onopen = () => {
        if (cancelled) { ws.close(); return }
        fit.fit()
        ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
      }

      // Buffer output and only flush when visible
      let writeBuffer: Uint8Array[] = []
      let rafId: number | null = null
      const flushBuffer = () => {
        rafId = null
        if (writeBuffer.length === 0) return
        if (!visibleRef.current) return
        const total = writeBuffer.reduce((acc, b) => acc + b.length, 0)
        const merged = new Uint8Array(total)
        let offset = 0
        for (const buf of writeBuffer) { merged.set(buf, offset); offset += buf.length }
        writeBuffer = []
        term.write(merged)
      }

      ws.onmessage = (e) => {
        if (e.data instanceof ArrayBuffer) {
          writeBuffer.push(new Uint8Array(e.data))
          if (visibleRef.current && rafId === null) {
            rafId = requestAnimationFrame(flushBuffer)
          }
        }
      }

      ws.onclose = () => {
        writeBuffer.push(new TextEncoder().encode('\r\n\x1b[31m[disconnected]\x1b[0m\r\n'))
        if (visibleRef.current && rafId === null) {
          rafId = requestAnimationFrame(flushBuffer)
        }
      }

      const encoder = new TextEncoder()
      term.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(encoder.encode(data))
        }
      })

      term.attachCustomKeyEventHandler((e) => {
        if (e.type !== 'keydown') return false
        const mod = e.ctrlKey || e.metaKey
        if (mod && e.shiftKey && e.key === 'C') {
          const sel = term.getSelection()
          if (sel) navigator.clipboard.writeText(sel.replace(/\n/g, ''))
          return true
        }
        if (mod && e.shiftKey && e.key === 'V') {
          navigator.clipboard.readText().then(text => {
            if (ws.readyState === WebSocket.OPEN)
              ws.send(encoder.encode(text))
          })
          return true
        }
        return false
      })

      let resizeTimer: ReturnType<typeof setTimeout> | null = null
      const observer = new ResizeObserver(() => {
        if (!visibleRef.current) return
        if (resizeTimer) clearTimeout(resizeTimer)
        resizeTimer = setTimeout(() => {
          fit.fit()
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
          }
        }, 100)
      })
      observer.observe(containerRef.current!)

      cleanupRef.current = () => {
        if (resizeTimer) clearTimeout(resizeTimer)
        if (rafId !== null) cancelAnimationFrame(rafId)
        observer.disconnect()
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
          ws.close()
        }
        term.dispose()
        termRef.current = null
        fitRef.current = null
        wsRef.current = null
      }
    })

    const cleanupRef = { current: () => {} }
    return () => {
      cancelled = true
      cleanupRef.current()
    }
  }, [wsPath])

  // When becoming visible: re-fit after layout settles, focus
  useEffect(() => {
    if (!visible || !fitRef.current || !termRef.current) return
    const rafId = requestAnimationFrame(() => {
      fitRef.current?.fit()
      termRef.current?.focus()
      const ws = wsRef.current
      const term = termRef.current
      if (ws?.readyState === WebSocket.OPEN && term) {
        ws.send(JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }))
      }
    })
    return () => cancelAnimationFrame(rafId)
  }, [visible])

  return (
    <div
      ref={containerRef}
      className="absolute inset-2 outline-none"
      style={visible ? undefined : { visibility: 'hidden', pointerEvents: 'none' }}
    />
  )
}
