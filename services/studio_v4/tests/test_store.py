import sqlite3

import pytest

from studio import store


def test_enqueue_state_and_job_are_atomic():
    store.init()
    pid = store.create_project('atomic', 'test-hash')
    with store.conn() as db:
        db.execute("CREATE TRIGGER fail_enqueue BEFORE INSERT ON jobs BEGIN SELECT RAISE(ABORT, 'test crash'); END")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            store.enqueue(pid, 'mesh', 'uploaded', 'mesh_building')
        assert store.get_project(pid)['state'] == 'uploaded'
        assert not store.jobs(pid)
    finally:
        with store.conn() as db:
            db.execute('DROP TRIGGER fail_enqueue')
