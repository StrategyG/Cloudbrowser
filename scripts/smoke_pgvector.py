"""Real PostgreSQL/pgvector smoke: cosine retrieval and tenant partition."""
from __future__ import annotations

import os

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector

dsn = os.environ["RAG_TEST_DB_URL"]
with psycopg.connect(dsn, connect_timeout=10) as conn:
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)
    conn.execute("""CREATE TEMP TABLE smoke_knowledge (
        project_id text NOT NULL, source text NOT NULL,
        embedding vector(384) NOT NULL)""")
    one = Vector([1.0] + [0.0] * 383)
    other = Vector([0.0, 1.0] + [0.0] * 382)
    conn.execute("INSERT INTO smoke_knowledge VALUES (%s,%s,%s)",
                 ("arusia", "rigging-guide", one))
    conn.execute("INSERT INTO smoke_knowledge VALUES (%s,%s,%s)",
                 ("other", "private-foreign-document", one))
    conn.execute("INSERT INTO smoke_knowledge VALUES (%s,%s,%s)",
                 ("arusia", "audio-guide", other))
    rows = conn.execute("""SELECT source FROM smoke_knowledge
        WHERE project_id=%s ORDER BY embedding <=> %s LIMIT 2""",
        ("arusia", one)).fetchall()
    assert [row[0] for row in rows] == ["rigging-guide", "audio-guide"], rows
print("PASS real PostgreSQL pgvector: 384 dimensions, project isolation, cosine ordering")
