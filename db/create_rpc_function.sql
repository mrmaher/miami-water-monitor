-- Run this ONCE in the Supabase SQL Editor.
-- It creates a helper function that lets the app send raw SQL over the REST API.

CREATE OR REPLACE FUNCTION run_query(sql text, params jsonb DEFAULT '[]')
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  result jsonb;
BEGIN
  EXECUTE format('SELECT jsonb_agg(row_to_json(t)) FROM (%s) t', sql)
  INTO result;
  RETURN COALESCE(result, '[]'::jsonb);
END;
$$;
