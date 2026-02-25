import sqlite3
import threading

class Memory:
    def __init__(self, db_path="data/didier.db"):
        self.db_path = db_path
        self.conn = None
        self._lock = threading.Lock()

    def connect(self):
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """)
            self.conn.commit()

    def save_message(self, role, content):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("INSERT INTO conversations (role, content) VALUES (?, ?)", (role, content))
            self.conn.commit()

    def get_recent(self, limit=20):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT role, content, timestamp FROM conversations ORDER BY id DESC LIMIT ?", (limit,))
            return cur.fetchall()
