"""The service for managing and interacting with robots."""

from io import BytesIO
from typing import TYPE_CHECKING

import destiny_sdk
import httpx
from fastapi import status
from pydantic import UUID4, HttpUrl, TypeAdapter, ValidationError

from app.core.config import get_settings
from app.core.exceptions import (
    RobotEnhancementError,
    RobotUnreachableError,
    SQLDuplicateError,
    SQLNotFoundError,
)
from app.domain.references.models.models import (
    BatchEnhancementRequest,
    BatchEnhancementRequestStatus,
    Enhancement,
    EnhancementRequest,
    Reference,
)
from app.domain.robots.models import RobotConfig, Robots
from app.domain.service import GenericService
from app.persistence.blob.models import (
    BlobStorageFile,
)
from app.persistence.blob.service import (
    get_file_from_blob_storage,
    get_signed_url,
    upload_file_to_blob_storage,
)
from app.persistence.sql.uow import AsyncSqlUnitOfWork, unit_of_work

if TYPE_CHECKING:
    from app.domain.references.enhancement_service import EnhancementService
    from app.domain.references.reference_service import ReferenceService


MIN_FOR_5XX_STATUS_CODES = 500

settings = get_settings()


class RobotService(GenericService):
    """The service which manages interacting with robots."""

    def __init__(self, sql_uow: AsyncSqlUnitOfWork, robots: Robots) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(sql_uow)
        self.robots = robots

    def get_robot_url(self, robot_id: UUID4) -> HttpUrl:
        """Get the url for a given robot id."""
        return self.robots.get_robot_url(robot_id)

    def get_robot_config(self, robot_id: UUID4) -> RobotConfig:
        """Get the config for a given robot id."""
        return self.robots.get_robot_config(robot_id)

    async def send_enhancement_request_to_robot(
        self,
        robot_url: str,
        robot_id: UUID4,
        robot_request: destiny_sdk.robots.RobotRequest
        | destiny_sdk.robots.BatchRobotRequest,
    ) -> httpx.Response:
        """Send a request to a robot, handling error cases."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    robot_url, json=robot_request.model_dump(mode="json")
                )
        except httpx.RequestError as exception:
            error = f"Cannot request enhancement from Robot {robot_id}."
            raise RobotUnreachableError(error) from exception

        if response.status_code != status.HTTP_202_ACCEPTED:
            if response.status_code >= MIN_FOR_5XX_STATUS_CODES:
                error = f"Cannot request enhancement from Robot {robot_id}."
                raise RobotUnreachableError(error)
            # Expect this is a 4xx
            raise RobotEnhancementError(detail=response.text)

        return response

    async def request_enhancement_from_robot(
        self,
        robot_url: HttpUrl,
        enhancement_request: EnhancementRequest,
        reference: Reference,
    ) -> httpx.Response:
        """Request an enhancement from a robot."""
        robot_request = destiny_sdk.robots.RobotRequest(
            id=enhancement_request.id,
            reference=destiny_sdk.references.Reference(**reference.model_dump()),
            extra_fields=enhancement_request.enhancement_parameters,
        )

        return await self.send_enhancement_request_to_robot(
            robot_url=str(robot_url).rstrip("/") + "single/",
            robot_id=enhancement_request.robot_id,
            robot_request=robot_request,
        )

    @unit_of_work
    async def collect_and_dispatch_references_for_batch_enhancement(
        self,
        batch_enhancement_request: BatchEnhancementRequest,
        reference_service: "ReferenceService",
    ) -> None:
        """Collect and dispatch references for batch enhancement."""
        robot = self.get_robot_config(batch_enhancement_request.robot_id)
        references = await reference_service.get_hydrated_references(
            batch_enhancement_request.reference_ids,
            enhancement_types=robot.dependent_enhancements,
            external_identifier_types=robot.dependent_identifiers,
        )
        # Build jsonl file data using SDK model
        jsonl_data = "\n".join(
            reference.to_sdk().to_jsonl() for reference in references
        ).encode("utf-8")
        file = await upload_file_to_blob_storage(
            content=BytesIO(jsonl_data),
            path="batch_enhancement_request_reference_data",
            filename=f"{batch_enhancement_request.id}.jsonl",
        )

        batch_enhancement_request.reference_data_file = file
        batch_enhancement_request.result_file = BlobStorageFile(
            location=settings.default_blob_location,
            container=settings.default_blob_container,
            path="batch_enhancement_result",
            filename=f"{batch_enhancement_request.id}.jsonl",
        )

        robot_request = batch_enhancement_request.to_batch_robot_request_sdk(
            get_signed_url
        )

        await self.sql_uow.batch_enhancement_requests.update_by_pk(
            batch_enhancement_request.id,
            reference_data_file=batch_enhancement_request.reference_data_file.to_sql(),
            result_file=batch_enhancement_request.result_file.to_sql(),
        )

        try:
            await self.send_enhancement_request_to_robot(
                robot_url=str(robot.robot_url).rstrip("/") + "batch/",
                robot_id=batch_enhancement_request.robot_id,
                robot_request=robot_request,
            )
        except RobotUnreachableError as exception:
            await self.sql_uow.batch_enhancement_requests.update_by_pk(
                batch_enhancement_request.id,
                request_status=BatchEnhancementRequestStatus.FAILED,
                error=exception.detail,
            )
        except RobotEnhancementError as exception:
            await self.sql_uow.batch_enhancement_requests.update_by_pk(
                batch_enhancement_request.id,
                request_status=BatchEnhancementRequestStatus.REJECTED,
                error=exception.detail,
            )
        else:
            await self.sql_uow.batch_enhancement_requests.update_by_pk(
                batch_enhancement_request.id,
                request_status=BatchEnhancementRequestStatus.ACCEPTED,
            )

    async def handle_import_batch_enhancement_result_entry(
        self,
        file_entry: destiny_sdk.robots.BatchEnhancementResultEntry,
        enhancement_service: "EnhancementService",
    ) -> tuple[bool, str]:
        """Handle the import of a single batch enhancement result entry."""
        if isinstance(file_entry, destiny_sdk.robots.LinkedRobotError):
            return (
                False,
                f"""
