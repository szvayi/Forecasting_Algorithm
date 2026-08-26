import os
import sys
import argparse
from sqlalchemy import create_engine, text

def main():
    parser = argparse.ArgumentParser(description="Apply DB schema changes (Views)")
    parser.add_argument("--db-url", type=str, default=os.getenv("SALES_FORECAST_DB_URL"), help="Database URL")
    args = parser.parse_args()

    db_url = args.db_url
    if not db_url:
        print("❌ Error: No DB URL provided. Set SALES_FORECAST_DB_URL env var or use --db-url.")
        sys.exit(1)

    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            # Read SQL file
            sql_file = os.path.join(os.path.dirname(__file__), 'sql', 'create_view_sku_accuracy.sql')
            if not os.path.exists(sql_file):
                 print(f"❌ Error: SQL file not found: {sql_file}")
                 sys.exit(1)
            
            with open(sql_file, 'r', encoding='utf-8') as f:
                sql_content = f.read()
            
            # Since create_engine might not support running multiple statements directly in some drivers easily without splitting,
            # but usually execute(text()) handles it for simple scripts.
            # However, `pg_typeof` requires specific postgres context.
            
            # Let's try to execute it.
            # We need to handle the potential issue with `pg_typeof` if the column doesn't exist yet (but it should exist based on previous steps).
            # The SQL script uses `pg_typeof(sku_accuracy_json)` which assumes the column exists.
            
            print(f"Applying SQL from {sql_file}...")
            # We might need to split by ';' if it contains multiple statements, but here it's mainly one CREATE VIEW + COMMENT.
            # sqlalchemy `execute` might not support multiple statements in one go depending on driver.
            # Let's split manually to be safe.
            statements = [s.strip() for s in sql_content.split(';') if s.strip()]
            
            with conn.begin():
                for stmt in statements:
                    # Replace `pg_typeof(sku_accuracy_json)` with a safer check?
                    # Actually, we can check column type from information_schema first in python, but let's trust the SQL for now.
                    # Wait, `pg_typeof` takes an expression, so `sku_accuracy_json` must be a valid column reference.
                    # If the column `sku_accuracy_json` is not in the table, this will fail.
                    # We should probably check if column exists first or just let it fail.
                    conn.execute(text(stmt))
            
            print("✅ Successfully applied database view: finedatalink.v_spu_sku_accuracy_detail")
            
    except Exception as e:
        print(f"❌ Failed to apply DB changes: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
