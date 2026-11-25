# Progress

State of the Python and LangChain rebuild of `/Users/justinhooker/code/utility-agents` (Elixir,
commit `c3e4282`). The task prompt is `plans/port-python-langchain-fable-5-2.md` in that
repository. Update this file at every milestone.

## Done

- Scaffold, seed data, playbooks and golden file copied unchanged (commit `201c4ce`).
- Port of every module. The golden test passed against the untouched Elixir recording, and 14
  of 14 deliberate changes to prompts, schemas and texts failed it (commit `6664355`).
- Terminal app, command line, demo and eval (commit `976631f`).
- The Elixir test suite, 112 tests in 16 files, ported one to one (commit `606b77e`).
- Known problems 1 to 6 fixed with regression tests in `tests/test_regressions.py`, golden file
  recorded again and its diff read (commit `befd3cc`).
- Seed data check in `tests/test_seed_data.py`.
- Known problem 7, offline part: the HR, billing and field report flows were driven in a
  pseudo-terminal with real key presses and replayed model answers; the demo ran end to end
  with replayed answers.
- README written, without live numbers.

## Live checks done (2026-11-25, with Justin's yes)

- `uv` installed with Homebrew; `uv run ruff format --check`, `uv run ruff check` and
  `uv run pytest` pass with it.
- The six typed messages in the real terminal app: 7 requests, $0.0974. Every answer accepted;
  the street-only field report asked for the customer and the meter.
- The 13 cases that failed or were relabelled in the Elixir run: 12 pass, 0 unsafe, $0.1804.
  R-429 still fails (the usage record shows 287 kWh for October, the label says the records
  cannot settle whether the meter was read).

## The agent on LangChain 1.0 (2026-11-25, Justin's decision)

- `department.py` now builds the agent with `langchain.agents.create_agent` and middleware
  (call limit, retry, Anthropic prompt caching, tool errors, plus our `ProposalRules`,
  `OneStrictToolCall` and `Recorder`). `model.py` keeps `chat` and `structured`.
- All department, request path and eval tests passed unchanged. Three model tests were
  rewritten because `model.create_message` is gone; they now cover both paths.
- The golden diff against the hand-written loop: only `"ttl": "5m"` in the two caching
  markers of the three department requests.
- The four clean-up reviewers' findings were applied where they kept behaviour. Skipped:
  one pool for all playbooks' eval trials, lazy imports, caching the chat client, reading
  `decisions.jsonl` once per request, one shared ownership check, and scoping reads by
  customer at the tool layer (a behaviour change: see Open).

## Review (2026-11-25)

- Correctness review of the `create_agent` build found two bugs from the middleware order: a
  proposal filed on the eighth model request was thrown away, and a nudged reply was not
  counted, so nine paid requests were possible. Fixed in `dc80c51` with two regression tests.
- Rule review (`~/.claude/code-patterns.md`): fixed constants defined between functions,
  duplicated month and collection names, colour codes in three places, an `env` abbreviation,
  test URLs, a copied test helper, and two regression tests that asserted on constants.
- Left as they are, for Justin to decide: Python's one-line conditional (rule 17, 40 uses) and
  the tool table at the bottom of `tools.py` (rule 3; Python needs the functions first).
- Disputed with a reason: `model.text` (LangChain joins text blocks without a line break),
  `text.MONTHS` (the standard names follow the locale), `usage.py` (LangChain's usage callback
  keys by the model name the API returns; prices are keyed by the configured ID), `schema.py`
  (Pydantic's own output uses `$defs` and `anyOf`), and the two judges' error handling (their
  failure texts differ on purpose).
- Codex is not installed, so there was no second opinion.

## Next

- Justin decided on 2026-11-25: leave R-429 failing, and no full eval for now. The full eval
  of 246 cases (about $2.80) is the one open done-criterion. Ask before running it.
- A possible fix for R-429 that he did not choose: a code-made warning on an invoice whose
  meter figure equals the month before's.
- Never push or create a remote without his yes.

## Decisions

- Modules mirror the Elixir ones. `request_path.py` is `lib/utility_agents.ex`; `model.py` is
  `anthropic.ex`; `tools.py` holds the read tools and `file_proposal`; `department.py` holds the
  loop and `ask_department`; `tool_text.py` is `tools/text.ex`; `text.py` holds the date, month
  and number wording Elixir kept in `Presenter`; `work.py` holds the values that travel along
  the path; `prompts.py` holds every prompt text; `evaluation.py` is `eval.ex`.
- Settings are in `src/utility_agents/config.yml`.
- A check result is `None` when it passes and the reason as text when it fails.
- A tool that cannot do what was asked raises `ToolError`; its text goes back to the model.
- Tool schemas are generated from the Pydantic models by `schema.py`. Structured answers go
  through `with_structured_output(..., method="json_schema")` with a Pydantic model.
- Retries are ours, not the SDK's: the SDK also retries a reply timeout and a 504.
- The acceptance grep for regex is a text search, so no import may start with a name that
  begins with `re` (`records`, `replace`, `request_path`, `replay`). `tests/test_thesis.py`
  pins it.

## Differences from the Elixir version, on purpose

- The Anthropic SDK inside LangChain drops `"type"` next to `"enum"` in an output schema.
- A structured answer is validated with Pydantic, so an answer missing a field is unreadable.
- An API error body is printed as JSON, not as an Elixir map.
- Text of only spaces counts as no value in a proposal.
- `ask_department` with a department that cannot be asked returns the valid ones as a tool
  error. Elixir crashed.
- Known problems 1 to 6: see the commit message of `befd3cc` and the playbooks' Changes.

## Open

- Done-criterion 5 (full eval at 80% in every group, 0 unsafe) is not measured on this version.
- Both live checks were repeated on the `create_agent` build on 2026-11-25: the six typed
  messages (7 requests, $0.0766, all accepted) and the 13 cases (13/13, 0 unsafe, $0.2340).
  R-429 passed this time and failed the time before with the same prompts: run-to-run
  variation, not a fix.
- The agent can still read another customer's invoice with its read tools. The fact check
  stops it from naming that invoice in the proposal's fields, but no code reads the draft's
  prose. Scoping reads to the asking customer at the tool layer would close it.
