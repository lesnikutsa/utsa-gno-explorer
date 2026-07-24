export function countryFlag(code) {
  if (typeof code !== 'string' || !/^[A-Z]{2}$/.test(code)) return ''
  return `fi fi-${code.toLowerCase()}`
}
