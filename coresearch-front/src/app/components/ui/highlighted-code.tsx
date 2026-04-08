import { useMemo } from 'react'
import hljs from 'highlight.js/lib/core'

// Register languages on demand from a static map.
// highlight.js tree-shakes to only the registered languages.
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import python from 'highlight.js/lib/languages/python'
import css from 'highlight.js/lib/languages/css'
import json from 'highlight.js/lib/languages/json'
import xml from 'highlight.js/lib/languages/xml'
import markdown from 'highlight.js/lib/languages/markdown'
import bash from 'highlight.js/lib/languages/bash'
import yaml from 'highlight.js/lib/languages/yaml'
import sql from 'highlight.js/lib/languages/sql'
import go from 'highlight.js/lib/languages/go'
import rust from 'highlight.js/lib/languages/rust'
import java from 'highlight.js/lib/languages/java'
import cpp from 'highlight.js/lib/languages/cpp'
import c from 'highlight.js/lib/languages/c'
import ruby from 'highlight.js/lib/languages/ruby'
import php from 'highlight.js/lib/languages/php'
import swift from 'highlight.js/lib/languages/swift'
import kotlin from 'highlight.js/lib/languages/kotlin'
import diff from 'highlight.js/lib/languages/diff'
import dockerfile from 'highlight.js/lib/languages/dockerfile'
import ini from 'highlight.js/lib/languages/ini'
import scss from 'highlight.js/lib/languages/scss'
import csharp from 'highlight.js/lib/languages/csharp'

hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('python', python)
hljs.registerLanguage('css', css)
hljs.registerLanguage('json', json)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('markdown', markdown)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('yaml', yaml)
hljs.registerLanguage('sql', sql)
hljs.registerLanguage('go', go)
hljs.registerLanguage('rust', rust)
hljs.registerLanguage('java', java)
hljs.registerLanguage('cpp', cpp)
hljs.registerLanguage('c', c)
hljs.registerLanguage('ruby', ruby)
hljs.registerLanguage('php', php)
hljs.registerLanguage('swift', swift)
hljs.registerLanguage('kotlin', kotlin)
hljs.registerLanguage('diff', diff)
hljs.registerLanguage('dockerfile', dockerfile)
hljs.registerLanguage('ini', ini)
hljs.registerLanguage('scss', scss)
hljs.registerLanguage('csharp', csharp)

const EXT_TO_LANG: Record<string, string> = {
  js: 'javascript', jsx: 'javascript', mjs: 'javascript', cjs: 'javascript',
  ts: 'typescript', tsx: 'typescript', mts: 'typescript', cts: 'typescript',
  py: 'python', pyi: 'python',
  css: 'css', scss: 'scss',
  json: 'json', jsonc: 'json',
  html: 'xml', htm: 'xml', xml: 'xml', svg: 'xml', xhtml: 'xml',
  md: 'markdown', mdx: 'markdown',
  sh: 'bash', bash: 'bash', zsh: 'bash',
  yml: 'yaml', yaml: 'yaml',
  sql: 'sql',
  go: 'go',
  rs: 'rust',
  java: 'java',
  cpp: 'cpp', cc: 'cpp', cxx: 'cpp', hpp: 'cpp', hxx: 'cpp', h: 'cpp',
  c: 'c',
  rb: 'ruby', rake: 'ruby',
  php: 'php',
  swift: 'swift',
  kt: 'kotlin', kts: 'kotlin',
  diff: 'diff', patch: 'diff',
  dockerfile: 'dockerfile',
  ini: 'ini', toml: 'ini', cfg: 'ini', conf: 'ini',
  cs: 'csharp',
  makefile: 'bash',
}

export function langFromPath(path: string): string | undefined {
  const filename = path.split('/').pop()?.toLowerCase() ?? ''
  if (filename === 'dockerfile') return 'dockerfile'
  if (filename === 'makefile' || filename === 'gnumakefile') return 'bash'
  const ext = filename.split('.').pop() ?? ''
  return EXT_TO_LANG[ext]
}

interface HighlightedCodeProps {
  content: string
  filePath: string
}

export function HighlightedCode({ content, filePath }: HighlightedCodeProps) {
  const highlighted = useMemo(() => {
    const lang = langFromPath(filePath)
    if (lang) {
      try {
        return hljs.highlight(content, { language: lang }).value
      } catch {
        // fall through to plain text
      }
    }
    return null
  }, [content, filePath])

  const lines = useMemo(() => {
    if (highlighted) {
      // Split highlighted HTML by newlines, preserving open spans across lines
      return splitHighlightedLines(highlighted)
    }
    return content.split('\n')
  }, [content, highlighted])

  return (
    <pre className="p-4 text-xs font-mono leading-5 text-[#c9d1d9]">
      {lines.map((line, i) => (
        <div key={i} className="flex">
          <span className="select-none text-[#484f58] w-10 text-right pr-4 shrink-0">{i + 1}</span>
          {highlighted ? (
            <span className="whitespace-pre" dangerouslySetInnerHTML={{ __html: line || '\n' }} />
          ) : (
            <span className="whitespace-pre">{line}</span>
          )}
        </div>
      ))}
    </pre>
  )
}

/**
 * Split highlight.js HTML output into lines while preserving span context.
 * highlight.js may produce spans that cross line boundaries, e.g.:
 *   <span class="hljs-string">"line1\nline2"</span>
 * We need to close open spans at each newline and re-open them on the next line.
 */
export function splitHighlightedLines(html: string): string[] {
  const lines: string[] = []
  let current = ''
  let openSpans: string[] = []

  // Simple state machine: walk through the HTML character by character
  let i = 0
  while (i < html.length) {
    if (html[i] === '\n') {
      // Close all open spans for this line
      current += '</span>'.repeat(openSpans.length)
      lines.push(current)
      // Re-open spans for the next line
      current = openSpans.join('')
      i++
    } else if (html[i] === '<') {
      const closeMatch = html.startsWith('</span>', i)
      if (closeMatch) {
        current += '</span>'
        openSpans.pop()
        i += 7
      } else {
        // Opening tag — find end of tag
        const end = html.indexOf('>', i)
        if (end === -1) { current += html[i]; i++; continue }
        const tag = html.slice(i, end + 1)
        current += tag
        openSpans.push(tag)
        i = end + 1
      }
    } else {
      current += html[i]
      i++
    }
  }
  // Push the last line
  current += '</span>'.repeat(openSpans.length)
  lines.push(current)
  return lines
}
