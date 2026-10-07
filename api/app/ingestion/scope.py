"""Team-scope import: marks which COSEC users are in scope and their team.

The CSV is the full list each time (regenerated from data.json, which is the
current engineering roster until Zoho provides teams). When Zoho lands with
real teams+shifts, this text ``team`` column becomes the join key to
``teams.name`` and the shift FK you described — no ingestion change needed.
"""

import csv

from sqlalchemy import text


def import_scope(engine, csv_path: str, apply: bool) -> None:
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = [h.strip() if h else "" for h in (reader.fieldnames or [])]
        lowered = [h.lower() for h in headers]
        for required in ("user_id", "team"):
            if required not in lowered:
                print(f"missing required header: {required}")
                raise SystemExit(2)
        user_col = headers[lowered.index("user_id")]
        team_col = headers[lowered.index("team")]

        listed: list[tuple[str, str | None]] = []
        for raw in reader:
            uid = (raw.get(user_col) or "").strip()
            if not uid:
                continue
            team = (raw.get(team_col) or "").strip() or None
            listed.append((uid, team))

    with engine.connect() as conn:
        existing = {
            r[0] for r in conn.execute(text("SELECT user_id FROM cosec_users")).all()
        }

    matched = [(u, t) for u, t in listed if u in existing]
    unmatched = [u for u, _ in listed if u not in existing]
    print(f"listed={len(listed)} matched={len(matched)} unmatched={len(unmatched)}")
    for uid in unmatched:
        print(uid)

    if not apply:
        return

    with engine.begin() as conn:
        conn.execute(text("UPDATE cosec_users SET in_scope = false, team = NULL"))
        for uid, team in matched:
            conn.execute(
                text("UPDATE cosec_users SET in_scope = true, team = :team WHERE user_id = :user_id"),
                {"team": team, "user_id": uid},
            )
