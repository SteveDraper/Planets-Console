import { useEffect, useRef, useState } from 'react'
import { useSessionStore } from '../stores/session'
import { cn } from '../lib/utils'

type LoginModalProps = {
  isOpen: boolean
  onClose: () => void
}

export function LoginModal({ isOpen, onClose }: LoginModalProps) {
  const setCredentials = useSessionStore((s) => s.setCredentials)
  const dialogRef = useRef<HTMLDivElement>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  function closeAndReturnFocus() {
    const target = returnFocusRef.current
    onClose()
    if (target?.focus) {
      requestAnimationFrame(() => target.focus())
    }
  }

  useEffect(() => {
    if (!isOpen) return
    returnFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    const el = dialogRef.current
    if (!el) return
    const focusables = el.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    )
    const first = focusables[0]
    if (first) first.focus()
  }, [isOpen])

  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        closeAndReturnFocus()
      }
      if (e.key === 'Tab') {
        const el = dialogRef.current
        if (!el) return
        const focusables = Array.from(
          el.querySelectorAll<HTMLElement>(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
          )
        )
        const len = focusables.length
        if (len === 0) return
        const i = focusables.indexOf(document.activeElement as HTMLElement)
        if (e.shiftKey) {
          if (i <= 0) {
            e.preventDefault()
            focusables[len - 1]?.focus()
          }
        } else {
          if (i === -1 || i >= len - 1) {
            e.preventDefault()
            focusables[0]?.focus()
          }
        }
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isOpen])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmedName = name.trim()
    if (!trimmedName) {
      setError('Name is required')
      return
    }
    setCredentials(trimmedName, password)
    closeAndReturnFocus()
  }

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      aria-hidden="false"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="login-dialog-title"
        className={cn(
          'flex w-full max-w-sm flex-col gap-3 rounded border border-[#52575d] bg-[#40454a] p-4 shadow-lg',
          'focus:outline-none'
        )}
      >
        <h2 id="login-dialog-title" className="text-sm font-medium text-slate-200">
          Log in to planets.nu
        </h2>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="login-name" className="text-xs text-slate-400">
              Name
            </label>
            <input
              id="login-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoComplete="username"
              className="rounded border border-[#52575d] bg-[#2b2e32] px-2 py-1.5 text-sm text-slate-200 focus:border-slate-400 focus:outline-none"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="login-password" className="text-xs text-slate-400">
              Password
            </label>
            <input
              id="login-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              className="rounded border border-[#52575d] bg-[#2b2e32] px-2 py-1.5 text-sm text-slate-200 focus:border-slate-400 focus:outline-none"
            />
          </div>
          {error && (
            <p className="text-xs text-red-400" role="alert">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={closeAndReturnFocus}
              className="rounded border border-[#52575d] px-3 py-1.5 text-xs text-slate-300 hover:bg-white/10"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="rounded border border-[#52575d] bg-[#52575d] px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-[#5e6369]"
            >
              Log in
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
