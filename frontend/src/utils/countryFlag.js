export function countryFlag(code) {
  if (typeof code !== 'string' || !/^[A-Z]{2}$/.test(code)) return ''
  return String.fromCodePoint(...code.split('').map((character) => 127397 + character.charCodeAt(0)))
}
