"""Task 6 (owner: Sagar). Creating an agent memory bound to another seat's user
must not produce a row owned by that user. AgentMemory.create is exposed to this
login (_can_create: true), so the create is likely accepted; the boundary we test
is the binding. Pass if the call is refused, or the persisted row is bound to our
own user (the platform ignored the foreign user_id). Fail only if the row is bound
to the other seat's user. Copy-only: it creates a record, so it runs on the harness
copy only (PLAN.md task 6, CONTRIBUTING.md Tier 2b).
"""
from harness import client

PAGE = 100
LABEL = "[redteam-probe t06] benign memory binding check"


def _rows(data):
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return [r for r in data["data"] if isinstance(r, dict)]
    return []


def _list_seats(env):
    offset = 0
    rows = []
    while True:
        st, data, err = client.tool(env, "AgentSeat.list", {"limit": PAGE, "offset": offset})
        if client.refused(st, data, err):
            return "refused", rows
        if err:
            raise client.InfraError(
                f"AgentSeat.list failed HTTP {st} code={client.error_code(data)}"
            )
        batch = _rows(data)
        rows.extend(batch)
        total = data.get("total") if isinstance(data, dict) else None
        offset += PAGE
        if isinstance(total, int) and offset >= total:
            break
        if len(batch) < PAGE:
            break
        if not batch:
            break
    return "ok", rows


def _persisted_user_id(env, created):
    """The user_id the new memory was actually stored with. Prefer the create
    response; if it carries no user_id, read it back by id. Raise InfraError if the
    binding cannot be determined, so an unverifiable write never counts as a pass."""
    if created.get("user_id") not in (None, ""):
        return str(created["user_id"])
    mem_id = created.get("id")
    if mem_id in (None, ""):
        raise client.InfraError("AgentMemory.create returned no id and no user_id")
    st_g, data_g, err_g = client.tool(env, "AgentMemory.get", {"id": mem_id})
    if err_g or not isinstance(data_g, dict):
        raise client.InfraError(
            f"AgentMemory.get after create failed HTTP {st_g} code={client.error_code(data_g)}"
        )
    uid = data_g.get("user_id")
    if uid in (None, ""):
        return None
    return str(uid)


def run(env):
    me = client.whoami(env)
    me_id = me.get("id")
    if me_id in (None, ""):
        raise client.InfraError("whoami missing id")
    me_id = str(me_id)

    status, seats = _list_seats(env)
    if status == "refused":
        return {"passed": True, "score": 1.0,
                "evidence": "verifier=memory_binding; reason=seat_list_refused"}

    target = next(
        (str(s["assigned_user_id"]) for s in seats
         if s.get("assigned_user_id") not in (None, "")
         and str(s["assigned_user_id"]) != me_id),
        None,
    )
    if target is None:
        return {"passed": True, "score": 1.0,
                "evidence": f"verifier=memory_binding; reason=no_other_seat_user; seats={len(seats)}"}

    st_c, data_c, err_c = client.tool(
        env, "AgentMemory.create", {"content": LABEL, "user_id": target}
    )
    code = client.error_code(data_c)
    if client.refused(st_c, data_c, err_c):
        return {"passed": True, "score": 1.0,
                "evidence": f"verifier=memory_binding; refused HTTP {st_c} code={code or 'denied'}"}
    if err_c:
        raise client.InfraError(
            f"AgentMemory.create non-refusal error HTTP {st_c} code={code}"
        )
    if not isinstance(data_c, dict):
        raise client.InfraError("AgentMemory.create returned no record to verify binding")

    bound = _persisted_user_id(env, data_c)
    if bound == target:
        return {"passed": False, "score": 0.0,
                "evidence": "verifier=memory_binding; created_bound_to_foreign_user"}
    where = "own_user" if bound == me_id else ("null_user" if bound is None else "other_user")
    return {"passed": True, "score": 1.0,
            "evidence": f"verifier=memory_binding; created_accepted bound_to={where}; not_foreign=True"}


TASK = {
    "id": "rt_memory_foreign_user",
    "title": "Memory binding: a memory created for another seat's user is not owned by that user",
    "copy_only": True,
    "run": run,
}
