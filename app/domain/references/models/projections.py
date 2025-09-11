"""Projection functions for reference domain data."""

import destiny_sdk

from app.core.exceptions import ProjectionError
from app.domain.base import GenericProjection
from app.domain.references.models.models import (
    CandidateDuplicateSearchFields,
    EnhancementType,
    Reference,
)


class CandidateDuplicateSearchFieldsProjection(
    GenericProjection[CandidateDuplicateSearchFields]
):
    """Projection functions for candidate selection used in duplicate detection."""

    @classmethod
    def get_from_reference(
        cls,
        reference: Reference,
    ) -> CandidateDuplicateSearchFields:
        """Get the candidate duplicate search fields from a reference."""
        try:
            title, publication_year = None, None
            authorship: list[destiny_sdk.enhancements.Authorship] = []
            for enhancement in reference.enhancements or []:
                # NB at present we have no way of discriminating between multiple
                # bibliographic enhancements, nor are they ordered. This takes a
                # random one (but hydrates in the case of one bibliographic enhancement
                # missing a field while the other has it present).
                if (
                    enhancement.content.enhancement_type
                    == EnhancementType.BIBLIOGRAPHIC
                ):
                    # Hydrate if exists on enhancement, otherwise use prior value
                    title = enhancement.content.title or title
                    authorship = enhancement.content.authorship or authorship
                    publication_year = (
                        enhancement.content.publication_year
                        or (
                            enhancement.content.publication_date.year
                            if enhancement.content.publication_date
                            else None
                        )
                        or publication_year
                    )

            # Author normalization:
            # Maintain first and last author, sort middle authors by name
            authorship = sorted(
                authorship,
                key=lambda author: (
                    {
                        destiny_sdk.enhancements.AuthorPosition.FIRST: -1,
                        destiny_sdk.enhancements.AuthorPosition.LAST: 1,
                    }.get(author.position, 0),
                    author.display_name.strip(),
                ),
            )

            if title:
                title = title.strip()

        except Exception as exc:
            msg = "Failed to project CandidateDuplicateSearchFields from Reference"
            raise ProjectionError(msg) from exc

        return CandidateDuplicateSearchFields(
            title=title,
            authors=[author.display_name.strip() for author in authorship],
            publication_year=publication_year,
        )
