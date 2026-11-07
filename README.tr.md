<div align="center">

# Citewell

**AI asistanları için kaynak gösteren doküman hafızası.**<br>
Çevrimdışı · MCP-yerel · Türkçeye hazır

[English README](README.md) · [Dokümantasyon](https://omerozkilic.github.io/citewell) · [Mimari kararlar](docs/adr/index.md)

</div>

---

Citewell, Claude Desktop, Claude Code, Cursor ve diğer [MCP](https://modelcontextprotocol.io)
istemcilerine **kendi dokümanlarınıza** erişim veren, arayüzsüz (headless) bir RAG sunucusudur.
Döndürdüğü her parça **dosya, sayfa, chunk id ve birebir alıntı** içerir; böylece cevaplar
doğrulanabilir.

Kendi LLM çağrısı **yoktur, API anahtarı gerektirmez**. Citewell bulur; cevabı asistanınız yazar.

```text
Siz    ▸ Ankara'da otelde bir gece için en fazla ne kadar harcayabilirim?

Claude ▸ (citewell.search_documents çağrılır)
         Ankara, İstanbul ve İzmir'de gecelik konaklama üst sınırı 3.500 TL'dir [1].

         Kaynaklar
         [1] calisan-el-kitabi.pdf, s. 4
```

## Öne çıkanlar

- **Kaynaklı, doğrulanabilir parçalar** — sayfa sınırını asla aşmayan chunking, birebir alıntılar,
  kararlı chunk id'leri.
- **MCP-yerel** — masaüstü istemciler için stdio, `/mcp` altında Streamable HTTP, yapılandırılmış
  araç çıktısı, resource'lar ve alıntı prompt'u. Tasarım gereği salt okunur.
- **Hibrit arama** — pgvector (HNSW) + PostgreSQL tam metin araması, Reciprocal Rank Fusion ile
  birleştirme, opsiyonel `bge-reranker-v2-m3`.
- **Önce Türkçe** — Türkçe kök bulma (`turkish` tsvector), doğru `I/ı` – `İ/i` dönüşümü, Türkçe
  karakter kullanmadan arama (`ogrenci izni` → `öğrenci izni`), cp1254 desteği, çok dilli `bge-m3`,
  Türkçe eval setleri.
- **Çevrimdışı ve gizli** — modeller yereldir; tek seferlik indirmeden sonra hiçbir veri makinenizden
  çıkmaz.
- **Ölçülebilir** — Recall@k, MRR, isabet oranı, sayfa isabeti, p50/p95 gecikme.

## Hızlı başlangıç (PyPI, klonlamadan)

```bash
uv tool install "citewell[models]"      # veya: pipx install "citewell[models]"

# PostgreSQL + pgvector
docker run -d --name citewell-db -p 127.0.0.1:5432:5432 \
  -e POSTGRES_USER=citewell -e POSTGRES_PASSWORD=citewell -e POSTGRES_DB=citewell \
  -v citewell-pgdata:/var/lib/postgresql/data pgvector/pgvector:pg17

citewell init
citewell models download                # bir kez (~4–5 GB), internet gerekir; sonra çevrimdışı
citewell ingest ~/Belgeler/politikalar -c politikalar
citewell search "yıllık izin kaç gün?" -c politikalar
claude mcp add -s user citewell -- citewell mcp   # Claude Code'a bağla
```

## Hızlı başlangıç (Docker)

```bash
git clone https://github.com/omerozkilic/citewell && cd citewell
docker compose up -d
cp -r ~/Belgeler/politikalar/* data/
docker compose run --rm citewell models download     # bir kez, internet gerekir
docker compose run --rm citewell ingest /data
docker compose run --rm citewell search "yıllık izin kaç gün?"
```

Claude Code'a bağlamak için:

```bash
claude mcp add --transport http citewell http://localhost:8000/mcp
```

Claude Desktop, Cursor yapılandırmaları, CLI, REST API ve değerlendirme için
[İngilizce README](README.md) ve [dokümantasyon sitesine](https://omerozkilic.github.io/citewell) bakın.

## Değerlendirme

```bash
citewell eval examples/eval/tr-sample.jsonl -k 5 -r vector,keyword,hybrid,hybrid+rerank --markdown
```

**İlk sonuçlar — İş Kanunu (4857):** mevzuat.gov.tr'deki resmi PDF üzerinde 20 doğal dilde soru;
doğru maddenin doğru sayfası gelirse isabet sayılır. `bge-m3` + `bge-reranker-v2-m3`, Apple Silicon:

| Run | Recall@5 | MRR@5 | Hit@5 | Page hit@5 | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|
| vector | 1.000 | 0.885 | 1.000 | 1.000 | 45 | 95 |
| keyword | 0.850 | 0.614 | 0.850 | 0.850 | 8 | 11 |
| **hybrid** (default) | **1.000** | **0.893** | **1.000** | **1.000** | **48** | **54** |
| hybrid + rerank | 1.000 | 0.950 | 1.000 | 1.000 | 3259 | 3771 |

Hibrit arama tüm sorularda doğru madde ve sayfayı ilk 5'te buluyor; reranker sıralamayı iyileştiriyor
ama dizüstü bilgisayarda sorgu başına ~3 sn eklediği için isteğe bağlı. Küçük ve tek alanlı bir settir
(20 soru, tek kanun) — ilk veri noktasıdır. Daha büyük, bağımsız Türkçe eval seti katkıları çok
değerlidir.

## Katkı

[CONTRIBUTING.md](CONTRIBUTING.md) — Türkçe issue ve PR'lar memnuniyetle karşılanır.

## Lisans

[MIT](LICENSE) © Ömer Özkılıç
