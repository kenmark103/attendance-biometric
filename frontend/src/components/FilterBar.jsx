// Sticky one-row filter bar (§5). Reads filters from props (URL-derived),
// writes via onChange(patch, {replace}).
import React, { useState, useRef, useEffect } from 'react';
import { colors } from '../theme.js';
import { teamSlug, dayAndShortISO } from '../metrics.js';
import { RANGES, RANGE_LABEL, SHIFTS, monthLabel, rangeDates, isDefaultFilter } from '../filters.js';

const GROUP_KEY = 'attendance.teamGroups.v1';

function loadGroups() {
  try {
    const raw = localStorage.getItem(GROUP_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr.filter((g) => g && g.name && Array.isArray(g.teams)) : [];
  } catch { return []; }
}
function saveGroups(groups) {
  try { localStorage.setItem(GROUP_KEY, JSON.stringify(groups)); } catch { /* private mode */ }
}

export default function FilterBar({ filters, months, teams, teamHeadcounts, months_, daysInView, today, onChange, neverPunchedCount }) {
  const [open, setOpen] = useState(false);
  const [teamQuery, setTeamQuery] = useState('');
  const [groupName, setGroupName] = useState('');
  const [groups, setGroups] = useState(loadGroups);
  const popRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    function onDoc(e) {
      if (popRef.current && !popRef.current.contains(e.target)) setOpen(false);
    }
    function onKey(e) { if (e.key === 'Escape') setOpen(false); }
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey); };
  }, [open ]);

  const sel = {
    fontFamily: 'inherit', fontSize: 13, padding: '7px 10px', border: `1px solid ${colors.line}`,
    borderRadius: 4, background: colors.panel, color: colors.ink, maxWidth: 220,
  };
  const segBtn = (active) => ({
    fontFamily: 'inherit', fontSize: 12.5, padding: '7px 12px', cursor: 'pointer', whiteSpace: 'nowrap',
    border: `1px solid ${active ? colors.ink : colors.line}`,
    background: active ? colors.ink : colors.panel,
    color: active ? colors.paper : colors.ink, borderRadius: 20,
  });

  const selected = filters.teams; // null = all
  const teamCount = selected ? selected.length : teams.length;
  const visibleTeams = teams.filter((t) => t.toLowerCase().includes(teamQuery.toLowerCase()));
  const showReset = !isDefaultFilter({ ...filters, teams: filters.teams }, months, today);

  function toggleTeam(slug) {
    const cur = selected || teams.map(teamSlug);
    const next = cur.includes(slug) ? cur.filter((s) => s !== slug) : [...cur, slug];
    if (!next.length) return; // selection is never empty
    onChange({ teams: next.length === teams.length ? null : next });
  }

  return (
    <div style={{
      position: 'sticky', top: 0, zIndex: 50, background: colors.paper,
      borderBottom: `1px solid ${colors.line}`, padding: '8px 0', marginBottom: 16,
    }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', maxWidth: 1280 }}>
        <select aria-label="Month" value={filters.month} onChange={(e) => onChange({ month: e.target.value, range: undefined, day: '' })} style={sel}>
          {months.map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}
        </select>
        <div role="group" aria-label="Range" style={{ display: 'flex', gap: 4 }}>
          {RANGES.map((r) => (
            <button key={r} onClick={() => onChange({ range: r, day: '' })} style={segBtn(filters.range === r)}>
              {r === 'whole' ? 'Whole month' : RANGE_LABEL[r]}
            </button>
          ))}
        </div>
        <select aria-label="Day" value={filters.day} onChange={(e) => onChange({ day: e.target.value })} style={sel}>
          <option value="">All {daysInView.length} days in view</option>
          {daysInView.map((d) => (
            <option key={d.date} value={d.date}>
              {dayAndShortISO(d.date)}{d.weekend ? ' (weekend)' : ''}{d.holiday ? ' (holiday)' : ''}
            </option>
          ))}
        </select>
        <select aria-label="Shift" value={filters.shift} onChange={(e) => onChange({ shift: e.target.value })} style={sel}>
          {SHIFTS.map((s) => <option key={s} value={s}>{s === 'all' ? 'All shifts' : s[0].toUpperCase() + s.slice(1)}</option>)}
        </select>
        <div style={{ position: 'relative' }} ref={popRef}>
          <button onClick={() => { setOpen((o) => !o); setTeamQuery(''); }} style={{ ...sel, cursor: 'pointer' }} aria-haspopup="true" aria-expanded={open}>
            Teams: {selected ? `${teamCount} of ${teams.length}` : `All ${teams.length}`} ▾
          </button>
          {open && (
            <div style={{
              position: 'absolute', top: '110%', left: 0, width: 320, maxHeight: 420, overflowY: 'auto',
              background: colors.panel, border: `1px solid ${colors.line}`, borderRadius: 6,
              boxShadow: '0 8px 24px rgba(0,0,0,0.12)', padding: 10, zIndex: 60,
            }}>
              <input value={teamQuery} onChange={(e) => setTeamQuery(e.target.value)} placeholder="Search teams"
                style={{ ...sel, width: '100%', boxSizing: 'border-box', marginBottom: 8 }} />
              <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                <button onClick={() => onChange({ teams: null })} style={{ ...segBtn(false), fontSize: 12 }}>Select all</button>
                <button onClick={() => onChange({ teams: selected ? selected.slice(0, 1) : null })} style={{ ...segBtn(false), fontSize: 12 }}>Clear</button>
              </div>
              {visibleTeams.map((t) => {
                const slug = teamSlug(t);
                const checked = !selected || selected.includes(slug);
                return (
                  <label key={t} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, padding: '5px 4px', cursor: 'pointer' }}>
                    <input type="checkbox" checked={checked} onChange={() => toggleTeam(slug)} />
                    <span style={{ flex: 1 }}>{t}</span>
                    <span style={{ color: colors.muted, fontFamily: "'IBM Plex Mono', monospace", fontSize: 12 }}>{teamHeadcounts[t] ?? 0}</span>
                  </label>
                );
              })}
              <div style={{ borderTop: `1px solid ${colors.line}`, marginTop: 8, paddingTop: 8 }}>
                <div style={{ fontSize: 12, color: colors.muted, fontWeight: 600, marginBottom: 6 }}>Saved groups</div>
                {groups.map((g) => (
                  <div key={g.name} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, padding: '3px 0' }}>
                    <button onClick={() => onChange({ teams: g.teams.filter((s) => teams.map(teamSlug).includes(s)) })} style={{ background: 'none', border: 'none', color: colors.select, cursor: 'pointer', fontSize: 13, textAlign: 'left', flex: 1 }}>{g.name} ({g.teams.length})</button>
                    <button onClick={() => { const n = groups.filter((x) => x.name !== g.name); setGroups(n); saveGroups(n); }} style={{ background: 'none', border: 'none', color: colors.muted, cursor: 'pointer' }} aria-label={`Delete ${g.name}`}>×</button>
                  </div>
                ))}
                <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                  <input value={groupName} onChange={(e) => setGroupName(e.target.value)} placeholder="Save current as group…"
                    style={{ ...sel, flex: 1, fontSize: 12 }} />
                  <button onClick={() => {
                    const name = groupName.trim();
                    if (!name) return;
                    const n = [...groups.filter((x) => x.name !== name), { name, teams: selected || teams.map(teamSlug) }];
                    setGroups(n); saveGroups(n); setGroupName('');
                  }} style={{ ...segBtn(false), fontSize: 12 }}>Save</button>
                </div>
              </div>
              <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12.5, marginTop: 10, paddingTop: 8, borderTop: `1px solid ${colors.line}`, cursor: 'pointer' }}>
                <input type="checkbox" checked={filters.nopunch} onChange={(e) => onChange({ nopunch: e.target.checked })} />
                Exclude employees with no punches{filters.nopunch || neverPunchedCount === 0 ? '' : ` (${neverPunchedCount})`}
              </label>
            </div>
          )}
        </div>
        {showReset && (
          <button onClick={() => onChange({ month: undefined, range: undefined, day: '', shift: 'all', teams: null, nopunch: false }, { reset: true })}
            style={{ marginLeft: 'auto', background: 'none', border: 'none', color: colors.select, cursor: 'pointer', fontSize: 13 }}>
            Reset
          </button>
        )}
      </div>
    </div>
  );
}
