--
-- PostgreSQL database dump
--

-- Dumped from database version 17.6 (Debian 17.6-1.pgdg13+1)
-- Dumped by pg_dump version 17.2

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: batch_enhancement_request; Type: TABLE DATA; Schema: public; Owner: localuser
--

COPY public.batch_enhancement_request (reference_ids, robot_id, request_status, enhancement_parameters, error, id, created_at, updated_at, reference_data_file, result_file, validation_result_file, source) FROM stdin;
{53750d62-5c92-4452-ac39-c8ad1cfa1869,bfacd10f-4f37-4726-b4a7-b94fe5f8fe51,e2277656-4930-4c5a-8718-c3eb422385bb}	cb73f9a3-af2a-4bfa-9502-f61d5fe18b11	completed	null	\N	e041edff-7dda-4027-833b-11a1519c85ed	2025-08-24 23:22:57.607468+00	2025-08-24 23:22:57.73667+00	minio://destiny-repository/batch_enhancement_request_reference_data/e041edff-7dda-4027-833b-11a1519c85ed.jsonl	minio://destiny-repository/batch_enhancement_result/e041edff-7dda-4027-833b-11a1519c85ed_robot.jsonl	minio://destiny-repository/batch_enhancement_result/e041edff-7dda-4027-833b-11a1519c85ed_repo.jsonl	BatchEnhancementRequest:8d02e4c6-bf02-40a3-973a-39c6d5b864b4
{94cc5574-7f0f-4e3f-a3a2-df3df7a0effb,dbe0c689-8cf2-4c50-80de-fa6c873333ed}	cb73f9a3-af2a-4bfa-9502-f61d5fe18b11	completed	null	\N	ce6d68fb-1b24-4304-80d1-aac18a8d15eb	2025-08-24 23:22:57.279554+00	2025-08-24 23:22:57.522253+00	minio://destiny-repository/batch_enhancement_request_reference_data/ce6d68fb-1b24-4304-80d1-aac18a8d15eb.jsonl	minio://destiny-repository/batch_enhancement_result/ce6d68fb-1b24-4304-80d1-aac18a8d15eb_robot.jsonl	minio://destiny-repository/batch_enhancement_result/ce6d68fb-1b24-4304-80d1-aac18a8d15eb_repo.jsonl	ImportBatch:dcb831e0-1315-4825-9d03-4fbd5838d0e2
{53750d62-5c92-4452-ac39-c8ad1cfa1869,bfacd10f-4f37-4726-b4a7-b94fe5f8fe51,e2277656-4930-4c5a-8718-c3eb422385bb}	dda2bbb2-2fa2-4dda-859e-8ef3f9e76c49	completed	null	\N	8d02e4c6-bf02-40a3-973a-39c6d5b864b4	2025-08-24 23:22:57.476149+00	2025-08-24 23:22:57.596465+00	minio://destiny-repository/batch_enhancement_request_reference_data/8d02e4c6-bf02-40a3-973a-39c6d5b864b4.jsonl	minio://destiny-repository/batch_enhancement_result/8d02e4c6-bf02-40a3-973a-39c6d5b864b4_robot.jsonl	minio://destiny-repository/batch_enhancement_result/8d02e4c6-bf02-40a3-973a-39c6d5b864b4_repo.jsonl	\N
\.


--
-- Data for Name: reference; Type: TABLE DATA; Schema: public; Owner: localuser
--

COPY public.reference (visibility, id, created_at, updated_at) FROM stdin;
public	53750d62-5c92-4452-ac39-c8ad1cfa1869	2025-08-24 23:22:51.595397+00	2025-08-24 23:22:51.595402+00
restricted	bfacd10f-4f37-4726-b4a7-b94fe5f8fe51	2025-08-24 23:22:51.629774+00	2025-08-24 23:22:51.62978+00
public	68a835f7-d5d0-4f8a-8c24-322f25460dca	2025-08-24 23:22:51.645195+00	2025-08-24 23:22:51.645199+00
public	e2277656-4930-4c5a-8718-c3eb422385bb	2025-08-24 23:22:51.66595+00	2025-08-24 23:22:51.665956+00
public	94cc5574-7f0f-4e3f-a3a2-df3df7a0effb	2025-08-24 23:22:51.677673+00	2025-08-24 23:22:51.677676+00
hidden	dbe0c689-8cf2-4c50-80de-fa6c873333ed	2025-08-24 23:22:51.68658+00	2025-08-24 23:22:51.686583+00
public	59d19872-380b-428d-9e12-c0bf2682f6cb	2025-08-24 23:22:55.131432+00	2025-08-24 23:22:55.131436+00
public	23f552f5-833f-4ce4-b3d8-ba1932340e0b	2025-08-24 23:22:55.149103+00	2025-08-24 23:22:55.149105+00
public	f6e488b6-7d86-4ca1-85f5-c71c27176b6b	2025-08-24 23:22:55.157869+00	2025-08-24 23:22:55.15787+00
public	b9db25d5-febb-48b4-896a-dcbc8455c492	2025-08-24 23:22:55.162435+00	2025-08-24 23:22:55.162436+00
\.


--
-- Data for Name: enhancement; Type: TABLE DATA; Schema: public; Owner: localuser
--

