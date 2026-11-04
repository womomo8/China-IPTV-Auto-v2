
def _load_candidates_and_reserve_rounds(
    database_path: Path,
    run_id: int,
    runner_identity: str,
    environment_type: str,
    required_rounds: int = BASIC_ROUNDS_REQUIRED,
) -> tuple[list[dict[str, Any]], int]:
    """
    Reserve missing basic rounds or resume pending records.

    Existing database lines must pass the IPv4 admission gate before
    measurement reservations are created. DNS checks run outside the
    write transaction to avoid holding the SQLite write lock.
    """
    candidates: list[dict[str, Any]] = []
    skipped = 0
    timestamp = _now()

    # Read eligible database lines first. This is deliberately outside
    # the write transaction because IPv4 admission may perform DNS lookup.
    with database_session(database_path) as db:
        run = db.execute(
            """
            SELECT runner_identity, environment_type
              FROM runs
             WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()

        if run is None:
            raise ValueError(f"任务记录不存在：run_id={run_id}")
        if run["runner_identity"] != runner_identity:
            raise ValueError("runner_identity 与任务记录不一致")
        if run["environment_type"] != environment_type:
            raise ValueError("environment_type 与任务记录不一致")
        if environment_type not in SUPPORTED_ENVIRONMENTS:
            raise ValueError(
                "基础测速目前只允许 cloud，不能冒充国内家庭实测"
            )

        admission_rows = db.execute(
            """
            SELECT l.line_id, l.url
              FROM lines AS l
             WHERE NOT EXISTS (
                   SELECT 1 FROM blacklists b
                    WHERE b.active = 1
                      AND (
                           (b.target_type = 'line'
                            AND b.target_id = l.line_id)
                        OR (b.target_type = 'url'
                            AND b.target_id = l.url)
                      )
             )
             ORDER BY l.line_id
            """
        ).fetchall()

    # Only URLs that passed IPv4 admission are allowed to reserve
    # or resume basic measurement attempts.
    admitted_urls: dict[str, str] = {}

    for row in admission_rows:
        line_id = str(row["line_id"])
        url = str(row["url"] or "")

        try:
            admission = check_ipv4_url(url)
        except Exception:
            # Fail closed. A broken admission check must never allow
            # an unverified line into the measurement pipeline.
            continue

        if admission.allowed:
            admitted_urls[line_id] = url

    # Keep the original atomic reservation logic. Re-read the rows
    # under the write lock and verify that the URL has not changed
    # since its IPv4 admission check.
    with database_session(database_path) as db:
        db.execute("BEGIN IMMEDIATE")

        run = db.execute(
            """
            SELECT runner_identity, environment_type
              FROM runs
             WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()

        if run is None:
            raise ValueError(f"任务记录不存在：run_id={run_id}")
        if run["runner_identity"] != runner_identity:
            raise ValueError("runner_identity 与任务记录不一致")
        if run["environment_type"] != environment_type:
            raise ValueError("environment_type 与任务记录不一致")
        if environment_type not in SUPPORTED_ENVIRONMENTS:
            raise ValueError(
                "基础测速目前只允许 cloud，不能冒充国内家庭实测"
            )

        rows = db.execute(
            """
            SELECT l.line_id, l.url, l.headers_json
              FROM lines AS l
             WHERE NOT EXISTS (
                   SELECT 1 FROM blacklists b
                    WHERE b.active = 1
                      AND (
                           (b.target_type = 'line'
                            AND b.target_id = l.line_id)
                        OR (b.target_type = 'url'
                            AND b.target_id = l.url)
                      )
             )
             ORDER BY l.line_id
            """
        ).fetchall()

        for row in rows:
            line_id = str(row["line_id"])
            current_url = str(row["url"] or "")

            # Exclude old IPv6/private lines, temporary DNS failures,
            # and URLs changed after the admission check.
            if admitted_urls.get(line_id) != current_url:
                continue

            existing_rows = db.execute(
                """
                SELECT measurement_id, round_no, status, evidence_json
                  FROM measurements
                 WHERE run_id = ?
                   AND line_id = ?
                   AND runner_identity = ?
                   AND environment_type = ?
                 ORDER BY round_no, measurement_id
                """,
                (
                    run_id,
                    line_id,
                    runner_identity,
                    environment_type,
                ),
            ).fetchall()

            basic_existing = [
                item for item in existing_rows
                if not _is_stability_retest(
                    _decode_evidence(item["evidence_json"])
                )
            ]

            try:
                headers = json.loads(row["headers_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                headers = {}
            if not isinstance(headers, dict):
                headers = {}

            # Resume pending reservations first. Terminal records,
            # including failed attempts, count as completed attempts.
            pending_records = [
                item for item in basic_existing
                if item["status"] == "pending"
            ]
            for pending in pending_records:
                candidates.append({
                    "measurement_id": int(pending["measurement_id"]),
                    "line_id": line_id,
                    "round_no": int(pending["round_no"]),
                    "url": current_url,
                    "headers": headers,
                })

            remaining = max(0, required_rounds - len(basic_existing))
            if remaining == 0:
                skipped += 1
                continue

            history = db.execute(
                """
                SELECT round_no, evidence_json
                  FROM measurements
                 WHERE line_id = ?
                   AND runner_identity = ?
                   AND environment_type = ?
                """,
                (line_id, runner_identity, environment_type),
            ).fetchall()

            occupied_rounds = {
                int(historical["round_no"])
                for historical in history
            }

            # Fill the lowest unused round numbers first.
            # Stability retests occupy their numbers but do not count
            # toward the required basic measurement rounds.
            next_round = 1

            # A failed attempt remains a failed attempt and is not
            # silently retried as a successful attempt.
            for _ in range(remaining):
                while next_round in occupied_rounds:
                    next_round += 1

                cursor = db.execute(
                    """
                    INSERT INTO measurements
                        (run_id, line_id, round_no, measured_at,
                         runner_identity, environment_type, status,
                         latency_ms, throughput_kbps, error_class,
                         evidence_json)
                    VALUES (?, ?, ?, ?, ?, ?, 'pending',
                            NULL, NULL, '', ?)
                    """,
                    (
                        run_id,
                        line_id,
                        next_round,
                        timestamp,
                        runner_identity,
                        environment_type,
                        json.dumps({
                            "measurement_stage": "basic",
                            "reserved_at": timestamp,
                            "environment_type": environment_type,
                            "media_playback_confirmed": False,
                        }),
                    ),
                )

                measurement_id = int(cursor.lastrowid)
                candidates.append({
                    "measurement_id": measurement_id,
                    "line_id": line_id,
                    "round_no": next_round,
                    "url": current_url,
                    "headers": headers,
                })
                occupied_rounds.add(next_round)
                next_round += 1

    return candidates, skipped
