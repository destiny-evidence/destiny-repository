"""Generate fake data for testing purposes."""  # noqa: INP001

import argparse
from pathlib import Path

from destiny_sdk.enhancements import (
    Annotation,
    AnnotationEnhancement,
    BibliographicMetadataEnhancement,
    BooleanAnnotation,
    EnhancementFileInput,
    EnhancementType,
)
from destiny_sdk.identifiers import (
    DOIIdentifier,
    ExternalIdentifier,
    ExternalIdentifierType,
)
from destiny_sdk.visibility import Visibility
from faker import Faker
from pydantic import BaseModel

fa = Faker()


class FakeReferenceForImport(BaseModel):
    """A fake reference for import with identifiers and enhancements."""

    visibility: Visibility = Visibility.PUBLIC
    identifiers: list[ExternalIdentifier]
    enhancements: list[EnhancementFileInput]


def generate_fake_annotations() -> list[Annotation]:
    """
    Generate a list of fake annotations for a reference.

    :return: A list of Annotation instances.
    """
    return [
        BooleanAnnotation(
            scheme="ring",
            value=fa.boolean(),
            label=word,
            score=fa.pyfloat(left_digits=0, right_digits=2, positive=True),
            data={},
        )
        for word in ["earth", "fire", "wind", "water", "heart"]
    ]


def generate_fake_enhancements() -> list[EnhancementFileInput]:
    """
    Generate a list of fake enhancements for a reference.

    :return: A list of Enhancement instances.
    """
    return [
        EnhancementFileInput(
            enhancement_type=EnhancementType.BIBLIOGRAPHIC,
            source="Fake",
            visibility=Visibility.PUBLIC,
            processor_version="fake v1",
            content=BibliographicMetadataEnhancement(
                title=fa.sentence(),
            ),
        ),
        EnhancementFileInput(
            enhancement_type=EnhancementType.ANNOTATION,
            source="Fake",
            visibility=Visibility.PUBLIC,
            processor_version="fake v1",
            content=AnnotationEnhancement(annotations=generate_fake_annotations()),
        ),
    ]


def generate_fake_reference_for_import() -> FakeReferenceForImport:
    """
    Generate a fake reference for import with the given identifiers and enhancements.

    :return: An instance of FakeReferenceForImport.
    """
    return FakeReferenceForImport(
        identifiers=[
            DOIIdentifier(
                identifier_type=ExternalIdentifierType.DOI, identifier=fa.doi()
            )
        ],
        enhancements=generate_fake_enhancements(),
    )


def main() -> None:
    """Generate fake references and write them to a file."""
    parser = argparse.ArgumentParser(description="Generate fake references")
    parser.add_argument(
        "--count",
        "-c",
        type=int,
        default=1000,
        help="Number of fake references to generate",
    )
    parser.add_argument(
        "--output", "-o", type=str, required=True, help="Output filename"
    )
    args = parser.parse_args()
    with Path(args.output).open("w") as f:
        for _ in range(args.count):
            fake_ref = generate_fake_reference_for_import()
            f.write(fake_ref.model_dump_json() + "\n")


if __name__ == "__main__":
    main()
