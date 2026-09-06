import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8')
const layout = read('../src/layouts/CosmosExplorerLayout.jsx')
const styles = read('../src/styles/cosmos-responsive.css')

test('Cosmos layout loads isolated medium-width responsive polish', () => {
  assert.match(layout, /import '\.\.\/styles\/cosmos-responsive\.css'/)
  assert.match(styles, /\.app-frame:has\(\.cosmos-node-strip\) \.topbar-block-time__label\s*\{\s*display:\s*none;/)
  assert.match(styles, /\.app-frame:has\(\.cosmos-node-strip\) \.topbar-block-time-control\s*\{[^}]*width:\s*90px;[^}]*flex-basis:\s*90px;/s)
})

test('Cosmos node strip uses stable equal columns instead of flex row stretching', () => {
  assert.match(styles, /@media \(max-width: 1100px\) and \(min-width: 761px\)[\s\S]*\.cosmos-node-strip > dl\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*repeat\(4, minmax\(0, 1fr\)\);/)
  assert.match(styles, /@media \(max-width: 760px\)[\s\S]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\);/)
  assert.match(styles, /@media \(max-width: 480px\)[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\);/)
})
