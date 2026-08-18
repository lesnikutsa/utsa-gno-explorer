import { useEffect, useState } from 'react'

export const INTERNAL_NAVIGATION_EVENT = 'explorer:navigate'

const currentHref = () => window.location.href

export const isInterceptableNavigation = (event, destination, target) => {
  if (event.defaultPrevented || event.button !== 0) return false
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false
  if (target && target.toLowerCase() !== '_self') return false

  const url = new URL(destination, currentHref())
  return url.origin === window.location.origin
}

export const navigateInternal = (destination) => {
  const url = new URL(destination, currentHref())
  if (url.origin !== window.location.origin) return false
  if (url.href === currentHref()) return false

  window.history.pushState({}, '', `${url.pathname}${url.search}${url.hash}`)
  window.scrollTo(0, 0)
  window.dispatchEvent(new Event(INTERNAL_NAVIGATION_EVENT))
  return true
}

export const usePathname = () => {
  const [pathname, setPathname] = useState(() => window.location.pathname)

  useEffect(() => {
    const updatePathname = () => setPathname(window.location.pathname)
    window.addEventListener('popstate', updatePathname)
    window.addEventListener(INTERNAL_NAVIGATION_EVENT, updatePathname)
    return () => {
      window.removeEventListener('popstate', updatePathname)
      window.removeEventListener(INTERNAL_NAVIGATION_EVENT, updatePathname)
    }
  }, [])

  return pathname
}
