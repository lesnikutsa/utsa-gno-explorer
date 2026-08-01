const NON_PRINTABLE_ARGUMENT = /[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/u

export function isValidArgumentValue(value) {
  return typeof value === 'string'
    && Array.from(value).length <= 256
    && !NON_PRINTABLE_ARGUMENT.test(value)
}
