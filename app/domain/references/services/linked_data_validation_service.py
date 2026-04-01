"""Service for validating LinkedDataEnhancements against an OWL/SKOS ontology."""

import functools

from pydantic import BaseModel, Field
from pyld import jsonld
from pyld.jsonld import JsonLdError
from pyshacl import validate as shacl_validate
from pyshacl.errors import ReportableRuntimeError
from rdflib import Graph

from app.core.config import get_settings
from app.external.vocabulary.client import VocabularyArtifactClient

_SHAPES_PATH = get_settings().project_root / "app" / "static" / "evrepo-core-shapes.ttl"


@functools.cache
def _get_bundled_shapes() -> Graph:
    """Return the bundled SHACL shapes graph, parsing on first call."""
    shapes = Graph()
    shapes.parse(str(_SHAPES_PATH), format="turtle")
    return shapes


class LinkedDataValidationResult(BaseModel):
    """Result of validating a LinkedDataEnhancement."""

    conforms: bool
    errors: list[str] = Field(default_factory=list)


class LinkedDataValidationService:
    """Validates LinkedDataEnhancements using JSON-LD expansion and SHACL."""

    def __init__(self, vocab_client: VocabularyArtifactClient) -> None:
        """Initialise with the bundled SHACL shapes and a vocabulary client."""
        self._shapes = _get_bundled_shapes()
        self._vocab_client = vocab_client

    async def validate(
        self,
        data: dict,
        vocabulary_uri: str,
    ) -> LinkedDataValidationResult:
        """
        Validate a LinkedDataEnhancement's data field.

        Validates:
        1. JSON-LD expansion succeeds and produces a non-empty graph.
        2. The expanded data can be converted to an rdflib graph.
        3. The data conforms to the SHACL shapes.

        :raises VocabularyFetchError: If vocabulary artifacts cannot be fetched.
        """
        context_uri = data["@context"]
        ontology = await self._vocab_client.get_vocabulary(vocabulary_uri)
        await self._vocab_client.get_context(context_uri)

        loader_options = {"documentLoader": self._vocab_client.document_loader}

        errors: list[str] = []

        # Step 1: JSON-LD expansion
        try:
            expanded = jsonld.expand(data, options=loader_options)
        except JsonLdError as exc:
            return LinkedDataValidationResult(
                conforms=False,
                errors=[f"JSON-LD expansion failed: {exc}"],
            )

        if not expanded:
            return LinkedDataValidationResult(
                conforms=False,
                errors=["JSON-LD expansion produced an empty graph."],
            )

        # Step 2: Convert expanded JSON-LD to an rdflib graph
        try:
            data_graph = Graph()
            data_graph.parse(
                data=jsonld.to_rdf(
                    data,
                    {**loader_options, "format": "application/n-quads"},
                ),
                format="nquads",
            )
        except (JsonLdError, ValueError) as exc:
            return LinkedDataValidationResult(
                conforms=False,
                errors=[f"Failed to convert JSON-LD to RDF graph: {exc}"],
            )

        # Step 3: SHACL validation
        try:
            conforms, _graph, results_text = shacl_validate(
                data_graph,
                shacl_graph=self._shapes,
                ont_graph=ontology,
                inference="none",
                abort_on_first=False,
            )
        except ReportableRuntimeError as exc:
            return LinkedDataValidationResult(
                conforms=False,
                errors=[f"SHACL validation error: {exc}"],
            )

        if not conforms:
            errors.append(f"SHACL validation failed:\n{results_text}")

        return LinkedDataValidationResult(
            conforms=conforms,
            errors=errors,
        )
