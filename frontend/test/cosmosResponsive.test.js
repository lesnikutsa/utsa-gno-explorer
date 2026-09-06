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

test('Cosmos node strip stays on one row for collapsed desktop widths and degrades safely below that', () => {
  assert.match(styles, /@media \(max-width: 1100px\) and \(min-width: 900px\)[\s\S]*grid-template-columns:\s*\.65fr 1\.15fr \.75fr \.8fr \.85fr 1\.55fr \.9fr;/)
  assert.match(styles, /@media \(max-width: 899px\) and \(min-width: 761px\)[\s\S]*grid-template-columns:\s*repeat\(12, minmax\(0, 1fr\)\);/)
  assert.match(styles, /\.cosmos-node-strip > dl > div:nth-child\(-n\+4\)\s*\{[^}]*grid-column:\s*span 3;/s)
  assert.match(styles, /\.cosmos-node-strip > dl > div:nth-child\(n\+5\)\s*\{[^}]*grid-column:\s*span 4;/s)
  assert.match(styles, /@media \(max-width: 760px\)[\s\S]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\);/)
  assert.match(styles, /\.cosmos-node-strip > dl > div:last-child:nth-child\(odd\)\s*\{[^}]*grid-column:\s*1 \/ -1;/s)
  assert.match(styles, /@media \(max-width: 480px\)[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\);/)
})
