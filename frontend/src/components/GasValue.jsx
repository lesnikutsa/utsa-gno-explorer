import { formatGas, parseGas } from '../utils/gas'

export function GasValue({ used, wanted }) {
  const formattedUsed = formatGas(used)
  const hasGasContext = parseGas(used) !== null && parseGas(wanted) !== null
  const title = hasGasContext ? `Used ${formattedUsed} of ${formatGas(wanted)} gas` : undefined

  return <span className="mono" title={title}>{formattedUsed}</span>
}
