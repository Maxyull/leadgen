from leadgen.enrich.signaux import accroche_mail, analyser

PAGE_IA = """<html><head><title>Cabinet Dupont - Avocats en droit social</title>
<meta name="description" content="Le cabinet accompagne les entreprises en droit du travail et en contentieux prud'homal.">
</head><body>
<h1>Cabinet Dupont</h1>
<p>Nous utilisons l'intelligence artificielle pour accelerer la redaction de vos actes.</p>
<p>Nos donnees personnelles sont traitees conformement au RGPD.</p>
<script>var x = "chatgpt";</script>
</body></html>"""

PAGE_MUETTE = "<html><body><h1>Etude notariale</h1><p>Bienvenue.</p></body></html>"


def test_titre_et_accroche():
    a = analyser(PAGE_IA)
    assert a["titre"] == "Cabinet Dupont - Avocats en droit social"
    assert a["accroche"].startswith("Le cabinet accompagne")


def test_signaux_detectes():
    signaux = analyser(PAGE_IA)["signaux"]
    assert "ia" in signaux
    assert "rgpd" in signaux
    assert "droit-social" in signaux
    assert "sante" not in signaux


def test_le_javascript_ne_declenche_pas_de_signal():
    """« chatgpt » n'est present que dans un <script> : ca ne compte pas."""
    page = '<html><body><p>Bonjour</p><script>var x="chatgpt";</script></body></html>'
    assert analyser(page)["signaux"] == []


def test_repli_sur_h1_et_premier_paragraphe():
    a = analyser(PAGE_MUETTE)
    assert a["titre"] == "Etude notariale"
    assert a["accroche"] == "Bienvenue."
    assert a["signaux"] == []


def test_accroche_tronquee():
    long_texte = "mot " * 200
    a = analyser(f"<html><body><p>{long_texte}</p></body></html>")
    assert len(a["accroche"]) <= 184
    assert a["accroche"].endswith("...")


def test_page_vide():
    a = analyser("")
    assert a == {"titre": "", "accroche": "", "signaux": []}


def test_angle_le_plus_fort_en_premier():
    assert "IA ET de RGPD" in accroche_mail({"signaux": ["ia", "rgpd"]})
    assert "parle d'IA" in accroche_mail({"signaux": ["ia", "paie"]})
    assert "article 9" in accroche_mail({"signaux": ["sante"]})
    assert accroche_mail({"signaux": []}) == ""
    assert accroche_mail({}) == ""
