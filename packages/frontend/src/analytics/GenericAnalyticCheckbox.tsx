import { AnalyticSidebarTile } from './AnalyticSidebarTile'

export type GenericAnalyticCheckboxProps = {
  name: string
  enabled: boolean
  supportsMode: boolean
  depressed: boolean
  onToggle: () => void
}

/** Default sidebar row: shared enable checkbox and tile chrome, no extra controls. */
export function GenericAnalyticCheckbox(props: GenericAnalyticCheckboxProps) {
  return <AnalyticSidebarTile {...props} />
}
