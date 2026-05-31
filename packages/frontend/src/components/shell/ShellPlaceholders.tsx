import { errorDetailFromUnknown } from '../../lib/queryRetry'

export function ShellCenterPane({ message }: { message: string }) {
  return (
    <main className="flex flex-1 items-center justify-center bg-black p-8 text-gray-400">
      {message}
    </main>
  )
}

export function ShellErrorPane({
  title,
  error,
  fallbackDetail,
  footer,
}: {
  title: string
  error: unknown
  fallbackDetail?: string
  footer?: string
}) {
  const detail = errorDetailFromUnknown(error, fallbackDetail ?? 'Unknown error')
  return (
    <main className="flex max-w-3xl flex-1 flex-col items-center justify-center gap-2 bg-black p-8 text-red-400">
      <p className="text-center font-medium">{title}</p>
      <p className="whitespace-pre-wrap break-words text-left text-sm text-red-300/90">
        {detail}
      </p>
      {footer != null ? (
        <p className="text-center text-sm text-gray-500">{footer}</p>
      ) : null}
    </main>
  )
}
