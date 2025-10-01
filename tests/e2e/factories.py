# ruff: noqa: S311 D101 D102 D106
"""Factories for creating test domain models."""

import random
import uuid

import factory
from destiny_sdk.enhancements import (
    AbstractContentEnhancement,
    AbstractProcessType,
    AnnotationEnhancement,
    AnnotationType,
    AuthorPosition,
    Authorship,
    BibliographicMetadataEnhancement,
    BooleanAnnotation,
    DriverVersion,
    EnhancementType,
    Location,
    LocationEnhancement,
    ScoreAnnotation,
)
from destiny_sdk.identifiers import (
    DOIIdentifier,
    OpenAlexIdentifier,
    OtherIdentifier,
    PubMedIdentifier,
)
from faker import Faker

from app.domain.references.models.models import (
    Enhancement,
    LinkedExternalIdentifier,
    Reference,
    Visibility,
)
from app.domain.robots.models.models import Robot

fake = Faker()
max_list_length = 3


class DOIIdentifierFactory(factory.Factory):
    class Meta:
        model = DOIIdentifier

    identifier = factory.Faker("doi")


class PubMedIdentifierFactory(factory.Factory):
    class Meta:
        model = PubMedIdentifier

    identifier = factory.Faker("pyint", min_value=100000, max_value=999999)


class OpenAlexIdentifierFactory(factory.Factory):
    class Meta:
        model = OpenAlexIdentifier

    identifier = factory.LazyFunction(
        lambda: f"W{fake.pyint(min_value=1000000, max_value=9999999)}"
    )


class OtherIdentifierFactory(factory.Factory):
    class Meta:
        model = OtherIdentifier

    identifier = factory.Faker("word")
    other_identifier_name = factory.Faker("company")


class BibliographicMetadataEnhancementFactory(factory.Factory):
    class Meta:
        model = BibliographicMetadataEnhancement

    enhancement_type = EnhancementType.BIBLIOGRAPHIC
    authorship = factory.LazyFunction(
        lambda: fake.random_elements(
            [
                Authorship(
                    display_name=fake.name(),
                    position=fake.enum(AuthorPosition),
                    orcid=fake.uuid4() if fake.pybool() else None,
                )
            ],
            length=fake.pyint(min_value=1, max_value=max_list_length),
        )
    )
    cited_by_count = factory.LazyFunction(
        lambda: fake.pyint(min_value=0, max_value=1000)
    )
    created_date = factory.LazyFunction(lambda: fake.date_this_century())
    publication_date = factory.LazyFunction(lambda: fake.date_this_century())
    publication_year = factory.LazyFunction(lambda: int(fake.year()))
    publisher = factory.Faker("company")
    title = factory.LazyFunction(lambda: fake.sentence(nb_words=6))


class AbstractContentEnhancementFactory(factory.Factory):
    class Meta:
        model = AbstractContentEnhancement

    enhancement_type = EnhancementType.ABSTRACT
    process = factory.LazyFunction(lambda: fake.enum(AbstractProcessType))
    abstract = factory.LazyFunction(lambda: "\n".join(fake.paragraphs(nb=3)))


class AnnotationEnhancementFactory(factory.Factory):
    class Meta:
        model = AnnotationEnhancement

    enhancement_type = EnhancementType.ANNOTATION
    annotations = factory.LazyFunction(
        lambda: fake.random_elements(
            [
                BooleanAnnotation(
                    annotation_type=AnnotationType.BOOLEAN,
                    scheme=fake.word(),
                    label=fake.word(),
                    value=fake.pybool(),
                    score=fake.pyfloat(0, 1),
                    data=fake.pydict(value_types=[str]),
                ),
                ScoreAnnotation(
                    annotation_type=AnnotationType.SCORE,
                    scheme=fake.word(),
                    label=fake.word(),
                    value=fake.pybool(),
                    score=fake.pyfloat(0, 1),
                    data=fake.pydict(value_types=[str]),
                ),
            ],
            length=fake.pyint(1, max_list_length),
        )
    )


class LocationEnhancementFactory(factory.Factory):
    class Meta:
        model = LocationEnhancement

    enhancement_type = EnhancementType.LOCATION
    locations = factory.LazyFunction(
        lambda: [
            Location(
                is_oa=fake.pybool(),
                version=fake.enum(DriverVersion),
                landing_page_url=fake.url(),
                pdf_url=fake.url(),
                license=fake.license_plate(),  # why not
                extra=fake.pydict(value_types=[str]),
            )
            for _ in range(fake.pyint(1, max_list_length))
        ]
    )


class LinkedExternalIdentifierFactory(factory.Factory):
    class Meta:
        model = LinkedExternalIdentifier

    id = factory.LazyFunction(uuid.uuid4)
    identifier = factory.LazyFunction(
        lambda: fake.random_element(
            [
                DOIIdentifierFactory(),
                PubMedIdentifierFactory(),
                OpenAlexIdentifierFactory(),
                OtherIdentifierFactory(),
            ]
        )
    )
    reference_id = factory.LazyFunction(uuid.uuid4)


class EnhancementFactory(factory.Factory):
    class Meta:
        model = Enhancement

    id = factory.LazyFunction(uuid.uuid4)
    source = factory.Faker("company")
    visibility = Visibility.PUBLIC
    robot_version = factory.LazyFunction(lambda: fake.numerify("%!!.%!!.%!!"))
    content = factory.LazyFunction(
        lambda: fake.random_element(
            [
                BibliographicMetadataEnhancementFactory(),
                AbstractContentEnhancementFactory(),
                AnnotationEnhancementFactory(),
                LocationEnhancementFactory(),
            ]
        )
    )
    reference_id = factory.LazyFunction(uuid.uuid4)


class ReferenceFactory(factory.Factory):
    class Meta:
        model = Reference

    id = factory.LazyFunction(uuid.uuid4)
    visibility = Visibility.PUBLIC

    @factory.post_generation
    def identifiers(self, create, extracted, **kwargs):  # noqa: ANN001, ANN003, ARG002
        if not extracted:
            self.identifiers = [
                LinkedExternalIdentifierFactory(reference_id=self.id)
                for _ in range(random.randint(1, max_list_length))
            ]
        else:
            self.identifiers = extracted

    @factory.post_generation
    def enhancements(self, create, extracted, **kwargs):  # noqa: ANN001, ANN003, ARG002
        if not extracted:
            self.enhancements = [
                EnhancementFactory(reference_id=self.id)
                for _ in range(random.randint(1, max_list_length))
            ]
        else:
            self.enhancements = extracted


class RobotFactory(factory.Factory):
    class Meta:
        model = Robot

    id = factory.LazyFunction(uuid.uuid4)
    base_url = factory.Faker("url")
    description = factory.Faker("sentence")
    name = factory.Faker("name")
    owner = factory.Faker("company")
