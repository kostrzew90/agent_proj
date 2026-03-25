#!/usr/bin/env python3
"""
Database operations for OSINT Tracker
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor, Json

logger = logging.getLogger(__name__)


class Database:
    """PostgreSQL database handler for OSINT checks"""

    def __init__(self):
        self.config = {
            'host': os.getenv('OSINT_DB_HOST', 'postgres'),
            'port': int(os.getenv('OSINT_DB_PORT', '5432')),
            'user': os.getenv('OSINT_DB_USER', 'n8n'),
            'password': os.getenv('OSINT_DB_PASSWORD', 'n8npass'),
            'dbname': os.getenv('OSINT_DB_NAME', 'n8n')
        }

    def get_connection(self):
        """Get database connection"""
        return psycopg2.connect(**self.config)

    def ensure_tables(self):
        """Create tables if they don't exist"""
        conn = self.get_connection()
        cur = conn.cursor()

        try:
            # Main checks table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS osint_checks (
                    id SERIAL PRIMARY KEY,
                    input_value VARCHAR(255) NOT NULL,
                    input_type VARCHAR(20) NOT NULL,
                    normalized_value VARCHAR(255),
                    check_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    duration_ms INTEGER,
                    sources_checked INTEGER,
                    sources_success INTEGER,
                    risk_category VARCHAR(20),
                    risk_factors TEXT[],
                    summary_json JSONB
                )
            """)

            # Sources detail table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS osint_sources (
                    id SERIAL PRIMARY KEY,
                    check_id INTEGER REFERENCES osint_checks(id) ON DELETE CASCADE,
                    source_name VARCHAR(100) NOT NULL,
                    source_category VARCHAR(50),
                    status VARCHAR(20) NOT NULL,
                    found BOOLEAN,
                    raw_response JSONB,
                    extracted_data JSONB,
                    response_time_ms INTEGER,
                    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    error_message TEXT
                )
            """)

            # Indexes
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_osint_checks_input
                ON osint_checks(input_value)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_osint_checks_type
                ON osint_checks(input_type)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_osint_checks_timestamp
                ON osint_checks(check_timestamp)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_osint_sources_check
                ON osint_sources(check_id)
            """)

            conn.commit()
            logger.info("Database tables ensured")

        except Exception as e:
            logger.error(f"Error creating tables: {e}")
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    def save_check(self, result) -> int:
        """
        Save check result to database
        Returns: check_id
        """
        conn = self.get_connection()
        cur = conn.cursor()

        try:
            # Insert main check record
            cur.execute("""
                INSERT INTO osint_checks (
                    input_value, input_type, normalized_value,
                    duration_ms, sources_checked, sources_success,
                    risk_category, risk_factors, summary_json
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING id
            """, (
                result.input_value,
                result.input_type,
                result.normalized_value,
                result.duration_ms,
                result.sources_checked,
                result.sources_found,
                result.risk_category,
                result.risk_factors,
                Json(result.to_dict())
            ))

            check_id = cur.fetchone()[0]

            # Insert source results
            for source in result.sources:
                cur.execute("""
                    INSERT INTO osint_sources (
                        check_id, source_name, source_category,
                        status, found, raw_response, extracted_data,
                        response_time_ms, error_message
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                """, (
                    check_id,
                    source.source_name,
                    source.source_category,
                    source.status,
                    source.found,
                    Json(source.raw_response),
                    Json(source.extracted_data),
                    source.response_time_ms,
                    source.error_message
                ))

            conn.commit()
            logger.info(f"Saved check {check_id} to database")
            return check_id

        except Exception as e:
            logger.error(f"Error saving check: {e}")
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    def get_history(self, input_value: str, limit: int = 10) -> list[dict]:
        """
        Get check history for a given input
        """
        conn = self.get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cur.execute("""
                SELECT
                    id, input_value, input_type, normalized_value,
                    check_timestamp, duration_ms, sources_checked,
                    sources_success, risk_category, risk_factors
                FROM osint_checks
                WHERE input_value = %s OR normalized_value = %s
                ORDER BY check_timestamp DESC
                LIMIT %s
            """, (input_value, input_value, limit))

            return [dict(row) for row in cur.fetchall()]

        finally:
            cur.close()
            conn.close()

    def get_check_details(self, check_id: int) -> Optional[dict]:
        """
        Get full check details including sources
        """
        conn = self.get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # Get main check
            cur.execute("""
                SELECT * FROM osint_checks WHERE id = %s
            """, (check_id,))

            check = cur.fetchone()
            if not check:
                return None

            # Get sources
            cur.execute("""
                SELECT * FROM osint_sources WHERE check_id = %s
            """, (check_id,))

            sources = cur.fetchall()

            result = dict(check)
            result['sources'] = [dict(s) for s in sources]

            return result

        finally:
            cur.close()
            conn.close()

    def get_all_checks(self, limit: int = 50) -> list[dict]:
        """
        Get all checks ordered by timestamp
        """
        conn = self.get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cur.execute("""
                SELECT
                    id, input_value, input_type, normalized_value,
                    check_timestamp, duration_ms, sources_checked,
                    sources_success, risk_category
                FROM osint_checks
                ORDER BY check_timestamp DESC
                LIMIT %s
            """, (limit,))

            return [dict(row) for row in cur.fetchall()]

        finally:
            cur.close()
            conn.close()

    def check_exists(self, input_value: str, max_age_days: int = 7) -> Optional[dict]:
        """
        Check if recent check exists for this input
        Returns the most recent check if within max_age_days
        """
        conn = self.get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        try:
            cur.execute("""
                SELECT * FROM osint_checks
                WHERE (input_value = %s OR normalized_value = %s)
                AND check_timestamp > NOW() - INTERVAL '%s days'
                ORDER BY check_timestamp DESC
                LIMIT 1
            """, (input_value, input_value, max_age_days))

            row = cur.fetchone()
            return dict(row) if row else None

        finally:
            cur.close()
            conn.close()
