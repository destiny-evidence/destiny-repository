"""The service for managing and interacting with robots."""

import destiny_sdk
import httpx
from fastapi import status
from pydantic import UUID4, HttpUrl

from app.core.exceptions import RobotEnhancementError, RobotUnreachableError
from app.domain.references.enhancement_service import EnhancementService
from app.domain.references.models.models import (
    BatchEnhancementRequest,
    BatchEnhancementRequestStatus,
    EnhancementRequest,
    Reference,
)
from app.domain.references.reference_service import ReferenceService
from app.domain.robots.models import RobotConfig, Robots
from app.domain.service import GenericService
from app.persistence.blob.models import (
    BlobSignedUrlType,
    BlobStorageFile,
)
from app.persistence.blob.service import upload_file_to_blob_storage
from app.persistence.sql.uow import AsyncSqlUnitOfWork, unit_of_work

MIN_FOR_5XX_STATUS_CODES = 500


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
            robot_url=str(robot_url),
            robot_id=enhancement_request.robot_id,
            robot_request=robot_request,
        )

    @unit_of_work
    async def collect_and_dispatch_references_for_batch_enhancement(
        self,
        batch_enhancement_request: BatchEnhancementRequest,
        reference_service: ReferenceService,
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
            file=jsonl_data,
            path="batch_enhancement_request_reference_data",
            filename=f"{batch_enhancement_request.id}.jsonl",
        )

        await self.sql_uow.batch_enhancement_requests.update_by_pk(
            batch_enhancement_request.id,
            reference_data_file=file.to_sql(),
        )

        robot_request = destiny_sdk.robots.BatchRobotRequest(
            id=batch_enhancement_request.id,
            reference_storage_url=file.to_signed_url(BlobSignedUrlType.DOWNLOAD),
            result_storage_url=BlobStorageFile(
                path="batch_enhancement_result",
                filename=f"{batch_enhancement_request.id}.jsonl",
            ).to_signed_url(BlobSignedUrlType.UPLOAD),
            extra_fields=batch_enhancement_request.enhancement_parameters,
        )
        try:
            await self.send_enhancement_request_to_robot(
                robot_url=str(robot.robot_url),
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

    async def validate_and_import_batch_enhancement_result(
        self,
        batch_enhancement_request: BatchEnhancementRequest,
        enhancement_service: EnhancementService,
    ) -> None:
        """Validate and import the result of a batch enhancement request."""
