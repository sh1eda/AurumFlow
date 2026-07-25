from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from openai_codex import Codex, Sandbox


ROOT = Path(__file__).resolve().parents[1]
BACKLOG = ROOT / "tasks" / "backlog"
ACTIVE = ROOT / "tasks" / "active"
COMPLETED = ROOT / "tasks" / "completed"
FAILED = ROOT / "tasks" / "failed"
REPORTS = ROOT / "reports" / "agent-runs"


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0


def run_command(command: str) -> CommandResult:
    process = subprocess.run(
        command,
        cwd=ROOT,
        shell=True,
        text=True,
        capture_output=True,
        timeout=3600,
    )

    return CommandResult(
        command=command,
        returncode=process.returncode,
        stdout=process.stdout,
        stderr=process.stderr,
    )


def ensure_clean_worktree() -> None:
    result = run_command("git status --porcelain")

    if not result.passed:
        raise RuntimeError(result.stderr)

    if result.stdout.strip():
        raise RuntimeError(
            "Working tree clean değil. Agent çalıştırılmadan önce "
            "mevcut değişiklikleri commit veya stash yap."
        )


def load_next_task() -> tuple[Path, dict[str, Any]]:
    tasks = sorted(BACKLOG.glob("*.yaml"))

    if not tasks:
        raise RuntimeError("Backlog içinde görev bulunamadı.")

    task_path = tasks[0]

    with task_path.open("r", encoding="utf-8") as file:
        task = yaml.safe_load(file)

    return task_path, task


def build_implementation_prompt(task: dict[str, Any]) -> str:
    return f"""
You are the implementer for the XAUUSD trading AI repository.

Follow AGENTS.md and all repository instructions.

Task:

{yaml.safe_dump(task, sort_keys=False)}

Requirements:

1. Inspect the repository before editing.
2. Make only the smallest required changes.
3. Respect allowed_paths and forbidden_paths.
4. Do not commit, push, merge, trade or access broker systems.
5. Run relevant focused tests.
6. Finish with a structured implementation report.
"""


def build_review_prompt(task: dict[str, Any]) -> str:
    return f"""
Act as an independent senior reviewer.

Review the current uncommitted diff against this task:

{yaml.safe_dump(task, sort_keys=False)}

Do not modify any files.

Check:

- Acceptance criteria
- Look-ahead bias
- Data leakage
- Dataset mutation
- Production behavior changes
- Missing tests
- Weak assertions
- Unsafe file access
- Unrequested scope expansion

End with exactly one verdict:

VERDICT: PASS

or

VERDICT: FAIL
"""


def path_is_allowed(path: str, task: dict[str, Any]) -> bool:
    normalized = path.strip()

    forbidden = task.get("forbidden_paths", [])
    allowed = task.get("allowed_paths", [])

    if any(normalized.startswith(item) for item in forbidden):
        return False

    if allowed and not any(normalized.startswith(item) for item in allowed):
        return False

    return True


def validate_changed_paths(task: dict[str, Any]) -> tuple[bool, list[str]]:
    result = run_command("git diff --name-only")
    changed = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    invalid = [path for path in changed if not path_is_allowed(path, task)]
    return not invalid, invalid


def save_report(task_id: str, payload: dict[str, Any]) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = REPORTS / f"{task_id}-{timestamp}.json"

    report_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return report_path


def move_task(source: Path, target_directory: Path) -> Path:
    target_directory.mkdir(parents=True, exist_ok=True)
    target = target_directory / source.name
    shutil.move(str(source), str(target))
    return target


def main() -> int:
    ensure_clean_worktree()

    task_path, task = load_next_task()
    task_id = task["id"]
    active_path = move_task(task_path, ACTIVE)

    iterations: list[dict[str, Any]] = []
    max_iterations = int(task.get("max_iterations", 3))

    try:
        with Codex() as codex:
            thread = codex.thread_start(
                sandbox=Sandbox.workspace_write,
            )

            for iteration_number in range(1, max_iterations + 1):
                implementation = thread.run(
                    build_implementation_prompt(task),
                    sandbox=Sandbox.workspace_write,
                )

                paths_ok, invalid_paths = validate_changed_paths(task)

                command_results = [
                    run_command(command)
                    for command in task.get("validation_commands", [])
                ]

                tests_ok = all(result.passed for result in command_results)

                review = thread.run(
                    build_review_prompt(task),
                    sandbox=Sandbox.read_only,
                )

                reviewer_passed = "VERDICT: PASS" in review.final_response

                iteration = {
                    "iteration": iteration_number,
                    "implementation_response": implementation.final_response,
                    "changed_paths_valid": paths_ok,
                    "invalid_paths": invalid_paths,
                    "validation": [
                        {
                            "command": result.command,
                            "returncode": result.returncode,
                            "stdout": result.stdout,
                            "stderr": result.stderr,
                        }
                        for result in command_results
                    ],
                    "review_response": review.final_response,
                    "reviewer_passed": reviewer_passed,
                }

                iterations.append(iteration)

                if paths_ok and tests_ok and reviewer_passed:
                    report_path = save_report(
                        task_id,
                        {
                            "task": task,
                            "status": "ready_for_human_review",
                            "iterations": iterations,
                        },
                    )

                    move_task(active_path, COMPLETED)

                    print(f"PASS: {task_id}")
                    print(f"Report: {report_path}")
                    print("Changes are ready for human review.")
                    return 0

                correction_prompt = f"""
The previous attempt did not pass validation.

Invalid paths:
{invalid_paths}

Validation failures:
{[
    {
        "command": result.command,
        "returncode": result.returncode,
        "stderr": result.stderr[-3000:],
    }
    for result in command_results
    if not result.passed
]}

Reviewer response:
{review.final_response}

Fix only the identified failures. Do not broaden the scope.
"""

                thread.run(
                    correction_prompt,
                    sandbox=Sandbox.workspace_write,
                )

        report_path = save_report(
            task_id,
            {
                "task": task,
                "status": "failed",
                "iterations": iterations,
            },
        )

        move_task(active_path, FAILED)
        print(f"FAIL: Maximum iterations reached. Report: {report_path}")
        return 1

    except Exception as exc:
        save_report(
            task_id,
            {
                "task": task,
                "status": "error",
                "error": repr(exc),
                "iterations": iterations,
            },
        )

        if active_path.exists():
            move_task(active_path, FAILED)

        raise


if __name__ == "__main__":
    sys.exit(main())