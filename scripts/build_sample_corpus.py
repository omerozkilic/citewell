"""Build the sample Turkish PDF used by the demo corpus and the eval set.

The content is fictional ("Defne Yazılım A.Ş."), written for Citewell. Each page
carries distinct facts so that page-level hit rate can be measured.

    uv run --group dev python scripts/build_sample_corpus.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

PAGES: list[tuple[str, list[str]]] = [
    (
        "1. Giriş ve Çalışma Saatleri",
        [
            "Bu el kitabı Defne Yazılım A.Ş. çalışanlarının hak ve sorumluluklarını özetler. "
            "El kitabı her yıl Ocak ayında İnsan Kaynakları birimi tarafından güncellenir.",
            "Standart çalışma süresi haftada 40 saattir. Çekirdek çalışma saatleri hafta içi 10.00 ile "
            "16.00 arasıdır; bu saatler dışında çalışanlar başlangıç ve bitiş saatlerini esnek olarak "
            "belirleyebilir.",
            "Fazla mesai yalnızca yöneticinin yazılı onayıyla yapılır. Onaylanan fazla mesai, saat ücretinin "
            "yüzde elli fazlasıyla ödenir ya da çalışanın tercihine göre serbest zaman olarak kullandırılır.",
            "Deneme süresi işe başlangıç tarihinden itibaren iki aydır.",
        ],
    ),
    (
        "2. Yıllık İzin",
        [
            "Kıdemi bir yıldan beş yıla kadar olan çalışanlar yılda 14 iş günü ücretli yıllık izin kullanır. "
            "Kıdemi beş yıldan fazla, on beş yıldan az olanlar için bu süre 20 iş günüdür. On beş yıl ve "
            "üzeri kıdemde yıllık izin 26 iş günüdür.",
            "Yıllık izin talepleri en az iki hafta önceden İK portalı üzerinden yapılmalıdır. Beş iş gününü "
            "aşan izinler için ekip liderinin onayı gerekir.",
            "Kullanılmayan yıllık izinden en fazla 5 gün bir sonraki yıla devredilebilir. Devredilen günler "
            "31 Mart tarihine kadar kullanılmazsa düşer.",
        ],
    ),
    (
        "3. Hastalık ve Mazeret İzinleri",
        [
            "Hastalık nedeniyle işe gelemeyen çalışan, aynı gün saat 10.00'a kadar yöneticisini "
            "bilgilendirir. "
            "İki günü aşan hastalık izinlerinde doktor raporu zorunludur.",
            "Evlenen çalışana 3 gün, çocuğu olan babaya 5 gün ücretli mazeret izni verilir. Birinci derece "
            "yakınını kaybeden çalışana 3 gün ücretli izin tanınır.",
            "Taşınma durumunda yılda bir kez 1 gün mazeret izni kullanılabilir.",
        ],
    ),
    (
        "4. Masraf ve Seyahat",
        [
            "İş seyahatlerinde konaklama için gecelik üst sınır İstanbul, Ankara ve İzmir'de 3.500 TL, diğer "
            "şehirlerde 2.500 TL'dir. Yurt dışı seyahatlerde üst sınır gecelik 150 avrodur.",
            "Günlük yemek harcırahı yurt içinde 750 TL'dir. Harcırah, fatura gerektirmeden bordroya eklenir.",
            "Masraf beyanları harcamadan sonraki 30 gün içinde fiş veya e-fatura ile birlikte sisteme "
            "girilmelidir. Süresi geçen beyanlar finans biriminin onayına tabidir.",
            "Uçak biletleri ekonomi sınıfında alınır; dört saati aşan uçuşlarda yöneticinin onayıyla bir üst "
            "sınıf tercih edilebilir.",
        ],
    ),
    (
        "5. Eğitim ve Gelişim",
        [
            "Her çalışanın yıllık 15.000 TL eğitim bütçesi vardır. Bu bütçe kurs, sertifika, konferans ve "
            "kitap harcamaları için kullanılabilir.",
            "Şirket tarafından karşılanan ve bedeli 20.000 TL'yi aşan sertifika programlarında çalışan, "
            "sertifika tarihinden itibaren bir yıl şirkette kalmayı taahhüt eder.",
            "Mentorluk programına katılım gönüllüdür ve her çeyrek başında başvurular alınır.",
        ],
    ),
    (
        "6. Etik ve Disiplin",
        [
            "Çalışanlar, değeri 1.000 TL'yi aşan hediye ve ağırlamaları kabul edemez; daha düşük değerli "
            "hediyeler Uyum birimine bildirilir.",
            "Çıkar çatışması doğurabilecek her durum, öğrenildiği tarihten itibaren 7 gün içinde Etik "
            "Kurulu'na yazılı olarak bildirilir.",
            "Etik ihlal bildirimleri etik@defneyazilim.example adresine veya anonim bildirim hattına "
            "yapılabilir. Bildirimde bulunan çalışana misilleme yapılması disiplin suçudur.",
        ],
    ),
]


def main(out: Path) -> None:
    font = next((f for f in FONT_CANDIDATES if Path(f).exists()), None)
    if font is None:
        sys.exit("no Unicode TTF font found; edit FONT_CANDIDATES")
    pdfmetrics.registerFont(TTFont("Body", font))
    h = ParagraphStyle("h", fontName="Body", fontSize=16, leading=20, spaceAfter=12)
    p = ParagraphStyle("p", fontName="Body", fontSize=11, leading=15, spaceAfter=8)
    story: list[object] = []
    for i, (title, paras) in enumerate(PAGES):
        story.append(Paragraph(title, h))
        story.extend(Paragraph(t, p) for t in paras)
        story.append(Spacer(1, 0.5 * cm))
        if i < len(PAGES) - 1:
            story.append(PageBreak())
    doc = SimpleDocTemplate(
        str(out), pagesize=A4, title="Defne Yazılım Çalışan El Kitabı", author="Citewell örnek korpus"
    )
    doc.build(story)
    print(f"wrote {out}")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("examples/corpus/calisan-el-kitabi.pdf")
    target.parent.mkdir(parents=True, exist_ok=True)
    main(target)
