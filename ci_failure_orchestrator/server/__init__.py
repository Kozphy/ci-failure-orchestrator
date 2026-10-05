"""HTTP API and background worker for the agent execution foundation.

Requires the ``server`` extra (FastAPI, SQLAlchemy, Pydantic, uvicorn, psycopg). Run state,
audit events and an evidence mirror live in a SQL database (PostgreSQL in deployment, SQLite
for local tests); evidence files stay under the artifacts root for the existing CLI readers.
"""
