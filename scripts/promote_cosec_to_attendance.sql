-- Promote COSEC staging rows into the dashboard tables.
--
-- Repeatable: every INSERT uses ON CONFLICT DO NOTHING, so re-running only
-- fills gaps. Rows already in attendance_records (e.g. the 4,356 migrated
-- file rows) are NEVER overwritten — file semantics win on overlap.
--
-- Mapping (each rule validated against the Aug/Sep overlap before writing):
--   present   = punch1 OR punch2 present (100% agreement incl. 8 file-present
--               out-punch-only anomaly rows; punch1-only rule agreed 99.8%)
--   late/early= *_min > 0 (100% agreement on 4,290 overlap rows)
--   times     = punch AT TIME ZONE 'Africa/Nairobi' (matches file to the minute)
--   hours     = work_time_min / 60 (matches file, e.g. 320 -> 5.33)
--   shift     = left NULL: device working_shift codes ('09','27','AL',...)
--               don't map to shift_templates; nothing honest to put there.
-- Only in_scope users (engineering roster) are promoted.
--
-- Run: psql $DATABASE_URL -f scripts/promote_cosec_to_attendance.sql

DO $$
DECLARE
    inserted_attendance int;
BEGIN
    -- 1. Teams referenced by in-scope users (usually all exist already).
    INSERT INTO teams (name)
    SELECT DISTINCT trim(u.team)
    FROM cosec_users u
    WHERE u.in_scope AND u.team IS NOT NULL AND trim(u.team) <> ''
    ON CONFLICT (name) DO NOTHING;

    -- 2. Employees for in-scope device users not yet tracked.
    -- NB: never renames existing employees; the file roster stays canonical.
    INSERT INTO employees (id, name)
    SELECT u.user_id, u.user_name
    FROM cosec_users u
    WHERE u.in_scope
    ON CONFLICT (id) DO NOTHING;

    -- 3. Attendance rows: only (employee, date) pairs not already present.
    INSERT INTO attendance_records
        (employee_id, date, check_in, check_out, work_hours, overtime_hours,
         late_in, early_out, present, team_id, source, raw_ref)
    SELECT
        c.user_id,
        c.process_date,
        (c.punch1 AT TIME ZONE 'Africa/Nairobi')::time,
        (c.punch2 AT TIME ZONE 'Africa/Nairobi')::time,
        COALESCE(c.work_time_min, 0) / 60.0,
        COALESCE(c.overtime_min, 0) / 60.0,
        COALESCE(c.late_in_min, 0) > 0,
        COALESCE(c.early_out_min, 0) > 0,
        (c.punch1 IS NOT NULL OR c.punch2 IS NOT NULL),
        t.id,
        'biometric',
        'cosec_daily:' || c.user_id || ':' || c.process_date
    FROM cosec_attendance_daily c
    JOIN cosec_users u ON u.user_id = c.user_id
    LEFT JOIN teams t ON t.name = trim(u.team)
    WHERE u.in_scope
    ON CONFLICT (employee_id, date) DO NOTHING;
    GET DIAGNOSTICS inserted_attendance = ROW_COUNT;

    -- 4. Keep employees.current_team_id in sync (same statement as POST /attendance/bulk).
    UPDATE employees e SET current_team_id = latest.team_id
    FROM (
        SELECT DISTINCT ON (employee_id) employee_id, team_id
        FROM attendance_records
        ORDER BY employee_id, date DESC
    ) AS latest
    WHERE e.id = latest.employee_id AND latest.team_id IS NOT NULL;

    -- 5. Audit trail for the Sync-check tab (actual inserted count, not a constant).
    INSERT INTO sync_log (source, records_processed, records_failed, status, notes)
    VALUES ('cosec_promotion', inserted_attendance, 0, 'complete',
            'promoted in_scope staging rows missing from attendance_records; existing rows untouched');

    RAISE NOTICE 'promoted % new attendance rows', inserted_attendance;
END
$$;
