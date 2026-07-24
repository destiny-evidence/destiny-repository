"""Service for managing reference duplicate detection."""

from typing import Literal, assert_never
from uuid import UUID

from opentelemetry import trace

from app.core.config import DedupCandidateScoringConfig, Environment, get_settings
from app.core.exceptions import DeduplicationValueError
from app.core.telemetry.logger import get_logger
from app.domain.references.models.models import (
    Candidate,
    CandidateCanonicalSearchFields,
    CandidateCanonicalSearchQuery,
    CandidateElasticsearchRoute,
    CandidateIdentifier,
    CandidateIdentifierRoute,
    CandidateSelectionDiagnostics,
    CandidateSelectionInput,
    CandidateSelectionRequest,
    CandidateSelectionResult,
    DuplicateDetermination,
    EnhancementType,
    ExternalIdentifierType,
    GenericExternalIdentifier,
    IdentifierLookup,
    InputSearchability,
    Reference,
    ReferenceDuplicateDecision,
    ReferenceDuplicateDeterminationResult,
    RetrievalPolicyName,
    YearDecay,
)
from app.domain.references.models.projections import (
    CandidateReferenceProjection,
    ReferenceSearchFieldsProjection,
)
from app.domain.references.models.retrieval_policy import (
    RetrievalPolicy,
    YearStrategy,
    resolve_retrieval_policy,
)
from app.domain.references.services.anti_corruption_service import (
    ReferenceAntiCorruptionService,
)
from app.domain.service import GenericService
from app.persistence.es.uow import AsyncESUnitOfWork
from app.persistence.sql.uow import AsyncSqlUnitOfWork
from app.utils.regex import UNICODE_LETTER_PATTERN, is_meaningful_token

logger = get_logger(__name__)
settings = get_settings()
tracer = trace.get_tracer(__name__)

# ES does not index identifiers, so exact-identifier candidates come from Postgres.
_UNIONABLE_IDENTIFIER_TYPES = frozenset(
    {
        ExternalIdentifierType.DOI,
        ExternalIdentifierType.PM_ID,
        ExternalIdentifierType.OPEN_ALEX,
    }
)


def _candidate_author_terms(
    authors: list[str], *, scoring_config: DedupCandidateScoringConfig
) -> tuple[str, ...]:
    """Return bounded, deduplicated author terms for candidate retrieval."""
    queries: list[str] = []
    seen_terms: set[str] = set()
    for author in authors:
        tokens = [
            token
            for token in UNICODE_LETTER_PATTERN.findall(author)
            if is_meaningful_token(token, scoring_config.min_author_token_length)
        ]
        if not tokens:
            continue

        terms = " ".join(tokens)
        if terms in seen_terms:
            continue

        seen_terms.add(terms)
        queries.append(terms)
        if len(queries) >= scoring_config.max_author_clauses:
            break

    return tuple(queries)


def build_candidate_canonical_search_query(
    search_fields: CandidateCanonicalSearchFields,
    *,
    scoring_config: DedupCandidateScoringConfig,
    policy: RetrievalPolicy,
    reference_id: UUID | None,
) -> CandidateCanonicalSearchQuery:
    """Interpret a retrieval policy as a service-owned search specification."""
    if not search_fields.title:
        msg = "Candidate retrieval requires a title."
        raise DeduplicationValueError(msg)

    publication_year_decay: YearDecay | None = None
    match policy.year_strategy:
        case YearStrategy.HARD_WINDOW:
            publication_year_range = (
                (
                    search_fields.publication_year - 1,
                    search_fields.publication_year + 1,
                )
                if search_fields.publication_year
                else None
            )
        case YearStrategy.NO_FILTER:
            publication_year_range = None
        case YearStrategy.SOFT_DECAY:
            if policy.year_decay is None or not search_fields.publication_year:
                msg = "soft_year_decay requires a decay config and a publication year."
                raise DeduplicationValueError(msg)
            publication_year_range = None
            publication_year_decay = YearDecay(
                **policy.year_decay.model_dump(),
                origin=search_fields.publication_year,
            )
        case _:  # pragma: no cover - exhaustiveness guard
            assert_never(policy.year_strategy)

    return CandidateCanonicalSearchQuery(
        title=search_fields.title,
        title_fuzziness=policy.title_fuzziness,
        title_boost=2.0,
        title_operator="or",
        title_minimum_should_match="50%",
        author_terms=_candidate_author_terms(
            search_fields.authors, scoring_config=scoring_config
        ),
        # The best-matching author dominates; additional matches add 10% each.
        author_tie_breaker=0.1,
        publication_year_range=publication_year_range,
        publication_year_decay=publication_year_decay,
        # Prevent concurrently deduplicated references forming conflicting links.
        duplicate_determination=DuplicateDetermination.CANONICAL,
        excluded_reference_id=reference_id,
    )


