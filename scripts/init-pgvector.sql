-- Enable pgvector in the application database.
CREATE EXTENSION IF NOT EXISTS vector;

-- Separate database for Langfuse so its schema never collides with app tables.
CREATE DATABASE langfuse;
