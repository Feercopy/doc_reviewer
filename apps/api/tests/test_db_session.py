from app.db.session import connect_args_for_url


def test_psycopg_postgres_disables_prepared_statements():
    assert connect_args_for_url("postgresql+psycopg://gate:gate@postgres:5432/gate") == {
        "prepare_threshold": None,
    }


def test_sqlite_keeps_thread_check_disabled_for_test_clients():
    assert connect_args_for_url("sqlite+pysqlite:///:memory:") == {"check_same_thread": False}


def test_other_database_urls_do_not_get_driver_specific_args():
    assert connect_args_for_url("postgresql://gate:gate@postgres:5432/gate") == {}
