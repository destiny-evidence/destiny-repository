# ruff: noqa: S311 D101 D102 D106
"""Factories for creating test domain models."""

import random

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


class AuthorshipFactory(factory.Factory):
    class Meta:
        model = Authorship

    display_name = factory.Faker("name")
    position = factory.Faker("enum", enum_cls=AuthorPosition)
    orcid = factory.Faker("uuid4")


class BibliographicMetadataEnhancementFactory(factory.Factory):
    class Meta:
        model = BibliographicMetadataEnhancement

    enhancement_type = EnhancementType.BIBLIOGRAPHIC
    authorship = factory.LazyFunction(
        lambda: AuthorshipFactory.build_batch(
            fake.pyint(min_value=1, max_value=max_list_length)
        )
    )
    cited_by_count = factory.Faker("pyint", min_value=0, max_value=1000)
    created_date = factory.Faker("date_this_century")
    publication_date = factory.Faker("date_this_century")
    publisher = factory.Faker("company")
    title = factory.Faker("sentence", nb_words=6)

    @factory.post_generation
    def publication_year(self, create, extracted, **kwargs):  # noqa: ANN001, ANN003, ARG002
        """Set publication year from publication date if not provided seperately."""
        if not extracted:
            self.publication_year = (
                self.publication_date.year if self.publication_date else None
            )
        else:
            self.publication_year = extracted


class AbstractContentEnhancementFactory(factory.Factory):
    class Meta:
        model = AbstractContentEnhancement

    enhancement_type = EnhancementType.ABSTRACT
    process = factory.Faker("enum", enum_cls=AbstractProcessType)
    abstract = factory.LazyFunction(lambda: "\n".join(fake.paragraphs(nb=3)))


class BooleanAnnotationFactory(factory.Factory):
    class Meta:
        model = BooleanAnnotation

    annotation_type = AnnotationType.BOOLEAN
    scheme = factory.Faker("word")
    label = factory.Faker("word")
    value = factory.Faker("pybool")
    score = factory.Faker("pyfloat", min_value=0, max_value=1)
    data = factory.Faker("pydict", value_types=[str])


class ScoreAnnotationFactory(factory.Factory):
    class Meta:
        model = ScoreAnnotation

    annotation_type = AnnotationType.SCORE
    scheme = factory.Faker("word")
    label = factory.Faker("word")
    value = factory.Faker("pybool")
    score = factory.Faker("pyfloat", min_value=0, max_value=1)
    data = factory.Faker("pydict", value_types=[str])


class AnnotationEnhancementFactory(factory.Factory):
    class Meta:
        model = AnnotationEnhancement

    enhancement_type = EnhancementType.ANNOTATION
    annotations = factory.LazyFunction(
        lambda: fake.random_elements(
            [
                BooleanAnnotationFactory(),
                ScoreAnnotationFactory(),
            ],
            length=fake.pyint(1, max_list_length),
        )
    )


class LocationFactory(factory.Factory):
    class Meta:
        model = Location

    is_oa = factory.Faker("pybool")
    version = factory.Faker("enum", enum_cls=DriverVersion)
    landing_page_url = factory.Faker("url")
    pdf_url = factory.Faker("url")
    license = factory.Faker("license_plate")
    extra = factory.Faker("pydict", value_types=[str])


class LocationEnhancementFactory(factory.Factory):
    class Meta:
        model = LocationEnhancement

    enhancement_type = EnhancementType.LOCATION
    locations = factory.LazyFunction(
        lambda: LocationFactory.build_batch(fake.pyint(1, max_list_length))
    )


class LinkedExternalIdentifierFactory(factory.Factory):
    class Meta:
        model = LinkedExternalIdentifier

    id = factory.Faker("uuid4")
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
    reference_id = factory.Faker("uuid4")


class EnhancementFactory(factory.Factory):
    class Meta:
        model = Enhancement

    id = factory.Faker("uuid4")
    source = factory.Faker("company")
    visibility = Visibility.PUBLIC
    robot_version = factory.Faker("numerify", text="%!!.%!!.%!!")
    created_at = factory.Faker("date_time_this_month")
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
    reference_id = factory.Faker("uuid4")


class ReferenceFactory(factory.Factory):
    class Meta:
        model = Reference

    id = factory.Faker("uuid4")
    visibility = factory.Faker("enum", enum_cls=Visibility)

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

    id = factory.Faker("uuid4")
    description = factory.Faker("sentence")
    name = factory.Faker("name")
    owner = factory.Faker("company")
