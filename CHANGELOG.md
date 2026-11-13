# Changelog

## [0.3.0](https://github.com/omerozkilic/citewell/compare/v0.2.0...v0.3.0) (2026-11-13)


### Features

* citewell doctor checks models, migrations and offline readiness ([#57](https://github.com/omerozkilic/citewell/issues/57)) ([83ea3d2](https://github.com/omerozkilic/citewell/commit/83ea3d29b36445c5a201728e72fe851853fa4fd7)), closes [#35](https://github.com/omerozkilic/citewell/issues/35)
* citewell watch re-indexes a folder when files change ([#59](https://github.com/omerozkilic/citewell/issues/59)) ([1874a46](https://github.com/omerozkilic/citewell/commit/1874a4604d4b21515a526af913ca5e7cc8a3e7c7))
* **eval:** 42 harder Turkish questions for the sample corpus ([#65](https://github.com/omerozkilic/citewell/issues/65)) ([f3ec769](https://github.com/omerozkilic/citewell/commit/f3ec769fa0243ab25f184de5d51707d9633102cc)), closes [#22](https://github.com/omerozkilic/citewell/issues/22)
* **eval:** complete the legislation eval with KVKK and the Constitution ([#64](https://github.com/omerozkilic/citewell/issues/64)) ([b2ed351](https://github.com/omerozkilic/citewell/commit/b2ed35121ef6452fe8870f73898d73e07b3c2822)), closes [#20](https://github.com/omerozkilic/citewell/issues/20)
* load PPTX, XLSX, CSV, EPUB and EML files ([#61](https://github.com/omerozkilic/citewell/issues/61)) ([93744f6](https://github.com/omerozkilic/citewell/commit/93744f6cdeccbbf40f47eed0f8e91078b06bb4af)), closes [#36](https://github.com/omerozkilic/citewell/issues/36)
* OCR for scanned PDFs (opt-in, local Tesseract) ([#62](https://github.com/omerozkilic/citewell/issues/62)) ([fb80d49](https://github.com/omerozkilic/citewell/commit/fb80d491624df2bbb47d87a092207225c5180e14)), closes [#17](https://github.com/omerozkilic/citewell/issues/17)
* render ruled PDF tables as Markdown rows (opt-in) ([#60](https://github.com/omerozkilic/citewell/issues/60)) ([b4c1ff4](https://github.com/omerozkilic/citewell/commit/b4c1ff4b633e019cd3d2dfd4b9c7b4194858bfd3)), closes [#18](https://github.com/omerozkilic/citewell/issues/18)
* **security:** cap query length, add search statement timeout, harden compose ([#53](https://github.com/omerozkilic/citewell/issues/53)) ([48b1ec7](https://github.com/omerozkilic/citewell/commit/48b1ec7d730ddf4ba7f750d2d55765c9403c4ff4))
* **security:** parser limits and model revision pinning ([#56](https://github.com/omerozkilic/citewell/issues/56)) ([328e620](https://github.com/omerozkilic/citewell/commit/328e6206c3295434641d466144ffe01567b02276))
* server.json for the official MCP Registry ([#63](https://github.com/omerozkilic/citewell/issues/63)) ([28c6b34](https://github.com/omerozkilic/citewell/commit/28c6b34a3a1b626e4f114e81867762909bdcc8a7)), closes [#21](https://github.com/omerozkilic/citewell/issues/21)


### Bug Fixes

* **cli:** keep square brackets in printed messages (citewell[models]) ([#66](https://github.com/omerozkilic/citewell/issues/66)) ([17078d7](https://github.com/omerozkilic/citewell/commit/17078d775cc86d6802d0df7c2a6b87590b3bfb73))
* **ingest:** log expected rejections as a warning, without a traceback ([#68](https://github.com/omerozkilic/citewell/issues/68)) ([1cdb19b](https://github.com/omerozkilic/citewell/commit/1cdb19b3ea4f5764707f711160150d4f9c2835f9))


### Documentation

* Docs/roadmap features ([#52](https://github.com/omerozkilic/citewell/issues/52)) ([bd06158](https://github.com/omerozkilic/citewell/commit/bd06158df55b746fdbd5631b8526131996267774))

## [0.2.0](https://github.com/omerozkilic/citewell/compare/v0.1.1...v0.2.0) (2026-11-08)


### Features

* MCP collection-name completion and ingest --prune ([b2946b5](https://github.com/omerozkilic/citewell/commit/b2946b535d8dec1fdeec46e7e225f9f3c08a4103))
* show printed PDF page labels in citations ([d4c6699](https://github.com/omerozkilic/citewell/commit/d4c669984271ecfa43b5ad6a96751f8b980b934b))
* Turkish search works without Turkish characters ([1b43c80](https://github.com/omerozkilic/citewell/commit/1b43c805cfdd273988a844103f440397933f1e2c))
* verify_quote tool checks quotations against the source ([4ee420d](https://github.com/omerozkilic/citewell/commit/4ee420deae15d09e1d656b84424306d8fc3a6cae))


### Documentation

* install from PyPI with uv tool; pin workflow actions to commit SHAs ([88f7a2d](https://github.com/omerozkilic/citewell/commit/88f7a2de6abb941d78d66bf35a9614e16e6844eb))
* link roadmap items to GitHub issues and milestones ([2787350](https://github.com/omerozkilic/citewell/commit/278735042aa5d39cd2784c7f1967d5c6b2bc7209))

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
