# Changelog

## [0.1.1](https://github.com/omerozkilic/citewell/compare/v0.1.0...v0.1.1) (2026-11-03)


### Bug Fixes

* **release:** keep uv.lock in sync, use vX.Y.Z tags and publish versioned images ([#5](https://github.com/omerozkilic/citewell/issues/5)) ([a05c042](https://github.com/omerozkilic/citewell/commit/a05c0429c8373b696102ccccfc28ddf748ed0567))

## 0.1.0 (2026-11-03)


### Features

* drop near-duplicate passages, time searches without model loading, preload models ([cdd5de0](https://github.com/omerozkilic/citewell/commit/cdd5de04b46ccac19114ee3b5ed41d3cd62d256f))
* **eval:** Turkish legislation eval set with article-based page resolution ([8276f23](https://github.com/omerozkilic/citewell/commit/8276f230fa50bb2c6d92a65583b8a0e0f9f97897))
* hybrid search with RRF fusion and optional cross-encoder rerank ([4b3829c](https://github.com/omerozkilic/citewell/commit/4b3829ce9a27f32e0c03df3a04b6470371f94598))
* MCP server, REST API and CLI ([1f97659](https://github.com/omerozkilic/citewell/commit/1f9765999d64aec9adbdc5ae0247c4e3fb1d148e))
* page-aware ingest pipeline with Turkish-aware text handling ([8a7e0ef](https://github.com/omerozkilic/citewell/commit/8a7e0ef0b689c0ed319199f80ee2acaf2476289b))
* retrieval eval harness and Turkish sample corpus ([6a2e67f](https://github.com/omerozkilic/citewell/commit/6a2e67fa52c930b83ff3937172b885bcf4801327))


### Bug Fixes

* fail fast with an actionable message when PostgreSQL is unreachable ([a3d1892](https://github.com/omerozkilic/citewell/commit/a3d1892daba8df70ef335a889d9001452aca1894))
* load cached models without network calls and quiet model-library logs ([29973cb](https://github.com/omerozkilic/citewell/commit/29973cb98065de8cbffbef610a5fef7352661453))
* stay offline once models are cached and flag PDF pages without text ([478efc6](https://github.com/omerozkilic/citewell/commit/478efc683056a0f8757ef3fc7c436ad1aad66e29))


### Documentation

* publish first bge-m3 results on the Turkish Labour Law eval ([967246f](https://github.com/omerozkilic/citewell/commit/967246f9e47a9257998701066a5b065ab97eac53))
* README, MkDocs site, ADRs and community files ([9db71d1](https://github.com/omerozkilic/citewell/commit/9db71d1b295b5f023e4c4aa85a2ecd8fcc8e34ab))

## Changelog

All notable changes to this project are documented here. This file is maintained by
[release-please](https://github.com/googleapis/release-please) from
[Conventional Commits](https://www.conventionalcommits.org/).
