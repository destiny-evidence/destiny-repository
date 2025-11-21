"""
Generic scheduled-job runner.

This module provides a CLI entry point that dynamically imports a Taskiq task
by path (module:task_name) and enqueues it using the task's .kiq() helper.

Usage (example):
  python -m app.scheduled_tasks.run_task app.tasks:my_task
"""

import argparse
import asyncio
import importlib

from app.core.telemetry.logger import get_logger

logger = get_logger(__name__)


async def run_task(task_path: str) -> None:
    """
    Import and enqueue a task by its module:callable path.

    Args:
        task_path: Import path in the format `module.path:callable_name`.

    """
    if ":" not in task_path:
        logger.error("Task path must be 'module:callable', got: %s", task_path)
        raise SystemExit(2)

    module_path, task_name = task_path.rsplit(":", 1)

    try:
        module = importlib.import_module(module_path)
    except Exception:
        logger.exception("Failed to import module %s", module_path)
        raise

    if not hasattr(module, task_name):
        logger.error("Module %s has no attribute %s", module_path, task_name)
        raise SystemExit(2)

    task = getattr(module, task_name)

    # Expect task to be a Taskiq-decorated callable exposing .kiq()
    if not hasattr(task, "kiq"):
        logger.error(
            "Task %s does not expose .kiq() - is it decorated?",
            task_path,
        )
        raise SystemExit(2)

    logger.info("Enqueueing task %s", task_path)

    await task.kiq()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for task runner."""
    parser = argparse.ArgumentParser(
        description="Enqueue a Taskiq task by module:callable path"
    )
    parser.add_argument("task", help="Task to run, e.g. 'app.module.tasks:my_task'")

    ns = parser.parse_args(argv)

    try:
        asyncio.run(run_task(ns.task))
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 1
    except Exception:
        logger.exception("Error running task %s", ns.task)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
