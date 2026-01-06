"""
Generic job runner.

This module provides a CLI entry point that dynamically imports a task
by path (module:task_name) and executes it.

Usage (example):
  python -m app.run_task app.tasks:my_task
"""

import argparse
import asyncio
import importlib

from app.core.config import get_settings
from app.core.telemetry.logger import get_logger, logger_configurer
from app.core.telemetry.otel import configure_otel
from app.persistence.es.client import es_manager
from app.persistence.sql.session import db_manager

logger = get_logger(__name__)
settings = get_settings()
logger_configurer.configure_console_logger(
    log_level=settings.log_level, rich_rendering=settings.running_locally
)

if settings.otel_config and settings.otel_enabled:
    configure_otel(
        settings.otel_config,
        settings.app_name,
        settings.toml.app_version,
        settings.env,
        settings.trace_repr,
    )


async def run_task(task_path: str) -> None:
    """
    Import and execute a task directly by its module:callable path.

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

    if not callable(task):
        logger.error("Task %s is not callable", task_path)
        raise SystemExit(2)

    logger.info("Initializing resources")
    db_manager.init(settings.db_config, settings.app_name)
    await es_manager.init(settings.es_config)

    try:
        logger.info("Executing task %s", task_path)
        result = task()

        if asyncio.iscoroutine(result):
            await result
    finally:
        logger.info("Cleaning up resources")
        await db_manager.close()
        await es_manager.close()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for task runner."""
    parser = argparse.ArgumentParser(
        description="Run a specified task by its module:path"
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
