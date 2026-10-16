// Single source of truth for day-status colours: heatmap cells, legends,
// breakdown bars and badges all read from here so they can never drift.
import { colors } from './theme.js';

export const STATUS_COLORS = {
  present: colors.good,
  missing_checkout: '#c58a1b',
  present_zoho_only: '#9ab87a',
  leave: '#3b6ea5',
  leave_conflict: '#8a4b9e',
  half_leave: '#7aa5c9',
  on_duty: '#2e7d6f',
  no_record: colors.alert,
  absent: colors.alert,
  absent_unverified: '#d8b4a0',
  unverified: '#d8cf9e',
  not_employed: '#e8e8e4',
  in_progress: `${colors.good}59`,
  pending: 'transparent',
  weekend: '#d9d9d4',
  worked_weekend: '#b9c4b1',
  holiday: '#d9d9d4',
  worked_holiday: '#b09ac0',
};

// Statuses shown in the dashboard legend.
export const LEGACY_LEGEND = ['present', 'missing_checkout', 'leave', 'no_record', 'in_progress'];
export const OVERLAY_LEGEND = [
  'present', 'present_zoho_only', 'missing_checkout', 'leave', 'leave_conflict',
  'half_leave', 'on_duty', 'absent', 'absent_unverified', 'unverified',
  'not_employed', 'worked_holiday', 'worked_weekend',
];