COPY public.enhancement (visibility, source, reference_id, enhancement_type, robot_version, content, id, created_at, updated_at, derived_from) FROM stdin;
public	openalex	53750d62-5c92-4452-ac39-c8ad1cfa1869	bibliographic	\N	{"title": null, "publisher": "Example Publisher", "authorship": [{"orcid": "0000-0001-2345-6789", "position": "first", "display_name": "Alice Example"}], "created_date": "2020-05-01", "cited_by_count": 10, "enhancement_type": "bibliographic", "publication_date": "2020-04-01", "publication_year": 2020}	8de0e437-8180-42ad-ae9b-be54bc0eec11	2025-08-24 23:22:51.597447+00	2025-08-24 23:22:51.59745+00	\N
public	user	68a835f7-d5d0-4f8a-8c24-322f25460dca	annotation	\N	{"annotations": [{"data": {"score": 0.95}, "label": "Sample Tag", "score": null, "value": true, "scheme": "custom:tag", "annotation_type": "boolean"}], "enhancement_type": "annotation"}	320d26f4-dafe-418f-a06f-5d784f879234	2025-08-24 23:22:51.646143+00	2025-08-24 23:22:51.646149+00	\N
public	openalex	68a835f7-d5d0-4f8a-8c24-322f25460dca	location	\N	{"locations": [{"extra": {"note": "sample location"}, "is_oa": true, "license": "cc-by", "pdf_url": "https://example.com/document.pdf", "version": "publishedVersion", "landing_page_url": "https://example.com/landing"}], "enhancement_type": "location"}	5fa472b2-f617-4be7-8b96-9ff079eab737	2025-08-24 23:22:51.646151+00	2025-08-24 23:22:51.646151+00	\N
public	openalex	68a835f7-d5d0-4f8a-8c24-322f25460dca	bibliographic	\N	{"title": null, "publisher": "Another Publisher", "authorship": [{"orcid": "0000-0002-3456-7890", "position": "last", "display_name": "Bob Reviewer"}], "created_date": "2021-01-01", "cited_by_count": 5, "enhancement_type": "bibliographic", "publication_date": "2020-12-01", "publication_year": 2020}	ae2a5782-0c59-4e0a-b8fc-66930ca77a37	2025-08-24 23:22:51.646151+00	2025-08-24 23:22:51.646152+00	\N
public	openalex	e2277656-4930-4c5a-8718-c3eb422385bb	location	\N	{"locations": [{"extra": {"note": "sample location"}, "is_oa": true, "license": "cc-by", "pdf_url": "https://example.com/document.pdf", "version": "publishedVersion", "landing_page_url": "https://example.com/landing"}], "enhancement_type": "location"}	32d3e5de-654e-409d-837d-b87d2e56600f	2025-08-24 23:22:51.666696+00	2025-08-24 23:22:51.6667+00	\N
public	manual	e2277656-4930-4c5a-8718-c3eb422385bb	abstract	\N	{"process": "closed_api", "abstract": "This abstract is added.", "enhancement_type": "abstract"}	639124d6-98d5-4662-98fa-531fb519cde1	2025-08-24 23:22:51.666701+00	2025-08-24 23:22:51.666701+00	\N
public	manual	59d19872-380b-428d-9e12-c0bf2682f6cb	annotation	\N	{"annotations": [{"data": {}, "label": "Merged", "score": null, "value": true, "scheme": "custom:tag", "annotation_type": "boolean"}], "enhancement_type": "annotation"}	30b040e0-d1f5-491e-a46b-9cf29e306b80	2025-08-24 23:22:55.132513+00	2025-08-24 23:22:55.132516+00	\N
public	openalex	f6e488b6-7d86-4ca1-85f5-c71c27176b6b	location	\N	{"locations": [{"extra": {"note": "sample location"}, "is_oa": true, "license": "cc-by", "pdf_url": "https://example.com/document.pdf", "version": "publishedVersion", "landing_page_url": "https://example.com/landing"}], "enhancement_type": "location"}	c8113843-c56f-4378-b974-6d22caff6e9e	2025-08-24 23:22:55.158136+00	2025-08-24 23:22:55.158137+00	\N
restricted	reviewer	bfacd10f-4f37-4726-b4a7-b94fe5f8fe51	annotation	\N	{"annotations": [{"data": {}, "label": "Revised", "score": null, "value": true, "scheme": "custom:note", "annotation_type": "boolean"}], "enhancement_type": "annotation"}	3511ef3e-7aea-4b14-a061-3096966fd0ce	2025-08-24 23:22:51.633852+00	2025-08-24 23:22:55.863421+00	\N
restricted	manual	bfacd10f-4f37-4726-b4a7-b94fe5f8fe51	abstract	\N	{"process": "closed_api", "abstract": "Updated abstract text for clarity.", "enhancement_type": "abstract"}	5022231e-9442-4d49-bd2a-0938ae73ba63	2025-08-24 23:22:51.63384+00	2025-08-24 23:22:55.863423+00	\N
public	auto	e2277656-4930-4c5a-8718-c3eb422385bb	abstract	\N	{"process": "closed_api", "abstract": "Revised abstract content for updated entry.", "enhancement_type": "abstract"}	6c982d8c-b778-4ab4-8332-f4eacb9c1b7e	2025-08-24 23:22:55.98947+00	2025-08-24 23:22:55.989472+00	\N
public	editor	94cc5574-7f0f-4e3f-a3a2-df3df7a0effb	annotation	\N	{"annotations": [{"data": {"info": "updated emphasis"}, "label": "Emphasized", "score": null, "value": true, "scheme": "custom:highlight", "annotation_type": "boolean"}], "enhancement_type": "annotation"}	11e3eabd-9929-465a-b5c8-881c91f14418	2025-08-24 23:22:51.67804+00	2025-08-24 23:22:57.188922+00	\N
public	openalex	94cc5574-7f0f-4e3f-a3a2-df3df7a0effb	location	\N	{"locations": [{"extra": {"note": "updated landing page"}, "is_oa": true, "license": "cc-by", "pdf_url": "https://example.com/document.pdf", "version": "publishedVersion", "landing_page_url": "https://example.com/landing_v2"}], "enhancement_type": "location"}	fd362a3e-986f-460a-9422-88361457fb25	2025-08-24 23:22:51.678038+00	2025-08-24 23:22:57.188925+00	\N
public	manual	94cc5574-7f0f-4e3f-a3a2-df3df7a0effb	annotation	\N	{"annotations": [{"data": {"extra": "additional info"}, "label": "NewTag", "score": null, "value": true, "scheme": "custom:tag", "annotation_type": "boolean"}], "enhancement_type": "annotation"}	4bfbc232-9e03-42c9-9d42-1a7b2d5b0f4d	2025-08-24 23:22:57.189746+00	2025-08-24 23:22:57.189747+00	\N
hidden	openalex	dbe0c689-8cf2-4c50-80de-fa6c873333ed	bibliographic	\N	{"title": null, "publisher": "Hidden Publisher", "authorship": [{"orcid": "0000-0003-4567-8901", "position": "first", "display_name": "Wynstan"}], "created_date": "2022-06-01", "cited_by_count": 3, "enhancement_type": "bibliographic", "publication_date": "2022-05-01", "publication_year": 2022}	9ce8919e-6cfb-462f-9c9c-b20ddccc4855	2025-08-24 23:22:51.68739+00	2025-08-24 23:22:57.200082+00	\N
public	Toy Robot	94cc5574-7f0f-4e3f-a3a2-df3df7a0effb	annotation	0.2.0	{"annotations": [{"data": {"toy": "Emperor Zurg"}, "label": "toy", "score": 0.18, "scheme": "meta:toy", "annotation_type": "score"}], "enhancement_type": "annotation"}	58076e72-4692-4907-b966-7075bf192c5f	2025-08-24 23:22:57.466154+00	2025-08-24 23:22:57.46616+00	\N
public	Toy Robot	dbe0c689-8cf2-4c50-80de-fa6c873333ed	annotation	0.2.0	{"annotations": [{"data": {"toy": "Little Green Man n+1"}, "label": "toy", "score": 0.67, "scheme": "meta:toy", "annotation_type": "score"}], "enhancement_type": "annotation"}	9c7072a3-d445-42db-beda-1bc7bdd09788	2025-08-24 23:22:57.471216+00	2025-08-24 23:22:57.471218+00	\N
public	Toy Robot	53750d62-5c92-4452-ac39-c8ad1cfa1869	annotation	0.2.0	{"annotations": [{"data": {"toy": "Etch a Sketch"}, "label": "toy", "score": 0.58, "scheme": "meta:toy", "annotation_type": "score"}], "enhancement_type": "annotation"}	5a2b9cd1-2194-40f4-8efb-f13578225c1f	2025-08-24 23:22:57.570057+00	2025-08-24 23:22:57.570061+00	\N
public	Toy Robot	bfacd10f-4f37-4726-b4a7-b94fe5f8fe51	annotation	0.2.0	{"annotations": [{"data": {"toy": "Jessie"}, "label": "toy", "score": 0.91, "scheme": "meta:toy", "annotation_type": "score"}], "enhancement_type": "annotation"}	d07555d5-004c-455c-bfd9-f46aa5626186	2025-08-24 23:22:57.573425+00	2025-08-24 23:22:57.573427+00	\N
public	Toy Robot	e2277656-4930-4c5a-8718-c3eb422385bb	annotation	0.2.0	{"annotations": [{"data": {"toy": "Bullseye"}, "label": "toy", "score": 0.88, "scheme": "meta:toy", "annotation_type": "score"}], "enhancement_type": "annotation"}	0a7741fe-35d9-4cd3-858e-b643e53235f4	2025-08-24 23:22:57.5764+00	2025-08-24 23:22:57.576402+00	\N
public	Toy Robot	53750d62-5c92-4452-ac39-c8ad1cfa1869	annotation	0.2.0	{"annotations": [{"data": {"toy": "Buzz Lightyear"}, "label": "toy", "score": 0.89, "scheme": "meta:toy", "annotation_type": "score"}], "enhancement_type": "annotation"}	c5914afc-8e2d-489b-9e96-26a508dc4e8f	2025-08-24 23:22:57.70831+00	2025-08-24 23:22:57.708313+00	\N
public	Toy Robot	bfacd10f-4f37-4726-b4a7-b94fe5f8fe51	annotation	0.2.0	{"annotations": [{"data": {"toy": "Mr. Potatohead"}, "label": "toy", "score": 0.04, "scheme": "meta:toy", "annotation_type": "score"}], "enhancement_type": "annotation"}	7d2c536c-d237-44c4-a6df-ab2789c38b40	2025-08-24 23:22:57.711663+00	2025-08-24 23:22:57.711665+00	\N
public	Toy Robot	e2277656-4930-4c5a-8718-c3eb422385bb	annotation	0.2.0	{"annotations": [{"data": {"toy": "Bo Peep"}, "label": "toy", "score": 0.36, "scheme": "meta:toy", "annotation_type": "score"}], "enhancement_type": "annotation"}	1990beee-7f30-4ffb-83e3-5ca89c2a3cb0	2025-08-24 23:22:57.714629+00	2025-08-24 23:22:57.71463+00	\N
public	Toy Robot	53750d62-5c92-4452-ac39-c8ad1cfa1869	annotation	0.2.0	{"annotations": [{"data": {"toy": "Slinky Dog"}, "label": "toy", "score": 0.66, "scheme": "meta:toy", "annotation_type": "score"}], "enhancement_type": "annotation"}	12a023e6-1fd2-4460-a29e-cf8255e03fd0	2025-08-25 00:08:40.727628+00	2025-08-25 00:08:40.727632+00	\N
public	Toy Robot	bfacd10f-4f37-4726-b4a7-b94fe5f8fe51	annotation	0.2.0	{"annotations": [{"data": {"toy": "Stinky Pete"}, "label": "toy", "score": 0.74, "scheme": "meta:toy", "annotation_type": "score"}], "enhancement_type": "annotation"}	34889ed8-7d33-4364-90bc-9031beed5eff	2025-08-25 00:09:21.029568+00	2025-08-25 00:09:21.029572+00	\N
public	Toy Robot	e2277656-4930-4c5a-8718-c3eb422385bb	annotation	0.2.0	{"annotations": [{"data": {"toy": "Buzz Lightyear"}, "label": "toy", "score": 0.42, "scheme": "meta:toy", "annotation_type": "score"}], "enhancement_type": "annotation"}	1068de61-f2e0-4aad-a12b-e1860f562bbc	2025-08-25 00:09:44.765128+00	2025-08-25 00:09:44.765132+00	\N
public	Toy Robot	68a835f7-d5d0-4f8a-8c24-322f25460dca	annotation	0.2.0	{"annotations": [{"data": {"toy": "Little Green Man 1"}, "label": "toy", "score": 0.4, "scheme": "meta:toy", "annotation_type": "score"}], "enhancement_type": "annotation"}	35a9cd57-7ba6-4f25-9eca-f79ba0f2ccf5	2025-08-25 00:09:31.878626+00	2025-08-25 00:09:31.878628+00	\N
public	Toy Robot	94cc5574-7f0f-4e3f-a3a2-df3df7a0effb	annotation	0.2.0	{"annotations": [{"data": {"toy": "Buzz Lightyear"}, "label": "toy", "score": 0.64, "scheme": "meta:toy", "annotation_type": "score"}], "enhancement_type": "annotation"}	bc65df50-b223-4a6a-a302-fbe3211f8a9c	2025-08-25 00:10:03.68693+00	2025-08-25 00:10:03.686933+00	\N
\.


