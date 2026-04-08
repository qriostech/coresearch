import { useMemo, useRef, useCallback } from 'react'
import hljs from 'highlight.js/lib/core'
import { langFromPath, splitHighlightedLines } from './highlighted-code'

interface HighlightedEditorProps {
  content: string
  filePath: string
  onChange: (value: string) => void
}

export function HighlightedEditor({ content, filePath, onChange }: HighlightedEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const preRef = useRef<HTMLPreElement>(null)

  const highlighted = useMemo(() => {
    const lang = langFromPath(filePath)
    if (lang) {
      try {
        return hljs.highlight(content, { language: lang }).value
      } catch {
        return null
      }
    }
    return null
  }, [content, filePath])

  const lines = useMemo(() => {
    if (highlighted) {
      return splitHighlightedLines(highlighted)
    }
    return content.split('\n')
  }, [content, highlighted])

  const syncScroll = useCallback(() => {
    if (textareaRef.current && preRef.current) {
      preRef.current.scrollTop = textareaRef.current.scrollTop
      preRef.current.scrollLeft = textareaRef.current.scrollLeft
    }
  }, [])

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Tab') {
      e.preventDefault()
      const ta = e.currentTarget
      const start = ta.selectionStart
      const end = ta.selectionEnd
      const val = ta.value
      const newVal = val.substring(0, start) + '  ' + val.substring(end)
      onChange(newVal)
      requestAnimationFrame(() => {
        ta.selectionStart = ta.selectionEnd = start + 2
      })
    }
  }, [onChange])

  return (
    <div className="relative flex-1 overflow-hidden">
      {/* Highlighted code layer (behind) */}
      <pre
        ref={preRef}
        className="absolute inset-0 p-4 text-xs font-mono leading-5 text-[#c9d1d9] overflow-hidden pointer-events-none m-0"
        aria-hidden
      >
        {lines.map((line, i) => (
          <div key={i} className="flex">
            <span className="select-none text-[#484f58] w-10 text-right pr-4 shrink-0">{i + 1}</span>
            {highlighted ? (
              <span className="whitespace-pre" dangerouslySetInnerHTML={{ __html: line || '\n' }} />
            ) : (
              <span className="whitespace-pre">{line || '\n'}</span>
            )}
          </div>
        ))}
      </pre>
      {/* Transparent textarea layer (in front) */}
      <textarea
        ref={textareaRef}
        value={content}
        onChange={e => onChange(e.target.value)}
        onScroll={syncScroll}
        onKeyDown={handleKeyDown}
        className="absolute inset-0 w-full h-full bg-transparent text-transparent caret-[#58a6ff] font-mono text-xs leading-5 p-4 pl-[3.5rem] resize-none outline-none border-none m-0 overflow-auto"
        spellCheck={false}
        autoCapitalize="off"
        autoCorrect="off"
      />
    </div>
  )
}
