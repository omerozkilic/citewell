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
- **Önce Türkçe** — Türkçe kök bulma (`turkish` tsvector), doğru `I/ı` – `İ/i` dönüşümü, cp1254
  desteği, çok dilli `bge-m3`, Türkçe eval seti.
- **Çevrimdışı ve gizli** — modeller yereldir; tek seferlik indirmeden sonra hiçbir veri makinenizden
  çıkmaz.
- **Ölçülebilir** — Recall@k, MRR, isabet oranı, sayfa isabeti, p50/p95 gecikme.

## Hızlı başlangıç

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

35 soruluk örnek set bir duman testidir, benchmark değildir. Gerçek Türkçe dokümanlardan oluşan eval
setleri katkısı çok değerlidir.

## Katkı

[CONTRIBUTING.md](CONTRIBUTING.md) — Türkçe issue ve PR'lar memnuniyetle karşılanır.

## Lisans

[MIT](LICENSE) © Ömer Özkılıç