--
-- Data for Name: enhancement_request; Type: TABLE DATA; Schema: public; Owner: localuser
--

COPY public.enhancement_request (reference_id, robot_id, request_status, enhancement_parameters, error, id, created_at, updated_at, source) FROM stdin;
53750d62-5c92-4452-ac39-c8ad1cfa1869	cb73f9a3-af2a-4bfa-9502-f61d5fe18b11	completed	null	\N	faf24918-a72a-4f59-82a8-415694ed4d59	2025-08-25 00:08:40.55134+00	2025-08-25 00:08:40.973972+00	\N
bfacd10f-4f37-4726-b4a7-b94fe5f8fe51	cb73f9a3-af2a-4bfa-9502-f61d5fe18b11	completed	null	\N	c10a5666-d9b6-4bbb-ae44-ec1b16458a0b	2025-08-25 00:09:20.991712+00	2025-08-25 00:09:21.118343+00	\N
68a835f7-d5d0-4f8a-8c24-322f25460dca	cb73f9a3-af2a-4bfa-9502-f61d5fe18b11	completed	null	\N	4dc19c54-9767-4f58-8d2c-abd47c9f9b40	2025-08-25 00:09:31.848792+00	2025-08-25 00:09:31.945238+00	\N
e2277656-4930-4c5a-8718-c3eb422385bb	cb73f9a3-af2a-4bfa-9502-f61d5fe18b11	completed	null	\N	639f7d63-3718-4852-8694-b3fae9925324	2025-08-25 00:09:44.731044+00	2025-08-25 00:09:44.829452+00	\N
94cc5574-7f0f-4e3f-a3a2-df3df7a0effb	cb73f9a3-af2a-4bfa-9502-f61d5fe18b11	completed	null	\N	906deb14-652f-47d8-8084-892252103a34	2025-08-25 00:10:03.647823+00	2025-08-25 00:10:03.769983+00	\N
\.


