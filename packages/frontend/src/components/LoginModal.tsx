import { useLayoutEffect, useRef, useState } from 'react'
import {
  dropCredentials,
  exchangeCredentials,
  probeCredentials,
} from '../api/credentialsClient'
import { useModalKeydownFocusTrap } from '../lib/modalKeydownFocusTrap'
import {
  clearRememberedLoginUsername,
  readRememberedLoginUsername,
  writeRememberedLoginUsername,
} from '../lib/rememberedLoginUsername'
import { restoreFocusToElementOrFallback } from '../lib/restoreFocus'
import { useSessionStore } from '../stores/session'
import { cn } from '../lib/utils'

type LoginModalProps = {
  isOpen: boolean
  onClose: () => void
  getFocusRestoreFallback?: () => HTMLElement | null
  /** Called after login exchange or name-only identity switch succeeds. */
  onIdentityEstablished?: () => void
  reportShellError?: (message: string) => void
}

/** Match non-autofill styling; browsers force autofill backgrounds unless overridden. */
const loginFieldClassName = cn(
  'rounded border border-[#52575d] bg-[#2b2e32] px-2 py-1.5 text-sm text-slate-200',
  'focus:border-slate-400 focus:outline-none',
  '[&:-webkit-autofill]:border-[#52575d] [&:-webkit-autofill]:shadow-[inset_0_0_0_1000px_rgb(43_46_50)] [&:-webkit-autofill]:[-webkit-text-fill-color:rgb(226_232_240)]',
  '[&:autofill]:border-[#52575d] [&:autofill]:bg-[#2b2e32] [&:autofill]:text-slate-200'
)

export function LoginModal({
  isOpen,
  onClose,
  getFocusRestoreFallback,
  onIdentityEstablished,
  reportShellError,
}: LoginModalProps) {
  const adoptLoginName = useSessionStore((s) => s.adoptLoginName)
  const clearSession = useSessionStore((s) => s.clearSession)
  const sessionName = useSessionStore((s) => s.name)
  const dialogRef = useRef<HTMLDivElement>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [dropKeyOnLogout, setDropKeyOnLogout] = useState(false)

  function closeAndReturnFocus() {
    const target = returnFocusRef.current
    onClose()
    restoreFocusToElementOrFallback(target, getFocusRestoreFallback)
  }

  useLayoutEffect(() => {
    if (!isOpen) return
    returnFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    const savedName = readRememberedLoginUsername()
    setName(savedName)
    setPassword('')
    setError(null)
    setBusy(false)
    setDropKeyOnLogout(false)

    const el = dialogRef.current
    if (!el) return
    const focusables = el.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    )
    const target =
      savedName !== '' && focusables.length >= 2 ? focusables[1] : focusables[0]
    target?.focus()
  }, [isOpen])

  useModalKeydownFocusTrap(isOpen, dialogRef, closeAndReturnFocus)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmedName = name.trim()
    if (!trimmedName) {
      setError('Name is required')
      return
    }
    setBusy(true)
    setError(null)
    try {
      if (password.trim() !== '') {
        await exchangeCredentials(trimmedName, password)
        adoptLoginName(trimmedName)
        writeRememberedLoginUsername(trimmedName)
        onIdentityEstablished?.()
        closeAndReturnFocus()
        return
      }
      const present = await probeCredentials(trimmedName)
      if (!present) {
        setError('Password required (no stored account API key for this name)')
        return
      }
      adoptLoginName(trimmedName)
      writeRememberedLoginUsername(trimmedName)
      onIdentityEstablished?.()
      closeAndReturnFocus()
    } catch (err) {
      const message =
        err instanceof Error ? err.message : typeof err === 'string' ? err : 'Login failed'
      setError(message)
      reportShellError?.(message)
    } finally {
      setBusy(false)
    }
  }

  const handleLogOut = async () => {
    const current = sessionName?.trim() ?? name.trim()
    setBusy(true)
    setError(null)
    try {
      if (dropKeyOnLogout && current) {
        await dropCredentials(current)
      }
      clearSession()
      clearRememberedLoginUsername()
      closeAndReturnFocus()
    } catch (err) {
      const message =
        err instanceof Error ? err.message : typeof err === 'string' ? err : 'Log out failed'
      setError(message)
      reportShellError?.(message)
    } finally {
      setBusy(false)
    }
  }

  if (!isOpen) return null

  const showLogOut = Boolean(sessionName?.trim())

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
              disabled={busy}
              className={loginFieldClassName}
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
              disabled={busy}
              className={loginFieldClassName}
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
              disabled={busy}
              className="rounded border border-[#52575d] px-3 py-1.5 text-xs text-slate-300 hover:bg-white/10"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy}
              className="rounded border border-[#52575d] bg-[#52575d] px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-[#5e6369] disabled:opacity-50"
            >
              Log in
            </button>
          </div>
        </form>
        {showLogOut && (
          <div className="flex flex-col gap-2 border-t border-[#52575d] pt-3">
            <label className="flex items-center gap-2 text-xs text-slate-400">
              <input
                type="checkbox"
                checked={dropKeyOnLogout}
                onChange={(e) => setDropKeyOnLogout(e.target.checked)}
                disabled={busy}
              />
              Also delete stored account API key on this server
            </label>
            <button
              type="button"
              onClick={() => void handleLogOut()}
              disabled={busy}
              className="self-start rounded border border-[#52575d] px-3 py-1.5 text-xs text-slate-300 hover:bg-white/10 disabled:opacity-50"
            >
              Log out
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
