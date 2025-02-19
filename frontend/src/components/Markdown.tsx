import { Fragment, type ReactNode } from 'react'
import clsx from 'clsx'

/**
 * A deliberately small markdown renderer.
 *
 * The answer text is produced by the backend and may contain data taken from
 * a spreadsheet, so it is treated as *text*.  The renderer never uses
 * `dangerouslySetInnerHTML`: every token is turned into a React element, which
 * makes HTML injection impossible by construction.
 */

const INLINE_PATTERN = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const parts = text.split(INLINE_PATTERN).filter((part) => part !== '' && part !== undefined)
  return parts.map((part, index) => {
    const key = `${keyPrefix}-${index}`
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return (
        <strong key={key} className="font-semibold text-slate-900 dark:text-slate-100">
          {part.slice(2, -2)}
        </strong>
      )
    }
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return (
        <code
          key={key}
          className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.85em] text-slate-800 dark:bg-slate-800 dark:text-slate-200"
        >
          {part.slice(1, -1)}
        </code>
      )
    }
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) {
      return <em key={key}>{part.slice(1, -1)}</em>
    }
    return <Fragment key={key}>{part}</Fragment>
  })
}

export function Markdown({ text, className }: { text: string; className?: string }) {
  const lines = (text ?? '').split('\n')
  const blocks: ReactNode[] = []
  let listItems: string[] = []
  let ordered = false

  const flushList = (key: string) => {
    if (!listItems.length) return
    const items = listItems.map((item, index) => (
      <li key={`${key}-li-${index}`} className="ml-4">
        {renderInline(item, `${key}-${index}`)}
      </li>
    ))
    blocks.push(
      ordered ? (
        <ol key={key} className="my-2 list-decimal space-y-1 text-slate-700 dark:text-slate-300">
          {items}
        </ol>
      ) : (
        <ul key={key} className="my-2 list-disc space-y-1 text-slate-700 dark:text-slate-300">
          {items}
        </ul>
      ),
    )
    listItems = []
  }

  lines.forEach((rawLine, index) => {
    const line = rawLine.trimEnd()
    const key = `l${index}`

    if (!line.trim()) {
      flushList(`${key}-list`)
      return
    }

    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    if (heading) {
      flushList(`${key}-list`)
      const level = heading[1].length
      const size =
        level === 1
          ? 'text-lg'
          : level === 2
            ? 'text-base'
            : level === 3
              ? 'text-sm'
              : 'text-xs'
      blocks.push(
        <h3
          key={key}
          className={clsx(
            'mb-1.5 mt-4 font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400',
            size,
          )}
        >
          {renderInline(heading[2], key)}
        </h3>,
      )
      return
    }

    const bullet = /^\s*[-*]\s+(.*)$/.exec(line)
    if (bullet) {
      if (ordered) flushList(`${key}-list`)
      ordered = false
      listItems.push(bullet[1])
      return
    }

    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    if (numbered) {
      if (!ordered) flushList(`${key}-list`)
      ordered = true
      listItems.push(numbered[1])
      return
    }

    flushList(`${key}-list`)
    blocks.push(
      <p key={key} className="my-1.5 leading-relaxed text-slate-700 dark:text-slate-300">
        {renderInline(line, key)}
      </p>,
    )
  })

  flushList('final-list')

  return <div className={clsx('text-sm', className)}>{blocks}</div>
}
