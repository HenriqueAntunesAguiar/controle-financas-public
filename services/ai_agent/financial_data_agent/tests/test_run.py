from dotenv import load_dotenv
from financial_data_agent import FinancialDataAgent
from memory import create_thread_config, create_thread_id
from observability import flush_langfuse, observe_agent_run

load_dotenv()

agent = FinancialDataAgent().as_agent()
thread_id = create_thread_id()
try:

    while True:

        print("\n===to stop say 'stop'===\n")
        user_input = input("User: ").strip()

        if user_input.lower() == "stop":
            break

        with observe_agent_run(session_id=thread_id, metadata={"entrypoint": "test_run"} ) as config:
            config.update(create_thread_config(thread_id))
            result = agent.invoke({"messages": [{"role": "user", "content": user_input}]}, config=config)

        print('AI:', result["messages"][-1].content, '\n')

finally:
    flush_langfuse()
