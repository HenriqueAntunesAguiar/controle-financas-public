from dotenv import load_dotenv
from langgraph.types import Command

from financial_operation_agent import FinancialOperationAgent
from memory import create_thread_config, create_thread_id
from observability import flush_langfuse, observe_agent_run


def main() -> None:
    load_dotenv()
    agent = FinancialOperationAgent().as_agent()
    thread_id = create_thread_id()

    try:
        _run(agent, thread_id)
    finally:
        flush_langfuse()


def _run(agent, thread_id: str) -> None:
    while True:
        print("\n===to stop say 'stop'===\n")
        user_input = input("User: ").strip()

        if user_input.lower() == "stop":
            break

        with observe_agent_run(session_id=thread_id, trace_name="financial-operation-agent", metadata={"entrypoint": "test_run"}) as config:
            config.update(create_thread_config(thread_id))
            result = agent.invoke({"messages": [{"role": "user", "content": user_input}]}, config=config)

            while result.get("__interrupt__"):
                interrupt = result["__interrupt__"][0]
                action = interrupt.value["action_requests"][0]
                print("\n", action["description"], "\n")
                decision = input("Type 'approve' or 'reject': ").strip().lower()
                while decision not in {"approve", "reject"}:
                    decision = input("Type 'approve' or 'reject': ").strip().lower()
                review = {"type": decision}
                if decision == "reject":
                    review["message"] = "Operation rejected by the user."
                result = agent.invoke(Command(resume={interrupt.id: {"decisions": [review]}}), config=config)
        print("AI:", result["messages"][-1].content, "\n")


if __name__ == "__main__":
    main()
