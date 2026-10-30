/** A tiny router on the History API (avoids a dependency for six screens and one dynamic route). */

import { useEffect, useState, type AnchorHTMLAttributes, type MouseEvent } from 'react'

const listeners = new Set<() => void>()

export function navigate(to: string) {
  if (to === window.location.pathname) return
  window.history.pushState(null, '', to)
  listeners.forEach((l) => l())
  window.scrollTo(0, 0)
}

export function usePath(): string {
  const [path, setPath] = useState(window.location.pathname)
  useEffect(() => {
    const update = () => setPath(window.location.pathname)
    listeners.add(update)
    window.addEventListener('popstate', update)
    return () => {
      listeners.delete(update)
      window.removeEventListener('popstate', update)
    }
  }, [])
  return path
}

/** "/runs/:id" matched against "/runs/abc" -> { id: "abc" } */
export function match(pattern: string, path: string): Record<string, string> | null {
  const p = pattern.split('/').filter(Boolean)
  const s = path.split('/').filter(Boolean)
  if (p.length !== s.length) return null
  const params: Record<string, string> = {}
  for (let i = 0; i < p.length; i++) {
    if (p[i].startsWith(':')) params[p[i].slice(1)] = decodeURIComponent(s[i])
    else if (p[i] !== s[i]) return null
  }
  return params
}

export function Link({ to, onClick, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { to: string }) {
  return (
    <a
      href={to}
      onClick={(e: MouseEvent<HTMLAnchorElement>) => {
        onClick?.(e)
        if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.button !== 0) return
        e.preventDefault()
        navigate(to)
      }}
      {...rest}
    />
  )
}
