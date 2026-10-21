"""Showcase: the configuration, the adapter and what montar takes to the browser.

Lives in `tests/` of the
library. Runs in the hook with the other tests: if the adapter stops
returning the format the page draws, the commit stops here, not in the browser.
"""
import importlib.util
import json
import shutil
import tempfile
import unittest
import zipfile
from unittest import mock
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("montar", RAIZ / "vitrine" / "montar.py")
montar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(montar)

CFG = json.loads((RAIZ / "vitrine" / "vitrine.json").read_text(encoding="utf-8"))


def _valido():
    return {
        "resumo": "1 trecho marcado.",
        "aviso": "Aponta trechos para revisão.",
        "marcas": [{"inicio": 0, "fim": 3, "rotulo": "Regra 1", "detalhe": "motivo"}],
        "tabela": {"titulo": "Regras", "colunas": ["Regra", "Trechos"], "linhas": [["1", 1]]},
    }


def _com_campo(c, tipo):
    """Name of a field of the requested type in configuration c, creating one if there is none
    (a showcase may have only a file field; another, only text)."""
    for campo in c["campos"]:
        if (campo["tipo"] == "arquivo") == (tipo == "arquivo"):
            return campo["nome"]
    c["campos"].append({"nome": "_plantado", "rotulo": "P", "tipo": tipo, "exemplo": "x"})
    return "_plantado"


def _com_texto(c):
    return _com_campo(c, "texto")


def _com_arquivo(c):
    return _com_campo(c, "arquivo")