--
-- Data for Name: external_identifier; Type: TABLE DATA; Schema: public; Owner: localuser
--

COPY public.external_identifier (reference_id, identifier_type, other_identifier_name, identifier, id, created_at, updated_at) FROM stdin;
53750d62-5c92-4452-ac39-c8ad1cfa1869	doi	\N	10.1234/sampledoi	cbdf2182-4f18-48b3-a89b-0b3a6e4def71	2025-08-24 23:22:51.602134+00	2025-08-24 23:22:51.602138+00
53750d62-5c92-4452-ac39-c8ad1cfa1869	pm_id	\N	987654	9134494e-f95b-4a8e-b764-764e05aa8536	2025-08-24 23:22:51.602138+00	2025-08-24 23:22:51.602139+00
bfacd10f-4f37-4726-b4a7-b94fe5f8fe51	pm_id	\N	123456	9597ef3f-c07b-49ce-93d7-ffc0340d7096	2025-08-24 23:22:51.635402+00	2025-08-24 23:22:51.635406+00
bfacd10f-4f37-4726-b4a7-b94fe5f8fe51	other	CustomID	OTHER-001	68e7bb1e-8a5e-4b1d-9de3-c0df4f918de2	2025-08-24 23:22:51.635407+00	2025-08-24 23:22:51.635408+00
68a835f7-d5d0-4f8a-8c24-322f25460dca	other	ISBN	1234567891011	2a96b6a4-8ef6-4122-bdd6-4663dcf4f46f	2025-08-24 23:22:51.647237+00	2025-08-24 23:22:51.647239+00
68a835f7-d5d0-4f8a-8c24-322f25460dca	doi	\N	10.2345/newdoi	891ef946-d572-45fd-8361-6499b0c18354	2025-08-24 23:22:51.64724+00	2025-08-24 23:22:51.647242+00
e2277656-4930-4c5a-8718-c3eb422385bb	open_alex	\N	W123456789	f2f340fd-6ae9-47be-a360-dcb621281df3	2025-08-24 23:22:51.667238+00	2025-08-24 23:22:51.66724+00
e2277656-4930-4c5a-8718-c3eb422385bb	pm_id	\N	55555	321364e4-ddb7-4d8f-a416-efed2799d17c	2025-08-24 23:22:51.66724+00	2025-08-24 23:22:51.667241+00
94cc5574-7f0f-4e3f-a3a2-df3df7a0effb	open_alex	\N	W123456790	973d38f5-e239-477c-a02d-00b71707efd7	2025-08-24 23:22:51.678654+00	2025-08-24 23:22:51.678655+00
94cc5574-7f0f-4e3f-a3a2-df3df7a0effb	doi	\N	10.3456/anotherdoi	b090ae66-ea2f-443a-a2a9-b57ba5b51388	2025-08-24 23:22:51.678656+00	2025-08-24 23:22:51.678656+00
dbe0c689-8cf2-4c50-80de-fa6c873333ed	open_alex	\N	W123456791	f7dba658-9e84-4578-b5e5-0fec1cceee90	2025-08-24 23:22:51.687989+00	2025-08-24 23:22:51.687992+00
59d19872-380b-428d-9e12-c0bf2682f6cb	open_alex	\N	W123456794	2acabf9e-cd1a-4aa5-b57f-7228ced0111d	2025-08-24 23:22:55.133459+00	2025-08-24 23:22:55.133461+00
23f552f5-833f-4ce4-b3d8-ba1932340e0b	doi	\N	10.1111/wrong	7e51b892-0619-416c-bb44-ca633b413a8d	2025-08-24 23:22:55.149349+00	2025-08-24 23:22:55.14935+00
f6e488b6-7d86-4ca1-85f5-c71c27176b6b	open_alex	\N	W123456792	e6144cc1-87e3-40e5-9cc7-175a40efd8b0	2025-08-24 23:22:55.158382+00	2025-08-24 23:22:55.158383+00
b9db25d5-febb-48b4-896a-dcbc8455c492	open_alex	\N	W123456793	ed74f424-ae9d-40e5-b6d4-ca6340473edc	2025-08-24 23:22:55.162626+00	2025-08-24 23:22:55.162626+00
53750d62-5c92-4452-ac39-c8ad1cfa1869	other	scopus	SC12345678	d3f9d186-e8ca-44e4-96f0-abd38ed86a82	2025-08-24 23:22:55.855539+00	2025-08-24 23:22:55.855541+00
dbe0c689-8cf2-4c50-80de-fa6c873333ed	doi	\N	10.1235/sampledoitwoelectricboogaloo	401f3d95-2995-4fb6-ac70-2bf3adf0e7f5	2025-08-24 23:22:51.687993+00	2025-08-24 23:22:57.200861+00
dbe0c689-8cf2-4c50-80de-fa6c873333ed	pm_id	\N	77777	a595180d-8e9f-4e39-adbe-8bc6d6a0bee0	2025-08-24 23:22:57.201329+00	2025-08-24 23:22:57.20133+00
\.


