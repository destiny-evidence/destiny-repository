"""Unit tests for the LinkedDataProjectionService."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from destiny_sdk.enhancements import LinkedDataEnhancement
from rdflib import Graph

from app.core.config import get_settings
from app.domain.references.models.es import ReferenceSearchFieldsMixin
from app.domain.references.models.models import ReferenceSearchFields
from app.domain.references.services.linked_data_projection_service import (
    LinkedDataProjectionService,
)
from app.domain.references.services.world_bank_income_groups import (
    LOWER_MIDDLE_INCOME,
)
from app.domain.references.services.world_bank_regions import (
    LATIN_AMERICA_CARIBBEAN,
    SOUTH_ASIA,
    SUB_SAHARAN_AFRICA,
)
from app.external.vocabulary.client import (
    VocabularyArtifactClient,
    _build_concept_labels,
    _build_concept_schemes,
)

ESEA_NS = "https://vocab.esea.education/"
EVREPO_NS = "https://vocab.evidence-repository.org/"
EVREPO_CONTEXT_URI = EVREPO_NS + "context.jsonld"
EVREPO_VOCAB_URI = EVREPO_NS + "vocabulary.ttl"

ESEA_VOCAB_URI = "https://vocab.esea.education/vocabulary/v1"
ESEA_CONTEXT_URI = "https://vocab.esea.education/context/v1.jsonld"

_STATIC_ESEA_VOCAB_DIR = (
    get_settings().project_root / "app" / "static" / "vocab" / "esea"
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def projector_esea() -> LinkedDataProjectionService:
    vocab_graph = Graph()
    vocab_graph.parse(_STATIC_ESEA_VOCAB_DIR / "esea-vocab.ttl", format="turtle")
    with (_STATIC_ESEA_VOCAB_DIR / "esea-context.jsonld").open() as f:
        context = json.load(f)

    client = MagicMock(spec=VocabularyArtifactClient)
    client.get_vocabulary = AsyncMock(return_value=vocab_graph)
    client.get_context = AsyncMock(return_value=context)
    client.get_concept_labels = AsyncMock(
        return_value=_build_concept_labels(vocab_graph)
    )
    client.get_concept_schemes = AsyncMock(
        return_value=_build_concept_schemes(vocab_graph)
    )
    return LinkedDataProjectionService(client)


@pytest.fixture
def projector_esea_with_evrepo() -> LinkedDataProjectionService:
    """Projector whose vocab graph also declares the evrepo core ontology.

    Matches deployed reality: the ESEA project's published vocabulary embeds
    the evrepo core concepts (EffectSizeMetricScheme, EstimateSourceScheme).
    """
    vocab_graph = Graph()
    vocab_graph.parse(_STATIC_ESEA_VOCAB_DIR / "esea-vocab.ttl", format="turtle")
    vocab_graph.parse(FIXTURES_DIR / "evrepo-core.ttl", format="turtle")
    with (_STATIC_ESEA_VOCAB_DIR / "esea-context.jsonld").open() as f:
        context = json.load(f)

    client = MagicMock(spec=VocabularyArtifactClient)
    client.get_vocabulary = AsyncMock(return_value=vocab_graph)
    client.get_context = AsyncMock(return_value=context)
    client.get_concept_labels = AsyncMock(
        return_value=_build_concept_labels(vocab_graph)
    )
    client.get_concept_schemes = AsyncMock(
        return_value=_build_concept_schemes(vocab_graph)
    )
    return LinkedDataProjectionService(client)


@pytest.fixture
def esea_test_data() -> dict:
    """The 7d6f1092 test reference data (content.data only)."""
    with (FIXTURES_DIR / "7d6f1092-linked-data.json").open() as f:
        return json.load(f)


@pytest.fixture
def esea_enhancement(esea_test_data) -> LinkedDataEnhancement:
    return LinkedDataEnhancement(
        context_uri=ESEA_CONTEXT_URI,
        vocabulary_uri=ESEA_VOCAB_URI,
        data=esea_test_data,
    )


EVREPO_LOCATION_CONTEXT = {
    "@context": {
        "@vocab": "https://example.org/location",
        "evrepo": EVREPO_NS,
        "gn": "http://www.geonames.org/ontology#",
        "codedValue": "evrepo:codedValue",
        "status": {"@id": "evrepo:status", "@type": "@id"},
        "countryCode": "gn:countryCode",
    }
}


@pytest.fixture
def projector_location() -> LinkedDataProjectionService:
    vocab_graph = Graph()
    vocab_graph.bind("evrepo", EVREPO_NS)
    client = MagicMock(spec=VocabularyArtifactClient)
    client.get_vocabulary = AsyncMock(return_value=vocab_graph)
    client.get_context = AsyncMock(return_value=EVREPO_LOCATION_CONTEXT)
    client.get_concept_labels = AsyncMock(return_value={})
    client.get_concept_schemes = AsyncMock(return_value={})
    return LinkedDataProjectionService(client)


@pytest.fixture
def location_coding_annotation_enhancement() -> LinkedDataEnhancement:
    """Example LocationCodingAnnotation enhancement (New Delhi, IN; Bangladesh, BD)."""
    with (FIXTURES_DIR / "destiny-location-enhancement.json").open() as f:
        example = json.load(f)
    return LinkedDataEnhancement(
        context_uri=EVREPO_CONTEXT_URI,
        vocabulary_uri=EVREPO_VOCAB_URI,
        data=example["data"],
    )


def _location_coding_annotation(
    geonames_id: str, country_code: str | None, status: str | None
) -> dict:
    """Build a LocationCodingAnnotation; ``None`` omits the field."""
    coded_value: dict = {
        "@id": f"http://sws.geonames.org/{geonames_id}/",
        "@type": "GeonamesFeature",
        "geonamesID": geonames_id,
    }
    if country_code is not None:
        coded_value["countryCode"] = country_code
    annotation: dict = {
        "@type": "LocationCodingAnnotation",
        "codedBy": "mordecai3/3.0.0",
        "codedValue": coded_value,
    }
    if status is not None:
        annotation["status"] = status
    return annotation


def _location_lde_enhancement(*annotations: dict) -> LinkedDataEnhancement:
    return LinkedDataEnhancement(
        context_uri=EVREPO_CONTEXT_URI,
        vocabulary_uri=EVREPO_VOCAB_URI,
        data={
            "@context": EVREPO_CONTEXT_URI,
            "@type": "LinkedDataEnhancement",
            "hasInvestigation": {
                "@type": "Investigation",
                "mentionedPlace": list(annotations),
            },
        },
    )


class TestLinkedDataProjectionService:
    @pytest.mark.asyncio
    async def test_extracts_coded_concept_uris(self, projector_esea, esea_enhancement):
        result = await projector_esea.project(esea_enhancement)

        expected_concepts = {
            f"{ESEA_NS}C00008",  # documentType: Journal Article
            f"{ESEA_NS}C00040",  # educationTheme
            f"{ESEA_NS}C00002",  # educationLevel: Primary Education
            f"{ESEA_NS}C00189",  # sampleFeatures
            f"{ESEA_NS}C00145",  # setting
            f"{ESEA_NS}C00123",  # outcome (appears in both findings)
            f"{ESEA_NS}C00118",  # outcome (appears in both findings)
            f"{ESEA_NS}C00122",  # outcome (second finding only)
        }
        assert result.concepts == expected_concepts

    @pytest.mark.asyncio
    async def test_excludes_numeric_coding_annotations(
        self, projector_esea, esea_enhancement
    ):
        """NumericCodingAnnotation (sampleSize, duration) should not appear."""
        result = await projector_esea.project(esea_enhancement)
        concept_uris = result.concepts

        # No numeric values should be in concepts
        for uri in concept_uris:
            assert uri.startswith("http"), f"Non-URI in concepts: {uri}"

    @pytest.mark.asyncio
    async def test_excludes_string_coding_annotations(
        self, projector_esea, esea_enhancement
    ):
        """StringCodingAnnotation (participants='Students') should not appear
        as a concept URI."""
        result = await projector_esea.project(esea_enhancement)

        # "Students" is a string coded value, not a concept URI
        assert "Students" not in result.concepts

    @pytest.mark.asyncio
    async def test_resolves_labels(self, projector_esea, esea_enhancement):
        result = await projector_esea.project(esea_enhancement)

        assert "Journal Article" in result.labels
        assert "Primary Education" in result.labels

    @pytest.mark.asyncio
    async def test_resolves_evaluated_properties(
        self, projector_esea, esea_enhancement
    ):
        result = await projector_esea.project(esea_enhancement)

        expected_properties = {
            f"{ESEA_NS}documentType",
            f"{ESEA_NS}educationTheme",
            f"{ESEA_NS}educationLevel",
            f"{ESEA_NS}sampleFeatures",
            f"{ESEA_NS}setting",
            f"{ESEA_NS}outcome",
        }
        assert result.evaluated_properties == expected_properties

    @pytest.mark.asyncio
    async def test_not_reported_excluded_from_concepts_but_in_properties(
        self, projector_esea
    ):
        """Concepts with notReported status should be excluded from concepts
        but their property should appear in evaluated_properties."""
        data = {
            "@context": ESEA_CONTEXT_URI,
            "@type": "Investigation",
            "documentType": {
                "@type": "DocumentTypeCodingAnnotation",
                "codedValue": {"@id": "esea:C00008"},
                "status": "evrepo:notReported",
            },
        }
        enhancement = LinkedDataEnhancement(
            context_uri=ESEA_CONTEXT_URI,
            vocabulary_uri=ESEA_VOCAB_URI,
            data=data,
        )
        result = await projector_esea.project(enhancement)

        assert f"{ESEA_NS}C00008" not in result.concepts
        assert f"{ESEA_NS}documentType" in result.evaluated_properties

    @pytest.mark.asyncio
    async def test_not_applicable_excluded_from_concepts_but_in_properties(
        self, projector_esea
    ):
        data = {
            "@context": ESEA_CONTEXT_URI,
            "@type": "Investigation",
            "documentType": {
                "@type": "DocumentTypeCodingAnnotation",
                "codedValue": {"@id": "esea:C00008"},
                "status": "evrepo:notApplicable",
            },
        }
        enhancement = LinkedDataEnhancement(
            context_uri=ESEA_CONTEXT_URI,
            vocabulary_uri=ESEA_VOCAB_URI,
            data=data,
        )
        result = await projector_esea.project(enhancement)

        assert f"{ESEA_NS}C00008" not in result.concepts
        assert "Journal Article" not in result.labels
        assert f"{ESEA_NS}documentType" in result.evaluated_properties

    @pytest.mark.asyncio
    async def test_empty_data(self, projector_esea):
        enhancement = LinkedDataEnhancement(
            context_uri=ESEA_CONTEXT_URI,
            vocabulary_uri=ESEA_VOCAB_URI,
            data={
                "@context": ESEA_CONTEXT_URI,
                "@type": "Investigation",
            },
        )
        result = await projector_esea.project(enhancement)

        assert result.concepts == set()
        assert result.labels == set()
        assert result.evaluated_properties == set()
        assert result.countries == set()
        assert result.country_wb_regions == set()
        assert result.country_wb_income_groups == set()

    @pytest.mark.asyncio
    async def test_extracts_country_codes(self, projector_esea):
        data = {
            "@context": ESEA_CONTEXT_URI,
            "@type": "Investigation",
            "hasFinding": [
                {
                    "@type": "Finding",
                    "hasContext": {
                        "@type": "Context",
                        "country": [
                            {
                                "@type": "StringCodingAnnotation",
                                "codedValue": {
                                    "@type": "xsd:string",
                                    "@value": "KE",
                                },
                                "status": "evrepo:coded",
                                "supportingText": "Kenya",
                            },
                            {
                                "@type": "StringCodingAnnotation",
                                "codedValue": {
                                    "@type": "xsd:string",
                                    "@value": "GH",
                                },
                                "status": "evrepo:coded",
                            },
                        ],
                    },
                }
            ],
        }
        enhancement = LinkedDataEnhancement(
            context_uri=ESEA_CONTEXT_URI,
            vocabulary_uri=ESEA_VOCAB_URI,
            data=data,
        )
        result = await projector_esea.project(enhancement)

        assert result.countries == {"KE", "GH"}
        # Both KE and GH are Sub-Saharan Africa — regions deduplicate.
        assert result.country_wb_regions == {SUB_SAHARAN_AFRICA}
        assert result.country_wb_income_groups == {LOWER_MIDDLE_INCOME}

    @pytest.mark.asyncio
    async def test_projects_distinct_regions_for_distinct_countries(
        self, projector_esea
    ):
        data = {
            "@context": ESEA_CONTEXT_URI,
            "@type": "Investigation",
            "hasFinding": [
                {
                    "@type": "Finding",
                    "hasContext": {
                        "@type": "Context",
                        "country": [
                            {
                                "@type": "StringCodingAnnotation",
                                "codedValue": {
                                    "@type": "xsd:string",
                                    "@value": "KE",
                                },
                                "status": "evrepo:coded",
                            },
                            {
                                "@type": "StringCodingAnnotation",
                                "codedValue": {
                                    "@type": "xsd:string",
                                    "@value": "IN",
                                },
                                "status": "evrepo:coded",
                            },
                            {
                                "@type": "StringCodingAnnotation",
                                "codedValue": {
                                    "@type": "xsd:string",
                                    "@value": "BR",
                                },
                                "status": "evrepo:coded",
                            },
                        ],
                    },
                }
            ],
        }
        enhancement = LinkedDataEnhancement(
            context_uri=ESEA_CONTEXT_URI,
            vocabulary_uri=ESEA_VOCAB_URI,
            data=data,
        )
        result = await projector_esea.project(enhancement)

        assert result.country_wb_regions == {
            SUB_SAHARAN_AFRICA,
            SOUTH_ASIA,
            LATIN_AMERICA_CARIBBEAN,
        }

    @pytest.mark.asyncio
    async def test_unknown_country_code_omitted_from_regions(self, projector_esea):
        data = {
            "@context": ESEA_CONTEXT_URI,
            "@type": "Investigation",
            "hasFinding": [
                {
                    "@type": "Finding",
                    "hasContext": {
                        "@type": "Context",
                        "country": [
                            {
                                "@type": "StringCodingAnnotation",
                                "codedValue": {
                                    "@type": "xsd:string",
                                    "@value": "ZZ",
                                },
                                "status": "evrepo:coded",
                            },
                            {
                                "@type": "StringCodingAnnotation",
                                "codedValue": {
                                    "@type": "xsd:string",
                                    "@value": "KE",
                                },
                                "status": "evrepo:coded",
                            },
                        ],
                    },
                }
            ],
        }
        enhancement = LinkedDataEnhancement(
            context_uri=ESEA_CONTEXT_URI,
            vocabulary_uri=ESEA_VOCAB_URI,
            data=data,
        )
        result = await projector_esea.project(enhancement)

        # ZZ has no WB region or income group; KE still resolves.
        assert result.countries == {"ZZ", "KE"}
        assert result.country_wb_regions == {SUB_SAHARAN_AFRICA}
        assert result.country_wb_income_groups == {LOWER_MIDDLE_INCOME}

    @pytest.mark.asyncio
    async def test_normalises_country_codes_to_uppercase(self, projector_esea):
        data = {
            "@context": ESEA_CONTEXT_URI,
            "@type": "Investigation",
            "hasFinding": [
                {
                    "@type": "Finding",
                    "hasContext": {
                        "@type": "Context",
                        "country": [
                            {
                                "@type": "StringCodingAnnotation",
                                "codedValue": {
                                    "@type": "xsd:string",
                                    "@value": "ke",
                                },
                                "status": "evrepo:coded",
                            },
                        ],
                    },
                }
            ],
        }
        enhancement = LinkedDataEnhancement(
            context_uri=ESEA_CONTEXT_URI,
            vocabulary_uri=ESEA_VOCAB_URI,
            data=data,
        )
        result = await projector_esea.project(enhancement)

        assert result.countries == {"KE"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status",
        ["evrepo:notReported", "evrepo:notApplicable"],
    )
    async def test_excludes_uncoded_country(self, projector_esea, status):
        data = {
            "@context": ESEA_CONTEXT_URI,
            "@type": "Investigation",
            "hasFinding": [
                {
                    "@type": "Finding",
                    "hasContext": {
                        "@type": "Context",
                        "country": [
                            {
                                "@type": "StringCodingAnnotation",
                                "codedValue": {
                                    "@type": "xsd:string",
                                    "@value": "KE",
                                },
                                "status": status,
                            },
                        ],
                    },
                }
            ],
        }
        enhancement = LinkedDataEnhancement(
            context_uri=ESEA_CONTEXT_URI,
            vocabulary_uri=ESEA_VOCAB_URI,
            data=data,
        )
        result = await projector_esea.project(enhancement)

        assert result.countries == set()

    @pytest.mark.asyncio
    async def test_ignores_other_string_coding_annotations(self, projector_esea):
        """Only `country` properties are projected, not every StringCodingAnnotation."""
        data = {
            "@context": ESEA_CONTEXT_URI,
            "@type": "Investigation",
            "hasFinding": [
                {
                    "@type": "Finding",
                    "hasContext": {
                        "@type": "Context",
                        "participants": [
                            {
                                "@type": "StringCodingAnnotation",
                                "codedValue": {
                                    "@type": "xsd:string",
                                    "@value": "Students",
                                },
                                "status": "evrepo:coded",
                            },
                        ],
                    },
                }
            ],
        }
        enhancement = LinkedDataEnhancement(
            context_uri=ESEA_CONTEXT_URI,
            vocabulary_uri=ESEA_VOCAB_URI,
            data=data,
        )
        result = await projector_esea.project(enhancement)

        assert result.countries == set()

    @pytest.mark.asyncio
    async def test_scheme_to_property_mapping(self, projector_esea):
        vocab_uri = ESEA_VOCAB_URI
        mapping = await projector_esea._get_scheme_to_property(vocab_uri)  # noqa: SLF001
        assert mapping[f"{ESEA_NS}DocumentTypeScheme"] == (f"{ESEA_NS}documentType")
        assert mapping[f"{ESEA_NS}EducationLevelScheme"] == (f"{ESEA_NS}educationLevel")
        assert mapping[f"{ESEA_NS}EducationThemeScheme"] == (f"{ESEA_NS}educationTheme")
        assert mapping[f"{ESEA_NS}OutcomeScheme"] == f"{ESEA_NS}outcome"

    @pytest.mark.asyncio
    async def test_unwrapped_concept_properties_discovery(
        self, projector_esea_with_evrepo
    ):
        """SPARQL discovers ObjectProperties whose range is a ConceptScheme.

        These are the unwrapped concept references handled by the second-pass
        walk (no CodingAnnotation envelope). With the evrepo core ontology
        loaded, this returns exactly the two EffectEstimate concept properties.
        """
        vocab_uri = ESEA_VOCAB_URI
        properties = await projector_esea_with_evrepo._get_unwrapped_concept_properties(  # noqa: SLF001
            vocab_uri
        )

        assert properties == {
            f"{EVREPO_NS}effectSizeMetric",
            f"{EVREPO_NS}estimateSource",
        }

    def test_unwrapped_concept_properties_discovers_direct_scheme_range(self):
        """Property whose range IS skos:ConceptScheme (production vocab shape).

        The shared evrepo-core.ttl fixture uses range = ConceptClass (a class
        subClassOf skos:Concept), which exercises one UNION branch. This
        synthetic graph covers the other branch.
        """
        graph = Graph()
        graph.parse(
            data="""
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
            @prefix ex: <https://example.org/> .

            ex:myConceptProperty a owl:ObjectProperty ;
                rdfs:range ex:MyScheme .
            ex:MyScheme a skos:ConceptScheme .
            """,
            format="turtle",
        )

        properties = LinkedDataProjectionService._build_unwrapped_concept_properties(  # noqa: SLF001
            graph
        )

        assert properties == {"https://example.org/myConceptProperty"}

    def test_unwrapped_concept_properties_discovers_direct_concept_range(self):
        """Property whose range IS the bare skos:Concept class (HPV vocab shape).

        HPV's ``evrepo:hasAppliedConcept`` declares ``rdfs:range skos:Concept``
        directly — not a subclass. The discovery must recognise it as long as
        the vocab contains at least one concept scoped to a scheme.
        """
        graph = Graph()
        graph.parse(
            data="""
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
            @prefix ex: <https://example.org/> .

            ex:hasAppliedConcept a owl:ObjectProperty ;
                rdfs:range skos:Concept .
            ex:Scheme a skos:ConceptScheme .
            ex:c1 a skos:Concept ;
                skos:inScheme ex:Scheme .
            """,
            format="turtle",
        )

        properties = LinkedDataProjectionService._build_unwrapped_concept_properties(  # noqa: SLF001
            graph
        )

        assert properties == {"https://example.org/hasAppliedConcept"}

    def test_unwrapped_concept_properties_skips_direct_concept_range_without_instances(
        self,
    ):
        """A property ranging over skos:Concept is not discovered when no
        concrete concepts exist in the graph — matches branch 2's intent of
        requiring at least one populated scheme."""
        graph = Graph()
        graph.parse(
            data="""
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
            @prefix ex: <https://example.org/> .

            ex:hasAppliedConcept a owl:ObjectProperty ;
                rdfs:range skos:Concept .
            """,
            format="turtle",
        )

        properties = LinkedDataProjectionService._build_unwrapped_concept_properties(  # noqa: SLF001
            graph
        )

        assert properties == set()

    @pytest.mark.asyncio
    async def test_extracts_effect_size_metric_uri(
        self, projector_esea_with_evrepo, esea_enhancement
    ):
        """EffectEstimate.effectSizeMetric is an unwrapped concept reference
        (no CodingAnnotation wrapper, no codedValue triple). It must still be
        projected when the vocab declares the URI as a skos:Concept."""
        result = await projector_esea_with_evrepo.project(esea_enhancement)

        assert f"{EVREPO_NS}hedgesG" in result.concepts
        assert f"{EVREPO_NS}effectSizeMetric" in result.evaluated_properties

    @pytest.mark.asyncio
    async def test_extracts_both_effect_estimate_concept_properties(
        self, projector_esea_with_evrepo
    ):
        """Both unwrapped concept properties on EffectEstimate (effectSizeMetric
        and estimateSource) must project. The realistic fixture omits
        estimateSource (the EEF mapping robot doesn't emit it), so cover that
        path with a synthetic graph."""
        data = {
            "@context": ESEA_CONTEXT_URI,
            "@type": "Investigation",
            "hasInvestigation": [
                {
                    "@type": "Investigation",
                    "hasFinding": [
                        {
                            "@type": "Finding",
                            "hasEffectEstimate": [
                                {
                                    "@type": "EffectEstimate",
                                    "effectSizeMetric": "evrepo:hedgesG",
                                    "estimateSource": "evrepo:computedFromStats",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        enhancement = LinkedDataEnhancement(
            context_uri=ESEA_CONTEXT_URI,
            vocabulary_uri=ESEA_VOCAB_URI,
            data=data,
        )
        result = await projector_esea_with_evrepo.project(enhancement)

        assert f"{EVREPO_NS}hedgesG" in result.concepts
        assert f"{EVREPO_NS}computedFromStats" in result.concepts
        assert f"{EVREPO_NS}effectSizeMetric" in result.evaluated_properties
        assert f"{EVREPO_NS}estimateSource" in result.evaluated_properties


class TestLocationCodingAnnotationCountries:
    @pytest.mark.asyncio
    async def test_extracts_country_from_example_enhancement(
        self, projector_location, location_coding_annotation_enhancement
    ):
        result = await projector_location.project(
            location_coding_annotation_enhancement
        )

        assert result.countries == {"IN", "BD"}

    @pytest.mark.asyncio
    async def test_extracts_countries_from_multiple_mentions(self, projector_location):
        enhancement = _location_lde_enhancement(
            _location_coding_annotation("1261481", "IN", "evrepo:coded"),
            _location_coding_annotation("184745", "KE", "evrepo:coded"),
        )

        result = await projector_location.project(enhancement)

        assert result.countries == {"IN", "KE"}

    @pytest.mark.asyncio
    async def test_deduplicates_countries_across_mentions(self, projector_location):
        enhancement = _location_lde_enhancement(
            _location_coding_annotation("1261481", "IN", "evrepo:coded"),
            _location_coding_annotation("1275339", "IN", "evrepo:coded"),
        )

        result = await projector_location.project(enhancement)

        assert result.countries == {"IN"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status",
        ["evrepo:notReported", "evrepo:notApplicable"],
    )
    async def test_excludes_uncoded_mention(self, projector_location, status):
        enhancement = _location_lde_enhancement(
            _location_coding_annotation("1261481", "IN", status),
        )

        result = await projector_location.project(enhancement)

        assert result.countries == set()

    @pytest.mark.asyncio
    async def test_includes_mention_without_status(self, projector_location):
        enhancement = _location_lde_enhancement(
            _location_coding_annotation("1261481", "IN", None),
        )

        result = await projector_location.project(enhancement)

        assert result.countries == {"IN"}

    @pytest.mark.asyncio
    async def test_normalises_country_code_to_uppercase(self, projector_location):
        enhancement = _location_lde_enhancement(
            _location_coding_annotation("1261481", " in ", "evrepo:coded"),
        )

        result = await projector_location.project(enhancement)

        assert result.countries == {"IN"}

    @pytest.mark.asyncio
    async def test_feature_without_country_code_is_skipped(self, projector_location):
        enhancement = _location_lde_enhancement(
            _location_coding_annotation("6295630", None, "evrepo:coded"),
        )

        result = await projector_location.project(enhancement)

        assert result.countries == set()

    @pytest.mark.asyncio
    async def test_shared_feature_is_included_if_any_mention_is_coded(
        self, projector_location
    ):
        enhancement = _location_lde_enhancement(
            _location_coding_annotation("1261481", "IN", "evrepo:notReported"),
            _location_coding_annotation("1261481", "IN", "evrepo:coded"),
        )

        result = await projector_location.project(enhancement)

        assert result.countries == {"IN"}

    @pytest.mark.asyncio
    async def test_derives_region_and_income_group_from_example_enhancement(
        self, projector_location, location_coding_annotation_enhancement
    ):
        result = await projector_location.project(
            location_coding_annotation_enhancement
        )

        assert result.country_wb_regions == {SOUTH_ASIA}
        assert result.country_wb_income_groups == {LOWER_MIDDLE_INCOME}

    @pytest.mark.asyncio
    async def test_derives_distinct_regions_across_mentions(self, projector_location):
        enhancement = _location_lde_enhancement(
            _location_coding_annotation("1261481", "IN", "evrepo:coded"),
            _location_coding_annotation("184745", "KE", "evrepo:coded"),
        )

        result = await projector_location.project(enhancement)

        assert result.country_wb_regions == {SOUTH_ASIA, SUB_SAHARAN_AFRICA}
        # IN and KE are both lower-middle income — income groups deduplicate.
        assert result.country_wb_income_groups == {LOWER_MIDDLE_INCOME}

    @pytest.mark.asyncio
    async def test_unknown_country_code_omitted_from_region_and_income_group(
        self, projector_location
    ):
        enhancement = _location_lde_enhancement(
            _location_coding_annotation("1261481", "IN", "evrepo:coded"),
            _location_coding_annotation("0000001", "ZZ", "evrepo:coded"),
        )

        result = await projector_location.project(enhancement)

        assert result.countries == {"IN", "ZZ"}
        assert result.country_wb_regions == {SOUTH_ASIA}
        assert result.country_wb_income_groups == {LOWER_MIDDLE_INCOME}

    @pytest.mark.asyncio
    async def test_example_enhancement_populates_search_document_fields(
        self, projector_location, location_coding_annotation_enhancement
    ):
        projection = await projector_location.project(
            location_coding_annotation_enhancement
        )

        fields = ReferenceSearchFieldsMixin.from_projections(
            ReferenceSearchFields(), projection
        )

        assert sorted(fields.linked_data_countries or []) == ["BD", "IN"]
        assert fields.linked_data_country_wb_regions == [SOUTH_ASIA]
        assert fields.linked_data_country_wb_income_groups == [LOWER_MIDDLE_INCOME]
