export const THEME_STORAGE_KEY = 'utsa-gno-explorer.theme'
export const DEFAULT_THEME = 'dark'

export function isTheme(value) {
  return value === 'dark' || value === 'light'
}

export function readStoredTheme(storage = window.localStorage) {
  try {
    const storedTheme = storage.getItem(THEME_STORAGE_KEY)
    return isTheme(storedTheme) ? storedTheme : DEFAULT_THEME
  } catch {
    return DEFAULT_THEME
  }
}

export function applyTheme(theme, root = document.documentElement) {
  const safeTheme = isTheme(theme) ? theme : DEFAULT_THEME
  root.dataset.theme = safeTheme
  return safeTheme
}

export function initializeTheme() {
  return applyTheme(readStoredTheme())
}
