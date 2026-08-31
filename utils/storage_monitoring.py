"""Инциденты источников и расчёт статистики надёжности."""

from datetime import datetime, timedelta


def _storage_datetime(value):
    try:
        parsed = datetime.fromisoformat(str(value or ""))
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        return None


def _non_negative_int(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _incident_from_row(row, now=None):
    item = dict(row)
    moment = now or datetime.now()
    started = _storage_datetime(item.get("started_at"))
    finished = _storage_datetime(item.get("resolved_at")) or moment
    seconds = max(0, int((finished - started).total_seconds())) if started else 0
    item["is_active"] = not bool(item.get("resolved_at"))
    item["duration_seconds"] = seconds
    return item


class MonitoringStorage:
    def __init__(self, initialize_database, connection_factory, lock):
        self._initialize_database = initialize_database
        self._connection_factory = connection_factory
        self._lock = lock

    def sync_source_incidents(self, statuses, now=None):
        """Открывает и закрывает инциденты по результатам реальных проверок."""
        moment = now or datetime.now()
        checked_at = moment.isoformat(timespec="seconds")
        changes = {"opened": 0, "updated": 0, "resolved": 0}
        self._initialize_database()

        with self._lock, self._connection_factory() as connection:
            for raw_item in statuses:
                if not isinstance(raw_item, dict):
                    continue
                source = " ".join(str(raw_item.get("source", "")).split())
                if not source:
                    continue
                status = str(raw_item.get("status", "")).strip().casefold()
                active_rows = connection.execute(
                    """
                    SELECT * FROM source_incidents
                    WHERE source = ? AND resolved_at = ''
                    ORDER BY id
                    """,
                    (source,),
                ).fetchall()

                active_code = status if status in {"error", "empty"} else ""
                incident_key = f"{source}:{active_code}" if active_code else ""
                current = next(
                    (
                        row
                        for row in active_rows
                        if row["incident_key"] == incident_key
                    ),
                    None,
                )

                for row in active_rows:
                    if current is not None and row["id"] == current["id"]:
                        continue
                    resolution = (
                        "Источник отключён"
                        if status == "disabled"
                        else "Работа восстановлена"
                    )
                    connection.execute(
                        """
                        UPDATE source_incidents
                        SET resolved_at = ?, resolution = ?
                        WHERE id = ?
                        """,
                        (checked_at, resolution, row["id"]),
                    )
                    changes["resolved"] += 1

                if not active_code:
                    continue

                failure_streak = _non_negative_int(
                    raw_item.get("failure_streak")
                )
                level = "critical" if failure_streak >= 3 else "warning"
                title = (
                    f"{source}: ошибка парсинга"
                    if active_code == "error"
                    else f"{source}: пустая выдача"
                )
                message = str(raw_item.get("error", "")).strip()
                if not message and active_code == "empty":
                    message = "Парсер вернул 0 материалов"

                if current is None:
                    connection.execute(
                        """
                        INSERT INTO source_incidents(
                            incident_key, source, code, level, title, message,
                            started_at, last_seen_at, checks_count
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                        """,
                        (
                            incident_key,
                            source,
                            active_code,
                            level,
                            title,
                            message,
                            checked_at,
                            checked_at,
                        ),
                    )
                    changes["opened"] += 1
                else:
                    connection.execute(
                        """
                        UPDATE source_incidents
                        SET level = ?, title = ?, message = ?, last_seen_at = ?,
                            checks_count = checks_count + 1
                        WHERE id = ?
                        """,
                        (
                            level,
                            title,
                            message,
                            checked_at,
                            current["id"],
                        ),
                    )
                    changes["updated"] += 1

        return changes

    def list_source_incidents(self, state="all", limit=200):
        """Возвращает последние инциденты для администраторского журнала."""
        state = str(state or "all").strip().casefold()
        if state not in {"all", "active", "resolved"}:
            raise ValueError("Неизвестный фильтр инцидентов")
        try:
            limit = min(500, max(1, int(limit)))
        except (TypeError, ValueError):
            limit = 200
        where = {
            "all": "",
            "active": "WHERE resolved_at = ''",
            "resolved": "WHERE resolved_at != ''",
        }[state]
        self._initialize_database()
        with self._connection_factory() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM source_incidents
                {where}
                ORDER BY CASE WHEN resolved_at = '' THEN 0 ELSE 1 END,
                         started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_incident_from_row(row) for row in rows]

    def source_incident_statistics(self, now=None):
        """Считает активные, критические и недавно закрытые инциденты."""
        moment = now or datetime.now()
        since = (moment - timedelta(hours=24)).isoformat(timespec="seconds")
        self._initialize_database()
        with self._connection_factory() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN resolved_at = '' THEN 1 ELSE 0 END) AS active,
                    SUM(CASE WHEN resolved_at = '' AND level = 'critical'
                             THEN 1 ELSE 0 END) AS critical,
                    SUM(CASE WHEN resolved_at >= ? THEN 1 ELSE 0 END) AS resolved_24h
                FROM source_incidents
                """,
                (since,),
            ).fetchone()
        return {
            "total": int(row["total"] or 0),
            "active": int(row["active"] or 0),
            "critical": int(row["critical"] or 0),
            "resolved_24h": int(row["resolved_24h"] or 0),
        }

    def source_reliability_statistics(self, days=7, now=None, sources=None):
        """Считает доступность источников по времени записанных инцидентов."""
        try:
            days = min(365, max(1, int(days)))
        except (TypeError, ValueError):
            days = 7
        moment = now or datetime.now()
        period_start = moment - timedelta(days=days)
        period_seconds = max(1, int((moment - period_start).total_seconds()))
        start_text = period_start.isoformat(timespec="seconds")
        end_text = moment.isoformat(timespec="seconds")
        self._initialize_database()
        with self._connection_factory() as connection:
            rows = connection.execute(
                """
                SELECT * FROM source_incidents
                WHERE started_at < ?
                  AND (resolved_at = '' OR resolved_at > ?)
                ORDER BY source COLLATE NOCASE, started_at
                """,
                (end_text, start_text),
            ).fetchall()

        by_source = {}
        for row in rows:
            by_source.setdefault(row["source"], []).append(dict(row))
        names = {
            " ".join(str(source or "").split())
            for source in (sources or ())
            if " ".join(str(source or "").split())
        }
        names.update(by_source)

        result = []
        for source in names:
            incidents = by_source.get(source, [])
            intervals = []
            critical_count = 0
            active_count = 0
            checks_count = 0
            for incident in incidents:
                started = _storage_datetime(incident.get("started_at"))
                resolved = _storage_datetime(incident.get("resolved_at"))
                if started is None:
                    continue
                interval_start = max(period_start, started)
                interval_end = min(moment, resolved or moment)
                if interval_end <= interval_start:
                    continue
                intervals.append((interval_start, interval_end))
                critical_count += incident.get("level") == "critical"
                active_count += not bool(incident.get("resolved_at"))
                checks_count += _non_negative_int(incident.get("checks_count"))

            merged = []
            for interval_start, interval_end in sorted(intervals):
                if not merged or interval_start > merged[-1][1]:
                    merged.append([interval_start, interval_end])
                elif interval_end > merged[-1][1]:
                    merged[-1][1] = interval_end
            downtime = sum(
                max(0, int((interval_end - interval_start).total_seconds()))
                for interval_start, interval_end in merged
            )
            uptime = max(
                0.0,
                100.0 * (period_seconds - downtime) / period_seconds,
            )
            result.append({
                "source": source,
                "uptime_percent": round(uptime, 3),
                "downtime_seconds": downtime,
                "incident_count": len(intervals),
                "critical_count": critical_count,
                "active_count": active_count,
                "checks_count": checks_count,
                "average_incident_seconds": (
                    int(downtime / len(intervals)) if intervals else 0
                ),
            })

        return sorted(
            result,
            key=lambda item: (
                item["uptime_percent"],
                -item["downtime_seconds"],
                item["source"].casefold(),
            ),
        )
