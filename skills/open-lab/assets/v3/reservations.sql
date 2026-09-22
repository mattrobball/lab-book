-- Apply once as the database owner. No application role owns this schema.
-- A shared database is for ONE lab; provision each investigator tag as a role.
BEGIN;
CREATE ROLE lab_book_member NOLOGIN;
CREATE SCHEMA lab_book;
REVOKE ALL ON SCHEMA lab_book FROM PUBLIC;
GRANT USAGE ON SCHEMA lab_book TO lab_book_member;

CREATE TABLE lab_book.reservations (
  lease uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor name NOT NULL DEFAULT current_user,
  run_id text NOT NULL CHECK (run_id ~ '^R-([a-z0-9-]+-)?[0-9]+$'),
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
  started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  deadline timestamptz NOT NULL,
  released_at timestamptz,
  UNIQUE (actor, run_id),
  CHECK (deadline > started_at)
);
ALTER TABLE lab_book.reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE lab_book.reservations FORCE ROW LEVEL SECURITY;
CREATE POLICY notice_read ON lab_book.reservations FOR SELECT TO lab_book_member USING (true);
CREATE POLICY own_insert ON lab_book.reservations FOR INSERT TO lab_book_member
  WITH CHECK (actor = current_user);
CREATE POLICY own_release ON lab_book.reservations FOR UPDATE TO lab_book_member
  USING (actor = current_user AND released_at IS NULL)
  WITH CHECK (actor = current_user AND released_at IS NOT NULL);
CREATE POLICY own_reap ON lab_book.reservations FOR DELETE TO lab_book_member
  USING (actor = current_user AND released_at IS NOT NULL);
GRANT SELECT ON lab_book.reservations TO lab_book_member;
GRANT INSERT (run_id, payload, deadline) ON lab_book.reservations TO lab_book_member;
GRANT UPDATE (released_at) ON lab_book.reservations TO lab_book_member;
GRANT DELETE ON lab_book.reservations TO lab_book_member;

CREATE FUNCTION lab_book.take_lease(p jsonb) RETURNS jsonb
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
    VALUES (p->>'run', p, clock_timestamp() + make_interval(secs => seconds))
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

CREATE FUNCTION lab_book.release_lease(p jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, lab_book AS $$
DECLARE r lab_book.reservations; late boolean;
BEGIN
  SELECT * INTO r FROM lab_book.reservations WHERE lease = (p->>'lease')::uuid
    AND actor = current_user AND run_id = p->>'run' FOR UPDATE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('outcome', 'unsolicited');
  END IF;
  late := r.deadline <= clock_timestamp() OR r.released_at IS NOT NULL;
  UPDATE lab_book.reservations SET released_at = clock_timestamp()
    WHERE lease = r.lease AND released_at IS NULL;
  RETURN jsonb_build_object('outcome', CASE WHEN late THEN 'unsolicited' ELSE 'released' END);
END $$;

CREATE FUNCTION lab_book.list_leases(p jsonb DEFAULT '{}'::jsonb) RETURNS jsonb
LANGUAGE sql SECURITY INVOKER SET search_path = pg_catalog, lab_book AS $$
  SELECT jsonb_build_object('actor', current_user::text, 'reservations', coalesce(jsonb_agg(
      to_jsonb(r) || jsonb_build_object('state', CASE WHEN r.deadline <= clock_timestamp()
          THEN 'stale' ELSE 'taken' END) ORDER BY r.started_at), '[]'::jsonb))
    FROM lab_book.reservations r WHERE r.released_at IS NULL
      AND (NOT p ? 'problem' OR r.payload->>'problem' = p->>'problem');
$$;

CREATE FUNCTION lab_book.reap_leases(p jsonb DEFAULT '{}'::jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, lab_book AS $$
DECLARE count_rows integer;
BEGIN
  -- Expired, unreturned work stays visible as stale. Only closed OWN rows go.
  DELETE FROM lab_book.reservations WHERE actor = current_user AND released_at IS NOT NULL;
  GET DIAGNOSTICS count_rows = ROW_COUNT;
  RETURN jsonb_build_object('removed', count_rows);
END $$;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA lab_book FROM PUBLIC;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA lab_book TO lab_book_member;
COMMIT;
