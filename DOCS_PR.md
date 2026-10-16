# Listing past dev in the CrewAI docs

The text below is ready to send to the CrewAI repository
([crewAIInc/crewAI](https://github.com/crewAIInc/crewAI)). Send it only after
`crewai-pastdotdev` is on PyPI, because the page tells readers to install it.
[PUBLISHING.md](PUBLISHING.md) gives the order of the steps.

CrewAI has no catalogue or registry for third-party tools and memory
providers. Its guide "Publish Custom Tools" says that a package on PyPI is
enough ("no PR to the CrewAI repo required"). A listing in the docs is a
documentation pull request to the CrewAI repository. MongoDB got its memory
backend listed this way (issue #8096, pull request #8097).

The CrewAI repository has these rules (from `.github/CONTRIBUTING.md` and
`DOCS_TRANSLATIONS.md`, October 2026):

1. A first-time contributor opens an issue first. A pull request that does
   not mention an open issue is closed automatically (label `needs-issue`).
2. A pull request or issue written with an AI assistant must carry the label
   `llm-generated`. A contributor outside the CrewAI team cannot add labels,
   so the pull request body asks for it.
3. Docs changes go in `docs/edge/en/` and in the same files for `ar`, `ko` and
   `pt-BR`. A new page also gets an entry in `docs/docs.json` for each of the
   four languages. The `docs/v*/` snapshots are not edited.
4. The pull request title follows Conventional Commits, for example
   `docs: ...`, in lowercase, under 72 characters.
5. The branch name is `docs/<short-description>`.

---

## 1. The issue

Open it at https://github.com/crewAIInc/crewAI/issues/new/choose with the
**Feature request** template.

**Title**

```
[FEATURE] Document past dev as a memory and tools integration
```

**Feature Area**: Documentation

**Is your feature request related to a an existing bug? Please link it here.**

```
NA
```

**Describe the solution you'd like**

```
past dev is a memory API for AI agents (https://past.dev). The
crewai-pastdotdev package on PyPI connects it to CrewAI in two ways:

- PastDevMemory, a subclass of crewai.memory.Memory. Pass it as memory= to a
  Crew or an Agent: CrewAI's saves go to past dev's ingest endpoint and its
  recalls to past dev's recall endpoint, for one identity that the developer
  fixes.
- PastDevRecallTool and PastDevIngestTool, two BaseTool subclasses for
  agents. The model gives only the query or the content.

I would like to add:

1. A page for it under Tools > AI & Machine Learning
   (docs/edge/en/tools/ai-ml/pastdev.mdx) and a card on the AI & Machine
   Learning overview.
2. One sentence on the Memory page, in the "Storage Backend" section, next to
   the MongoDB backend, for teams that keep memory in a hosted memory API.

The same changes go to the ar, ko and pt-BR docs.
```

**Describe alternatives you've considered**

```
A StorageBackend. It does not fit: StorageBackend.search() receives a query
embedding, while past dev takes the query text and does its own extraction,
embedding and ranking. So the package subclasses Memory and replaces
remember/recall/forget, and Crew and Agent accept it through the existing
memory_kind="memory" discriminator.
```

**Additional context**

```
Package: https://pypi.org/project/crewai-pastdotdev/
Source: https://github.com/pastdotdev/crewai-pastdotdev
Tested with crewai 1.15.28 on Python 3.10, 3.12 and 3.13.
```

**Willingness to Contribute**: Yes, I'd be happy to submit a pull request

---

## 2. The pull request

**Branch**: `docs/past-dev-memory`

**Title** (replace `NNNN` with the issue number)

```
docs: add past dev memory and tools page (#NNNN)
```

**Body**

```
## Summary

Closes #NNNN.

Adds a page for past dev (https://past.dev), a memory API for AI agents,
and links it from the AI & Machine Learning overview and the Memory page.
The integration is the crewai-pastdotdev package on PyPI: PastDevMemory (a
Memory subclass for Crew and Agent memory) and PastDevRecallTool /
PastDevIngestTool.

This PR was drafted with an AI assistant. Please apply the `llm-generated`
label (I cannot add labels).

## Changes

- `docs/edge/en/tools/ai-ml/pastdev.mdx` (new page), and the same page in
  `ar`, `ko` and `pt-BR`
- `docs/edge/{en,ar,ko,pt-BR}/tools/ai-ml/overview.mdx`: one card
- `docs/edge/{en,ar,ko,pt-BR}/concepts/memory.mdx`: one sentence in
  "Storage Backend"
- `docs/docs.json`: the new page in the AI & Machine Learning group of each
  language

## Test plan

- [ ] `cd docs && mintlify broken-links`
- [ ] `cd docs && mintlify dev`, and check the new page and the two links
```

### 2.1 New page: `docs/edge/en/tools/ai-ml/pastdev.mdx`

````mdx
---
title: past dev
description: Keep CrewAI memory in past dev, a memory API for AI agents, and give agents Recall and Ingest tools.
icon: clock-rotate-left
mode: "wide"
---

# past dev

## Description

[past dev](https://past.dev) is a memory API for AI agents. It keeps what your
crews learn and returns it in later runs, with the date and the source of
every memory. When a later statement replaces an earlier one, past dev marks
the earlier one as superseded.

The `crewai-pastdotdev` package connects past dev to CrewAI in two ways:

- **`PastDevMemory`**: a `Memory` that you pass as `memory=` to a `Crew` or an
  `Agent`. A save is a past dev Ingest and a search is a past dev Recall.
- **`PastDevRecallTool`** and **`PastDevIngestTool`**: tools that an agent
  calls when it decides to. The model gives only the query or the content.

## Installation

```shell
uv add crewai-pastdotdev
# or
pip install crewai-pastdotdev
```

Make a project API key in the past dev console and set it:

```shell
export PAST_API_KEY="past_sk_..."
```

If you run past dev in your own cloud, also set `PAST_API_HOST`. The default
is `https://api.past.dev`.

## The identity

Every memory in past dev belongs to an identity: the id of the person or
account the memory is about, for example the user id in your application.
Your code sets the identity, never the model. The tools have no identity
argument, so an agent cannot read or write the memory of another person.
Make one memory or one tool for each user.

## Crew memory

```python Code
from crewai import Agent, Crew, Task
from crewai_pastdotdev import PastDevMemory

memory = PastDevMemory(identity="user-42")

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

Before each task, CrewAI recalls with the task description and adds the
memories to the agent's prompt. After each task, it saves the task and its
result. past dev extracts the memories on its side, so `PastDevMemory` makes
no extra LLM call for a save. The "Search memory" and "Save to memory" tools
that CrewAI gives to agents also go through past dev.

| Parameter | Default | Description |
| :- | :- | :- |
| `identity` | required | The identity for every save and recall. |
| `api_key` | `PAST_API_KEY` | The project API key. |
| `api_host` | `PAST_API_HOST` or `https://api.past.dev` | The API host. |
| `audience` | none | An audience slug for saved memories. Without it, a memory is visible to the whole project. |
| `recall_level` | `low` | The evidence budget of a recall: `low`, `medium`, `high` or `extra-high`. |
| `read_only` | `False` | Recall only. |

past dev keeps memory on its servers, so the local store operations
(`tree()`, `info()`, `list_records()`, `update()`, `reset()`) are not
available. `forget(record_ids=[...])` deletes data points by their source id.

## Agent tools

```python Code
from crewai import Agent
from crewai_pastdotdev import PastDevIngestTool, PastDevRecallTool

agent = Agent(
    role="Support agent",
    goal="Help the customer with what you know about them",
    backstory="You remember every earlier conversation.",
    tools=[
        PastDevRecallTool(identity="user-42"),
        PastDevIngestTool(identity="user-42"),
    ],
)
```

| Tool | Argument from the model | Constructor parameters |
| :- | :- | :- |
| `PastDevRecallTool` | `query` | `identity`, `limit`, `level`, `api_key`, `api_host` |
| `PastDevIngestTool` | `content` | `identity`, `audience`, `label`, `metadata`, `api_key`, `api_host` |

## More information

- [past dev quickstart](https://past.dev/docs/memory-api/quickstart)
- [past dev API reference](https://past.dev/docs/memory-api/api-reference)
- [crewai-pastdotdev on PyPI](https://pypi.org/project/crewai-pastdotdev/)
````

### 2.2 Card: `docs/edge/en/tools/ai-ml/overview.mdx`

Add after the "Code Interpreter Tool" card, inside `<CardGroup cols={2}>`:

```mdx
  <Card title="past dev" icon="clock-rotate-left" href="/en/tools/ai-ml/pastdev">
    Keep crew memory in past dev and give agents Recall and Ingest tools.
  </Card>
```

### 2.3 Memory page: `docs/edge/en/concepts/memory.mdx`

In "## Storage Backend", add a third item after "**Custom backend**":

```mdx
- **Hosted memory API**: To keep memory in [past dev](https://past.dev) instead of a local store, pass `PastDevMemory` from the `crewai-pastdotdev` package as `memory=`. past dev does its own extraction, embedding and ranking. See the [past dev page](/en/tools/ai-ml/pastdev).
```

### 2.4 Navigation: `docs/docs.json`

In each language's "AI & Machine Learning" group, add the page after
`edge/<lang>/tools/ai-ml/e2bsandboxtools`:

```json
"edge/en/tools/ai-ml/pastdev"
"edge/ar/tools/ai-ml/pastdev"
"edge/ko/tools/ai-ml/pastdev"
"edge/pt-BR/tools/ai-ml/pastdev"
```

### 2.5 The other languages

Make `ar`, `ko` and `pt-BR` copies of 2.1, 2.2 and 2.3 with the process in
the CrewAI repository's `DOCS_TRANSLATIONS.md`: translate the prose and the
frontmatter values, keep the code blocks, identifiers and URLs, and change
internal links from `/en/` to `/ar/`, `/ko/` or `/pt-BR/`. Keep the product
name "past dev" and the operation names Ingest and Recall in English.
