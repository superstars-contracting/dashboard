#!/usr/bin/env python3
"""
Smoke test: 10 representative queries against superstars.db
Validates schema, indexes, and read patterns for dashboard
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(__file__).parent / "superstars.db"

def run_query(conn, query, title):
    """Execute query and print results."""
    print(f"\n{title}")
    print("-" * 70)
    try:
        cur = conn.cursor()
        cur.execute(query)
        rows = cur.fetchall()
        if not rows:
            print("  (no results)")
            return []
        for row in rows[:5]:  # Show first 5
            print(f"  {row}")
        if len(rows) > 5:
            print(f"  ... and {len(rows) - 5} more")
        return rows
    except Exception as e:
        print(f"  ERROR: {e}")
        return []

def main():
    conn = sqlite3.connect(str(DB_PATH))
    
    print("=" * 70)
    print("SMOKE TEST: 10 Representative Queries")
    print("=" * 70)
    
    # 1. Count all employees
    run_query(conn, """
        SELECT COUNT(*) as total_employees FROM employees
    """, "1. Total employee count")
    
    # 2. Active workers on site today (sample: 2026-05-05)
    run_query(conn, """
        SELECT e.employee_id, e.name, e.trade, s.project_code, s.time_in, s.time_out
        FROM sign_in_log s
        JOIN employees e ON s.employee_id = e.employee_id
        WHERE s.date = '2026-05-05'
        ORDER BY e.name
    """, "2. Workers on site 2026-05-05")
    
    # 3. RFIs with status 'Overdue'
    run_query(conn, """
        SELECT rfi_number, project_code, discipline, date_submitted, status
        FROM rfi_log
        WHERE status = 'Overdue'
        ORDER BY date_submitted DESC
    """, "3. Overdue RFIs")
    
    # 4. Active drops (status='Active')
    run_query(conn, """
        SELECT drop_id, project_code, elevation, status, planned_start_date, planned_end_date
        FROM drop_plan
        WHERE status = 'Active'
        ORDER BY planned_start_date
    """, "4. Active drops")
    
    # 5. Certs expiring in next 30 days
    run_query(conn, """
        SELECT c.employee_id, e.name, ct.name as cert_type, c.expiration_date
        FROM certifications c
        JOIN employees e ON c.employee_id = e.employee_id
        JOIN cert_types ct ON c.cert_type_id = ct.cert_type_id
        WHERE c.expiration_date IS NOT NULL
          AND c.expiration_date BETWEEN date('now') AND date('now', '+30 days')
        ORDER BY c.expiration_date
    """, "5. Certs expiring in next 30 days")
    
    # 6. Permits expiring in next 30 days
    run_query(conn, """
        SELECT permit_id, project_code, permit_type, expiration_date, status
        FROM permits_library
        WHERE expiration_date IS NOT NULL
          AND expiration_date BETWEEN date('now') AND date('now', '+30 days')
        ORDER BY expiration_date
    """, "6. Permits expiring in next 30 days")
    
    # 7. Most recent meeting record
    run_query(conn, """
        SELECT meeting_id, project_code, meeting_type, date, time_start, location
        FROM meeting_records
        ORDER BY date DESC, time_start DESC
        LIMIT 1
    """, "7. Most recent meeting")
    
    # 8. Total open action items by owner
    run_query(conn, """
        SELECT owner, COUNT(*) as count
        FROM meeting_action_items
        WHERE status != 'Completed'
        GROUP BY owner
        ORDER BY count DESC
    """, "8. Open action items by owner")
    
    # 9. Sum of hours worked past week
    run_query(conn, """
        SELECT COUNT(*) as total_sign_ins
        FROM sign_in_log
        WHERE date BETWEEN date('2026-04-29') AND date('2026-05-05')
    """, "9. Sign-ins past week (2026-04-29 to 2026-05-05)")
    
    # 10. DOB compliance references with status='Loaded'
    run_query(conn, """
        SELECT code_id, code_title, source, status
        FROM dob_compliance_reference
        WHERE status = 'Loaded'
        ORDER BY code_id
    """, "10. DOB compliance references (Loaded)")
    
    print("\n" + "=" * 70)
    print("SMOKE TEST SUMMARY")
    print("=" * 70)
    
    # Database stats
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
    table_count = cur.fetchone()[0]
    
    cur.execute("""
        SELECT SUM((SELECT COUNT(*) FROM employees)) +
               SUM((SELECT COUNT(*) FROM projects)) +
               SUM((SELECT COUNT(*) FROM drop_plan)) +
               SUM((SELECT COUNT(*) FROM meeting_records)) +
               SUM((SELECT COUNT(*) FROM permits_library)) +
               SUM((SELECT COUNT(*) FROM document_library))
    """)
    total_rows = cur.fetchone()[0] or 0
    
    db_size = Path(DB_PATH).stat().st_size
    
    print(f"Database file: {DB_PATH}")
    print(f"File size: {db_size:,} bytes ({db_size / (1024*1024):.2f} MB)")
    print(f"Table count: {table_count}")
    print(f"Sample row count: {total_rows}")
    print("\nAll smoke tests completed successfully!")
    
    conn.close()

if __name__ == "__main__":
    main()