def _unsearchable_reason(
    search_fields: CandidateCanonicalSearchFields, policy: RetrievalPolicy
) -> str:
    """Explain which Elasticsearch search fields are absent, per policy."""
    checks: list[tuple[str, object]] = [
        ("title", search_fields.title),
        ("authors", search_fields.authors),
    ]
    if policy.requires_publication_year:
        checks.append(("publication_year", search_fields.publication_year))
    missing = [name for name, value in checks if not value]
    return (
        f"Not searchable via Elasticsearch (missing: {', '.join(missing)}); "
        "exact identifier matches, if any, are still returned."
    )


def _searchability_reason(
    search_fields: CandidateCanonicalSearchFields,
    policy: RetrievalPolicy,
    *,
    searchable: bool,
) -> str:
    """Reason string separating year-absent-but-permitted from ordinary cases."""
    if not searchable:
        return _unsearchable_reason(search_fields, policy)
    if search_fields.publication_year is None:
        return (
            f"searchable: publication_year absent, not required by "
            f"policy '{policy.name}'"
        )
    return "ok"


class DeduplicationService(GenericService[ReferenceAntiCorruptionService]):
    """Service for managing reference duplicate detection."""

    def __init__(
        self,
        anti_corruption_service: ReferenceAntiCorruptionService,
        sql_uow: AsyncSqlUnitOfWork,
        es_uow: AsyncESUnitOfWork,
    ) -> None:
        """Initialize the service with a unit of work."""
        super().__init__(anti_corruption_service, sql_uow, es_uow)

    async def get_deduplication_candidates(
        self, request: CandidateSelectionRequest
    ) -> CandidateSelectionResult:
        """
        Retrieve ranked candidate canonicals for a reference, without persisting.

        Read-only evaluation surface for deduplication candidate retrieval: it runs
        the shared Elasticsearch candidate query and, optionally, unions exact
        identifier matches from Postgres, returning route provenance and retrieval
        diagnostics. It writes no duplicate-decision or candidate state.
        """
        k = request.k or settings.dedup_scoring.candidate_k
        policy = resolve_retrieval_policy(request.retrieval_policy)

        (
            search_fields,
            self_id,
            identifier_lookups,
        ) = await self._resolve_candidate_selection_input(request.input)

        # Exact identifier matching does not depend on bibliographic searchability;
        # it is the route for records that fail the ES searchability gate, so it runs
        # regardless of it.
        identifier_matches: dict[UUID, dict[tuple, CandidateIdentifier]] = {}
        if policy.union_identifiers and identifier_lookups:
            identifier_matches = await self._union_identifier_matches(
                identifier_lookups, self_id=self_id
            )

        # The ES candidate query and its index-version stamp are only meaningful for
        # searchable inputs.
        searchable = policy.is_input_searchable(search_fields)
        es_result = None
        index_version = None
        if searchable:
            index_version = await self.es_uow.references.get_current_index_name()
            query = build_candidate_canonical_search_query(
                search_fields,
                scoring_config=settings.dedup_scoring,
                policy=policy,
                reference_id=self_id,
            )
            es_result = await self.es_uow.references.search_for_candidate_canonicals(
                query,
                k=k,
                # Exact total for reporting by default; callers benchmarking
                # throughput pass false for the production-cost proxy.
                track_total_hits=request.track_total_hits,
            )

        es_hits = es_result.hits if es_result else []
        es_scores = {hit.id: hit.score for hit in es_hits}
        es_ranks = {hit.id: rank for rank, hit in enumerate(es_hits, start=1)}

        # Identifier-only matches rank ahead of ES-scored matches for evaluator
        # visibility; everything carrying an ES score follows in score order.
        identifier_only_ids = [
            cid for cid in identifier_matches if cid not in es_scores
        ]
        ordered_ids = identifier_only_ids + [hit.id for hit in es_hits]

        hydrated_by_id: dict[UUID, Reference] = {}
        if request.hydrate and ordered_ids:
            hydrated = await self.sql_uow.references.get_hydrated(
                ordered_ids, enhancement_types=[EnhancementType.BIBLIOGRAPHIC]
            )
            hydrated_by_id = {reference.id: reference for reference in hydrated}

        candidates = []
        for rank, cid in enumerate(ordered_ids, start=1):
            routes: list[CandidateElasticsearchRoute | CandidateIdentifierRoute] = []
            if cid in es_scores:
                routes.append(
                    CandidateElasticsearchRoute(
                        policy=policy.name,
                        rank=es_ranks[cid],
                        score=es_scores[cid],
                    )
                )
            if cid in identifier_matches:
                routes.append(
                    CandidateIdentifierRoute(
                        matched_identifiers=list(identifier_matches[cid].values())
                    )
                )
            candidates.append(
                Candidate(
                    reference_id=cid,
                    rank=rank,
                    routes=routes,
                    reference=CandidateReferenceProjection.get_from_reference(
                        hydrated_by_id[cid]
                    )
                    if request.hydrate and cid in hydrated_by_id
                    else None,
                )
            )

        es_returned = len(es_hits)
        return CandidateSelectionResult(
            retrieval_policy=policy.name,
            index_version=index_version,
            k_requested=k,
            input_searchability=InputSearchability(
                searchable=searchable,
                reason=_searchability_reason(
                    search_fields, policy, searchable=searchable
                ),
            ),
            diagnostics=CandidateSelectionDiagnostics(
                es_took_ms=es_result.took_ms if es_result else None,
                es_total_hits=es_result.total.value if es_result else None,
                es_returned=es_returned,
                identifier_returned=len(identifier_matches),
                candidate_count=len(ordered_ids),
                truncated=(es_result.total.value > es_returned) if es_result else False,
                kth_es_score=es_hits[k - 1].score if es_returned >= k else None,
                lowest_es_score=es_hits[-1].score if es_hits else None,
            ),
            candidates=candidates,
        )

    async def _resolve_candidate_selection_input(
        self, input_: CandidateSelectionInput
    ) -> tuple[CandidateCanonicalSearchFields, UUID | None, list[IdentifierLookup]]:
        """Resolve request input into search fields, a self-id, and id lookups."""
        if input_.reference_id is not None:
            reference = await self.sql_uow.references.get_by_pk(
                input_.reference_id, preload=["enhancements", "identifiers"]
            )
            search_fields = (
                ReferenceSearchFieldsProjection.get_canonical_candidate_search_fields(
                    reference
                )
            )
            lookups = [
                IdentifierLookup.from_specific(linked.identifier)
                for linked in (reference.identifiers or [])
                if linked.identifier.identifier_type in _UNIONABLE_IDENTIFIER_TYPES
            ]
            return search_fields, reference.id, lookups

        search_fields = CandidateCanonicalSearchFields(
            title=input_.title,
            authors=input_.authors,
            publication_year=input_.publication_year,
        )
        lookups = [
            self._identifier_lookup_from_candidate(identifier)
            for identifier in input_.identifiers
            if identifier.identifier_type in _UNIONABLE_IDENTIFIER_TYPES
        ]
        return search_fields, None, lookups

    @staticmethod
    def _identifier_lookup_from_candidate(
        identifier: CandidateIdentifier,
    ) -> IdentifierLookup:
        """Normalise an input identifier into a lookup, canonicalising its value."""
        try:
            return IdentifierLookup.from_generic(identifier)
        except ValueError as exc:
            msg = f"Invalid identifier for candidate selection: {identifier.identifier}"
            raise DeduplicationValueError(msg) from exc

    async def _union_identifier_matches(
        self,
        lookups: list[IdentifierLookup],
        *,
        self_id: UUID | None,
    ) -> dict[UUID, dict[tuple, CandidateIdentifier]]:
        """Exact-match identifiers in Postgres, resolved to canonical candidates."""
        matched_references = await self.sql_uow.references.find_with_identifiers(
            lookups,
            preload=["identifiers", "duplicate_decision"],
            match="any",
        )
        query_keys = {(lookup.identifier_type, lookup.identifier) for lookup in lookups}
        matches: dict[UUID, dict[tuple, CandidateIdentifier]] = {}
        for reference in matched_references:
            if reference.id == self_id:
                continue
            # Unlike the ES query, this read-only path does not restrict to
            # CANONICAL-at-rest references: that filter guards a nomination write
            # race we don't have, so an exact identifier match is surfaced whatever
            # its dedup state. A match on a duplicate resolves to its canonical,
            # which may be a different, older reference outside the queried set.
            if reference.is_canonical_like:
                canonical_id = reference.id
            elif (
                reference.duplicate_decision
                and reference.duplicate_decision.canonical_reference_id
            ):
                canonical_id = reference.duplicate_decision.canonical_reference_id
            else:
                msg = (
                    "Identifier match is a determined duplicate without a canonical "
                    "reference id. This should not happen."
                )
                raise RuntimeError(msg)
            if canonical_id == self_id:
                continue
            bucket = matches.setdefault(canonical_id, {})
            for linked in reference.identifiers or []:
                key = (
                    linked.identifier.identifier_type,
                    str(linked.identifier.identifier),
                )
                if key in query_keys:
                    bucket[key] = CandidateIdentifier.from_specific(linked.identifier)
        return matches

    async def find_exact_duplicate(self, reference: Reference) -> Reference | None:
        """
        Find exact duplicate references for the given reference.

        This is *not* part of the regular deduplication flow but is used to circumvent
        importing and processing redundant references.

        Exact duplicates are defined in
        :attr:`app.domain.references.models.models.Reference.is_superset()`.
        A reference may have more than one exact duplicate, this just returns the first.

        :param reference: The reference to find duplicates for.
        :type reference: app.domain.references.models.models.Reference
        :return: The supersetting reference, or None if no duplicate was found.
        :rtype: app.domain.references.models.models.Reference | None
        """
        if not reference.identifiers:
            msg = "Reference must have identifiers to find duplicates."
            raise DeduplicationValueError(msg)

        # We can't be sure of low cardinality on "other" identifiers, so make sure
        # there's at least one defined identifier type.
        if not any(
            identifier.identifier.identifier_type != ExternalIdentifierType.OTHER
            for identifier in reference.identifiers
        ):
            logger.warning(
                "Reference did not have any non-other identifiers, exact duplicate "
                "search skipped."
            )
            return None

        # Find candidates using only non-"other" identifiers. The "other" type
        # index (ix_external_identifier_type_other) has poor selectivity at scale,
        # causing multi-second scans. is_superset validates the full match. (#604)
        candidates = await self.sql_uow.references.find_with_identifiers(
            [
                GenericExternalIdentifier.from_specific(identifier.identifier)
                for identifier in reference.identifiers
                if identifier.identifier.identifier_type != ExternalIdentifierType.OTHER
            ],
            preload=["identifiers", "enhancements", "duplicate_decision"],
        )

        # Now, find if any candidates are perfect supersets of the new reference.
        # Try canonical references first to form a nicer tree, but it's
        # not super important.
        for candidate in sorted(
            candidates,
            key=lambda candidate: (
                1
                if candidate.is_canonical is True
                else 0
                if candidate.is_canonical is False
                else -1
            ),
            reverse=True,
        ):
            if candidate.is_superset(reference):
                return candidate
        return None

    async def register_duplicate_decision_for_reference(
        self,
        reference_id: UUID,
        enhancement_id: UUID | None = None,
        duplicate_determination: Literal[DuplicateDetermination.EXACT_DUPLICATE]
        | None = None,
        canonical_reference_id: UUID | None = None,
    ) -> ReferenceDuplicateDecision:
        """
        Register a duplicate decision for a reference.

        :param reference: The reference to register the duplicate decision for.
        :type reference: app.domain.references.models.models.Reference
        :param enhancement_id: The enhancement ID triggering with the duplicate
            decision, defaults to None
        :type enhancement_id: UUID | None, optional
        :param duplicate_determination: Flag indicating if a reference was an exact
            duplicate and not imported, defaults to None
        :type duplicate_determination: Literal[DuplicateDetermination.EXACT_DUPLICATE]
            | None, optional
        :param canonical_reference_id: The canonical reference ID this reference is an
            exact duplicate of, defaults to None
        :type canonical_reference_id: UUID | None, optional
        :return: The registered duplicate decision
        :rtype: ReferenceDuplicateDecision
        """
        if (duplicate_determination is not None) != (
            canonical_reference_id is not None
        ):
            msg = (
                "Both or neither of duplicate_determination and "
                "canonical_reference_id must be provided."
            )
            raise DeduplicationValueError(msg)
        _duplicate_determination = (
            duplicate_determination
            if duplicate_determination
            else DuplicateDetermination.PENDING
        )
        reference_duplicate_decision = ReferenceDuplicateDecision(
            reference_id=reference_id,
            enhancement_id=enhancement_id,
            duplicate_determination=_duplicate_determination,
            canonical_reference_id=canonical_reference_id,
            # If exact duplicate passed in, the decision is terminal and hence active
            active_decision=_duplicate_determination
            == DuplicateDetermination.EXACT_DUPLICATE,
        )
        return await self.sql_uow.reference_duplicate_decisions.add(
            reference_duplicate_decision
        )

    async def nominate_candidate_canonicals(
        self, reference_duplicate_decision: ReferenceDuplicateDecision
    ) -> ReferenceDuplicateDecision:
        """
        Nominate candidate canonical references for the given decision.

        This uses the control retrieval policy's search strategy.

        :param reference_duplicate_decision: The decision to find candidates for.
        :type reference_duplicate_decision: ReferenceDuplicateDecision
        :return: The updated decision with candidate IDs and status.
        :rtype: ReferenceDuplicateDecision
        """
        if not settings.feature_flags.enable_canonical_candidate_search:
            return await self.sql_uow.reference_duplicate_decisions.update_by_pk(
                reference_duplicate_decision.id,
                duplicate_determination=DuplicateDetermination.UNSEARCHABLE,
                detail="Canonical candidate search is disabled.",
            )

        reference = await self.sql_uow.references.get_by_pk(
            reference_duplicate_decision.reference_id,
            preload=["enhancements", "identifiers"],
        )

        search_fields = (
            ReferenceSearchFieldsProjection.get_canonical_candidate_search_fields(
                reference
            )
        )

        if not search_fields.is_searchable:
            return await self.sql_uow.reference_duplicate_decisions.update_by_pk(
                reference_duplicate_decision.id,
                duplicate_determination=DuplicateDetermination.UNSEARCHABLE,
            )
        # The candidate depth here preserves this path's historical behaviour; the
        # production K is chosen by the recall@K evaluation, not this path.
        query = build_candidate_canonical_search_query(
            search_fields,
            scoring_config=settings.dedup_scoring,
            policy=resolve_retrieval_policy(RetrievalPolicyName.CURRENT_FUZZY_V1),
            reference_id=reference.id,
        )
        search_result = await self.es_uow.references.search_for_candidate_canonicals(
            query,
            k=10,
        )

        if not search_result.hits:
            reference_duplicate_decision = (
                await self.sql_uow.reference_duplicate_decisions.update_by_pk(
                    reference_duplicate_decision.id,
                    # This should simplify to CANONICAL only once the search strategy is
                    # implemented and evaluated.
                    duplicate_determination=DuplicateDetermination.CANONICAL
                    if settings.env == Environment.TEST
                    else DuplicateDetermination.UNSEARCHABLE,
                )
            )
        else:
            # Is there a search result score that would be enough for us to mark as
            # duplicate without proceeding to the next step?
            reference_duplicate_decision = (
                await self.sql_uow.reference_duplicate_decisions.update_by_pk(
                    reference_duplicate_decision.id,
                    candidate_canonical_ids=[
                        result.id for result in search_result.hits
                    ],
                    duplicate_determination=DuplicateDetermination.NOMINATED,
                )
            )

        return reference_duplicate_decision

    async def __placeholder_duplicate_determinator(
        self, reference_duplicate_decision: ReferenceDuplicateDecision
    ) -> ReferenceDuplicateDeterminationResult:
        """
        Implement a basic placeholder duplicate determinator.

        Temporary implementation: takes the first candidate as the duplicate.
        This is the one with the highest score in the candidate nomination stage.
        This completes the flow but should not be used in production.

        :param reference_duplicate_decision: The decision to determine duplicates for.
        :type reference_duplicate_decision: ReferenceDuplicateDecision
        :return: The result of the duplicate determination.
        :rtype: ReferenceDuplicateDeterminationResult
        """
        return (
            ReferenceDuplicateDeterminationResult(
                duplicate_determination=DuplicateDetermination.DUPLICATE,
                canonical_reference_id=reference_duplicate_decision.candidate_canonical_ids[
                    0
                ],
            )
            if settings.env == Environment.TEST
            and reference_duplicate_decision.candidate_canonical_ids
            else ReferenceDuplicateDeterminationResult(
                duplicate_determination=DuplicateDetermination.UNSEARCHABLE,
                detail="Placeholder duplicate determinator used.",
            )
        )

    async def determine_canonical_from_candidates(
        self, reference_duplicate_decision: ReferenceDuplicateDecision
    ) -> ReferenceDuplicateDecision:
        """
        Determine a canonical reference from its candidates.

        :param reference_duplicate_decision: The decision to determine duplicates for.
        :type reference_duplicate_decision: ReferenceDuplicateDecision
        :return: The updated decision with the determination result.
        :rtype: ReferenceDuplicateDecision
        """
        if (
            reference_duplicate_decision.duplicate_determination
            in DuplicateDetermination.get_terminal_states()
        ):
            return reference_duplicate_decision

        duplicate_determination_result = (
            await self.__placeholder_duplicate_determinator(
                reference_duplicate_decision
            )
        )

        return await self.sql_uow.reference_duplicate_decisions.update_by_pk(
            reference_duplicate_decision.id,
            detail=duplicate_determination_result.detail,
            duplicate_determination=duplicate_determination_result.duplicate_determination,
            canonical_reference_id=duplicate_determination_result.canonical_reference_id,
        )

    async def map_duplicate_decision(
        self,
        new_decision: ReferenceDuplicateDecision,
        *,
        allow_destructive_decision: bool = False,
    ) -> tuple[ReferenceDuplicateDecision, bool, ReferenceDuplicateDecision | None]:
        """
        Apply the persistence changes from the new duplicate decision.

        If the new decision is not terminal, it is not made active.

        :param new_decision: The new decision to apply.
        :type new_decision: ReferenceDuplicateDecision
        :param allow_destructive_decision: If True, bypass the conflict check that
            would otherwise create a DECOUPLED decision. Used by the manual
            endpoint.
        :type allow_destructive_decision: bool
        :return: The applied decision, whether it changed, and the previous active
            decision (now deactivated) if one existed.
        :rtype: tuple[ReferenceDuplicateDecision, bool,
            ReferenceDuplicateDecision | None]
        """
        if (
            new_decision.duplicate_determination
            not in DuplicateDetermination.get_terminal_states()
        ):
            msg = "Only terminal duplicate determinations can be mapped."
            raise DeduplicationValueError(msg)

        if new_decision.canonical_reference_id:
            if new_decision.canonical_reference_id == new_decision.reference_id:
                msg = "Cannot mark a reference as a duplicate of itself."
                raise DeduplicationValueError(msg)

            canonical_ref = await self.sql_uow.references.get_by_pk(
                new_decision.canonical_reference_id,
                preload=["duplicate_decision", "canonical_reference"],
            )
            if not canonical_ref.is_canonical:
                non_canonical_determination = (
                    canonical_ref.duplicate_decision.duplicate_determination
                    if canonical_ref.duplicate_decision
                    else "none"
                )
                msg = (
                    "Cannot mark as duplicate of a non-canonical reference. "
                    f"Reference {new_decision.canonical_reference_id} has "
                    f"active determination: {non_canonical_determination}."
                )
                raise DeduplicationValueError(msg)

        reference = await self.sql_uow.references.get_by_pk(
            new_decision.reference_id,
            preload=["duplicate_decision", "duplicate_references"],
        )
        active_decision = reference.duplicate_decision

        # Preset to True, will be flipped if not changed
        decision_changed = True

        if (
            active_decision
            and active_decision.duplicate_determination
            == DuplicateDetermination.DUPLICATE
            and (
                # Duplicate is becoming canonical
                new_decision.duplicate_determination == DuplicateDetermination.CANONICAL
                or (
                    # Duplicate changes canonical reference
                    new_decision.duplicate_determination
                    == DuplicateDetermination.DUPLICATE
                    and active_decision.canonical_reference_id
                    != new_decision.canonical_reference_id
                )
            )
            and not allow_destructive_decision
        ):
            # Destructive change to the old canonical reference which now loses
            # a duplicate. Raise for manual review of the decision and the implications.
            new_decision.duplicate_determination = DuplicateDetermination.DECOUPLED
            new_decision.detail = (
                "Decouple reason: Existing duplicate decision changed. "
                + (new_decision.detail if new_decision.detail else "")
            )
        elif (
            new_decision.duplicate_determination == DuplicateDetermination.DUPLICATE
            and reference.has_duplicates
        ):
            # A canonical reference with duplicates has been flagged as a duplicate.
            # A future implementation may merge duplicate trees here, for now let's flag
            # for manual review.
            new_decision.duplicate_determination = DuplicateDetermination.DECOUPLED
            new_decision.detail = (
                "Decouple reason: Reference has existing duplicates and cannot "
                "become a duplicate itself. Remap existing duplicates before retrying. "
                + (new_decision.detail if new_decision.detail else "")
            )
        else:
            if active_decision:
                if (
                    active_decision.duplicate_determination
                    == new_decision.duplicate_determination
                    and active_decision.canonical_reference_id
                    == new_decision.canonical_reference_id
                ):
                    decision_changed = False
                active_decision.active_decision = False
            new_decision.active_decision = True

        # Update in-place, it's just easier
        if active_decision:
            await self.sql_uow.reference_duplicate_decisions.merge(active_decision)
        new_decision = await self.sql_uow.reference_duplicate_decisions.merge(
            new_decision
        )

        return new_decision, decision_changed, active_decision

    async def shortcut_deduplication_using_identifiers(  # noqa: PLR0912
        self,
        reference_duplicate_decision: ReferenceDuplicateDecision,
        trusted_unique_identifier_types: set[ExternalIdentifierType],
    ) -> list[ReferenceDuplicateDecision] | None:
        """
        Deduplicate the given reference using trusted unique identifiers.

        This shortcuts the regular deduplication flow and is only run on import.

        This is a very powerful operation and should only be used with identifier types
        that are certain to be unique and reliable. Misuse can lead to incorrect
        duplicate relationships that are hard to correct.

        The search will likely return multiple references ("candidates"),
        to be handled by:

        **Terminal Cases:**

        **A.** If they all belong to the same duplicate relationship graph, the given
        reference will be marked as duplicate of that graph's canonical reference.

        **B.** If they belong to more than one duplicate relationship graph, the given
        reference is marked as decoupled for manual review, as it indicates disconnected
        duplicate relationship graphs and undermines the assumption of the shortcut.

        **C.** If none of them belong to a duplicate relationship graph, the given
        reference becomes the canonical of a new duplicate relationship graph including
        all candidates.

        **D.** If some of them belong to a single duplicate relationship graph and some
        don't, the non-graph references are marked as duplicates of the canonical of
        the graph.


        **Non-terminal Cases:**

        **E.** Finally, if the given reference has no trusted identifiers or no
        candidates are found, no action is taken and regular deduplication continues.


        :param reference: The reference to deduplicate.
        :type reference: app.domain.references.models.models.Reference
        :param trusted_unique_identifier_types: The identifier types considered
            trusted unique identifiers.
        :type trusted_unique_identifier_types: set[ExternalIdentifierType]
        :return: The generated duplicate decisions, if any.
        :rtype: list[ReferenceDuplicateDecision] | None
        """
        if reference_duplicate_decision.duplicate_determination != (
            DuplicateDetermination.PENDING
        ):
            msg = "Shortcut deduplication can only be run on pending decisions."
            raise DeduplicationValueError(msg)

        reference = await self.sql_uow.references.get_by_pk(
            reference_duplicate_decision.reference_id,
            preload=["identifiers", "duplicate_decision"],
        )
        if not reference.identifiers:
            # No identifiers so we can't deduplicate
            return None

        trusted_identifiers = [
            GenericExternalIdentifier.from_specific(identifier.identifier)
            for identifier in reference.identifiers
            if identifier.identifier.identifier_type in trusted_unique_identifier_types
        ]
        candidates = await self.sql_uow.references.find_with_identifiers(
            trusted_identifiers,
            preload=["duplicate_decision"],
            match="any",
        )
        candidates = [
            candidate for candidate in candidates if candidate.id != reference.id
        ]
        if not candidates:
            if not trusted_identifiers:
                # No trusted identifiers to shortcut with, fall through to ES
                return None
            # Has trusted identifiers but no existing matches - new unique reference
            # Skip ES deduplication entirely since the trusted identifier guarantees
            # uniqueness within its source (e.g., OpenAlex W-ID)
            reference_duplicate_decision.duplicate_determination = (
                DuplicateDetermination.CANONICAL
            )
            reference_duplicate_decision.detail = (
                "New reference with trusted identifier(s), no existing matches"
            )
            reference_duplicate_decision, _, _ = await self.map_duplicate_decision(
                reference_duplicate_decision
            )
            return [reference_duplicate_decision]

        canonical_ids, undeduplicated_ids = set(), set()
        for candidate in candidates:
            if (
                not candidate.duplicate_decision
                or candidate.duplicate_decision.duplicate_determination
                == DuplicateDetermination.UNSEARCHABLE
            ):
                undeduplicated_ids.add(candidate.id)
            elif candidate.is_canonical:
                canonical_ids.add(candidate.id)
            elif candidate.duplicate_decision.canonical_reference_id:
                # Duplicate — use the decision's direct canonical reference ID
                canonical_ids.add(candidate.duplicate_decision.canonical_reference_id)

        if len(canonical_ids) > 1:
            return [
                await self.sql_uow.reference_duplicate_decisions.update_by_pk(
                    reference_duplicate_decision.id,
                    duplicate_determination=DuplicateDetermination.DECOUPLED,
                    detail=(
                        "Multiple canonical references found for trusted unique "
                        "identifiers. This may indicate we have disconnected duplicate "
                        "relationship graphs. Manual review required. Canonical IDs: "
                        f"{', '.join(
                            str(canonical_id) for canonical_id in canonical_ids
                        )}"
                    ),
                )
            ]

        if not canonical_ids:
            # No canonicals found, make this reference the canonical
            canonical_id = reference.id
            reference_duplicate_decision.duplicate_determination = (
                DuplicateDetermination.CANONICAL
            )
            reference_duplicate_decision.detail = (
                "Shortcutted with trusted identifier(s)"
            )

            reference_duplicate_decision, _, _ = await self.map_duplicate_decision(
                reference_duplicate_decision
            )
        else:
            # Exactly one canonical found, make this reference a duplicate of it
            canonical_id = canonical_ids.pop()
            reference_duplicate_decision.duplicate_determination = (
                DuplicateDetermination.DUPLICATE
            )
            reference_duplicate_decision.canonical_reference_id = canonical_id
            reference_duplicate_decision.detail = (
                "Shortcutted with trusted identifier(s)"
            )
            reference_duplicate_decision, _, _ = await self.map_duplicate_decision(
                reference_duplicate_decision
            )

        # Map any undeduplicated candidates as duplicates of the canonical
        # Guard: bulk-fetch active decisions to skip candidates another worker
        # already decided. Uses a scalar SELECT to bypass the ORM identity map
        # and see the latest committed state under READ COMMITTED.
        # UNSEARCHABLE decisions are not skipped — they should be pulled into
        # the duplicate graph.
        dedup_repo = self.sql_uow.reference_duplicate_decisions
        existing_decisions = await dedup_repo.get_active_decision_determinations(
            undeduplicated_ids
        )

        side_effect_decisions = []
        for candidate_id in undeduplicated_ids:
            existing_determination = existing_decisions.get(candidate_id)
            if (
                existing_determination is not None
                and existing_determination != DuplicateDetermination.UNSEARCHABLE
            ):
                logger.info(
                    "Candidate already has active non-UNSEARCHABLE "
                    "decision, skipping side-effect.",
                    candidate_id=str(candidate_id),
                    existing_determination=existing_determination,
                )
                continue

            decision, _, _ = await self.map_duplicate_decision(
                ReferenceDuplicateDecision(
                    reference_id=candidate_id,
                    duplicate_determination=DuplicateDetermination.DUPLICATE,
                    canonical_reference_id=canonical_id,
                    active_decision=True,
                    detail=(
                        f"Shortcutted via proxy reference {reference.id} "
                        "with trusted identifier(s)"
                    ),
                )
            )
            side_effect_decisions.append(decision)

        return [reference_duplicate_decision, *side_effect_decisions]
