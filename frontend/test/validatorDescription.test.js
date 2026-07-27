import test from 'node:test'
import assert from 'node:assert/strict'

import { parseValidatorDescription, splitValidatorDescriptionLinks } from '../src/utils/validatorDescription.js'

test('parses ordered labelled sections without requiring newlines', () => {
  const parsed = parseValidatorDescription('**Validator Name:** UTSA **Total AuM:** ~$5M')
  assert.equal(parsed.type, 'structured')
  assert.deepEqual(parsed.sections, [
    { label: 'Validator Name', content: 'UTSA' },
    { label: 'Total AuM', content: '~$5M' },
  ])
})

test('normalizes CRLF, trims outer whitespace, and preserves internal text', () => {
  const parsed = parseValidatorDescription(' Intro\r\nline \r\n ** About :** first\r\nsecond ')
  assert.equal(parsed.preamble, 'Intro\nline')
  assert.deepEqual(parsed.sections, [{ label: 'About', content: 'first\nsecond' }])
})

test('omits empty sections while retaining surrounding content', () => {
  const parsed = parseValidatorDescription('before ** Empty:** **Kept:** value')
  assert.equal(parsed.preamble, 'before')
  assert.deepEqual(parsed.sections, [{ label: 'Kept', content: 'value' }])
})

test('returns plain text when there are no recognized markers', () => {
  assert.deepEqual(parseValidatorDescription(' Independent validator since 2022. '), {
    type: 'plain', content: 'Independent validator since 2022.', preamble: '', sections: [],
  })
  assert.equal(parseValidatorDescription(`**${'x'.repeat(101)}:** value`).type, 'plain')
})

test('returns an empty model for null, undefined, and whitespace', () => {
  for (const value of [null, undefined, '', ' \r\n ', '**Empty:**']) assert.equal(parseValidatorDescription(value).type, 'empty')
})

test('recognizes only case-insensitive absolute HTTP URLs', () => {
  const parts = splitValidatorDescriptionLinks('a HTTP://EXAMPLE.com b https://utsa.tech c javascript:alert(1) data:text/html,x')
  assert.deepEqual(parts.filter((part) => part.type === 'link').map((part) => part.href), [
    'HTTP://EXAMPLE.com', 'https://utsa.tech',
  ])
})

test('keeps trailing punctuation outside URL hrefs without data loss', () => {
  const input = 'See https://example.com., then https://example.org/path);]'
  const parts = splitValidatorDescriptionLinks(input)
  assert.deepEqual(parts.filter((part) => part.type === 'link').map((part) => part.href), [
    'https://example.com', 'https://example.org/path',
  ])
  assert.equal(parts.map((part) => part.value).join(''), input)
})

test('leaves HTML as text for React to escape', () => {
  const input = '<script>alert(1)</script> and <b>text</b>'
  assert.deepEqual(splitValidatorDescriptionLinks(input), [{ type: 'text', value: input }])
})
