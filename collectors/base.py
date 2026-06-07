"""Base class for all collectors — works with SQLite (local) or Postgres (production)."""
import json
import traceback
from datetime import datetime, timezone
from typing import Optional

from db.connection import query_one, execute, commit, rollback, IS_POSTGRES

COLLECTOR_VERSION = "2.0.0"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class BaseCollector:
    source_name: str = ""

    def __init__(self):
        self.run_id: Optional[int] = None
        self.records_added = 0

    # ── DB helpers ────────────────────────────────────────────

    def _source_id(self) -> int:
        row = query_one("SELECT id FROM sources WHERE name = ?", (self.source_name,))
        if not row:
            raise ValueError(f"Source '{self.source_name}' not seeded. Run schema SQL first.")
        return row['id']

    def _site_id(self, site_name: str) -> int:
        row = query_one("SELECT id FROM sites WHERE name = ?", (site_name,))
        if not row:
            raise ValueError(f"Site '{site_name}' not found in DB.")
        return row['id']

    def _start_run(self) -> int:
        source_id = self._source_id()
        if IS_POSTGRES:
            row = query_one(
                "INSERT INTO collection_runs (source_id, started_at, status, collector_version) "
                "VALUES (?, NOW(), 'RUNNING', ?) RETURNING id",
                (source_id, COLLECTOR_VERSION)
            )
            self.run_id = row['id']
        else:
            self.run_id = execute(
                "INSERT INTO collection_runs (source_id, started_at, status, collector_version) "
                "VALUES (?, ?, 'RUNNING', ?)",
                (source_id, utcnow(), COLLECTOR_VERSION)
            )
        commit()
        return self.run_id

    def _finish_run(self, status: str = 'SUCCESS', error_msg: str = None):
        if IS_POSTGRES:
            execute(
                "UPDATE collection_runs SET completed_at=NOW(), status=?, records_added=?, error_msg=? WHERE id=?",
                (status, self.records_added, error_msg, self.run_id)
            )
        else:
            execute(
                "UPDATE collection_runs SET completed_at=?, status=?, records_added=?, error_msg=? WHERE id=?",
                (utcnow(), status, self.records_added, error_msg, self.run_id)
            )
        commit()

    def _insert_reading(self, *, site_name: str, metric: str, value: Optional[float],
                         unit: str, result_class: str, sample_date: str,
                         threshold_safe: float = None, threshold_unit: str = None,
                         source_url: str = None, lab_certified: bool = False,
                         raw_payload: dict = None, notes: str = None):
        source_id = self._source_id()
        row = query_one("SELECT veracity_tier FROM sources WHERE id=?", (source_id,))
        payload = json.dumps(raw_payload) if raw_payload else None

        if IS_POSTGRES:
            execute(
                """INSERT INTO water_readings
                   (run_id,site_id,source_id,metric,value,unit,result_class,
                    threshold_safe,threshold_unit,sample_date,collected_at,
                    source_url,lab_certified,veracity_tier,raw_payload,notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,NOW(),?,?,?,?,?)""",
                (self.run_id, self._site_id(site_name), source_id,
                 metric, value, unit, result_class,
                 threshold_safe, threshold_unit, sample_date,
                 source_url, lab_certified, row['veracity_tier'], payload, notes)
            )
        else:
            execute(
                """INSERT INTO water_readings
                   (run_id,site_id,source_id,metric,value,unit,result_class,
                    threshold_safe,threshold_unit,sample_date,collected_at,
                    source_url,lab_certified,veracity_tier,raw_payload,notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (self.run_id, self._site_id(site_name), source_id,
                 metric, value, unit, result_class,
                 threshold_safe, threshold_unit, sample_date, utcnow(),
                 source_url, 1 if lab_certified else 0, row['veracity_tier'],
                 json.dumps(raw_payload) if raw_payload else None, notes)
            )
        self.records_added += 1

    def _insert_advisory(self, *, site_name: str, advisory_type: str,
                          description: str = None, issued_date: str = None,
                          lifted_date: str = None, is_active: bool = True,
                          source_url: str = None, raw_payload: dict = None):
        source_id = self._source_id()
        row = query_one("SELECT veracity_tier FROM sources WHERE id=?", (source_id,))
        payload = json.dumps(raw_payload) if raw_payload else None

        if IS_POSTGRES:
            execute(
                """INSERT INTO advisories
                   (run_id,site_id,source_id,advisory_type,description,
                    issued_date,lifted_date,is_active,collected_at,
                    source_url,veracity_tier,raw_payload)
                   VALUES (?,?,?,?,?,?,?,?,NOW(),?,?,?)""",
                (self.run_id, self._site_id(site_name), source_id,
                 advisory_type, description, issued_date, lifted_date,
                 is_active, source_url, row['veracity_tier'], payload)
            )
        else:
            execute(
                """INSERT INTO advisories
                   (run_id,site_id,source_id,advisory_type,description,
                    issued_date,lifted_date,is_active,collected_at,
                    source_url,veracity_tier,raw_payload)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (self.run_id, self._site_id(site_name), source_id,
                 advisory_type, description, issued_date, lifted_date,
                 1 if is_active else 0, utcnow(),
                 source_url, row['veracity_tier'],
                 json.dumps(raw_payload) if raw_payload else None)
            )
        self.records_added += 1

    # ── Main entry point ──────────────────────────────────────

    def run(self) -> dict:
        self._start_run()
        try:
            self.collect()
            commit()
            self._finish_run('SUCCESS')
        except Exception as e:
            tb = traceback.format_exc()
            rollback()
            self._finish_run('FAILED', error_msg=str(e) + '\n' + tb)
            return {'source': self.source_name, 'status': 'FAILED',
                    'records': 0, 'error': str(e)}
        return {'source': self.source_name, 'status': 'SUCCESS',
                'records': self.records_added}

    def collect(self):
        raise NotImplementedError
