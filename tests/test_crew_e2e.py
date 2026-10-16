"""Small crews, run end to end with a scripted LLM and the fake past dev API."""

from __future__ import annotations

from conftest import FakePast, ScriptedLLM
from crewai import Agent, Crew, Task

from crewai_pastdotdev import PastDevClient, PastDevMemory, PastDevRecallTool


def _crew(llm: ScriptedLLM, **kwargs: object) -> tuple[Crew, Task]:
    agent = Agent(
        role="Account manager",
        goal="Write the weekly report the way the customer wants it",
        backstory="You know the customer well.",
        llm=llm,
        tools=kwargs.pop("tools", []),
        max_iter=3,
    )
    task = Task(
        description="Write this week's report for Ada.",
        expected_output="A report in the format Ada prefers.",
        agent=agent,
    )
    return Crew(agents=[agent], tasks=[task], **kwargs), task


def test_crew_memory_recalls_before_the_task_and_ingests_the_result(
    client: PastDevClient, fake_past: FakePast
) -> None:
    llm = ScriptedLLM(model="scripted", replies=["Final Answer: Three short bullet points."])
    memory = PastDevMemory(identity="ada", client=client)
    crew, task = _crew(llm, memory=memory)

    result = crew.kickoff()
    memory.drain_writes()

    assert result.raw == "Three short bullet points."
    recall = fake_past.bodies("/api/v1/recall")[0]
    assert recall["query"] == task.description and recall["identity"] == "ada"
    assert "Ada prefers short weekly reports." in llm.prompts[0]

    ingest = fake_past.bodies("/api/v1/ingest")
    assert len(ingest) == 1
    assert ingest[0]["identity"] == "ada"
    assert "Write this week's report for Ada." in ingest[0]["content"]
    assert "Three short bullet points." in ingest[0]["content"]
    assert ingest[0]["metadata"] == {"crewai_agent_role": "Account manager"}


def test_an_agent_calls_the_recall_tool(client: PastDevClient, fake_past: FakePast) -> None:
    llm = ScriptedLLM(
        model="scripted",
        replies=[
            (
                "Thought: I should check what Ada prefers.\n"
                "Action: past_dev_recall\n"
                'Action Input: {"query": "Ada report preferences"}'
            ),
            "Thought: I know what Ada wants.\nFinal Answer: A short weekly report.",
        ],
    )
    crew, _ = _crew(llm, tools=[PastDevRecallTool(identity="ada", client=client)])

    result = crew.kickoff()

    assert result.raw == "A short weekly report."
    assert fake_past.bodies("/api/v1/recall") == [
        {"query": "Ada report preferences", "identity": "ada", "limit": 10}
    ]
    assert fake_past.bodies("/api/v1/ingest") == []
    assert "past dev recalled 2 memories" in llm.prompts[-1]


def test_an_agent_kickoff_uses_its_own_past_dev_memory(
    client: PastDevClient, fake_past: FakePast
) -> None:
    llm = ScriptedLLM(model="scripted", replies=["Final Answer: Short and weekly."])
    memory = PastDevMemory(identity="ada", client=client)
    agent = Agent(
        role="Assistant", goal="Answer about Ada", backstory="You help.", llm=llm, memory=memory
    )
    assert agent.memory is memory

    result = agent.kickoff("How does Ada like her reports?")
    memory.drain_writes()

    assert result.raw == "Short and weekly."
    assert fake_past.bodies("/api/v1/recall")[0]["identity"] == "ada"
    ingest = fake_past.bodies("/api/v1/ingest")
    assert len(ingest) == 1 and "Short and weekly." in ingest[0]["content"]
