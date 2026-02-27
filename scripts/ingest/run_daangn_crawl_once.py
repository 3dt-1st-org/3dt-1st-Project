import importlib.util
import os
from pathlib import Path


def _load_function_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "functions"
        / "daangn_weekly_crawler"
        / "function_app.py"
    )
    spec = importlib.util.spec_from_file_location("daangn_function_app", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load function_app module")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    db_dsn = os.getenv("DB_DSN")
    if not db_dsn:
        raise RuntimeError("DB_DSN environment variable is required")

    app_module = _load_function_module()

    with app_module.psycopg.connect(db_dsn) as conn:
        run_id = app_module._insert_run_start(conn)
        try:
            post_count, comment_count = app_module._crawl_once(conn)
            app_module._finish_run(
                conn=conn,
                run_id=run_id,
                status="success",
                post_count=post_count,
                comment_count=comment_count,
                error_message=None,
            )
        except Exception as exc:
            conn.rollback()
            app_module._finish_run(
                conn=conn,
                run_id=run_id,
                status="failed",
                post_count=0,
                comment_count=0,
                error_message=str(exc)[:1000],
            )
            raise

    print(f"run_id={run_id}")
    print(f"post_count={post_count}")
    print(f"comment_count={comment_count}")


if __name__ == "__main__":
    main()
