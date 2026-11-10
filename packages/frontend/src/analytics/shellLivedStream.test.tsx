import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import type { AnalyticShellScope } from '../api/bff'
import { shellLivedStream } from './shellLivedStream'

type FakeSession = { token: string }

function FakeProvider({ token, children }: FakeSession & { children: ReactNode }) {
  return (
    <div>
      <span>{token}</span>
      {children}
    </div>
  )
}

function useFakeSession(): FakeSession {
  return { token: 'session-token' }
}

describe('shellLivedStream', () => {
  it('passes hook session props to Provider through Mount', () => {
    const stream = shellLivedStream({
      hook: useFakeSession,
      Provider: FakeProvider,
    })
    expect(stream.hook).toBe(useFakeSession)
    expect(stream.Provider).toBe(FakeProvider)

    const Mount = stream.Mount
    render(
      <Mount analyticScope={null} enabled>
        <span>child</span>
      </Mount>
    )
    expect(screen.getByText('session-token')).toBeInTheDocument()
    expect(screen.getByText('child')).toBeInTheDocument()
  })

  it('calls the hook and renders children when no Provider is bound', () => {
    const enabledFlags: boolean[] = []
    function useWatch(_analyticScope: AnalyticShellScope | null, enabled: boolean): undefined {
      enabledFlags.push(enabled)
    }
    const stream = shellLivedStream({ hook: useWatch })
    expect(stream.hook).toBe(useWatch)
    expect(stream).not.toHaveProperty('Provider')

    const Mount = stream.Mount
    render(
      <Mount analyticScope={null} enabled>
        <span>child</span>
      </Mount>
    )
    expect(enabledFlags).toEqual([true])
    expect(screen.getByText('child')).toBeInTheDocument()
  })

  it('requires Provider when the hook returns a session', () => {
    // @ts-expect-error session hooks must pass Provider
    shellLivedStream({ hook: useFakeSession })
  })
})
