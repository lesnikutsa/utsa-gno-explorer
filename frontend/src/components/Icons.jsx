function Icon({ children, className = '' }) {
  return <svg className={`icon ${className}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
}

export const HomeIcon = () => <Icon><path d="m4 11 8-7 8 7v9h-6v-6h-4v6H4Z" /></Icon>
export const BlocksIcon = () => <Icon><rect x="4" y="4" width="7" height="7" /><rect x="13" y="4" width="7" height="7" /><rect x="4" y="13" width="7" height="7" /><rect x="13" y="13" width="7" height="7" /></Icon>
export const ValidatorsIcon = () => <Icon><circle cx="12" cy="8" r="3" /><path d="M6.5 20c.4-4 2.2-6 5.5-6s5.1 2 5.5 6M18 7l1.5 1.5L22 6" /></Icon>
export const NetworkIcon = () => <Icon><circle cx="5" cy="12" r="2" /><circle cx="18" cy="6" r="2" /><circle cx="19" cy="18" r="2" /><path d="m7 11 9-4M7 13l10 4M18 8l1 8" /></Icon>
export const MapIcon = () => <Icon><path d="m4 6 5-2 6 2 5-2v14l-5 2-6-2-5 2Z" /><path d="M9 4v14M15 6v14" /></Icon>
export const ChainIcon = () => <Icon><path d="M9.5 14.5 8 16a3 3 0 0 1-4-4l3-3a3 3 0 0 1 4 0M14.5 9.5 16 8a3 3 0 0 1 4 4l-3 3a3 3 0 0 1-4 0M9 15l6-6" /></Icon>
export const SearchIcon = () => <Icon><circle cx="11" cy="11" r="6" /><path d="m16 16 4 4" /></Icon>
export const MenuIcon = () => <Icon><path d="M4 7h16M4 12h16M4 17h16" /></Icon>
export const ChevronDownIcon = () => <Icon><path d="m8 10 4 4 4-4" /></Icon>
