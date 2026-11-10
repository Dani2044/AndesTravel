"""HTTP tools API for the Andes Travel agents in watsonx Orchestrate.

Each route is one Orchestrate tool (its ``operation_id`` is the tool name). Data
lives in Supabase Postgres (``supabase/migrations``); without a database URL the
API falls back to an in-memory repository for local development and tests.
"""