Reference {file_entry.reference_id}: {file_entry.message}
""",
            )

        try:
            await enhancement_service.add_enhancement(Enhancement.from_sdk(file_entry))
        except SQLNotFoundError:
            return (
                False,
                f"""
Reference {file_entry.reference_id}: Reference doesn't exist.
""",
            )
        except SQLDuplicateError:
            return (
                False,
                f"""
Reference {file_entry.reference_id}: Enhancement already exists.
""",
            )

        return (
            True,
            f"""
Reference {file_entry.reference_id}: Enhancement added.
""",
        )

    async def validate_and_import_batch_enhancement_result(
        self,
        batch_enhancement_request: BatchEnhancementRequest,
        enhancement_service: "EnhancementService",
    ) -> None:
        """Validate and import the result of a batch enhancement request."""
        if not batch_enhancement_request.result_file:
            msg = """
Batch enhancement request has no result file location. This should not happen.
"""
            raise RuntimeError(msg)
        content = await get_file_from_blob_storage(
            batch_enhancement_request.result_file
        )
        json_content = content.decode("utf-8").split("\n")

        file_entry_validator: TypeAdapter[
            destiny_sdk.robots.BatchEnhancementResultEntry
        ] = TypeAdapter(destiny_sdk.robots.BatchEnhancementResultEntry)
        successes: list[str] = []
        failures: list[str] = []
        reference_ids: set[UUID4] = set()

        for entry_ref, entry in enumerate(json_content):
            try:
                file_entry = file_entry_validator.validate_json(entry)
            except ValidationError as exception:
                failures.append(f"""
Entry {entry_ref} could not be parsed: {exception}.
    """)
                continue

            if file_entry.reference_id not in batch_enhancement_request.reference_ids:
                failures.append(f"""
Reference {file_entry.reference_id}: not in batch enhancement request.
""")
                continue

            reference_ids.add(file_entry.reference_id)

            success, msg = await self.handle_import_batch_enhancement_result_entry(
                file_entry, enhancement_service
            )
            if success:
                successes.append(msg)
            else:
                failures.append(msg)

        if missing_references := (
            set(batch_enhancement_request.reference_ids) - reference_ids
        ):
            failures.extend(
                f"""
Reference {missing_reference}: not in batch enhancement result from robot.
"""
                for missing_reference in missing_references
            )

        if not failures:
            enhancement_service.update_batch_enhancement_request_status(
                batch_enhancement_request.id,
                BatchEnhancementRequestStatus.PARTIAL_FAILED,
            )
        elif not successes:
            enhancement_service.mark_batch_enhancement_request_failed(
                batch_enhancement_request.id,
                "Result received but every enhancement failed.",
            )
        else:
            enhancement_service.update_batch_enhancement_request_status(
                batch_enhancement_request.id,
                BatchEnhancementRequestStatus.COMPLETED,
            )

        validation_result_file_content = "\n".join([*successes, *failures]).encode(
            "utf-8"
        )
        validation_result_file = await upload_file_to_blob_storage(
            content=BytesIO(validation_result_file_content),
            path="batch_enhancement_result_result",
            filename=f"{batch_enhancement_request.id}.txt",
        )
        await self.sql_uow.batch_enhancement_requests.update_by_pk(
            batch_enhancement_request.id,
            result_data_file=validation_result_file.to_sql(),
        )
