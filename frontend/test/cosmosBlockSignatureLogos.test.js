import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

const page = fs.readFileSync(new URL('../src/pages/CosmosBlockDetail.jsx', import.meta.url), 'utf8')

test('commit signatures reuse validator-list avatars without changing signature identity links', () => {
  assert.match(page, /useCosmosResource\(`\/api\/networks\/\$\{network\.id\}\/validators`, null\)/)
  assert.match(page, /avatarByOperator = new Map\(\(validators\.data\?\.validators \|\| \[\]\)\.map/)
  assert.match(page, /imageSrc=\{sig\.operator_address \? avatarByOperator\.get\(sig\.operator_address\) : undefined\}/)
  assert.match(page, /href=\{sig\.operator_address \? `\/networks\/\$\{network\.id\}\/validators\/\$\{encodeURIComponent\(sig\.operator_address\)\}` : undefined\}/)
})
