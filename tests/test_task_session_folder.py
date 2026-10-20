"""Task sessions must be assigned folder='Tasks' at creation time."""
from src.task_scheduler import TaskScheduler


def test_llm_and_action_task_sessions_are_created_in_tasks_folder():
    """_execute_llm_task and _deliver_task_result both create sessions through this helper."""
    from types import SimpleNamespace
    added = []
    db = SimpleNamespace(add=added.append, commit=lambda: None)
    task = SimpleNamespace(id="t1", name="Digest", owner="alice", session_id=None)
    scheduler = TaskScheduler.__new__(TaskScheduler)
    scheduler._session_manager = None
    session_id = scheduler._ensure_task_session(task, db, "http://local.test/v1", "m")
    assert added[0].folder == "Tasks"
    assert task.session_id == session_id

