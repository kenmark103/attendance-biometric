// Filter state: the dashboard opens on the whole month; H1/H2 are opt-in.
import test from 'node:test';
import assert from 'node:assert/strict';
import { defaultFilters, parseFilters, serializeFilters, scopeCaption } from '../src/filters.js';

const TODAY = '2026-10-21';           // day 21 -> used to default to H2
const MONTHS = ['2026-09', '2026-10'];
const SLUGS = new Map([['team-a', 'Team A']]);

test('default is whole month even mid-month', () => {
  assert.equal(defaultFilters(MONTHS, TODAY).range, 'whole');
});

test('no range param in url -> whole', () => {
  const f = parseFilters('', MONTHS, SLUGS, TODAY);
  assert.equal(f.range, 'whole');
  assert.equal(f.month, '2026-10');
});

test('explicit half-month in url is still honoured', () => {
  assert.equal(parseFilters('range=h1', MONTHS, SLUGS, TODAY).range, 'h1');
  assert.equal(parseFilters('range=h2', MONTHS, SLUGS, TODAY).range, 'h2');
});

test('whole month is omitted from the url, halves are kept', () => {
  const f = parseFilters('', MONTHS, SLUGS, TODAY);
  assert.equal(serializeFilters(f, MONTHS, TODAY).toString(), '');
  f.range = 'h2';
  assert.equal(serializeFilters(f, MONTHS, TODAY).get('range'), 'h2');
  f.range = 'whole';
  assert.equal(serializeFilters(f, MONTHS, TODAY).get('range'), null);
});

test('reset (undefined month/range) does not emit range=undefined', () => {
  const p = serializeFilters({ month: undefined, range: undefined }, MONTHS, TODAY);
  assert.equal(p.get('range'), null);
  assert.equal(p.get('month'), null);
});

test('scope caption omits the range for a whole month', () => {
  const f = parseFilters('', MONTHS, SLUGS, TODAY);
  assert.equal(scopeCaption(f, SLUGS), 'October 2026 · All teams · All shifts');
  f.range = 'h2';
  assert.match(scopeCaption(f, SLUGS), /H2/);
});
