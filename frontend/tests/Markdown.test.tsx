import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Markdown } from '../src/components/Markdown'

describe('Markdown', () => {
  it('renders bold text as a strong element', () => {
    render(<Markdown text="**bold**" />)
    expect(screen.getByText('bold').tagName).toBe('STRONG')
  })

  it('renders inline code', () => {
    render(<Markdown text="use `SUM(Revenue)` here" />)
    expect(screen.getByText('SUM(Revenue)').tagName).toBe('CODE')
  })

  it('renders bullet lists', () => {
    render(<Markdown text={'- one\n- two'} />)
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })

  it('renders ordered lists', () => {
    render(<Markdown text={'1. first\n2. second'} />)
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })

  it('renders headings', () => {
    render(<Markdown text="### Result" />)
    expect(screen.getByText('Result').tagName).toBe('H3')
  })

  it('never interprets HTML as markup', () => {
    const { container } = render(<Markdown text='<img src=x onerror="alert(1)"> <script>alert(2)</script>' />)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect(container.textContent).toContain('<img src=x onerror="alert(1)">')
  })

  it('escapes HTML entities in the rendered text', () => {
    const { container } = render(<Markdown text="a < b & c > d" />)
    expect(container.textContent).toContain('a < b & c > d')
    expect(container.innerHTML).toContain('&lt;')
  })

  it('handles an empty answer', () => {
    const { container } = render(<Markdown text="" />)
    expect(container.textContent).toBe('')
  })
})
