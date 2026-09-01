import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
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
    expect(stream.lifetime).toBe('shell')
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
})
