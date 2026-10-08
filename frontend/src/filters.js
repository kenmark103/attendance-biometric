// URL filter state (§4.2). The URL query string is the single source of truth;
// components read via parseFilters and write via serializeFilters + navigate.
import { teamSlug } from './metrics.js';

export const RANGES = ['whole', 'h1', 'h2'];
export const RANGE_LABEL = { whole: 'Whole month', h1: 'H1 (1–15)', h2: 'H2 (16–end)' };
export const SHIFTS = ['all', 'day', 'night', 'hybrid'];

const MON_FULL = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
  'August', 'September', 'October', 'November', 'December'];

export function monthKeyOf(dateStr) {
  return String(dateStr).slice(0, 7); // YYYY-MM
}

export function monthLabel(yyyyMM) {
  const [y, m] = String(yyyyMM).split('-').map(Number);
  return `${MON_FULL[m - 1]} ${y}`;
}

export function monthShortLabel(yyyyMM) {
  const [y, m] = String(yyyyMM).split('-').map(Number);
  return `${MON_FULL[m - 1].slice(0, 3)} ${y}`;
}

export function halfOfDate(dateStr) {
  return Number(String(dateStr).slice(8, 10)) <= 15 ? 'h1' : 'h2';
}

export function currentMonthKey(today) {
  return String(today).slice(0, 7);
}

// Every calendar day of a month∩range (future days included; they classify
// as pending and stay out of denominators).
export function rangeDates(month, range) {
  const [y, m] = String(month).split('-').map(Number);
  if (!y || !m) return [];
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const out = [];
  for (let d = 1; d <= last; d++) {
    const iso = `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    if (range === 'h1' && d > 15) continue;
    if (range === 'h2' && d <= 15) continue;
    out.push(iso);
  }
  return out;
}

export function defaultFilters(months, today) {
  const cur = currentMonthKey(today);
  const month = months.includes(cur) ? cur : months[months.length - 1] || '';
  const range = month === cur ? halfOfDate(today) : 'whole';
  return { month, range, day: '', shift: 'all', teams: null, nopunch: false };
}

// slug <-> team-name maps built from the data.
export function teamMaps(teamNames) {
  const slugToName = new Map();
  for (const n of teamNames) slugToName.set(teamSlug(n), n);
  return { slugToName };
}

export function parseFilters(search, months, slugToName, today) {
  const p = new URLSearchParams(search || '');
  const dflt = defaultFilters(months, today);
  let month = p.get('month') || dflt.month;
  if (!months.includes(month)) month = dflt.month;
  let range = (p.get('range') || '').toLowerCase();
  if (!RANGES.includes(range)) {
    range = month === currentMonthKey(today) ? halfOfDate(today) : 'whole';
  }
  let day = p.get('day') || '';
  if (day && !rangeDates(month, range).includes(day)) day = '';
  let shift = (p.get('shift') || 'all').toLowerCase();
  if (!SHIFTS.includes(shift)) shift = 'all';
  let teams = null;
  const traw = p.get('teams');
  if (traw !== null) {
    const slugs = traw.split(',').map((s) => s.trim()).filter(Boolean)
      .filter((s) => slugToName.has(s));
    teams = slugs; // empty array = select-at-least-one enforced by UI, never persisted empty
    if (!slugs.length) teams = null;
  }
  return {
    month, range, day, shift, teams,
    nopunch: p.get('nopunch') === 'exclude',
    view: p.get('view') === 'heatmap' ? 'heatmap' : 'list',
    q: p.get('q') || '',
    type: p.get('type') || 'all',
    sort: p.get('sort') || '',
    allteams: p.get('allteams') === '1',
    group: p.get('group') || '',
  };
}

// Serialize back; defaults are omitted so URLs stay short and shareable.
export function serializeFilters(f, months, today) {
  const dflt = defaultFilters(months, today);
  const curIsMonth = f.month === currentMonthKey(today);
  const dfltRange = curIsMonth ? halfOfDate(today) : 'whole';
  const p = new URLSearchParams();
  if (f.month && f.month !== dflt.month) p.set('month', f.month);
  if (f.range !== (f.month === dflt.month ? dflt.range : dfltRange)) p.set('range', f.range);
  if (f.day) p.set('day', f.day);
  if (f.shift && f.shift !== 'all') p.set('shift', f.shift);
  if (f.teams) p.set('teams', f.teams.join(','));
  if (f.nopunch) p.set('nopunch', 'exclude');
  return p;
}

export function isDefaultFilter(f, months, today) {
  return serializeFilters({ ...f, view: 'list', q: '', type: 'all', sort: '', allteams: false, group: '' }, months, today).toString() === '';
}

// Short caption (§5.4): "October 2026 · H1 · 8 teams · All shifts".
export function scopeCaption(f, slugToName) {
  const parts = [monthLabel(f.month)];
  if (f.day) {
    parts.push(f.day.slice(8, 10).replace(/^0/, ''));
  } else if (f.range !== 'whole') {
    parts.push(RANGE_LABEL[f.range]);
  }
  if (!f.teams) parts.push('All teams');
  else if (f.teams.length <= 2) parts.push(f.teams.map((s) => slugToName.get(s)).join(', '));
  else parts.push(`${f.teams.length} teams`);
  parts.push(f.shift === 'all' ? 'All shifts' : `${f.shift[0].toUpperCase()}${f.shift.slice(1)} shift`);
  return parts.join(' · ');
}
