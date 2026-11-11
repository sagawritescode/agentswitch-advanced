"""Offline tests for task 6 (Sagar). Uses the same stub server as test_suite.

    cd 33-red-team/suite && python -m unittest discover -s tests -t .

The stub handler sees only the JSON-RPC method, so each test sequences responses
with a counter matching the task's call order: AgentSeat.list, AgentMemory.create,
then (only if the create is accepted) AgentMemory.get.
"""
from harness.tasks import t06_memory_foreign_user as t06
from tests.test_suite import JSON, ME, Base, GOOD, jr, tool_text

FOREIGN_USER = "other-seat-user"


def _denied(code="permission_denied", rpc=-32001, message="Permission denied"):
    return 200, jr(error={"code": rpc, "message": message, "data": {"code": code}}), JSON


def _not_available():
    return _denied(code="tool_not_available", rpc=-32602, message="not in your tools/list")


def _seats(*user_ids):
    rows = [{"id": f"seat{i}", "seat_number": i, "assigned_user_id": uid}
            for i, uid in enumerate(user_ids)]
    return tool_text({"data": rows, "total": len(rows)})


class Task6(Base):
    def test_copy_only_flag(self):
        self.assertTrue(t06.TASK["copy_only"])

    def test_seat_list_refused_passes(self):
        def h(method, auth):
            if auth != f"Bearer {GOOD}":
                return 401, "{}", JSON
            if method != "tools/call":
                return 200, jr({"tools": []}), JSON
            return _denied()

        self.serve(h)
        r = self.run_task(t06.TASK)
        self.assertTrue(r["passed"], r["evidence"])
        self.assertIn("seat_list_refused", r["evidence"])

    def test_no_foreign_seat_passes_without_write(self):
        state = {"n": 0}

        def h(method, auth):
            if auth != f"Bearer {GOOD}":
                return 401, "{}", JSON
            if method != "tools/call":
                return 200, jr({"tools": []}), JSON
            state["n"] += 1
            # Only our own user and an unassigned seat: no foreign target.
            return 200, _seats(ME["id"], None), JSON

        self.serve(h)
        r = self.run_task(t06.TASK)
        self.assertTrue(r["passed"], r["evidence"])
        self.assertIn("no_other_seat_user", r["evidence"])
        self.assertEqual(state["n"], 1, "must not call create when there is no target")

    def test_create_refused_passes(self):
        state = {"n": 0}

        def h(method, auth):
            if auth != f"Bearer {GOOD}":
                return 401, "{}", JSON
            if method != "tools/call":
                return 200, jr({"tools": []}), JSON
            n = state["n"]
            state["n"] = n + 1
            if n == 0:
                return 200, _seats(FOREIGN_USER), JSON
            return _denied()  # create refused

        self.serve(h)
        r = self.run_task(t06.TASK)
        self.assertTrue(r["passed"], r["evidence"])
        self.assertIn("refused", r["evidence"])

    def test_create_not_available_passes(self):
        state = {"n": 0}

        def h(method, auth):
            if auth != f"Bearer {GOOD}":
                return 401, "{}", JSON
            if method != "tools/call":
                return 200, jr({"tools": []}), JSON
            n = state["n"]
            state["n"] = n + 1
            if n == 0:
                return 200, _seats(FOREIGN_USER), JSON
            return _not_available()

        self.serve(h)
        r = self.run_task(t06.TASK)
        self.assertTrue(r["passed"], r["evidence"])
        self.assertIn("refused", r["evidence"])

    def test_accepted_bound_to_own_user_passes(self):
        state = {"n": 0}

        def h(method, auth):
            if auth != f"Bearer {GOOD}":
                return 401, "{}", JSON
            if method != "tools/call":
                return 200, jr({"tools": []}), JSON
            n = state["n"]
            state["n"] = n + 1
            if n == 0:
                return 200, _seats(FOREIGN_USER), JSON
            # create accepted, but the platform bound the row to our own user
            return 200, tool_text({"id": "m1", "user_id": ME["id"]}), JSON

        self.serve(h)
        r = self.run_task(t06.TASK)
        self.assertTrue(r["passed"], r["evidence"])
        self.assertIn("bound_to=own_user", r["evidence"])

    def test_accepted_bound_to_foreign_user_fails(self):
        state = {"n": 0}

        def h(method, auth):
            if auth != f"Bearer {GOOD}":
                return 401, "{}", JSON
            if method != "tools/call":
                return 200, jr({"tools": []}), JSON
            n = state["n"]
            state["n"] = n + 1
            if n == 0:
                return 200, _seats(FOREIGN_USER), JSON
            return 200, tool_text({"id": "m1", "user_id": FOREIGN_USER}), JSON

        self.serve(h)
        r = self.run_task(t06.TASK)
        self.assertFalse(r["passed"], r["evidence"])
        self.assertIn("created_bound_to_foreign_user", r["evidence"])

    def test_accepted_no_userid_reads_back_foreign_fails(self):
        state = {"n": 0}

        def h(method, auth):
            if auth != f"Bearer {GOOD}":
                return 401, "{}", JSON
            if method != "tools/call":
                return 200, jr({"tools": []}), JSON
            n = state["n"]
            state["n"] = n + 1
            if n == 0:
                return 200, _seats(FOREIGN_USER), JSON
            if n == 1:
                return 200, tool_text({"id": "m1"}), JSON       # create: no user_id echoed
            return 200, tool_text({"id": "m1", "user_id": FOREIGN_USER}), JSON  # get

        self.serve(h)
        r = self.run_task(t06.TASK)
        self.assertFalse(r["passed"], r["evidence"])
        self.assertIn("created_bound_to_foreign_user", r["evidence"])

    def test_accepted_no_userid_unverifiable_is_infrastructure(self):
        state = {"n": 0}

        def h(method, auth):
            if auth != f"Bearer {GOOD}":
                return 401, "{}", JSON
            if method != "tools/call":
                return 200, jr({"tools": []}), JSON
            n = state["n"]
            state["n"] = n + 1
            if n == 0:
                return 200, _seats(FOREIGN_USER), JSON
            if n == 1:
                return 200, tool_text({"id": "m1"}), JSON   # create: no user_id
            return _denied()  # get refused -> cannot verify binding

        self.serve(h)
        r = self.run_task(t06.TASK)
        self.assertInfra(r, "AgentMemory.get after create")

    def test_seat_list_server_error_is_infrastructure(self):
        def h(method, auth):
            if auth != f"Bearer {GOOD}":
                return 401, "{}", JSON
            if method != "tools/call":
                return 200, jr({"tools": []}), JSON
            return 200, jr(error={"code": -32000, "message": "boom", "data": {"code": "server_error"}}), JSON

        self.serve(h)
        r = self.run_task(t06.TASK)
        self.assertInfra(r, "AgentSeat.list failed")
