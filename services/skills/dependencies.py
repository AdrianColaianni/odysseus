"""Explicit collaborators for execution and audit coordination.

Services never import the skills transport module or copy credentials into a
second state store.
"""
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class AuditDependencies:
    test_jobs: dict
    audit_jobs: dict
    test_task: Callable
    test_messages: Callable
    baseline_messages: Callable
    evaluate_run: Callable
    evaluate_necessity: Callable
    evaluate_retrieval_precision: Callable
    should_check_retrieval_precision: Callable
    improve_markdown: Callable
    apply_markdown: Callable
    duplicate_blocker: Callable
    finalize_status: Callable
    finalize_batch: Callable
    auto_publish_policy: Callable
    utility_blocker: Callable
    verdict_efficiency: Callable
    run_test_job: Callable
    run_arm: Callable
    run_test_once: Callable
    audit_one: Callable
    run_batch: Callable
    resolve_models: Callable


def default_dependencies() -> AuditDependencies:
    """Wire the service implementations, read at call time so a patched one is used."""
    from services.skills import (
        agent_runner, audit_workflow, evaluation, model_selection, prompts, publication,
    )

    def with_deps(function):
        return lambda *args, **kwargs: function(*args, **kwargs, deps=deps)

    deps = AuditDependencies(
        test_jobs=agent_runner._skill_test_jobs,
        audit_jobs=audit_workflow._skill_audit_jobs,
        test_task=prompts._skill_test_task,
        test_messages=prompts._skill_test_messages,
        baseline_messages=prompts._skill_baseline_messages,
        evaluate_run=evaluation.evaluate_run,
        evaluate_necessity=evaluation.evaluate_necessity,
        evaluate_retrieval_precision=evaluation.evaluate_retrieval_precision,
        should_check_retrieval_precision=evaluation.should_check_retrieval_precision,
        improve_markdown=evaluation.improve_markdown,
        apply_markdown=publication.apply_markdown,
        duplicate_blocker=publication.duplicate_blocker,
        finalize_status=with_deps(publication.finalize_status),
        finalize_batch=with_deps(publication.finalize_batch),
        auto_publish_policy=publication.auto_publish_policy,
        utility_blocker=publication.utility_blocker,
        verdict_efficiency=evaluation.verdict_efficiency,
        run_test_job=with_deps(agent_runner.run_test_job),
        run_arm=agent_runner.run_audit_arm,
        run_test_once=with_deps(agent_runner.run_test_once),
        audit_one=with_deps(audit_workflow.audit_one_skill),
        run_batch=with_deps(audit_workflow.run_audit_batch),
        resolve_models=model_selection.resolve_audit_models,
    )
    return deps
