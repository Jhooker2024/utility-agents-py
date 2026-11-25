# Utility agents

The working code behind the advice deck "From 150 ideas to agents that work". The deck says how
to get from 150 agent ideas to agents people trust. This repository runs that design in the
client's own stack: Python, LangChain and Claude.

Scope: one working path for every request (front door, a department agent with its playbook,
three blind checks, a crawl/walk/run gate, a trace and a review log), with three department
agents: field operations (field reports to CRM), billing (invoice disputes) and HR (policy
questions). 246 labelled cases test them. The shared core is the expensive part; each extra
agent is a playbook, a Pydantic model and an entry in the playbook table.

To run it yourself, see [Running it](#running-it).

## How it works, in plain words

**Who.** Three kinds of people write to the utility: a customer with a question about a bill, a
technician reporting a site visit, and an employee with a question for HR. Three AI assistants
do the first round of work, one each for billing, field operations and HR. Each assistant can
read only the records of its own department. Staff stay in charge: they approve, correct or
reject what an assistant proposes.

**What.** For every message an assistant prepares a proposal: a reply to the customer, an
answer to the employee, or an update for the customer system after a visit. It does not write
loose text for a program to pick apart. It fills in a fixed form: which customer, which invoice
or meter, what was found, what is promised and anything that worries it. The system then
decides what may happen to the proposal and records that decision. This example stops there:
it sends nothing and changes no customer record.

**When a person steps in.** Each kind of work has a level of trust, which people set. The deck
calls the levels crawl, walk and run.

- Bill disputes: a person handles every one. They are about money, so they never go out alone.
- Field reports: a routine update for the customer system goes ahead alone. Anything else
  waits for a person.
- HR questions: an answer from the written policy goes out alone.

At every level a proposal waits for a person when a check fails, when the assistant asks for
one, when a customer's message comes from someone who is not on record, or when the message
raises a concern: a safety risk, a power outage, a vulnerable person, possible tampering, a
legal threat, money promised, a personal matter for HR, or instructions aimed at the AI. The
team that handles the concern is told at once. A proposal needs one click of approval when it
promises money or a date, when the assistant could not confirm something, when it passed
between departments, or after 50 automatic actions in a day. When staff reject something that
went ahead alone, that kind of work drops back one level for 30 days. One switch stops every AI
call at once.

**Where.** It runs on a laptop, in a terminal window with a menu. The customers, meters,
invoices and policies are made up for this example. The assistants are Claude models, reached
through Anthropic's service. Every step, every decision, every staff review and every message
to a team is written to a log file, together with what it cost.

**Why.** The deck names three problems at the client: programs that pull data out of loose
text by matching patterns, a home-built way of choosing AI models, and no tests or record of
what the AI did. This example shows the alternative. The assistant fills in a form, so nothing
is guessed from its wording. Ordinary program code, not AI, checks every fact on the form
against the records. Each assistant uses one AI model, set in one place, and a test run can
compare models on the same cases. Every step is recorded, so anyone can see why a decision was
made. And 246 example messages with known answers measure how often the assistants get it
right.

**How a message travels.**

1. A message comes in from the billing portal, the technicians' app or the HR portal, or as
   loose text such as an email.
2. The front door sends it to the right department. Messages from the three known places go
   straight there. For loose text an AI decides one thing only: is this for billing? If it is
   not, or the AI is unsure, a person gets it.
3. The department's assistant reads its playbook, the written instructions for that kind of
   work. It looks up the records, may ask another department one question, and fills in the
   form.
4. Three checks run. Is the form complete? Is every fact on it true: the customer, meter and
   invoice exist, each reading and date is in the report as quoted, each amount comes from a
   record, and the invoice belongs to the customer who asks? Does a second AI, which has not
   seen the playbook, agree that the proposal fits the message?
5. The gate decides: go ahead alone, wait for one click, or wait for a person. It gives every
   reason.
6. The decision is recorded and the teams that need to know are told. Staff can then approve,
   edit or reject it, and that choice is recorded too.

Three messages from a live run on 2026-11-25, typed the way people type:

| Message | What the system did |
|---|---|
| An employee: "how many vacation days do i get if i only work 3 days a week" | Answered from the annual leave policy: 15 days, with a note to check the rounding with HR. Went out without a person. |
| A customer: "ello, i think i was doubled invoice for the october ..." | Found the customer by name and drafted a reply: one invoice for October, 268 kWh, €85.76, the same as the meter recorded. Waits for a person, as every bill dispute does. |
| A technician: "veldweg 17 raalte. seal on the meter is broken and theres a wire going round it ..." | Filed suspected tampering for the right customer and meter. Waits for a person, and told revenue protection, the duty desk and billing. |

## Running it

You need Python 3.12 or later, [uv](https://docs.astral.sh/uv/) and an Anthropic API key.
Get the code:

```sh
git clone https://github.com/Jhooker2024/utility-agents-py.git
cd utility-agents-py
```

Put the key in a file named `.env` in that folder, which git ignores. The command loads it on
start, so the key never goes into a shell command:

```sh
ANTHROPIC_API_KEY=your-key
```

Then, from the same folder:

```sh
uv sync                                     # installs everything, once
uv run pytest                               # the tests: offline, free, no key needed
uv run utility-agents                       # the menu: type a request in your own words
uv run utility-agents demo                  # five stored requests, step by step
```

In the menu, move with the arrow keys or type a number, then press Enter. Enter on an empty
line goes back, and "Quit" leaves. Every request you type is a paid call to the AI, about one
to two cents each. The tests cost nothing. The full eval cost $2.61 when it ran on 2026-11-25.

`demo` sends five stored requests through the live system, each picked to prove one claim from
the deck, and prints what came in, what the agents did, what they propose, the three checks,
the decision with every reason, and the cost. `demo --detail` adds the raw trace. Each run is
saved to `logs/demo-<time>/transcript.txt`.

The menu offers HR, billing and a field report, each typed in your own words, plus the demo and
the evals (one playbook or all three). HR lists the policies an employee can ask about. Billing
lists what a customer can write about and asks for their email, which may be left empty. A field
report that does not say which customer or meter it is about asks for them once. It offers
the customers the agent found that the report could mean, by name, then that customer's meters
and cables, and runs once more with the answers. "I don't know" leaves it for a person, and
Enter on an empty line goes back to the menu. Each request shows first whether it goes ahead on
its own, needs one click or waits for a person, then the draft or CRM update and why. A "What
next?" list lets a person see the checks and steps, or approve, edit or reject the work. Each
choice is recorded as a staff review. Set `NO_COLOR=1` for plain text.

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
- **LangChain 1.0 as it is meant to be used.** A department agent is `create_agent` from the
  `langchain` package, and what bounds it is middleware: `ModelCallLimitMiddleware` (eight
  model requests, then a person), `ModelRetryMiddleware` (our retry rule),
  `AnthropicPromptCachingMiddleware`, `ToolErrorMiddleware` (a tool error goes back to the
  model as something it can fix), and two small ones of our own: the filing rules (stop when
  the proposal is filed, one correction, one nudge) and a recorder for the trace and the
  cost. The front door and the two judges use `with_structured_output(...,
  method="json_schema")` with a Pydantic model. Sonnet 5.5 rejects a forced tool choice,
  which LangChain's default structured output uses, so that default is not an option.
- **Our tool definitions, not LangChain's conversion.** The tools run as LangChain tools, but
  the model is sent the strict schema generated from our Pydantic models. LangChain's strict
  conversion marks every property required, which would force a transfer on every proposal
  and a customer on every list.
- **Proposals, not actions.** Nothing is sent and no CRM record is written. The gate's outcome
  (`held`, `one_click`, `automatic`) is logged; acting on it is the next integration.
- **Checks in code first.** Every ID exists in the department's records. Each reading and the
  visit date carry the report's exact words, which must be in the report and hold that figure or
  date. A report that names only a street lists the customers it could mean in a field of its
  own, each checked against the records, and a person picks; nothing is guessed from the text.
  An invoice carries the customer's words that identify it and must belong to the customer
  who asks. Each commitment names its words and its source (the message or a record ID). Code
  finds the words in the draft; from a record they must give one of its figures or dates and
  no figure the record does not hold. The judge only answers "does this fit the message" and
  never sees the playbook.
- **One retry rule.** The Anthropic SDK also retries a reply that timed out and a gateway
  timeout. The API may still finish and bill such a request, so the SDK's retries are off and
  `model.retry` allows only what was never worked. The agent's retry middleware and the
  structured answers use the same rule and the same cap.
- **Three JSON lines files, no database.** Trace, decisions and notifications are append-only.
  The daily cap and breaches are derived from them.
- **One model per role in config.** Departments run on Sonnet; the front door and the judges on
  Haiku.

## How it works in the code

```
request ─► chief_of_staff ─► department ─► (transfer?) ─► verifier ─► gate ─► trace + decisions
```

- `chief_of_staff` routes mapped channels (billing portal, field app, HR portal) by config with
  no model call. For free text such as email, a model only decides whether it is for billing;
  anything else goes to a person, and the same answer names the message's concerns.
- `department` builds the agent with `create_agent`: its playbook, its read tools
  (`find_customer`, `get_record`, `list_records`), `ask_department` and `file_proposal`. At
  most 8 model requests and 1 consult. A proposal that names another department in
  `transfer_to` is handed over once, and the concerns of both departments raise their flags. A
  second hand-over is held for a person. A field report is never handed over.
- `gate`: crawl holds everything, walk lets a CRM update act alone and makes replies one click,
  run acts alone. Today field reports are at walk, invoice disputes at crawl (and never act
  alone) and HR questions at run. A stage that is missing or misspelled holds. Needs
  attention, a failed check or any flag holds; a
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
  sees with `tests/golden/golden.json`. A changed prompt, schema, tool text or screen fails it.
  The file is recorded again only after a change meant to alter what is sent.
- `tests/test_regressions.py` has one test for each problem found in live use, named after
  the problem.
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

Full eval, 2026-11-25, on commit `0cdd84a`: all 246 cases, one run each, 12 minutes, $2.61.

| Playbook | Answerable | Unanswerable | Ambiguous | Unsafe | Cost |
|---|---|---|---|---|---|
| HR questions | 32/33 (97%) | 19/20 (95%) | 18/20 (90%) | 0 | $0.65 |
| Invoice disputes | 33/33 (100%) | 19/20 (95%) | 20/20 (100%) | 0 | $0.87 |
| Field reports | 59/60 (98%) | 20/20 (100%) | 19/20 (95%) | 0 | $1.09 |

239 of 246 passed. Every group is above the 80% a playbook needs, and nothing was unsafe. The
report recommends walk for invoice disputes and run for field reports. The stages stay where
they are: one run on cases seen while tuning is not enough to promote a playbook. Results move
by a case or two between runs.

The seven that failed:

- **R-553, R-554 (HR, ambiguous).** "Do field staff get the allowance?" and "Is 10 hours
  enough?" The answer led with one meaning where it should have asked or answered each.
- **R-540 (HR, unanswerable).** "Do we get paid for travel time to a customer?" No policy
  covers it; the answer named policy P-03.
- **R-518 (HR, answerable).** "Do I still get paid if I'm sick for three months?" The agent
  treated it as a personal situation and sent it to HR; the label expects an answer from
  policy P-05.
- **R-430 (invoice dispute, unanswerable).** "What will my corrected October amount be?" The
  draft said a colleague will correct the invoice, which the playbook allows for a bill based
  on an estimated reading. The judge still read it as a promise. It passed in two earlier
  runs, so the shared definition of a promise does not hold every time.
- **F-016 (field report, answerable).** A follow-up visit to a new meter was filed with the
  billing follow-up "meter replaced"; the label expects none.
- **F-154 (field report, ambiguous).** Two assets are at the address and the report does not
  say which was checked. The agent named the closest match; the label expects none named.

R-429 ("Was my meter actually read for October?") passed in this run and failed in an earlier
one with the same prompts. The usage record says the meter recorded 287 kWh and the agent
answers from it; the label says the records cannot settle whether the meter was read. That
disagreement between label and data is still open.

Also live that day, before two fixes to the order of the agent's middleware: **six messages
typed into the real terminal app**, the way a person types them (lower case, typos, no IDs):
two billing messages with no email, two HR questions and two field reports. Seven requests,
$0.08. Every answer was one staff would accept, and the report that named only a street asked
for the customer and the meter before it ran again.

After that run a code review found ten problems, among them fact checks that let a wrong
reading, a wrong year and an invented amount through. They are fixed, each with a test in
`tests/test_regressions.py`. The field report playbook also changed: a report that names only
a street is now searched for. Neither change has run live, so the numbers above are from
before them.

The cases were seen while tuning; a fresh blind batch is the honest next measure.

## Assumptions

- The labels stand in for staff decisions, and their expected flags are mine until someone at
  the client reviews them.
- A date without a year is read in the current year.
- The customer a request is from is known when the channel says so (the billing portal, or an
  email address on record). A customer's message from a sender not on record is flagged on
  every channel and gets no check against a customer.

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
- **The billing agent can still read another customer's invoice with its read tools.** The
  fact check stops a proposal from naming it, but no code reads the draft's wording. Fix:
  limit the read tools to the customer the request is from.
- **Whether the customer's words really identify one invoice is the agent's call.** Code checks
  that the words are in the message and that a request without them names no invoice.
- **A figure in an HR answer or a field note is not checked against its record**, because it
  is not a commitment. The independent reviewer is the only check on it.

## What I'd do next

- Act on the gate's outcome: send one-click drafts to a review queue, write automatic record
  updates to the CRM.
- Turn staff corrections into labelled cases automatically.
- A fresh, unseen batch of cases: the current ones were seen while tuning.
