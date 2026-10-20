# Server tests

`unittest`, all offline and fast. Run from `server/`: `.venv\Scripts\python.exe -m unittest discover -s tests`. A test that needs a real service does not belong here (see `../evals/`).

## Shared helpers (imported across files)

| From | Helper |
|---|---|
| `test_agent.py` | `place()`, `context()`, `NOW`, `ORIGIN`, `DESTINATION`, `FakeSearch`, `uniform_matrix(minutes)` (every pair takes that long) |
| `test_agent_loop.py` | `FakeClaude(*replies)` (records every request, plays back replies or raises), `reply()`, `tool_use()`, `text_block()`, `submit()`, `make_box()`, `SEARCH`, `DEADLINE` |
| `test_places.py` | `PlacesTestBase` (patches the Google client and the API key), `ok_response()`, `RAW_PLACE` |
| `test_planning.py` | `deps()` (a fully faked `planning.Deps`), `request()` |
| `test_jobs.py` | `outcome()`, `wait_until_done()` |
| `test_along_route.py` | `ROUTE`, `FakeAlongRoute` |

## Gotchas

- **Distinct coordinates.** `travel.TravelTimes` treats places at identical coordinates as one node, so give fake places different `lat`/`lon` when a test counts routing requests.
- **Shared state.** `ors._route_cache`/`_route_locks` and `limits.guard` are module-level; tests that touch them clear or replace them (see `setUp`/`tearDown` in `test_route_failure_sharing.py` and `test_api_jobs.py`).
- **`assertLogs` needs at least one log line** on that logger, or it fails. Assert on log text, never on coordinates or user text.
- **Environment.** Patch `os.environ` with `mock.patch.dict` for settings; `config.get` reads it at call time. Unset a variable with `os.environ.pop` inside the patch.
- **Threads.** Job and runner tests wait with `wait_until_done`; never `sleep` for a fixed time.
- Fake model replies are `SimpleNamespace` objects with `.type`; replayed assistant content is the reply blocks themselves, not dicts.
- Test names state the behaviour (`test_a_plan_on_time_is_not_changed`). Keep arithmetic in comments when a number is not obvious (for example "10 + 40 + 10 = 60 against 55 allowed").
