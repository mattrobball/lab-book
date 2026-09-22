-- Apply as database owner ONLY after owners close/reap their notices.
-- No promise is rewritten, no worker is stopped, and no data is discarded.
BEGIN;
LOCK TABLE lab_book.reservations IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM lab_book.reservations) THEN
    RAISE EXCEPTION 'close and reap notices before this migration; no rows were changed';
  END IF;
END $$;
ALTER TABLE lab_book.reservations ALTER COLUMN started_at SET DEFAULT statement_timestamp();
-- These constraints also govern DIRECT SQL, not just RPC entry points.
ALTER TABLE lab_book.reservations ADD CONSTRAINT notice_actor_namespace CHECK (
  (actor::text ~ '^[a-z0-9][a-z0-9-]*$'
   AND run_id ~ ('^R-' || actor::text || '-[0-9]+$')) IS TRUE);
ALTER TABLE lab_book.reservations ADD CONSTRAINT notice_payload_identity CHECK (
  (jsonb_typeof(payload->'run') = 'string' AND payload->>'run' = run_id
   AND (NOT payload ? 'actor' OR
        (jsonb_typeof(payload->'actor') = 'string' AND payload->>'actor' = actor::text))) IS TRUE);
ALTER TABLE lab_book.reservations ADD CONSTRAINT notice_complete_promise CHECK (
  (jsonb_typeof(payload->'question_id') = 'string' AND length(btrim(payload->>'question_id')) > 0
   AND jsonb_typeof(payload->'question') = 'string' AND length(btrim(payload->>'question')) > 0
   AND jsonb_typeof(payload->'method') = 'string' AND length(btrim(payload->>'method')) > 0
   AND jsonb_typeof(payload->'model') = 'string' AND length(btrim(payload->>'model')) > 0
   AND jsonb_typeof(payload->'expected_claim_shape') = 'string' AND length(btrim(payload->>'expected_claim_shape')) > 0
   AND jsonb_typeof(payload->'problem') = 'string' AND length(btrim(payload->>'problem')) > 0) IS TRUE);
ALTER TABLE lab_book.reservations ADD CONSTRAINT notice_budget CHECK (
  (jsonb_typeof(payload->'budget_seconds') = 'number'
   AND payload->>'budget_seconds' ~ '^[0-9]+$'
   AND (payload->>'budget_seconds')::numeric BETWEEN 1 AND 604800) IS TRUE);
ALTER TABLE lab_book.reservations ADD CONSTRAINT notice_exact_deadline CHECK (
  (deadline = started_at + make_interval(secs => (payload->>'budget_seconds')::integer)) IS TRUE);

CREATE OR REPLACE FUNCTION lab_book.take_lease(p jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, lab_book AS $$
DECLARE r lab_book.reservations; seconds integer; notices jsonb;
BEGIN
  IF p ? 'actor' AND p->>'actor' IS DISTINCT FROM current_user::text THEN
    RAISE EXCEPTION 'actor must match authenticated investigator';
  END IF;
  IF p->>'run' IS NULL OR p->>'run' !~ ('^R-' || current_user::text || '-[0-9]+$') THEN
    RAISE EXCEPTION 'run ID must belong to authenticated investigator';
  END IF;
  seconds := (p->>'budget_seconds')::integer;
  IF seconds IS NULL OR seconds < 1 OR seconds > 604800 THEN
    RAISE EXCEPTION 'budget_seconds must be between 1 and 604800';
  END IF;
  IF coalesce(p->>'question_id','') = '' OR coalesce(p->>'question','') = ''
     OR coalesce(p->>'method','') = '' OR coalesce(p->>'model','') = ''
     OR coalesce(p->>'expected_claim_shape','') = '' OR coalesce(p->>'problem','') = '' THEN
    RAISE EXCEPTION 'complete preregistration required';
  END IF;
  -- Idempotent reannouncement preserves the ORIGINAL promise and deadline.
  INSERT INTO lab_book.reservations(run_id, payload, deadline)
    VALUES (p->>'run', p, statement_timestamp() + make_interval(secs => seconds))
    ON CONFLICT (actor, run_id) DO NOTHING;
  SELECT * INTO STRICT r FROM lab_book.reservations
    WHERE actor = current_user AND run_id = p->>'run';
  IF r.payload IS DISTINCT FROM p THEN
    RAISE EXCEPTION 'run already announced with a different preregistration';
  END IF;
  SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.started_at), '[]'::jsonb) INTO notices
    FROM lab_book.reservations t WHERE t.released_at IS NULL AND t.lease <> r.lease
      AND t.payload->>'problem' = p->>'problem' AND t.payload->>'question_id' = p->>'question_id';
  RETURN jsonb_build_object('reservation', to_jsonb(r), 'notices', notices);
END $$;
COMMIT;
