import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const styles = readFileSync(new URL('../src/styles/app.css', import.meta.url), 'utf8')
const blocksPage = readFileSync(new URL('../src/pages/Blocks.jsx', import.meta.url), 'utf8')
const realmsPage = readFileSync(new URL('../src/pages/Realms.jsx', import.meta.url), 'utf8')
const validatorsPage = readFileSync(new URL('../src/pages/Validators.jsx', import.meta.url), 'utf8')

test('column centering is limited to the three requested table scopes', () => {
  assert.match(styles, /\.blocks-page__table--listing \.data-table th,\n\.blocks-page__table--listing \.data-table td,\n\.realms-page__table \.data-table th,\n\.realms-page__table \.data-table td,\n\.validators-page__table \.data-table th,\n\.validators-page__table \.data-table td \{ text-align: center; \}/)
  assert.match(blocksPage, /className="panel blocks-page__table blocks-page__table--listing"/)

  assert.match(styles, /\.data-table th \{ padding: 10px 16px;/)
  assert.match(styles, /\.data-table td \{ height: 35px; padding: 6px 12px;/)
  assert.match(styles, /\.data-table th \{[^}]*text-align: left;/)
  assert.match(styles, /\.transactions-page__table \.data-table th, \.transactions-page__table \.data-table td \{ text-align: center; \}/)
  assert.doesNotMatch(styles, /(?:dashboard-grid|realms-page__summary|realms-applications|validators-page__summary)[^\{]*\{[^}]*text-align: center;/)
})

test('nested table content is centered without changing its grouping', () => {
  assert.match(styles, /\.blocks-page__table--listing \.proposer-identity \{ margin-right: auto; margin-left: auto; \}/)
  assert.match(styles, /\.validators-page__table \.validator-identity-cell \{ justify-content: center; \}/)
  assert.match(styles, /\.validators-page__table \.validator-power,\n\.validators-page__table \.validator-signing-cell \{ align-items: center; \}/)
  assert.match(styles, /\.realms-page__table td \{[^}]*text-align: left; \}/)
})

test('realm sortable columns and fixed widths remain unchanged', () => {
  for (const definition of [
    "{ key: 'call_count', label: 'Direct Calls', sortable: true, defaultSortDirection: 'descending'",
    "{ key: 'success_rate', label: 'Success Rate', sortable: true, defaultSortDirection: 'descending'",
    "key: 'last_activity_at',\n    label: 'Last Activity',\n    sortable: true,\n    defaultSortDirection: 'descending'",
  ]) assert.ok(realmsPage.includes(definition))

  for (const [column, width] of [[1, 42], [2, 11], [3, 9], [4, 12], [5, 15], [6, 11]]) {
    assert.ok(styles.includes(`.realms-page__table th:nth-child(${column}) { width: ${width}%; }`))
  }
})

test('validator sorting and favorites contracts remain present', () => {
  assert.match(validatorsPage, /compareFavoriteGroups\(left, right, favorites\)/)
  assert.match(validatorsPage, /toggleValidatorFavorite\(currentFavorites, address\)/)
  assert.match(validatorsPage, /className=\{`validator-favorite \$\{isFavorite \? 'validator-favorite--active' : ''\}`\}/)
  assert.match(validatorsPage, /sortKey=\{sort\.key\} sortDirection=\{sort\.direction\} onSort=/)
})
