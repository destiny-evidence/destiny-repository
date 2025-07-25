import uuid

import destiny_sdk


def test_es_parsing():
    """Test that the Reference model can be parsed from an Elasticsearch document."""
    es_reference = {
        "_index": "destiny-repository-staging-reference",
        "_id": "7c54f72e-8833-484f-9000-4f403b13a243",
        "_score": 1.7860229,
        "_ignored": ["enhancements.content.abstract.keyword"],
        "_source": {
            "visibility": "public",
            "identifiers": [
                {"identifier_type": "open_alex", "identifier": "W1234567890"},
                {"identifier_type": "doi", "identifier": "10.1234/sample"},
            ],
            "enhancements": [
                {
                    "visibility": "public",
                    "source": "dummy",
                    "robot_version": "dummy",
                    "content": {
                        "enhancement_type": "bibliographic",
                        "authorship": [
                            {
                                "display_name": "Future E. Foundation",
                                "orcid": "0000-0001-2345-6789",
                                "position": "first",
                            }
                        ],
                        "cited_by_count": 3,
                        "created_date": "2016-08-23",
                        "publication_date": "2016-08-01",
                        "publication_year": 2016,
                        "publisher": "Research for Dummies",
                        "title": "Research!",
                    },
                },
                {
                    "visibility": "public",
                    "source": "dummy",
                    "robot_version": "dummy",
                    "content": {
                        "enhancement_type": "abstract",
                        "process": "other",
                        "abstract": "We did research.",
                    },
                },
                {
                    "visibility": "public",
                    "source": "Toy Robot",
                    "robot_version": "0.1.0",
                    "content": {
                        "enhancement_type": "annotation",
                        "annotations": [
                            {
                                "annotation_type": "score",
                                "scheme": "meta:toy",
                                "label": "toy",
                                "score": 0.89,
                                "data": {"toy": "Bo Peep"},
                            }
                        ],
                    },
                },
            ],
        },
    }

    reference = destiny_sdk.references.Reference.from_es(es_reference)
    assert reference.id == uuid.UUID("7c54f72e-8833-484f-9000-4f403b13a243")
    assert reference.visibility == destiny_sdk.visibility.Visibility.PUBLIC
    assert len(reference.identifiers) == 2
    assert len(reference.enhancements) == 3
    assert reference.enhancements[0].reference_id == uuid.UUID(
        "7c54f72e-8833-484f-9000-4f403b13a243"
    )
