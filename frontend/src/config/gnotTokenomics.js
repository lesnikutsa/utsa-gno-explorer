export const GNOT_TOKENOMICS = Object.freeze({
  total: 1_333_000_000,
  totalDisplay: '1.333B GNOT',
  accessibleTotal: '1.333 billion GNOT',
  sourceUrl: 'https://sale.gno.land/',
  circulatingAtTge: Object.freeze({
    amount: 197_320_000,
    display: '≈ 197.32M GNOT',
    percentage: '14.8%',
  }),
  allocations: Object.freeze([
    Object.freeze({ label: 'Cosmos Airdrop', amount: 350_000_000, percentage: '26.26%', color: '#5b8ff9' }),
    Object.freeze({ label: 'NewTendermint', amount: 332_000_000, percentage: '24.91%', color: '#61d9a7' }),
    Object.freeze({ label: 'Investors', amount: 300_000_000, percentage: '22.51%', color: '#f6bd16' }),
    Object.freeze({ label: 'AtomOne Airdrop', amount: 231_000_000, percentage: '17.33%', color: '#e868a2' }),
    Object.freeze({ label: 'Ecosystem Treasury', amount: 60_000_000, percentage: '4.50%', color: '#6dc8ec' }),
    Object.freeze({ label: 'Core Treasury', amount: 40_000_000, percentage: '3.00%', color: '#9270ca' }),
    Object.freeze({ label: 'Validator Treasury', amount: 20_000_000, percentage: '1.50%', color: '#ff8a4c' }),
  ]),
})

export default GNOT_TOKENOMICS
