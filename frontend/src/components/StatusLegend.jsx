// Dashboard status legend: one chip per day status (spec §11).
import React from 'react';
import { colors } from '../theme.js';
import { STATUS_COLORS } from '../statusColors.js';
import { statusLabel } from '../metrics.js';

export default function StatusLegend({ statuses, leaveLoaded }) {
  return (
    <div style={{ display: 'flex', gap: 14, fontSize: 12, color: colors.muted, marginTop: 8, flexWrap: 'wrap' }}>
      {statuses.map((s) => (
        <span key={s}>
          <span style={{
            display: 'inline-block', width: 9, height: 9, borderRadius: 2,
            background: STATUS_COLORS[s] || 'transparent',
            border: STATUS_COLORS[s] === 'transparent' ? `1px solid ${colors.line}` : 'none',
            marginRight: 5,
          }} />
          {statusLabel(s, leaveLoaded)}
        </span>
      ))}
    </div>
  );
}
