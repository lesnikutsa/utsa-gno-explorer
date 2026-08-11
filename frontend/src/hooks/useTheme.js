import { useCallback, useEffect, useState } from 'react'
import { applyTheme, DEFAULT_THEME, isTheme, THEME_STORAGE_KEY } from '../utils/theme'

export function useTheme() {
  const [theme, setTheme] = useState(() => {
    const documentTheme = document.documentElement.dataset.theme
    return isTheme(documentTheme) ? documentTheme : DEFAULT_THEME
  })

  useEffect(() => {
    applyTheme(theme)
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme)
    } catch {
      // Storage can be unavailable in privacy-restricted browsing contexts.
    }
  }, [theme])

  const toggleTheme = useCallback(() => {
    setTheme((currentTheme) => currentTheme === 'light' ? 'dark' : 'light')
  }, [])

  return { theme, toggleTheme }
}
