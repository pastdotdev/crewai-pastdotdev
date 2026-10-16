# crewai-pastdotdev

past dev is a memory API for AI agents. This package connects it to
[CrewAI](https://www.crewai.com): your crews keep what they learn in past dev
and recall it in later runs, with the date and the source of every memory.

It gives you two ways to use past dev:

- **`PastDevMemory`**: crew memory. Pass it as `memory=` to a `Crew` or an
  `Agent`. CrewAI recalls before each task and saves each task result. A save
  is a past dev **Ingest** and a search is a past dev **Recall**.
- **`PastDevRecallTool`** and **`PastDevIngestTool`**: tools that an agent
  calls when it decides to. The model gives only the query or the content.

[Website](https://past.dev) ·
[Quickstart](https://past.dev/docs/memory-api/quickstart) ·
[API reference](https://past.dev/docs/memory-api/api-reference)

## Install

```bash
pip install crewai-pastdotdev
```

The package needs Python 3.10 to 3.13 and CrewAI 1.14.6 or later.

## Set the API key

Make a project API key in the past dev console. It starts with `past_sk_`.

```bash
export PAST_API_KEY="past_sk_..."
```

If you run past dev in your own cloud, also set the API host. The default is
`https://api.past.dev`.

```bash
export PAST_API_HOST="https://past.example.com"
```

You can also give `api_key=` and `api_host=` to each class.

## The identity

Every memory in past dev belongs to an **identity**: the id of the person or
account the memory is about, for example the user id in your application.
Recall requires an identity. Ingest makes the identity the first time it sees
it.

**Your code sets the identity, never the model.** Take it from the user
record or the trigger of the run, and give it to the constructor. The tools
have no identity argument, so an agent cannot read or write the memory of
another person. Make one memory or one tool for each user.

## Use past dev as crew memory

```python
from crewai import Agent, Crew, Task
from crewai_pastdotdev import PastDevMemory

memory = PastDevMemory(identity=current_user.id)

writer = Agent(
    role="Account manager",
    goal="Write the weekly report the way the customer wants it",
    backstory="You know the customer well.",
)
report = Task(
    description="Write this week's report for the customer.",
    expected_output="A report in the format the customer prefers.",
    agent=writer,
)

crew = Crew(agents=[writer], tasks=[report], memory=memory)
crew.kickoff()
```

What happens in a run:

1. Before each task, CrewAI recalls with the task description. The recalled
   memories go into the agent's prompt.
2. After each task, CrewAI saves the task and its result. `PastDevMemory`
   ingests them as one data point. past dev extracts the memories on its own
   side, so no extra LLM call runs in your crew.
3. CrewAI also gives the agents its own "Search memory" and "Save to memory"
   tools. They go through past dev too.

You can also call the memory directly:

```python
record = memory.remember("The customer wants the report on Mondays.")
for match in memory.recall("When does the customer want the report?"):
    print(match.record.content, match.record.metadata["occurred_at"])
memory.forget(record_ids=[record.id])  # Delete data point
```

### Settings

| Argument | Default | What it does |
| :- | :- | :- |
| `identity` | required | The identity for every Ingest and Recall. |
| `api_key` | `PAST_API_KEY` | The project API key. |
| `api_host` | `PAST_API_HOST`, else `https://api.past.dev` | The API host. |
| `audience` | none | An audience slug for ingested memories. Without it, a memory is visible to the whole project. |
| `label` | none | A short title stored with each data point. |
| `recall_level` | `low` | The evidence budget of a recall: `low`, `medium`, `high` or `extra-high`. |
| `recall_max_tokens` | none | An exact evidence budget in tokens, instead of `recall_level`. |
| `read_only` | `False` | Recall only. Nothing is ingested. |

### How CrewAI concepts map to past dev

| CrewAI | past dev |
| :- | :- |
| `remember()`, `remember_many()` | Ingest (`POST /api/v1/ingest`). The source id is stable for the same identity and content, so a repeated save is free. |
| `recall()` | Recall (`POST /api/v1/recall`). `limit` is the number of memories, at most 200. |
| `forget(record_ids=[...])` | Delete data point (`DELETE /api/v1/data-points/{sourceId}`). |
| `MemoryMatch.score` | `1 / rank`. past dev ranks the results; it does not return a score. |
| Scopes, categories, agent role | Kept in the data point's metadata (`crewai_scope`, `crewai_categories`, `crewai_agent_role`). Recall does not filter on them. |
| `tree()`, `info()`, `list_records()`, `update()`, `reset()` | Not available: past dev keeps memory on its servers. Use the past dev console to browse. To change a fact, remember the new one: past dev marks the earlier statement as superseded. |

## Use past dev as agent tools

```python
from crewai import Agent
from crewai_pastdotdev import PastDevIngestTool, PastDevRecallTool

agent = Agent(
    role="Support agent",
    goal="Help the customer with what you know about them",
    backstory="You remember every earlier conversation.",
    tools=[
        PastDevRecallTool(identity=current_user.id),
        PastDevIngestTool(identity=current_user.id),
    ],
)
```

| Tool | The model gives | Other settings (in the constructor) |
| :- | :- | :- |
| `PastDevRecallTool` ("past dev Recall") | `query` | `identity`, `limit` (10), `level`, `api_key`, `api_host` |
| `PastDevIngestTool` ("past dev Ingest") | `content` | `identity`, `audience`, `label`, `metadata`, `api_key`, `api_host` |

The recall tool returns the memories as text: rank, date, content, and the
quotations from their sources. If a memory was superseded by a later
statement, the text says so.

## Credits and errors

Every Ingest and every Recall spends credits on your past dev plan. The
connection check (`PastDevClient().check_connection()`, which reads the
project's audiences) and Delete data point are free.

An error from the API raises `PastDevError` with the API's `code` (for
example `out-of-credits`), the HTTP `status`, the message and the
`request_id`. Give the request id to past dev support when you ask about a
call. The tools return the error to the agent as text, and tell it not to
retry when a retry cannot help.

The client sends a request again only when the API answers 429 for the rate
limit, after the wait the API asks for (two times at most). It never retries
`402 out-of-credits`, a monthly cap, or a `400`.

## The HTTP client

`PastDevClient` is a small client for the calls this package uses. You can
use it on its own:

```python
from crewai_pastdotdev import PastDevClient

with PastDevClient() as past:
    past.check_connection()
    past.ingest("The customer moved to Lyon.", identity="user-42", id="crm-note-17")
    page = past.recall("Where does the customer live?", identity="user-42", limit=5)
    past.delete_data_point("crm-note-17")
    audiences = past.list_audiences()
    identities = list(past.list_identities())
```

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
pytest
```

The tests use `httpx.MockTransport` and a scripted LLM, so they need no key
and no network. One live test runs a real Ingest, Recall and Delete data
point when `PAST_API_KEY` is set. It spends a few credits.

## License

MIT. See [LICENSE](LICENSE).
