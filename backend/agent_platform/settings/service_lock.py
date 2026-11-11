"""Local single-service guard, so a second launch cannot recover a live owner's windows."""
from contextlib import contextmanager
from pathlib import Path
import os


@contextmanager
def database_lock(database):
    """Identity comes from the database, never from an operator's state directory."""
    if str(database).startswith(("postgresql://", "postgres://")):
        import psycopg
        with psycopg.connect(database, autocommit=True) as connection:
            acquired = connection.execute("SELECT pg_try_advisory_lock(783206417)").fetchone()[0]
            if not acquired:
                raise RuntimeError("This database already has a running platform service")
            try:
                yield
            finally:
                connection.execute("SELECT pg_advisory_unlock(783206417)")
    else:
        path = Path(os.path.normcase(str(Path(database).resolve())))
        with service_lock(path.with_name(path.name + ".service.lock")):
            yield


@contextmanager
def service_lock(path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    stream = target.open("a+b")
    acquired = False
    try:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError as exc:
            raise RuntimeError("This database already has a running platform service") from exc
        yield
    finally:
        if acquired:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()
