// Attendance heatmap (§7): rows = employees, columns = calendar days.
// One shared click/hover handler (event delegation). Sticky headers, legend,
// hatch for non-working days, 150-employee cap.
import React, { useMemo } from 'react';
import { colors } from '../theme.js';
import { classifyDay, statusLabel, shortDateISO, day2ISO } from '../metrics.js';

const CELL = 18, GAP = 2;

const FILL = {
  present: colors.good,
  missing_checkout: '#c58a1b',
  leave: '#3b6ea5',
  no_record: colors.alert,
  in_progress: `${colors.good}59`,
  pending: 'transparent',
  weekend: '#d9d9d4',
  holiday: '#d9d9d4',
};

export default function AttendanceHeatmap({ employees, rows, dates, ctx, scope, groupByTeam = false }) {
  const { leaveLoaded } = ctx;
  const matrix = useMemo(() => {
    const byEmp = new Map();
    for (const r of rows) {
      if (!byEmp.has(r.employeeId)) byEmp.set(r.employeeId, new Map());
      byEmp.get(r.employeeId).set(r.date, r);
    }
    const ordered = [...employees].sort((a, b) =>
      a.team.localeCompare(b.team) || b.noRecord - a.noRecord || a.name.localeCompare(b.name));
    const capped = ordered.slice(0, 150);
    return {
      capped,
      truncated: ordered.length - capped.length,
      cells: capped.map((e) => dates.map((d) => {
        const rec = (byEmp.get(e.id) || new Map()).get(d) || { date: d, leaves: [] };
        return { rec, status: classifyDay(rec, ctx) };
      })),
    };
  }, [employees, rows, dates, ctx]);

  function onGridClick(e) {
    const t = e.target.closest('[data-emp][data-date]');
    if (!t) return;
    scope.update({ day: t.dataset.date }, { path: `/employees/${t.dataset.emp}` });
  }

  let lastTeam = null;
  return (
    <div>
      <Legend leaveLoaded={leaveLoaded} />
      <div style={{ overflowX: 'auto', border: `1px solid ${colors.line}`, borderRadius: 4, background: colors.panel }}>
        <table style={{ borderCollapse: 'separate', borderSpacing: GAP, margin: 8 }} onClick={onGridClick}>
          <thead>
            <tr>
              <th style={{ position: 'sticky', left: 0, background: colors.panel, zIndex: 2, textAlign: 'left', fontSize: 11, color: colors.muted, minWidth: 150 }}>Name</th>
              {dates.map((d, i) => (
                <th key={d} style={{ fontSize: 10, color: colors.muted, fontWeight: 400, minWidth: CELL, textAlign: 'center' }} title={shortDateISO(d)}>
                  <div>{i % 7 === 0 ? day2ISO(d) : ''}</div>
                  <div style={{ fontFamily: "'IBM Plex Mono', monospace" }}>{d.slice(8, 10)}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.cells.map((row, ri) => {
              const e = matrix.capped[ri];
              const showTeam = groupByTeam && e.team !== lastTeam;
              lastTeam = e.team;
              return (
                <React.Fragment key={e.id}>
                  {showTeam && (
                    <tr><td colSpan={dates.length + 1} style={{ fontSize: 11, fontWeight: 600, color: colors.muted, paddingTop: 6 }}>{e.team}</td></tr>
                  )}
                  <tr>
                    <td style={{ position: 'sticky', left: 0, background: colors.panel, zIndex: 1, fontSize: 12, whiteSpace: 'nowrap', maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis' }} title={e.name}>{e.name}</td>
                    {row.map(({ rec, status }, di) => {
                      const nonWorking = status === 'weekend' || status === 'holiday';
                      const label = `${e.name}, ${dates[di]}, ${statusLabel(status, leaveLoaded)}`;
                      const tip = `${label}${rec.checkIn ? `, in ${rec.checkIn}` : ''}${rec.checkOut ? `, out ${rec.checkOut}` : ''}${rec.hours ? `, ${rec.hours}h` : ''}`;
                      return (
                        <td key={dates[di]} data-emp={e.id} data-date={dates[di]}
                          title={tip} aria-label={label}
                          style={{
                            width: CELL, height: CELL, borderRadius: 3, cursor: 'pointer',
                            background: nonWorking
                              ? `repeating-linear-gradient(45deg, ${FILL[status]} 0 3px, #efefea 3px 6px)`
                              : FILL[status] || 'transparent',
                            border: status === 'in_progress' ? `1.5px dashed ${colors.good}`
                              : status === 'pending' ? `1px dotted ${colors.line}` : 'none',
                            boxSizing: 'border-box',
                          }} />
                      );
                    })}
                  </tr>
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {matrix.truncated > 0 && (
        <div style={{ fontSize: 12, color: colors.muted, marginTop: 8 }}>
          Showing 150 of {employees.length}. Narrow filters to see everyone.
        </div>
      )}
    </div>
  );
}

function Legend({ leaveLoaded }) {
  const items = [
    ['Present', FILL.present],
    ['Missing check-out', FILL.missing_checkout],
    ...(leaveLoaded ? [['On leave', FILL.leave]] : []),
    [statusLabel('no_record', leaveLoaded), FILL.no_record],
    ['In progress', FILL.in_progress],
    ['Non-working day', FILL.weekend, true],
  ];
  return (
    <div style={{ display: 'flex', gap: 14, fontSize: 12, color: colors.muted, marginBottom: 8, flexWrap: 'wrap' }}>
      {items.map(([label, fill, hatch]) => (
        <span key={label}>
          <span style={{
            display: 'inline-block', width: 12, height: 12, borderRadius: 3, marginRight: 5, verticalAlign: -1,
            background: hatch ? `repeating-linear-gradient(45deg, ${fill} 0 2px, #efefea 2px 4px)` : fill,
          }} />
          {label}
        </span>
      ))}
    </div>
  );
}