--
-- Data for Name: import_record; Type: TABLE DATA; Schema: public; Owner: localuser
--

COPY public.import_record (id, search_string, searched_at, processor_name, processor_version, notes, expected_reference_count, source_name, status, created_at, updated_at) FROM stdin;
98ea5e99-2a55-423b-b4b3-75081cfcc5a5	\N	2025-08-24 23:22:51.132657+00	test_robot	0.0.1	\N	-1	test_source	completed	2025-08-24 23:22:51.192434+00	2025-08-24 23:22:57.334612+00
\.


--
-- Data for Name: import_batch; Type: TABLE DATA; Schema: public; Owner: localuser
--

COPY public.import_batch (id, import_record_id, status, storage_url, created_at, updated_at, collision_strategy, callback_url) FROM stdin;
a13ae2e5-82ab-4ee3-a753-aac8ef10c742	98ea5e99-2a55-423b-b4b3-75081cfcc5a5	completed	http://fs:9000/e2e/test_complete_batch_import_workflow/4_file_with_duplicates_to_overwrite.jsonl?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=localuser%2F20250824%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20250824T232224Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=8a0a36be60706693d5f2d2b8a99f1cb4db09b54f6ce6e930aee55bff69c1fc98	2025-08-24 23:22:55.809319+00	2025-08-24 23:22:55.886771+00	overwrite	http://e2e:8001/callback/
b51d9ebd-dec6-4dd3-9413-b46279c1b03d	98ea5e99-2a55-423b-b4b3-75081cfcc5a5	completed	http://fs:9000/e2e/test_complete_batch_import_workflow/1_completely_valid_file.jsonl?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=localuser%2F20250824%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20250824T232224Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=2f4e1671fd27e2f7e6a9b1bd1e97c8d1a9468460d791d149d1887cc5b8c9ed2c	2025-08-24 23:22:51.324496+00	2025-08-24 23:22:53.197847+00	fail	http://e2e:8001/callback/
38fcaef0-c650-4e41-851d-134ba9991fdf	98ea5e99-2a55-423b-b4b3-75081cfcc5a5	completed	http://fs:9000/e2e/test_complete_batch_import_workflow/2_file_with_some_failures.jsonl?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=localuser%2F20250824%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20250824T232224Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=72e842522f886a80c6a518276d938f30b4e922239bd45b4352d6ccfca497f565	2025-08-24 23:22:54.892079+00	2025-08-24 23:22:55.360559+00	fail	http://e2e:8001/callback/
200bf700-721d-4402-a8e1-6e4888322315	98ea5e99-2a55-423b-b4b3-75081cfcc5a5	completed	http://fs:9000/e2e/test_complete_batch_import_workflow/5_file_with_duplicates_to_left_merge.jsonl?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=localuser%2F20250824%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20250824T232224Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=4f4ffcb367deee3aed8ed947080b9aba7a97b702be126e684eba2ce0b8dd8093	2025-08-24 23:22:55.93231+00	2025-08-24 23:22:56.008031+00	merge_defensive	http://e2e:8001/callback/
76562881-5d41-4dd0-8ea9-9f3b773ef361	98ea5e99-2a55-423b-b4b3-75081cfcc5a5	completed	http://fs:9000/e2e/test_complete_batch_import_workflow/3_file_with_duplicates.jsonl?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=localuser%2F20250824%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20250824T232224Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=1684aae130e8454b36d8ee7ab872457583ddb097079bc03bebf6d0074597be63	2025-08-24 23:22:55.582893+00	2025-08-24 23:22:55.706259+00	fail	http://e2e:8001/callback/
dcb831e0-1315-4825-9d03-4fbd5838d0e2	98ea5e99-2a55-423b-b4b3-75081cfcc5a5	completed	http://fs:9000/e2e/test_complete_batch_import_workflow/6_file_with_duplicates_to_right_merge.jsonl?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=localuser%2F20250824%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20250824T232224Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=a88a39e0174ec3f8b189982841e6bfe6c27a8310aedfd51a2c7057280b092041	2025-08-24 23:22:57.120436+00	2025-08-24 23:22:57.240075+00	merge_aggressive	http://e2e:8001/callback/
\.


--
-- Data for Name: import_result; Type: TABLE DATA; Schema: public; Owner: localuser
--

