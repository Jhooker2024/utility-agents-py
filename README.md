# Utility agents

The working code behind the advice deck "From 150 ideas to agents that work". The deck says how
to get from 150 agent ideas to agents people trust. This repository runs that design in the
client's own stack: Python, LangChain and Claude.

Scope: one working path for every request (front door, a department agent with its playbook,
three blind checks, a crawl/walk/run gate, a trace and a review log), with three department
agents: field operations (field reports to CRM), billing (invoice disputes) and HR (policy
questions). 246 labelled cases test them. The shared core is the expensive part; each extra
agent is a playbook, a Pydantic model and an entry in the playbook table.

## Running it

You need Python 3.12 or later, [uv](https://docs.astral.sh/uv/) and an Anthropic API key. Put
the key in `.env` at the repository root, which git ignores. The command loads it on start, so
the key never goes into a shell command:

```sh
ANTHROPIC_API_KEY=your-key
```

Then, from the repository root:

```sh
uv sync
uv run pytest                               # offline, no key needed
uv run utility-agents demo                  # five real requests, step by step
uv run utility-agents                       # the interactive menu
```

`demo` sends five stored requests through the live system, each picked to prove one claim from
the deck, and prints what came in, what the agents did, what they propose, the three checks,
the decision with every reason, and the cost. `demo --detail` adds the raw trace. Each run is
saved to `logs/demo-<time>/transcript.txt`.

The menu offers HR, billing and a field report, each typed in your own words, plus the demo and
the evals (one playbook or all three). HR lists the policies an employee can ask about. Billing
lists what a customer can write about and asks for their email, which may be left empty. A field
report that does not say which customer or meter it is about asks for them at the end and runs
again with them. Each request shows first whether it goes ahead on its own, needs one click or
waits for a person, then the draft or CRM update and why. A "What next?" list lets a person see
the checks and steps, or approve, edit or reject the work. Each choice is recorded as a staff
review. Set `NO_COLOR=1` for plain text.

The same things work as single commands:

```sh
uv run utility-agents submit field_app "Kerkstraat 4, C-1002, meter A-2002. Fuse replaced, 9,950 kWh on 24 Nov."
uv run utility-agents run F-001             # a stored field report
uv run utility-agents run R-203             # free text: the front door routes it
uv run utility-agents review F-001 edited --kind record_update --field follow_up=revisit
uv run utility-agents eval --playbook field_report
uv run utility-agents eval --playbook field_report --model claude-opus-5-5
```

`run` prints the decision as JSON. Every step goes to `logs/trace.jsonl`, every decision and
review to `logs/decisions.jsonl`, every team notification to `logs/notifications.jsonl`.
Running a request again prints its stored decision without calling the model, once it got a
proposal. A request held without one (no key, a failed API call, the kill switch) is worked
again. Set `AGENTS_KILL_SWITCH=1` to stop every model call.

All data in `src/utility_agents/seed` is hand-written for this example: ten customers, their
meters and cables, twenty invoices (a September and an October bill for every customer), meter
usage that matches every bill except one estimated October reading, a price per kWh for each
tariff, five HR policies, 253 requests (five of them for the demo) and the 246 labels that stand
in for staff decisions. Settings are in `src/utility_agents/config.yml`.

## How this maps to the deck

| Deck | Here |
|---|---|
| Slide 2: regex pulls data out of free text; fix: structured outputs, checked by code | `proposal.py`: the model fills a strict schema generated from Pydantic models; `verifier.py` checks it. No file imports `re`, and a test keeps it that way |
| Slide 2: a home-built router; fix: one model per agent, chosen by tests | `models` in `config.yml`, one per agent; `eval --model` compares models on the same cases |
| Slide 2: no evals, no tracing | `evaluation.py` over labelled cases; `logs/trace.jsonl`, one line per step; tokens and cost on every decision |
| Slide 3: chief of staff, rules first, AI only for free text, unsure goes to a person | `chief_of_staff.py`: free text from anyone can only reach billing; field reports come only through the field app and HR questions only through the HR portal |
| Slide 3: departments consult each other: ask, don't borrow access | `ask_department` in `department.py`; each department reads only its own records |
| Slide 3: three blind checks: true, formatted, makes sense | `verifier.py`: grounded, format, sense (the judge never sees the playbook) |
| Slide 3: one knowledge base of playbooks, owned per department | `src/utility_agents/playbooks/*.md`, each with a dated `## Changes` section |
| Slide 4: crawl, walk, run; daily cap; kill switch; a breach drops back a stage | `gate.py`, `decisions.py`; the kill switch in `model.py`, before any call; `flags.py` and `notifications.py`: a concern named in a fixed field goes to a person and tells its team |
| Slide 4: never automated: money, disputes, deadlines, legal, mass sends | Commitments force one click; invoice disputes never act alone; a field report that affects a bill tells billing through its billing follow-up |
| Slide 5: staff train it; you stay in charge | `review`: staff record what they did; a rejected automatic action drops the playbook a stage |

Not in code yet: the weekly spot check and "every correction becomes a test case" (slide 5).
The deck runs on AWS Bedrock; this example calls the Anthropic API directly.

## Trade-offs

- **Structured output instead of parsing.** A department ends by calling `file_proposal`, whose
  strict JSON schema is generated from the same Pydantic models that validate it. The validation
  and the fact check run inside that call, so a problem goes back to the model once as a tool
  error it can fix. Flags work the same way: the concerns a message raises are a fixed list the
  model fills, and code acts on them. The code has no regex and no confidence score: holds come
  from structured facts only.
- **LangChain for the model calls, a plain loop for the agent.** Every call goes through
  `ChatAnthropic`: `bind_tools(..., tool_choice="auto", strict=True, parallel_tool_calls=False)`
  for the agent and `with_structured_output(..., method="json_schema")` for the front door and
  the two judges. Sonnet 5.5 rejects a forced tool choice, which LangChain's default structured
  output uses, so the default is not an option. The loop that runs the tools is one short
  function and not a prebuilt agent, because its rules are the product: one consult, one
  correction, eight turns, then a person.
- **Proposals, not actions.** Nothing is sent and no CRM record is written. The gate's outcome
  (`held`, `one_click`, `automatic`) is logged; acting on it is the next integration.
- **Checks in code first.** Every ID exists in the department's records. Each reading and the
  visit date carry the report's exact words, which must be in the report and hold that figure or
  date. An invoice carries the customer's words that identify it and must belong to the customer
  who asks. Each commitment names its words and its source (the message or a record ID), and
  code finds them in the draft and the source. The judge only answers "does this fit the
  message" and never sees the playbook.
- **Our own retries.** The Anthropic SDK also retries a reply that timed out and a gateway
  timeout. The API may still finish and bill such a request, so `model.py` turns the SDK's
  retries off and retries only what was never worked.
- **Three JSON lines files, no database.** Trace, decisions and notifications are append-only.
  The daily cap and breaches are derived from them.
- **One model per role in config.** Departments run on Sonnet; the front door and the judges on
  Haiku.

## How it works

```
request ─► chief_of_staff ─► department ─► (transfer?) ─► verifier ─► gate ─► trace + decisions
```

- `chief_of_staff` routes mapped channels (billing portal, field app, HR portal) by config with
  no model call. For free text such as email, a model only decides whether it is for billing;
  anything else goes to a person, and the same answer names the message's concerns.
- `department` runs the agent loop with its playbook, its read tools (`find_customer`,
  `get_record`, `list_records`), `ask_department` and `file_proposal`. At most 8 model requests
  and 1 consult. A proposal that names another department in `transfer_to` is handed over once;
  a field report is never handed over.
- `gate`: crawl holds everything, walk lets a CRM update act alone and makes replies one click,
  run acts alone. Today field reports are at walk, invoice disputes at crawl (and never act
  alone) and HR questions at run. Needs attention, a failed check or any flag holds; a
  commitment, an unconfirmed fact, a hand-over or the daily cap of 50 makes it one click. A
  staff rejection of an automatic decision drops the playbook one stage for 30 days.
- `notifications` tells the team that handles each flag once: the duty desk, revenue protection,
  the customer care priority line, security, HR, the customer care manager, and billing for a
  field report's billing follow-up.
- `request_path.handle` is the whole path; the command line and the menu only read input and
  print.

## Testing it

`uv run pytest` runs offline. A local HTTP server stands in for the API and answers with
recorded-shape responses, so LangChain and the Anthropic SDK run as they do in production and
nothing is mocked. The tests check what code does with a model's answer; they cannot score the
model.

- `tests/test_golden.py` compares every request body the system sends and every text a person
  sees with `tests/golden/golden.json`. The file was recorded by the Elixir version this code was
  ported from; the port passed it unchanged before any fix was made (commit `6664355`). It is
  recorded again only after a change meant to alter what is sent.
- `tests/test_regressions.py` has one test for each problem the last live run showed, named
  after the problem.
- `tests/test_seed_data.py` checks that every customer has bills and meter usage the tools can
  answer from.

`uv run utility-agents eval [--playbook <playbook>] [--runs <1-10>]` and `uv run pytest -m live`
run the labelled cases against the API. Each case runs on its own through the whole path. Code
checks what has one right answer: nothing acted alone that had to wait, every expected flag was
raised, billing was told about a billing follow-up, every expected consult happened and the
right records are named. A judge model then decides whether staff would accept the proposal.
The cases come in three groups per playbook: answerable in different forms, unanswerable (the
agent must say so and not guess) and ambiguous (it must not pick one meaning). A playbook passes
at 80% in each group with nothing unsafe. The run's logs are deleted afterwards; the printed
report is the record.

Live checks on this version, 2026-11-25:

- **Six messages typed into the real terminal app**, the way a person types them (lower case,
  typos, no IDs): two billing messages with no email, two HR questions and two field reports.
  Seven requests, $0.10. Every answer was one staff would accept, and the report that named
  only a street asked for the customer and the meter before it ran again.
- **The 13 cases that failed or were relabelled in the Elixir version's last full run.** 12
  passed, nothing unsafe, $0.18. R-429 ("Was my meter actually read for October?") still
  fails: the usage record says the meter recorded 287 kWh, so the agent answered from it, and
  the label says the records cannot settle whether the meter was read.

The full eval of 246 cases has not been run on this version. The last full run was on the
Elixir version (2026-11-25, $2.78): invoice disputes 28/33, 17/20 and 17/20; field reports
58/60, 19/20 and 17/20; HR questions 32/33, 20/20 and 19/20 (answerable, unanswerable,
ambiguous); nothing unsafe. The cases were seen while tuning; a fresh blind batch is the honest
next measure.

## Assumptions

- The labels stand in for staff decisions, and their expected flags are mine until someone at
  the client reviews them.
- A date without a year is read in the current year.
- The customer a request is from is known when the channel says so (the billing portal, or an
  email address on record). A free-text sender not on record is flagged and gets no check
  against a customer.

## Known issues I'd fix with more time

The logs are local files, and nothing stops two processes from using them at the same moment.

- **The same request run twice at once is worked twice and billed twice.** Fix: a database with
  a unique constraint on the request ID.
- **The daily cap can be passed by one** when two requests finish at the same moment. Fix:
  count and write in one transaction.
- **Two tests can fail across midnight UTC**, because a typed request is stamped with today's
  date. Fix: pass the date into `new_request`.
- **A risk both models miss is not caught.** Flags come only from the structured concerns; the
  eval fails any playbook that misses one.
- **Whether the customer's words really identify one invoice is the agent's call.** Code checks
  that the words are in the message and that a request without them names no invoice.
- **A figure in an HR answer or a field note is not checked against its record**, because it
  is not a commitment. The independent reviewer is the only check on it.

## What I'd do next

- Act on the gate's outcome: send one-click drafts to a review queue, write automatic record
  updates to the CRM.
- Turn staff corrections into labelled cases automatically.
- A fresh, unseen batch of cases: the current ones were seen while tuning.
