import type { ScoresInferenceRowDetail } from '../../api/bff'
import type { LatticeSignature } from '../../api/inferenceStreamEventSchema'
import {
  formatLatticeBuildLabel,
  formatPlaceholderDepartureLabel,
  formatUnknownLossLeftoverModal,
  latticeSignaturesFromDetail,
  leftoverFromInferenceDetail,
  placeholderDeparturesFromDetail,
  shipClassLabel,
} from './uncharacterizedRosterChrome'

function LatticeSignatureSection({ signature }: { signature: LatticeSignature }) {
  return (
    <section className="rounded border border-[#52575d]/70 bg-[#2a2d30] p-3">
      <h3 className="text-xs font-medium text-slate-200">
        {shipClassLabel(signature.shipClass)} lattice
      </h3>
      <ul className="mt-2 flex flex-col gap-1 text-xs text-slate-300">
        <li>{formatLatticeBuildLabel(signature.build)}</li>
        <li>{formatPlaceholderDepartureLabel(signature.departure)}</li>
      </ul>
    </section>
  )
}

export function UncharacterizedRosterDetail({
  detail,
}: {
  detail: ScoresInferenceRowDetail
}) {
  const leftover = leftoverFromInferenceDetail(detail)
  const departures = placeholderDeparturesFromDetail(detail)
  const signatures = latticeSignaturesFromDetail(detail)

  return (
    <div className="flex flex-col gap-3">
      {leftover != null ? (
        <p className="text-xs text-slate-300">{formatUnknownLossLeftoverModal(leftover)}</p>
      ) : null}
      {departures.length > 0 ? (
        <section>
          <h3 className="text-xs font-medium text-slate-200">Placeholder departures</h3>
          <ul className="mt-2 flex flex-col gap-1 text-xs text-slate-300">
            {departures.map((departure, index) => (
              <li key={`departure-${departure.shipClass}-${index}`}>
                {formatPlaceholderDepartureLabel(departure)}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {signatures.length > 0 ? (
        <div className="flex flex-col gap-3">
          <h3 className="text-xs font-medium text-slate-200">Lattice signatures</h3>
          {signatures.map((signature, index) => (
            <LatticeSignatureSection
              key={`lattice-${signature.shipClass}-${index}`}
              signature={signature}
            />
          ))}
        </div>
      ) : null}
    </div>
  )
}