class Projeto(unittest.TestCase):
    def test_conferir_passa_com_o_exemplo(self):
        self.assertEqual(montar.conferir(RAIZ), [])

    def test_adaptador_aguenta_entrada_vazia(self):
        entradas = {c["nome"]: "" for c in CFG["campos"]}
        res = montar.carregar_adaptador(RAIZ).executar(entradas)
        self.assertEqual(montar.conferir_resultado(res, entradas, CFG.get("campo_marcado")), [])

    def test_posicao_conta_ponto_de_codigo(self):
        # Emoji and accent before the span: the page counts like Python.
        campo = CFG.get("campo_marcado")
        if campo is None:
            self.skipTest("no campo_marcado")
        entradas = {c["nome"]: c["exemplo"] for c in CFG["campos"]}
        entradas[campo] = "🙂 Ação. " + entradas[campo]
        res = montar.carregar_adaptador(RAIZ).executar(entradas)
        self.assertEqual(montar.conferir_resultado(res, entradas, campo), [])

    def test_montar_leva_o_pacote_inteiro_e_so_ele(self):
        with tempfile.TemporaryDirectory() as tmp:
            nomes = montar.montar(RAIZ, Path(tmp) / "site")
            with zipfile.ZipFile(Path(tmp) / "site" / "pacote.zip") as z:
                self.assertEqual(sorted(z.namelist()), sorted(nomes))
            self.assertIn("vitrine.py", nomes)
            self.assertFalse([n for n in nomes if "__pycache__" in n or n.endswith(".pyc")])
            esperado = {p.relative_to(RAIZ).as_posix() for p in (RAIZ / CFG["pacote"]).rglob("*")
                        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
            self.assertEqual(set(nomes) - {"vitrine.py"}, esperado)
            self.assertEqual(sorted(p.name for p in (Path(tmp) / "site").iterdir()),
                             ["index.html", "pacote.zip", "vitrine.json"])

    def test_saida_com_outra_coisa_e_recusada_intacta(self):
        with tempfile.TemporaryDirectory() as tmp:
            alheio = Path(tmp) / "importante.txt"
            alheio.write_text("não apagar", encoding="utf-8")
            with self.assertRaises(SystemExit):
                montar.montar(RAIZ, Path(tmp))
            self.assertEqual(alheio.read_text(encoding="utf-8"), "não apagar")

    def test_remontar_na_mesma_saida(self):
        with tempfile.TemporaryDirectory() as tmp:
            montar.montar(RAIZ, Path(tmp) / "site")
            montar.montar(RAIZ, Path(tmp) / "site")

    def test_cache_do_python_fica_de_fora(self):
        # Copy of the root with a planted cache: the real tree may have no cache.
        with tempfile.TemporaryDirectory() as tmp:
            copia = Path(tmp) / "raiz"
            for pasta in ("vitrine", CFG["pacote"]):
                shutil.copytree(RAIZ / pasta, copia / pasta,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            cache = copia / CFG["pacote"] / "__pycache__"
            cache.mkdir()
            (cache / "plantado.cpython-314.pyc").write_bytes(b"x")
            (copia / CFG["pacote"] / "solto.pyc").write_bytes(b"x")
            nomes = montar.montar(copia, Path(tmp) / "site")
            self.assertFalse([n for n in nomes if "__pycache__" in n or n.endswith(".pyc")], nomes)

    def test_ordem_do_zip_com_caixa_como_no_linux(self):
        # Uppercase before lowercase, as the CI's Linux sorts; Windows Path does not
        with tempfile.TemporaryDirectory() as tmp:
            copia = Path(tmp) / "raiz"
            for pasta in ("vitrine", CFG["pacote"]):
                shutil.copytree(RAIZ / pasta, copia / pasta,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            (copia / CFG["pacote"] / "a_plantado.txt").write_text("a", encoding="utf-8")
            (copia / CFG["pacote"] / "B_plantado.txt").write_text("b", encoding="utf-8")
            nomes = montar.montar(copia, Path(tmp) / "site")[:-1]  # the last one is vitrine.py
            self.assertEqual(nomes, sorted(nomes))

    def test_zip_sem_data_da_montagem(self):
        # Same tree, same zip: no entry carries the build time.
        with tempfile.TemporaryDirectory() as tmp:
            montar.montar(RAIZ, Path(tmp) / "site")
            with zipfile.ZipFile(Path(tmp) / "site" / "pacote.zip") as z:
                datas = {i.date_time for i in z.infolist()}
                sistemas = {(i.create_system, i.external_attr) for i in z.infolist()}
            self.assertEqual(datas, {(2020, 1, 1, 0, 0, 0)})
            # nor the system that built it (0 on Windows, 3 on Linux)
            self.assertEqual(sistemas, {(3, 0o644 << 16)})

    def test_pagina_sem_js_mostra_o_projeto(self):
        # Link previews and indexers do not run JS: title, description and language
        # come baked into the HTML, escaped.
        cfg = json.loads((RAIZ / "vitrine" / "vitrine.json").read_text(encoding="utf-8"))
        cfg = {**cfg, "titulo": 'A <b> & "c"', "descricao": 'D "e" <f>', "lang": "en"}
        texto = montar.pagina(RAIZ, cfg).decode("utf-8")
        self.assertIn("<title>A &lt;b&gt; &amp; &quot;c&quot;</title>", texto)
        self.assertIn('<meta name="description" content="D &quot;e&quot; &lt;f&gt;">', texto)
        self.assertIn('<html lang="en">', texto)
        self.assertNotIn("<title>Vitrine</title>", texto)

    def test_montar_grava_a_pagina(self):
        # The index.html that montar produces is the one from pagina(), not the template's copy.
        cfg = json.loads((RAIZ / "vitrine" / "vitrine.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            montar.montar(RAIZ, Path(tmp) / "site")
            gravado = (Path(tmp) / "site" / "index.html").read_bytes()
        self.assertEqual(gravado, montar.pagina(RAIZ, cfg))
        self.assertNotIn(b"<title>Vitrine</title>", gravado)

    def test_pagina_sem_a_marca_e_recusada(self):
        with tempfile.TemporaryDirectory() as tmp:
            copia = Path(tmp) / "b"
            (copia / "vitrine").mkdir(parents=True)
            (copia / "vitrine" / "index.html").write_text('<html lang="pt-BR"><title>Outro</title>', encoding="utf-8")
            with self.assertRaises(SystemExit):
                montar.pagina(copia, {"titulo": "x", "descricao": "y"})


class Contrato(unittest.TestCase):
    """Two proofs for the checker: it accepts the valid, it catches each planted defect."""

    def erros(self, res, texto="abcdef"):
        return montar.conferir_resultado(res, {"t": texto}, "t")

    def test_valido_passa(self):
        self.assertEqual(self.erros(_valido()), [])

    def test_defeitos_plantados(self):
        casos = {
            "no resumo": lambda r: r.pop("resumo"),
            "fim beyond the text": lambda r: r["marcas"][0].update(fim=7),
            "inicio equal to fim": lambda r: r["marcas"][0].update(inicio=3),
            "position as text": lambda r: r["marcas"][0].update(inicio="0"),
            "boolean position": lambda r: r["marcas"][0].update(inicio=False),
            "empty rotulo": lambda r: r["marcas"][0].update(rotulo=""),
            "wrong key": lambda r: r.update(marca=[]),
            "wrong key in the mark": lambda r: r["marcas"][0].update(cor="x"),
            "short row": lambda r: r["tabela"]["linhas"].append(["só uma"]),
            "object cell": lambda r: r["tabela"]["linhas"].append([{}, 1]),
            "no colunas": lambda r: r["tabela"].pop("colunas"),
            "does not become JSON": lambda r: r.update(aviso={1}),
            "NaN cell": lambda r: r["tabela"]["linhas"].append(["1", float("nan")]),
            "infinite cell": lambda r: r["tabela"]["linhas"].append(["1", float("inf")]),
        }
        for nome, estragar in casos.items():
            with self.subTest(nome):
                r = _valido()
                estragar(r)
                self.assertNotEqual(self.erros(r), [], nome)

    def test_marcas_sem_campo_marcado(self):
        self.assertNotEqual(montar.conferir_resultado(_valido(), {"t": "abcdef"}, None), [])

    def test_config_plantada(self):
        casos = {
            "unknown tipo": lambda c: c["campos"][0].update(tipo="numero"),
            "no exemplo": lambda c: c["campos"][0].pop("exemplo"),
            "nonexistent campo_marcado": lambda c: c.update(campo_marcado="outro"),
            "wrong key": lambda c: c.update(titlo="x"),
            "empty titulo": lambda c: c.update(titulo=" "),
            "descricao not text": lambda c: c.update(descricao=3),
            "empty lang": lambda c: c.update(lang=""),
            "wrong field key": lambda c: c["campos"][0].update(rotlo="x"),
            # the 1st field may be a file field, and then aceita is valid
            "aceita outside a file field": lambda c: c["campos"][0].update(tipo="textarea", aceita=".txt"),
            "repositorio without https": lambda c: c.update(repositorio="github.com/x"),
            "pacote as a path": lambda c: c.update(pacote="../outro"),
            "empty campos": lambda c: c.update(campos=[]),
            "link javascript:": lambda c: c.update(links=[{"texto": "x", "href": "javascript:alert(1)"}]),
            "link http": lambda c: c.update(links=[{"texto": "x", "href": "http://exemplo.com"}]),
            "link without texto": lambda c: c.update(links=[{"href": "https://exemplo.com"}]),
            "link with wrong key": lambda c: c.update(links=[{"texto": "x", "href": "https://e.com", "url": "x"}]),
            "links not a list": lambda c: c.update(links={"texto": "x"}),
            "exemplos not a list": lambda c: c.update(exemplos={"rotulo": "x"}),
            "exemplo without rotulo": lambda c: c.update(exemplos=[{"valores": {_com_texto(c): "x"}}]),
            "exemplo without valores": lambda c: c.update(exemplos=[{"rotulo": "x", "valores": {}}]),
            "exemplo with wrong key": lambda c: c.update(
                exemplos=[{"rotulo": "x", "valores": {_com_texto(c): "x"}, "valor": "x"}]),
            "exemplo of nonexistent field": lambda c: c.update(
                exemplos=[{"rotulo": "x", "valores": {"inexistente": "x"}}]),
            "exemplo of file field": lambda c: c.update(
                exemplos=[{"rotulo": "x", "valores": {_com_arquivo(c): "x"}}]),
            "exemplo with numeric value": lambda c: c.update(
                exemplos=[{"rotulo": "x", "valores": {_com_texto(c): 1}}]),
        }
        for nome, estragar in casos.items():
            with self.subTest(nome):
                c = json.loads(json.dumps(CFG))
                estragar(c)
                self.assertNotEqual(montar.conferir_config(c), [], nome)

    def test_campo_de_arquivo_com_aceita_passa(self):
        c = json.loads(json.dumps(CFG))
        c["campos"].append({"nome": "a", "rotulo": "A", "tipo": "arquivo", "exemplo": "x", "aceita": ".jsonl"})
        self.assertEqual(montar.conferir_config(c), [])

    def test_links_https_passam(self):
        c = json.loads(json.dumps(CFG))
        c["links"] = [{"texto": "Lista de espera", "href": "https://github.com/dono/repo/issues/1"}]
        self.assertEqual(montar.conferir_config(c), [])

    def test_exemplos_validos_passam(self):
        c = json.loads(json.dumps(CFG))
        c["exemplos"] = [{"rotulo": "HTML", "valores": {_com_texto(c): "<p>oi</p>"}}]
        self.assertEqual(montar.conferir_config(c), [])

    def test_conferir_roda_cada_exemplo(self):
        # The adapter receives the default and, then, each example on top of it.
        c = json.loads(json.dumps(CFG))
        nome = _com_texto(c)
        c["exemplos"] = [{"rotulo": "outro", "valores": {nome: "outro"}}]
        recebidas = []

        class Adaptador:
            @staticmethod
            def executar(entradas):
                recebidas.append(dict(entradas))
                return {"resumo": "ok"}

        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "vitrine").mkdir()
            (raiz / "vitrine" / "vitrine.json").write_text(json.dumps(c), encoding="utf-8")
            (raiz / c["pacote"]).mkdir(parents=True)
            (raiz / c["pacote"] / "__init__.py").write_text("", encoding="utf-8")
            with mock.patch.object(montar, "carregar_adaptador", return_value=Adaptador):
                self.assertEqual(montar.conferir(raiz), [])
        padrao = {x["nome"]: x["exemplo"] for x in c["campos"]}
        self.assertEqual(recebidas, [padrao, {**padrao, nome: "outro"}])


if __name__ == "__main__":
    unittest.main()
