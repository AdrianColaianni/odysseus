from src.action_intents import classify_tool_intent


def test_calendar_entry_request_promotes_to_agent():
    assert classify_tool_intent("Can you add an entry to my calendar?").needs_tools
    intent = classify_tool_intent("Can you add an entry to my calendar?")
    assert intent.needs_tools
    assert intent.category == "calendar"


def test_calendar_imperative_variants_promote_to_agent():
    assert classify_tool_intent("add lunch with Sam to my calendar tomorrow at noon").needs_tools
    assert classify_tool_intent("schedule a call with Mina next Friday").needs_tools
    assert classify_tool_intent("put dentist appointment on my calendar").needs_tools
    assert classify_tool_intent("Alright. Recreate that same appointment").needs_tools
    assert classify_tool_intent("delete that actually").needs_tools
    assert classify_tool_intent("Okay delete that doctor appointment from the calendar").needs_tools
    assert classify_tool_intent("have another go at adding a test entry to the calendar").needs_tools
    assert classify_tool_intent(
        "Okay so you should be able to create that calendar event for tomorrow at 1:30 p.m. right for me to go to the hardware store"
    ).needs_tools
    assert classify_tool_intent(
        "make it an appointment at 12pm for me to visit the doctor it's tomorrow the 2nd of June 2026"
    ).needs_tools


def test_calendar_read_requests_promote_to_agent():
    assert classify_tool_intent("What upcoming events do I have?").needs_tools
    assert classify_tool_intent("Can you show my next appointments?").needs_tools
    assert classify_tool_intent("Do I have upcoming Taekwondo classes this week?").needs_tools
    assert classify_tool_intent("What's on my calendar tomorrow?").needs_tools
    assert classify_tool_intent("When is my next meeting?").needs_tools


def test_note_todo_and_reminder_actions_promote_to_agent():
    assert classify_tool_intent("add milk to my todo list").needs_tools
    assert classify_tool_intent("take a note that the server needs checking").needs_tools
    assert classify_tool_intent("set a reminder to call Pat at 4pm").needs_tools


def test_email_and_ui_actions_promote_to_agent():
    assert classify_tool_intent("reply to that email").needs_tools
    assert classify_tool_intent("mark those emails as read").needs_tools
    assert classify_tool_intent("open my calendar").needs_tools
    assert classify_tool_intent("turn off web search").needs_tools


def test_research_action_promotes_to_agent():
    assert classify_tool_intent("research cost effective local models").needs_tools
    assert classify_tool_intent("can you look into GPU hosting options").needs_tools


def test_explicit_web_search_promotes_to_agent():
    assert classify_tool_intent("use web search and find a recipe for chocolate chip cookies").needs_tools
    assert classify_tool_intent("do a web search for the best chocolate chip cookies").needs_tools
    assert classify_tool_intent("search the web for current RTX 3090 prices").needs_tools
    assert classify_tool_intent("use web search and find a recipe").category == "web"


def test_chinese_web_lookup_requests_route_to_web_tools():
    intent = classify_tool_intent("帮我查一下这些店铺的地址，我要去打卡")

    assert intent.needs_tools
    assert intent.category == "web"


def test_nearest_place_lookup_promotes_to_web_agent():
    intent = classify_tool_intent("from vasaplan stockholm where is closest parking")
    assert intent.needs_tools
    assert intent.category == "web"


def test_workspace_agent_requests_promote_to_shell_workspace():
    prompts = [
        "fix the bug in this repo",
        "run the tests for this project",
        "debug the server logs",
        "run a performance benchmark on this project",
        "inspect the traceback and patch the code",
    ]
    for prompt in prompts:
        intent = classify_tool_intent(prompt)
        assert intent.needs_tools
        assert intent.category == "workspace"


def test_page_references_are_not_mistaken_for_named_computers():
    for prompt in (
        "What heading is visible on that page?",
        "Read it from the current page.",
        "Compare this with the same page.",
    ):
        intent = classify_tool_intent(prompt)
        assert intent.category != "workspace"

    intent = classify_tool_intent("check the service on odysseus")
    assert intent.needs_tools and intent.category == "workspace"


def test_direct_code_requests_promote_to_workspace_agent():
    prompts = [
        "write a Python function that parses CSV",
        "write answer.json",
        "create app.ts",
        "edit src/app.py",
        "Can you create a script in this project?",
        "edit the React component to show a loading state",
        "I want you to build a small command-line tool",
        "Can you code this in the repo?",
    ]
    for prompt in prompts:
        intent = classify_tool_intent(prompt)
        assert intent.needs_tools
        assert intent.category == "workspace"


def test_code_explanations_stay_plain_chat():
    assert not classify_tool_intent("How do I write a Python function?").needs_tools
    assert not classify_tool_intent("Can you explain how a React component works?").needs_tools


def test_shell_diagnostic_commands_promote_to_agent():
    prompts = [
        "lsblk",
        "run lsblk",
        "df -h",
        "docker ps",
        "nvidia-smi",
        "can you run journalctl -u odysseus",
    ]
    for prompt in prompts:
        intent = classify_tool_intent(prompt)
        assert intent.needs_tools
        assert intent.category in {"shell", "workspace"}


def test_shell_command_explanations_stay_plain_chat():
    assert not classify_tool_intent("How do I use lsblk?").needs_tools
    assert not classify_tool_intent("Can you explain docker ps?").needs_tools


def test_explanatory_calendar_questions_stay_plain_chat():
    assert not classify_tool_intent("How do I add an entry to my calendar?").needs_tools
    assert not classify_tool_intent("What about the built-in Odysseus calendar, is that linked to email?").needs_tools
    assert not classify_tool_intent("Can you explain how calendar reminders work?").needs_tools
    intent = classify_tool_intent("How do I add an entry to my calendar?")
    assert not intent.needs_tools
    assert intent.reason == "explanatory feature question"


def test_router_reports_non_calendar_categories():
    assert classify_tool_intent("reply to that email").category == "email"
    assert classify_tool_intent("open my calendar").category == "ui"
    assert classify_tool_intent("research cost effective local models").category == "research"