COPY public.import_result (id, import_batch_id, status, reference_id, failure_details, created_at, updated_at) FROM stdin;
53662313-b9ce-4b2f-8516-ac8d3e0ec1bf	b51d9ebd-dec6-4dd3-9413-b46279c1b03d	completed	53750d62-5c92-4452-ac39-c8ad1cfa1869	\N	2025-08-24 23:22:51.55987+00	2025-08-24 23:22:51.610757+00
a50b704b-6b48-4d06-8a1b-2b3940454e9f	b51d9ebd-dec6-4dd3-9413-b46279c1b03d	completed	bfacd10f-4f37-4726-b4a7-b94fe5f8fe51	\N	2025-08-24 23:22:51.614663+00	2025-08-24 23:22:51.637718+00
828a212e-f339-4672-9cba-c6a187c76221	b51d9ebd-dec6-4dd3-9413-b46279c1b03d	completed	68a835f7-d5d0-4f8a-8c24-322f25460dca	\N	2025-08-24 23:22:51.638956+00	2025-08-24 23:22:51.652166+00
f328b10b-df3d-474e-9856-bb9d3916ba44	b51d9ebd-dec6-4dd3-9413-b46279c1b03d	completed	e2277656-4930-4c5a-8718-c3eb422385bb	\N	2025-08-24 23:22:51.654894+00	2025-08-24 23:22:51.671516+00
1a74d64c-4f3a-477f-b3b4-643724e5bcb8	b51d9ebd-dec6-4dd3-9413-b46279c1b03d	completed	94cc5574-7f0f-4e3f-a3a2-df3df7a0effb	\N	2025-08-24 23:22:51.673173+00	2025-08-24 23:22:51.680097+00
baf9cd1d-8546-4274-ae95-3631abc89a99	b51d9ebd-dec6-4dd3-9413-b46279c1b03d	completed	dbe0c689-8cf2-4c50-80de-fa6c873333ed	\N	2025-08-24 23:22:51.681285+00	2025-08-24 23:22:51.690809+00
afe6cd23-f79b-43cb-819a-cc49eee33edf	38fcaef0-c650-4e41-851d-134ba9991fdf	completed	59d19872-380b-428d-9e12-c0bf2682f6cb	\N	2025-08-24 23:22:55.105443+00	2025-08-24 23:22:55.136383+00
ab99505c-1e91-491a-92ec-b177b81c8b96	38fcaef0-c650-4e41-851d-134ba9991fdf	failed	\N	Entry 2:\n\n1 validation error for ReferenceFileInputValidator\nidentifiers\n  Field required [type=missing, input_value={'visibility': 'public', ...', 'annotations': []}}]}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.11/v/missing	2025-08-24 23:22:55.138527+00	2025-08-24 23:22:55.140079+00
9545eeec-0738-409f-9e32-eacbdb3d7172	38fcaef0-c650-4e41-851d-134ba9991fdf	failed	\N	Entry 3:\n\n1 validation error for ReferenceFileInputValidator\nidentifiers\n  List should have at least 1 item after validation, not 0 [type=too_short, input_value=[], input_type=list]\n    For further information visit https://errors.pydantic.dev/2.11/v/too_short	2025-08-24 23:22:55.1411+00	2025-08-24 23:22:55.142231+00
a75453e3-1bd9-49ad-90e9-eb95035a8db0	38fcaef0-c650-4e41-851d-134ba9991fdf	failed	\N	Entry 4:\n\n1 validation error for ReferenceFileInputValidator\nidentifiers\n  Input should be a valid list [type=list_type, input_value='10.0000/typo', input_type=str]\n    For further information visit https://errors.pydantic.dev/2.11/v/list_type	2025-08-24 23:22:55.14311+00	2025-08-24 23:22:55.144095+00
58148138-6ea9-4933-b912-59191a5c2fb2	38fcaef0-c650-4e41-851d-134ba9991fdf	failed	\N	Entry 5\n\nAll identifiers failed to parse.\n\nIdentifier 1:\nInvalid identifier. Check the format and content of the identifier.\nAttempted to parse:\n{'identifier': '10.9999/invaliddoi'}\nError:\n1 validation error for tagged-union[DOIIdentifier,PubMedIdentifier,OpenAlexIdentifier,OtherIdentifier]\n  Unable to extract tag using discriminator 'identifier_type' [type=union_tag_not_found, input_value={'identifier': '10.9999/invaliddoi'}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.11/v/union_tag_not_found	2025-08-24 23:22:55.144861+00	2025-08-24 23:22:55.145944+00
a5865b7e-aacf-4159-8dd3-f62e7831c96e	38fcaef0-c650-4e41-851d-134ba9991fdf	partially_failed	23f552f5-833f-4ce4-b3d8-ba1932340e0b	Entry 6:\n\nEnhancement 1:\nInvalid enhancement. Check the format and content of the enhancement.\nError:\n1 validation error for EnhancementFileInput\ncontent\n  Input should be a valid dictionary or object to extract fields from [type=model_attributes_type, input_value='invalid content', input_type=str]\n    For further information visit https://errors.pydantic.dev/2.11/v/model_attributes_type	2025-08-24 23:22:55.146738+00	2025-08-24 23:22:55.150542+00
027ee3e2-4ecb-4b50-a7de-14d7bad3fd58	38fcaef0-c650-4e41-851d-134ba9991fdf	failed	\N	Entry 7\n\nAll identifiers failed to parse.\n\nIdentifier 1:\nInvalid identifier. Check the format and content of the identifier.\nAttempted to parse:\n{'identifier_type': 'pm_id', 'identifier': 'invalid'}\nError:\n1 validation error for tagged-union[DOIIdentifier,PubMedIdentifier,OpenAlexIdentifier,OtherIdentifier]\npm_id.identifier\n  Input should be a valid integer, unable to parse string as an integer [type=int_parsing, input_value='invalid', input_type=str]\n    For further information visit https://errors.pydantic.dev/2.11/v/int_parsing\n\nIdentifier 2:\nInvalid identifier. Check the format and content of the identifier.\nAttempted to parse:\n{'identifier_type': 'pm_id', 'identifier': 'invalid'}\nError:\n1 validation error for tagged-union[DOIIdentifier,PubMedIdentifier,OpenAlexIdentifier,OtherIdentifier]\npm_id.identifier\n  Input should be a valid integer, unable to parse string as an integer [type=int_parsing, input_value='invalid', input_type=str]\n    For further information visit https://errors.pydantic.dev/2.11/v/int_parsing	2025-08-24 23:22:55.151792+00	2025-08-24 23:22:55.152867+00
15287a6f-34ae-4c2a-bcb5-fd76fc53f456	38fcaef0-c650-4e41-851d-134ba9991fdf	partially_failed	f6e488b6-7d86-4ca1-85f5-c71c27176b6b	Entry 8:\n\nEnhancement 2:\nInvalid enhancement. Check the format and content of the enhancement.\nError:\n1 validation error for EnhancementFileInput\ncontent\n  Unable to extract tag using discriminator 'enhancement_type' [type=union_tag_not_found, input_value={'wrong_field': 'annotati...ations': 'not_an_array'}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.11/v/union_tag_not_found	2025-08-24 23:22:55.153754+00	2025-08-24 23:22:55.15952+00
d528c713-016a-4a6f-b0c5-822f653005fe	38fcaef0-c650-4e41-851d-134ba9991fdf	partially_failed	b9db25d5-febb-48b4-896a-dcbc8455c492	Entry 9:\n\nEnhancement 1:\nInvalid enhancement. Check the format and content of the enhancement.\nError:\n2 validation errors for EnhancementFileInput\ncontent.bibliographic.authorship.0.display_name\n  Field required [type=missing, input_value={}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.11/v/missing\ncontent.bibliographic.authorship.0.position\n  Field required [type=missing, input_value={}, input_type=dict]\n    For further information visit https://errors.pydantic.dev/2.11/v/missing	2025-08-24 23:22:55.160287+00	2025-08-24 23:22:55.163757+00
e7c85291-2929-4256-b025-57609e5480bf	76562881-5d41-4dd0-8ea9-9f3b773ef361	failed	\N	Entry 1:\n\nIdentifier(s) are already mapped on an existing reference:\n[LinkedExternalIdentifier(id=UUID('cbdf2182-4f18-48b3-a89b-0b3a6e4def71'), identifier=DOIIdentifier(identifier='10.1234/sampledoi', identifier_type=<ExternalIdentifierType.DOI: 'doi'>), reference_id=UUID('53750d62-5c92-4452-ac39-c8ad1cfa1869'), reference=None), LinkedExternalIdentifier(id=UUID('9134494e-f95b-4a8e-b764-764e05aa8536'), identifier=PubMedIdentifier(identifier=987654, identifier_type=<ExternalIdentifierType.PM_ID: 'pm_id'>), reference_id=UUID('53750d62-5c92-4452-ac39-c8ad1cfa1869'), reference=None)]	2025-08-24 23:22:55.650536+00	2025-08-24 23:22:55.661961+00
c7e89216-efed-46e3-a124-160f9e9027b6	76562881-5d41-4dd0-8ea9-9f3b773ef361	failed	\N	Entry 2:\n\nIdentifier(s) are already mapped on an existing reference:\n[LinkedExternalIdentifier(id=UUID('9597ef3f-c07b-49ce-93d7-ffc0340d7096'), identifier=PubMedIdentifier(identifier=123456, identifier_type=<ExternalIdentifierType.PM_ID: 'pm_id'>), reference_id=UUID('bfacd10f-4f37-4726-b4a7-b94fe5f8fe51'), reference=None), LinkedExternalIdentifier(id=UUID('68e7bb1e-8a5e-4b1d-9de3-c0df4f918de2'), identifier=OtherIdentifier(identifier='OTHER-001', identifier_type=<ExternalIdentifierType.OTHER: 'other'>, other_identifier_name='CustomID'), reference_id=UUID('bfacd10f-4f37-4726-b4a7-b94fe5f8fe51'), reference=None)]	2025-08-24 23:22:55.663579+00	2025-08-24 23:22:55.666924+00
0112ab41-9f77-40f6-9447-07392b2d7829	76562881-5d41-4dd0-8ea9-9f3b773ef361	failed	\N	Entry 3:\n\nIdentifier(s) are already mapped on an existing reference:\n[LinkedExternalIdentifier(id=UUID('2a96b6a4-8ef6-4122-bdd6-4663dcf4f46f'), identifier=OtherIdentifier(identifier='1234567891011', identifier_type=<ExternalIdentifierType.OTHER: 'other'>, other_identifier_name='ISBN'), reference_id=UUID('68a835f7-d5d0-4f8a-8c24-322f25460dca'), reference=None), LinkedExternalIdentifier(id=UUID('891ef946-d572-45fd-8361-6499b0c18354'), identifier=DOIIdentifier(identifier='10.2345/newdoi', identifier_type=<ExternalIdentifierType.DOI: 'doi'>), reference_id=UUID('68a835f7-d5d0-4f8a-8c24-322f25460dca'), reference=None)]	2025-08-24 23:22:55.667801+00	2025-08-24 23:22:55.669939+00
6eab4d6e-fd48-4347-b399-fcd60b54656f	a13ae2e5-82ab-4ee3-a753-aac8ef10c742	completed	53750d62-5c92-4452-ac39-c8ad1cfa1869	\N	2025-08-24 23:22:55.8421+00	2025-08-24 23:22:55.85779+00
79578161-9c58-4491-ae9a-8d1649a6e8b6	a13ae2e5-82ab-4ee3-a753-aac8ef10c742	completed	bfacd10f-4f37-4726-b4a7-b94fe5f8fe51	\N	2025-08-24 23:22:55.858717+00	2025-08-24 23:22:55.865086+00
27e7d6d2-1841-46c5-8251-96771c2b2fc4	a13ae2e5-82ab-4ee3-a753-aac8ef10c742	failed	\N	Entry 3:\n\nIncoming reference collides with more than one existing reference.	2025-08-24 23:22:55.866108+00	2025-08-24 23:22:55.868844+00
996753c9-3fb7-4869-b909-e2e30f423735	dcb831e0-1315-4825-9d03-4fbd5838d0e2	completed	94cc5574-7f0f-4e3f-a3a2-df3df7a0effb	\N	2025-08-24 23:22:57.177116+00	2025-08-24 23:22:57.191409+00
254e4c39-4bb8-4005-ace9-27a8e018a1d0	dcb831e0-1315-4825-9d03-4fbd5838d0e2	completed	dbe0c689-8cf2-4c50-80de-fa6c873333ed	\N	2025-08-24 23:22:57.192287+00	2025-08-24 23:22:57.202745+00
6aa82093-e1df-4b6c-b6b0-e1fef2b759fd	76562881-5d41-4dd0-8ea9-9f3b773ef361	failed	\N	Entry 4:\n\nIdentifier(s) are already mapped on an existing reference:\n[LinkedExternalIdentifier(id=UUID('f2f340fd-6ae9-47be-a360-dcb621281df3'), identifier=OpenAlexIdentifier(identifier='W123456789', identifier_type=<ExternalIdentifierType.OPEN_ALEX: 'open_alex'>), reference_id=UUID('e2277656-4930-4c5a-8718-c3eb422385bb'), reference=None), LinkedExternalIdentifier(id=UUID('321364e4-ddb7-4d8f-a416-efed2799d17c'), identifier=PubMedIdentifier(identifier=55555, identifier_type=<ExternalIdentifierType.PM_ID: 'pm_id'>), reference_id=UUID('e2277656-4930-4c5a-8718-c3eb422385bb'), reference=None)]	2025-08-24 23:22:55.671447+00	2025-08-24 23:22:55.677788+00
4bbf6acc-b097-499f-8f67-018f7867b4c2	76562881-5d41-4dd0-8ea9-9f3b773ef361	failed	\N	Entry 5:\n\nIdentifier(s) are already mapped on an existing reference:\n[LinkedExternalIdentifier(id=UUID('973d38f5-e239-477c-a02d-00b71707efd7'), identifier=OpenAlexIdentifier(identifier='W123456790', identifier_type=<ExternalIdentifierType.OPEN_ALEX: 'open_alex'>), reference_id=UUID('94cc5574-7f0f-4e3f-a3a2-df3df7a0effb'), reference=None), LinkedExternalIdentifier(id=UUID('b090ae66-ea2f-443a-a2a9-b57ba5b51388'), identifier=DOIIdentifier(identifier='10.3456/anotherdoi', identifier_type=<ExternalIdentifierType.DOI: 'doi'>), reference_id=UUID('94cc5574-7f0f-4e3f-a3a2-df3df7a0effb'), reference=None)]	2025-08-24 23:22:55.682966+00	2025-08-24 23:22:55.686215+00
97d6aa7c-49fe-42f2-8533-bac05eaa74a1	76562881-5d41-4dd0-8ea9-9f3b773ef361	failed	\N	Entry 6:\n\nIdentifier(s) are already mapped on an existing reference:\n[LinkedExternalIdentifier(id=UUID('f7dba658-9e84-4578-b5e5-0fec1cceee90'), identifier=OpenAlexIdentifier(identifier='W123456791', identifier_type=<ExternalIdentifierType.OPEN_ALEX: 'open_alex'>), reference_id=UUID('dbe0c689-8cf2-4c50-80de-fa6c873333ed'), reference=None), LinkedExternalIdentifier(id=UUID('401f3d95-2995-4fb6-ac70-2bf3adf0e7f5'), identifier=DOIIdentifier(identifier='10.1235/sampledoi', identifier_type=<ExternalIdentifierType.DOI: 'doi'>), reference_id=UUID('dbe0c689-8cf2-4c50-80de-fa6c873333ed'), reference=None)]	2025-08-24 23:22:55.687265+00	2025-08-24 23:22:55.690772+00
2b52cd5b-3515-4407-8111-2dd08f84a360	76562881-5d41-4dd0-8ea9-9f3b773ef361	failed	\N	Entry 7:\n\nIncoming reference collides with more than one existing reference.	2025-08-24 23:22:55.692135+00	2025-08-24 23:22:55.694401+00
2c48d7d0-7314-4dcb-9a2b-215ddf95cf7b	200bf700-721d-4402-a8e1-6e4888322315	completed	68a835f7-d5d0-4f8a-8c24-322f25460dca	\N	2025-08-24 23:22:55.961067+00	2025-08-24 23:22:55.980113+00
40a4d061-1957-4982-aa5b-26a76a27691f	200bf700-721d-4402-a8e1-6e4888322315	completed	e2277656-4930-4c5a-8718-c3eb422385bb	\N	2025-08-24 23:22:55.98129+00	2025-08-24 23:22:55.990648+00
\.


--
-- Data for Name: robot; Type: TABLE DATA; Schema: public; Owner: localuser
--

COPY public.robot (base_url, client_secret, description, name, owner, id, created_at, updated_at) FROM stdin;
http://127.0.0.1:8001/toy/enhancement/	e257c7431d8475d0ca91330d60663808299ffd851211abb8d9e62be9d14922d2	Provides toy annotation enhancements	Toy Robot 1	Future Evidence Foundation	cb73f9a3-af2a-4bfa-9502-f61d5fe18b11	2025-08-24 23:22:56.068721+00	2025-08-24 23:22:56.068725+00
http://127.0.0.1:8001/toy/enhancement/	795b37adce534d29091fecf78e099c01764dff04215eb637cdfa044a86452fb2	Provides toy annotation enhancements	Toy Robot 2 but really it is just Toy Robot 1	Future Evidence Foundation	dda2bbb2-2fa2-4dda-859e-8ef3f9e76c49	2025-08-24 23:22:57.467655+00	2025-08-24 23:22:57.467657+00
\.


--
-- Data for Name: robot_automation; Type: TABLE DATA; Schema: public; Owner: localuser
--

COPY public.robot_automation (robot_id, query, id, created_at, updated_at) FROM stdin;
cb73f9a3-af2a-4bfa-9502-f61d5fe18b11	{"bool": {"should": [{"bool": {"must_not": [{"nested": {"path": "reference.enhancements.content.annotations", "query": {"term": {"reference.enhancements.content.annotations.label": "toy"}}}}]}}, {"nested": {"path": "enhancement.content.annotations", "query": {"term": {"enhancement.content.annotations.label": "toy"}}}}], "minimum_should_match": 1}}	aaadc524-7835-41ca-b473-0fc587711560	2025-08-24 23:22:56.081575+00	2025-08-24 23:22:56.081578+00
\.


--
-- PostgreSQL database dump complete
--
