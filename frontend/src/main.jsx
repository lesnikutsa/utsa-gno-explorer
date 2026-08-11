import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import 'flag-icons/css/flag-icons.min.css'
import './styles/theme.css'
import './styles/app.css'
import { initializeTheme } from './utils/theme'

initializeTheme()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
