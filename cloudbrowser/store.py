from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(directory / "state.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.executescript("""
          PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, request_key TEXT UNIQUE, goal TEXT NOT NULL,
            status TEXT NOT NULL, messages TEXT NOT NULL DEFAULT '[]', result TEXT NOT NULL DEFAULT '',
            created REAL NOT NULL, updated REAL NOT NULL
          );
          CREATE TABLE IF NOT EXISTS approvals (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL, tool TEXT NOT NULL,
            summary TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created REAL NOT NULL
          );
          CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, kind TEXT NOT NULL,
            detail TEXT NOT NULL, created REAL NOT NULL
          );
          CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY, filename TEXT NOT NULL, path TEXT NOT NULL,
            size INTEGER NOT NULL, created REAL NOT NULL
          );
          CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY, definition TEXT NOT NULL, created REAL NOT NULL
          );
          CREATE TABLE IF NOT EXISTS workflows (
            job_id TEXT PRIMARY KEY, definition TEXT NOT NULL, created REAL NOT NULL
          );
          CREATE TABLE IF NOT EXISTS agent_tasks (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL, agent_id TEXT NOT NULL, step_id TEXT NOT NULL,
            status TEXT NOT NULL, goal TEXT NOT NULL, messages TEXT NOT NULL DEFAULT '[]',
            result TEXT NOT NULL DEFAULT '', outputs TEXT NOT NULL DEFAULT '[]',
            evidence TEXT NOT NULL DEFAULT '{}', review TEXT NOT NULL DEFAULT '{}',
            created REAL NOT NULL, updated REAL NOT NULL
          );
          CREATE INDEX IF NOT EXISTS task_job_index ON agent_tasks(job_id,step_id,created);
          CREATE TABLE IF NOT EXISTS job_outputs (
            job_id TEXT NOT NULL, artifact_id TEXT NOT NULL,
            PRIMARY KEY(job_id, artifact_id)
          );
          CREATE TABLE IF NOT EXISTS a2a_inbox (
            job_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, context_id TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS remote_tasks (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL, peer_id TEXT NOT NULL,
            request_key TEXT NOT NULL, message_id TEXT NOT NULL,
            remote_id TEXT NOT NULL DEFAULT '', response TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'submitting', created REAL NOT NULL,
            UNIQUE(job_id,request_key)
          );
          CREATE TABLE IF NOT EXISTS action_ledger (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL, tool TEXT NOT NULL,
            request_hash TEXT NOT NULL, summary TEXT NOT NULL, status TEXT NOT NULL,
            created REAL NOT NULL, updated REAL NOT NULL
          );
          CREATE INDEX IF NOT EXISTS action_job_index ON action_ledger(job_id, created);
          CREATE TABLE IF NOT EXISTS model_usage (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL, status TEXT NOT NULL,
            reserved INTEGER NOT NULL, charged INTEGER NOT NULL,
            prompt_tokens INTEGER, completion_tokens INTEGER, created REAL NOT NULL
          );
        """)
        if "project_id" not in {row[1] for row in self.db.execute("PRAGMA table_info(jobs)")}:
            self.db.execute("ALTER TABLE jobs ADD COLUMN project_id TEXT NOT NULL DEFAULT 'default'")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def _write(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self.lock, self.db:
            return self.db.execute(sql, args)

    def _rows(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(row) for row in self.db.execute(sql, args).fetchall()]

    def get(self, key: str, default: str = "") -> str:
        rows = self._rows("SELECT value FROM kv WHERE key=?", (key,))
        return rows[0]["value"] if rows else default

    def set(self, key: str, value: str) -> None:
        self._write("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, value))

    def create_job(self, goal: str, request_key: str | None = None, *, project_id: str = "default") -> dict:
        self.validate_project(project_id)
        job_id, now = uuid.uuid4().hex[:12], time.time()
        self._write(
            "INSERT OR IGNORE INTO jobs(id, request_key, goal, status, created, updated, project_id) VALUES (?,?,?,'queued',?,?,?)",
            (job_id, request_key, goal[:12000], now, now, project_id),
        )
        if request_key:
            return self._rows("SELECT * FROM jobs WHERE request_key=?", (request_key,))[0]
        return self.job(job_id)

    def job(self, job_id: str) -> dict:
        rows = self._rows("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not rows:
            raise ValueError("Job tidak ditemukan.")
        return rows[0]

    def jobs(self, project_id: str | None = None) -> list[dict]:
        columns = "id,goal,status,result,created,updated,project_id"
        if project_id is not None:
            return self._rows(f"SELECT {columns} FROM jobs WHERE project_id=? ORDER BY created DESC LIMIT 50", (project_id,))
        return self._rows(f"SELECT {columns} FROM jobs ORDER BY created DESC LIMIT 50")

    @staticmethod
    def validate_project(project_id: str) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", project_id):
            raise ValueError("Project must be a slug of 1–40 lowercase letters, digits, underscores or hyphens.")

    def set_project(self, project_id: str, brief: str | None = None) -> None:
        self.validate_project(project_id)
        if project_id.startswith("a2a-"):
            raise ValueError("The a2a- project prefix is reserved for external contexts.")
        self.set("current_project", project_id)
        if brief is not None:
            self.set("project_brief:" + project_id, brief[:8000])

    def update_job(self, job_id: str, *, status: str, messages: list | None = None, result: str | None = None) -> None:
        current = self.job(job_id)
        self._write(
            "UPDATE jobs SET status=?,messages=?,result=?,updated=? WHERE id=?",
            (status, json.dumps(messages) if messages is not None else current["messages"],
             result if result is not None else current["result"], time.time(), job_id),
        )

    def recover(self) -> None:
        # A browser click cannot be made exactly-once across a process crash: never replay it.
        self._write(
            "UPDATE jobs SET status='interrupted',result='Server restart; periksa browser lalu /resume ID.',updated=? "
            "WHERE status IN ('running','queued','awaiting_approval')", (time.time(),)
        )
        self._write("UPDATE approvals SET status='expired' WHERE status='pending'")
        self._write("UPDATE agent_tasks SET status='input_required', result='Server restart; review state before resuming.' WHERE status IN ('submitted','working')")
        self._write("UPDATE action_ledger SET status='unknown', updated=? WHERE status='applying'", (time.time(),))
        self._write("UPDATE action_ledger SET status='canceled', updated=? WHERE status IN ('pending','approved')", (time.time(),))
        self._write("UPDATE model_usage SET status='unknown' WHERE status='reserved'")

    def event(self, job_id: str | None, kind: str, detail: str) -> None:
        self._write("INSERT INTO events(job_id,kind,detail,created) VALUES (?,?,?,?)",
                    (job_id, kind, detail[:4000], time.time()))

    def events(self, job_id: str) -> list[dict]:
        return self._rows("SELECT * FROM events WHERE job_id=? ORDER BY id DESC LIMIT 100", (job_id,))

    def approval(self, job_id: str, tool: str, summary: str) -> str:
        approval_id = uuid.uuid4().hex[:12]
        self._write("INSERT INTO approvals(id,job_id,tool,summary,created) VALUES (?,?,?,?,?)",
                    (approval_id, job_id, tool, summary[:1000], time.time()))
        return approval_id

    def decide(self, approval_id: str, approved: bool) -> bool:
        return self._write("UPDATE approvals SET status=? WHERE id=? AND status='pending'",
                           ("approved" if approved else "rejected", approval_id)).rowcount == 1

    def pending_approvals(self) -> list[dict]:
        return self._rows("SELECT * FROM approvals WHERE status='pending' ORDER BY created")

    def artifact(self, artifact_id: str) -> dict:
        rows = self._rows("SELECT * FROM artifacts WHERE id=?", (artifact_id,))
        if not rows:
            raise ValueError("Artifact tidak ditemukan.")
        return rows[0]

    def add_artifact(self, artifact_id: str, filename: str, path: Path) -> dict:
        self._write("INSERT INTO artifacts VALUES (?,?,?,?,?)",
                    (artifact_id, filename[:150], str(path), path.stat().st_size, time.time()))
        return self.artifact(artifact_id)

    def artifacts(self) -> list[dict[str, Any]]:
        return self._rows("SELECT id,filename,size,created FROM artifacts ORDER BY created DESC LIMIT 100")

    def agent(self, agent_id: str) -> dict:
        rows = self._rows("SELECT definition FROM agents WHERE id=?", (agent_id,))
        if not rows:
            raise ValueError("Agent tidak ditemukan.")
        return json.loads(rows[0]["definition"])

    def agents(self) -> list[dict]:
        return [json.loads(row["definition"]) for row in self._rows("SELECT definition FROM agents ORDER BY created")]

    def add_agent(self, definition: dict) -> None:
        self._write("INSERT INTO agents VALUES (?,?,?)", (definition["id"], json.dumps(definition), time.time()))

    def workflow(self, job_id: str) -> dict | None:
        rows = self._rows("SELECT definition FROM workflows WHERE job_id=?", (job_id,))
        return json.loads(rows[0]["definition"]) if rows else None

    def save_workflow(self, job_id: str, definition: dict) -> None:
        self._write("INSERT OR REPLACE INTO workflows VALUES (?,?,?)", (job_id, json.dumps(definition), time.time()))

    def create_agent_task(self, job_id: str, agent_id: str, step_id: str, goal: str) -> dict:
        task_id, now = uuid.uuid4().hex, time.time()
        self._write("INSERT INTO agent_tasks(id,job_id,agent_id,step_id,status,goal,created,updated) VALUES (?,?,?,?,'submitted',?,?,?)",
                    (task_id, job_id, agent_id, step_id, goal, now, now))
        return self.agent_task(task_id)

    def agent_task(self, task_id: str) -> dict:
        rows = self._rows("SELECT * FROM agent_tasks WHERE id=?", (task_id,))
        if not rows:
            raise ValueError("Tugas agent tidak ditemukan.")
        return rows[0]

    def agent_tasks(self, job_id: str) -> list[dict]:
        return self._rows("SELECT * FROM agent_tasks WHERE job_id=? ORDER BY created", (job_id,))

    def update_agent_task(self, task_id: str, **fields) -> None:
        allowed = {"status", "messages", "result", "outputs", "evidence", "review"}
        if not fields or not fields.keys() <= allowed:
            raise ValueError("Invalid task update.")
        values = [json.dumps(value) if isinstance(value, (list, dict)) else value for value in fields.values()]
        self._write("UPDATE agent_tasks SET " + ",".join(key + "=?" for key in fields) + ",updated=? WHERE id=?",
                    (*values, time.time(), task_id))

    def link_output(self, job_id: str, artifact_id: str) -> None:
        self.artifact(artifact_id)
        self._write("INSERT OR IGNORE INTO job_outputs VALUES (?,?)", (job_id, artifact_id))

    def job_artifacts(self, job_id: str) -> list[dict]:
        return self._rows("SELECT a.* FROM artifacts a JOIN job_outputs o ON a.id=o.artifact_id WHERE o.job_id=?", (job_id,))

    def begin_action(self, job_id: str, tool: str, args: dict, summary: str) -> str:
        self.job(job_id)
        action_id, now = uuid.uuid4().hex[:12], time.time()
        digest = hashlib.sha256(json.dumps({"tool": tool, "args": args}, sort_keys=True).encode()).hexdigest()
        self._write("INSERT INTO action_ledger VALUES (?,?,?,?,?,'pending',?,?)",
                    (action_id, job_id, tool, digest, summary[:1000], now, now))
        return action_id

    def action_status(self, action_id: str, status: str) -> None:
        if status not in {"approved", "applying", "applied", "unknown", "rejected", "canceled"}:
            raise ValueError("Invalid action status.")
        self._write("UPDATE action_ledger SET status=?, updated=? WHERE id=?", (status, time.time(), action_id))

    def actions(self, job_id: str | None = None, *, unresolved: bool = False) -> list[dict]:
        where, params = [], []
        if job_id is not None:
            where.append("job_id=?")
            params.append(job_id)
        if unresolved:
            where.append("status='unknown'")
        clause = " WHERE " + " AND ".join(where) if where else ""
        return self._rows("SELECT * FROM action_ledger" + clause + " ORDER BY created DESC LIMIT 100", tuple(params))

    def resolve_action(self, action_id: str, applied: bool) -> bool:
        return self._write("UPDATE action_ledger SET status=?, updated=? WHERE id=? AND status='unknown'",
                           ("confirmed_applied" if applied else "confirmed_not_applied", time.time(), action_id)).rowcount == 1

    def reserve_model_call(self, job_id: str, limit: int, output_limit: int, reserve: int) -> str:
        with self.lock, self.db:
            count = int(self.get("model_calls:" + job_id, "0"))
            charged = self.db.execute("SELECT COALESCE(SUM(charged),0) FROM model_usage WHERE job_id=?", (job_id,)).fetchone()[0]
            if count >= limit:
                raise ValueError("Shared model-call budget reached. Review the job before starting more work.")
            if charged + reserve > output_limit:
                raise ValueError("Shared model output-token budget reached; no additional model request was sent.")
            call_id = uuid.uuid4().hex
            self.db.execute("INSERT INTO kv VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("model_calls:" + job_id, str(count + 1)))
            self.db.execute("INSERT INTO model_usage VALUES (?,?,'reserved',?,?,NULL,NULL,?)",
                            (call_id, job_id, reserve, reserve, time.time()))
        return call_id

    def settle_model_call(self, call_id: str, usage: dict | None, *, succeeded: bool) -> None:
        completion = usage.get("completion_tokens") if usage else None
        prompt = usage.get("prompt_tokens") if usage else None
        def valid(value):
            return type(value) is int and value >= 0
        completion = completion if valid(completion) else None
        prompt = prompt if valid(prompt) else None
        self._write("UPDATE model_usage SET status=?, prompt_tokens=?, completion_tokens=?, charged=CASE WHEN ? IS NULL THEN reserved ELSE ? END WHERE id=?",
                    ("completed" if succeeded else "unknown", prompt, completion, completion, completion, call_id))

    def model_budget(self, job_id: str) -> dict:
        rows = self._rows("SELECT COALESCE(SUM(charged),0) AS output_tokens_charged, COALESCE(SUM(prompt_tokens),0) AS reported_prompt_tokens, COUNT(*) AS recorded_calls FROM model_usage WHERE job_id=?", (job_id,))
        return rows[0] | {"model_calls": int(self.get("model_calls:" + job_id, "0"))}
