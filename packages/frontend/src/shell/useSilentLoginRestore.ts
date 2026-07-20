import { useEffect, useRef, useState } from 'react'
import { probeCredentials } from '../api/credentialsClient'
import {
  readRememberedLoginUsername,
} from '../components/LoginModal'
import { useSessionStore } from '../stores/session'

export type SilentLoginRestoreStatus = 'pending' | 'restored' | 'failed' | 'skipped'

/**
 * After shell hydration: credential probe for remembered username.
 * On success adopts the name (silent login restore). On failure signals the login modal.
 */
export function useSilentLoginRestore(enabled: boolean): {
  status: SilentLoginRestoreStatus
  shouldOpenLoginModal: boolean
  clearShouldOpenLoginModal: () => void
} {
  const adoptLoginName = useSessionStore((s) => s.adoptLoginName)
  const [status, setStatus] = useState<SilentLoginRestoreStatus>('pending')
  const [shouldOpenLoginModal, setShouldOpenLoginModal] = useState(false)
  const startedRef = useRef(false)

  useEffect(() => {
    if (!enabled || startedRef.current) return
    startedRef.current = true

    const remembered = readRememberedLoginUsername()
    if (!remembered) {
      setStatus('skipped')
      return
    }

    let cancelled = false
    void (async () => {
      try {
        const present = await probeCredentials(remembered)
        if (cancelled) return
        if (present) {
          adoptLoginName(remembered)
          setStatus('restored')
        } else {
          setStatus('failed')
          setShouldOpenLoginModal(true)
        }
      } catch {
        if (cancelled) return
        setStatus('failed')
        setShouldOpenLoginModal(true)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [enabled, adoptLoginName])

  return {
    status,
    shouldOpenLoginModal,
    clearShouldOpenLoginModal: () => setShouldOpenLoginModal(false),
  }
}
