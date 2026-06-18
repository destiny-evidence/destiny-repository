"""
Regression tests: every app entry point closes every persistence layer on shutdown.

If any of ``db_manager.close``, ``es_manager.close``, or
``close_blob_clients`` is dropped from main.py's FastAPI lifespan,
tasks.py's WORKER_SHUTDOWN handler, or run_task.py's finally block,
that layer leaks past process teardown (connections / aiohttp sessions
/ aio credentials). These tests drive each shutdown path with mocked
dependencies and assert every close was awaited.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.main as main_module
import app.run_task as run_task_module
import app.tasks as tasks_module


@pytest.mark.asyncio
async def test_main_lifespan_closes_every_persistence_layer() -> None:
    """FastAPI lifespan shutdown awaits db, es, and blob closes."""
    with (
        patch.object(main_module.db_manager, "init"),
        patch.object(main_module.db_manager, "close", new=AsyncMock()) as db_close,
        patch.object(main_module.es_manager, "init", new=AsyncMock()),
        patch.object(main_module.es_manager, "close", new=AsyncMock()) as es_close,
        patch.object(main_module.broker, "startup", new=AsyncMock()),
        patch.object(main_module.broker, "shutdown", new=AsyncMock()),
        patch.object(main_module, "close_blob_clients", new=AsyncMock()) as blob_close,
    ):
        async with main_module.lifespan(MagicMock()):
            pass

    db_close.assert_awaited_once()
    es_close.assert_awaited_once()
    blob_close.assert_awaited_once()


@pytest.mark.asyncio
async def test_tasks_worker_shutdown_closes_every_persistence_layer() -> None:
    """taskiq WORKER_SHUTDOWN handler awaits db, es, and blob closes."""
    with (
        patch.object(tasks_module.db_manager, "close", new=AsyncMock()) as db_close,
        patch.object(tasks_module.es_manager, "close", new=AsyncMock()) as es_close,
        patch.object(tasks_module, "close_blob_clients", new=AsyncMock()) as blob_close,
    ):
        await tasks_module.shutdown(MagicMock())

    db_close.assert_awaited_once()
    es_close.assert_awaited_once()
    blob_close.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_task_closes_every_persistence_layer() -> None:
    """run_task() awaits db, es, and blob closes in its finally block."""
    fake_module = MagicMock()
    fake_module.do_thing = AsyncMock()

    with (
        patch.object(
            run_task_module.importlib, "import_module", return_value=fake_module
        ),
        patch.object(run_task_module.db_manager, "init"),
        patch.object(run_task_module.db_manager, "close", new=AsyncMock()) as db_close,
        patch.object(run_task_module.es_manager, "init", new=AsyncMock()),
        patch.object(run_task_module.es_manager, "close", new=AsyncMock()) as es_close,
        patch.object(
            run_task_module, "close_blob_clients", new=AsyncMock()
        ) as blob_close,
    ):
        await run_task_module.run_task("fake.module:do_thing")

    db_close.assert_awaited_once()
    es_close.assert_awaited_once()
    blob_close.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_task_closes_every_persistence_layer_when_task_raises() -> None:
    """The finally block closes every layer even if the task raises."""
    fake_module = MagicMock()
    fake_module.do_thing = AsyncMock(side_effect=RuntimeError("boom"))

    with (
        patch.object(
            run_task_module.importlib, "import_module", return_value=fake_module
        ),
        patch.object(run_task_module.db_manager, "init"),
        patch.object(run_task_module.db_manager, "close", new=AsyncMock()) as db_close,
        patch.object(run_task_module.es_manager, "init", new=AsyncMock()),
        patch.object(run_task_module.es_manager, "close", new=AsyncMock()) as es_close,
        patch.object(
            run_task_module, "close_blob_clients", new=AsyncMock()
        ) as blob_close,
        pytest.raises(RuntimeError, match="boom"),
    ):
        await run_task_module.run_task("fake.module:do_thing")

    db_close.assert_awaited_once()
    es_close.assert_awaited_once()
    blob_close.assert_awaited_once()
