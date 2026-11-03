from contextlib import contextmanager
from typing import Generator

import mysql.connector
from mysql.connector.connection import MySQLConnection


class Database:
    def __init__(self, config):
        self.config = config

    def _build_connection_config(self) -> dict:
        return {
            "host": self.config.MYSQL_HOST,
            "port": int(self.config.MYSQL_PORT),
            "user": self.config.MYSQL_USER,
            "password": self.config.MYSQL_PASSWORD,
            "database": self.config.MYSQL_DATABASE,
            "charset": "utf8mb4",
            "use_unicode": True,
            "autocommit": False,
            "connection_timeout": 10,
        }

    @contextmanager
    def connection(self) -> Generator[MySQLConnection, None, None]:
        conn = mysql.connector.connect(**self._build_connection_config())
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()