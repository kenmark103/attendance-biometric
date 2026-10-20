// Charts on the existing recharts setup (spec: keep whatever is used, no new deps).
import React from 'react';
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import { colors } from '../theme.js';

const tipStyle = { border: `1px solid ${colors.line}`, borderRadius: 4, fontSize: 12.5 };

function RateDot({ cx, cy, payload }) {
  if (payload.rate === null || payload.rate === undefined) return null;
  const provisional = payload.state === 'provisional';
  return <circle cx={cx} cy={cy} r={3} fill={provisional ? '#fff' : colors.good} stroke={colors.good} strokeWidth={provisional ? 2 : 0} />;
}

function RateTip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  return (
    <div style={{ ...tipStyle, background: '#fff', padding: '8px 10px' }}>
      <div style={{ fontWeight: 600, marginBottom: 2 }}>{p.full || p.label}</div>
      <div>{p.rate === null || p.rate === undefined ? 'No data' : `${p.rate}% (${p.present}/${p.expected} present)`}</div>
      {p.state === 'provisional' && <div style={{ color: colors.muted }}>Provisional: leave data not loaded</div>}
      {p.state === 'no_data' && <div style={{ color: colors.muted }}>No data — no biometric records</div>}
    </div>
  );
}

// Single-series attendance line. Null rates are gaps (connectNulls false),
// so weekends/holidays/no-data days break the line instead of plotting 0%.
// Provisional days (leave data not yet loaded) get hollow markers and are
// overlaid with a dashed segment.
export function RateLine({ data, height = 200 }) {
  const hasProvisional = data.some((d) => d.state === 'provisional');
  return (
    <>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 4, right: 16, left: -12, bottom: 4 }}>
          <CartesianGrid strokeDasharray="2 4" stroke={colors.line} vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 12, fill: colors.muted }} axisLine={{ stroke: colors.line }} tickLine={false} interval="preserveStartEnd" />
          <YAxis tick={{ fontSize: 12, fill: colors.muted }} axisLine={false} tickLine={false} domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} label={{ value: '% of expected', angle: -90, position: 'insideLeft', fontSize: 11, fill: colors.muted }} />
          <Tooltip content={<RateTip />} />
          <Line type="monotone" dataKey="rate" name="rate" stroke={colors.good} strokeWidth={2} dot={<RateDot />} activeDot={{ r: 4 }} connectNulls={false} />
          {hasProvisional && (
            <Line type="monotone" dataKey="prov" name="prov" stroke={colors.good} strokeDasharray="4 3" strokeWidth={2} dot={{ r: 3, fill: '#fff', stroke: colors.good, strokeWidth: 2 }} connectNulls={false} legendType="none" activeDot={false} />
          )}
        </LineChart>
      </ResponsiveContainer>
      {hasProvisional && (
        <div style={{ display: 'flex', gap: 14, fontSize: 12, color: colors.muted, padding: '2px 4px 8px', flexWrap: 'wrap' }}>
          <span><span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 5, background: colors.good, marginRight: 5 }} />Actual</span>
          <span><span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 5, background: '#fff', border: `2px solid ${colors.good}`, marginRight: 5 }} />Provisional (leave data not loaded)</span>
        </div>
      )}
    </>
  );
}

// Stacked daily breakdown. Weekend/holiday columns are all-zero => empty.
export function BreakdownBars({ data, showLeave, showInProgress, showOverlay, height = 200 }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 4, right: 8, left: -12, bottom: 4 }}>
        <CartesianGrid strokeDasharray="2 4" stroke={colors.line} vertical={false} />
        <XAxis dataKey="label" tick={{ fontSize: 12, fill: colors.muted }} axisLine={{ stroke: colors.line }} tickLine={false} interval="preserveStartEnd" />
        <YAxis tick={{ fontSize: 12, fill: colors.muted }} axisLine={false} tickLine={false} allowDecimals={false} />
        <Tooltip contentStyle={tipStyle} labelFormatter={(label, payload) => payload?.[0]?.payload?.full || label} />
        <Bar dataKey="present" name="Present" stackId="a" fill={colors.good} />
        {showLeave && <Bar dataKey="leave" name="On leave" stackId="a" fill="#3b6ea5" />}
        {!showOverlay && <Bar dataKey="noRecord" name="No record" stackId="a" fill={colors.alert} />}
        {showOverlay && <Bar dataKey="absent" name="Absent" stackId="a" fill={colors.alert} />}
        {showOverlay && <Bar dataKey="unverified" name="Unverified" stackId="a" fill="#d8b4a0" />}
        {showInProgress && <Bar dataKey="inProgress" name="In progress" stackId="a" fill={`${colors.good}59`} radius={[2, 2, 0, 0]} />}
        {!showInProgress && <Bar dataKey="noRecord" name="x" stackId="a" fill="transparent" hide />}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function ChartLegend({ items }) {
  return (
    <div style={{ display: 'flex', gap: 14, fontSize: 12, color: colors.muted, marginTop: 8, flexWrap: 'wrap' }}>
      {items.map(([label, swatch, dashed]) => (
        <span key={label}>
          <span style={{
            display: 'inline-block', width: 9, height: 9, borderRadius: 2, background: swatch,
            marginRight: 5, border: dashed ? `1.5px dashed ${colors.good}` : 'none',
          }} />
          {label}
        </span>
      ))}
    </div>
  );
}

// 60x18 inline SVG sparkline of daily rates; nulls break the path (gaps).
export function Sparkline({ values, width = 60, height = 18 }) {
  const pts = values.map((v, i) => ({ v, x: values.length === 1 ? width / 2 : (i / (values.length - 1)) * width }));
  const y = (v) => height - 2 - (v / 100) * (height - 4);
  const segs = [];
  let cur = [];
  for (const p of pts) {
    if (p.v === null || p.v === undefined) { if (cur.length) segs.push(cur); cur = []; }
    else cur.push(p);
  }
  if (cur.length) segs.push(cur);
  return (
    <svg width={width} height={height} aria-hidden="true">
      {segs.map((s, i) => s.length === 1 ? (
        <circle key={i} cx={s[0].x} cy={y(s[0].v)} r={1.6} fill={colors.good} />
      ) : (
        <polyline key={i} fill="none" stroke={colors.good} strokeWidth={1.5}
          points={s.map((p) => `${p.x.toFixed(1)},${y(p.v).toFixed(1)}`).join(' ')} />
      ))}
    </svg>
  );
}
