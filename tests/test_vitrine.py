"""Vitrine: a configuração, o adaptador e o que o montar leva ao navegador.

Modelo da Coordenação (`modelo/vitrine/LEIA-ME.md`); mora em `tests/` da
biblioteca. Roda no gancho com os outros testes: se o adaptador deixar de
devolver o formato que a página desenha, o commit para aqui, não no navegador.
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
    """Nome de um campo do tipo pedido na configuração c, criando um se não houver
    (a do CM só tem campo de arquivo; a da LS, só de texto)."""
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
        # Emoji e acento antes do trecho: a página conta como o Python.
        campo = CFG.get("campo_marcado")
        if campo is None:
            self.skipTest("sem campo_marcado")
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
        # Cópia da raiz com cache plantado: a árvore real pode não ter cache.
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
        # Maiúscula antes de minúscula, como o Linux do CI ordena; o Path do Windows não
        with tempfile.TemporaryDirectory() as tmp:
            copia = Path(tmp) / "raiz"
            for pasta in ("vitrine", CFG["pacote"]):
                shutil.copytree(RAIZ / pasta, copia / pasta,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            (copia / CFG["pacote"] / "a_plantado.txt").write_text("a", encoding="utf-8")
            (copia / CFG["pacote"] / "B_plantado.txt").write_text("b", encoding="utf-8")
            nomes = montar.montar(copia, Path(tmp) / "site")[:-1]  # o último é o vitrine.py
            self.assertEqual(nomes, sorted(nomes))

    def test_zip_sem_data_da_montagem(self):
        # Mesma árvore, mesmo zip: nenhuma entrada leva a hora da montagem.
        with tempfile.TemporaryDirectory() as tmp:
            montar.montar(RAIZ, Path(tmp) / "site")
            with zipfile.ZipFile(Path(tmp) / "site" / "pacote.zip") as z:
                datas = {i.date_time for i in z.infolist()}
                sistemas = {(i.create_system, i.external_attr) for i in z.infolist()}
            self.assertEqual(datas, {(2020, 1, 1, 0, 0, 0)})
            # nem o sistema que montou (SN, 10/10: 0 no Windows, 3 no Linux)
            self.assertEqual(sistemas, {(3, 0o644 << 16)})


class Contrato(unittest.TestCase):
    """Duas provas do conferidor: aceita o válido, pega cada defeito plantado."""

    def erros(self, res, texto="abcdef"):
        return montar.conferir_resultado(res, {"t": texto}, "t")

    def test_valido_passa(self):
        self.assertEqual(self.erros(_valido()), [])

    def test_defeitos_plantados(self):
        casos = {
            "sem resumo": lambda r: r.pop("resumo"),
            "fim além do texto": lambda r: r["marcas"][0].update(fim=7),
            "inicio igual ao fim": lambda r: r["marcas"][0].update(inicio=3),
            "posição em texto": lambda r: r["marcas"][0].update(inicio="0"),
            "posição booleana": lambda r: r["marcas"][0].update(inicio=False),
            "rótulo vazio": lambda r: r["marcas"][0].update(rotulo=""),
            "chave errada": lambda r: r.update(marca=[]),
            "chave errada na marca": lambda r: r["marcas"][0].update(cor="x"),
            "linha curta": lambda r: r["tabela"]["linhas"].append(["só uma"]),
            "célula objeto": lambda r: r["tabela"]["linhas"].append([{}, 1]),
            "sem colunas": lambda r: r["tabela"].pop("colunas"),
            "não vira JSON": lambda r: r.update(aviso={1}),
            "célula NaN": lambda r: r["tabela"]["linhas"].append(["1", float("nan")]),
            "célula infinita": lambda r: r["tabela"]["linhas"].append(["1", float("inf")]),
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
            "tipo desconhecido": lambda c: c["campos"][0].update(tipo="numero"),
            "sem exemplo": lambda c: c["campos"][0].pop("exemplo"),
            "campo marcado inexistente": lambda c: c.update(campo_marcado="outro"),
            "chave errada": lambda c: c.update(titlo="x"),
            "chave de campo errada": lambda c: c["campos"][0].update(rotlo="x"),
            # o 1º campo pode ser de arquivo, e aí o aceita vale (CM, 10/10)
            "aceita fora de arquivo": lambda c: c["campos"][0].update(tipo="textarea", aceita=".txt"),
            "repositório sem https": lambda c: c.update(repositorio="github.com/x"),
            "pacote como caminho": lambda c: c.update(pacote="../outro"),
            "campos vazio": lambda c: c.update(campos=[]),
            "link javascript:": lambda c: c.update(links=[{"texto": "x", "href": "javascript:alert(1)"}]),
            "link http": lambda c: c.update(links=[{"texto": "x", "href": "http://exemplo.com"}]),
            "link sem texto": lambda c: c.update(links=[{"href": "https://exemplo.com"}]),
            "link com chave errada": lambda c: c.update(links=[{"texto": "x", "href": "https://e.com", "url": "x"}]),
            "links fora de lista": lambda c: c.update(links={"texto": "x"}),
            "exemplos fora de lista": lambda c: c.update(exemplos={"rotulo": "x"}),
            "exemplo sem rótulo": lambda c: c.update(exemplos=[{"valores": {_com_texto(c): "x"}}]),
            "exemplo sem valores": lambda c: c.update(exemplos=[{"rotulo": "x", "valores": {}}]),
            "exemplo com chave errada": lambda c: c.update(
                exemplos=[{"rotulo": "x", "valores": {_com_texto(c): "x"}, "valor": "x"}]),
            "exemplo de campo inexistente": lambda c: c.update(
                exemplos=[{"rotulo": "x", "valores": {"inexistente": "x"}}]),
            "exemplo de campo de arquivo": lambda c: c.update(
                exemplos=[{"rotulo": "x", "valores": {_com_arquivo(c): "x"}}]),
            "exemplo com valor número": lambda c: c.update(
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
        # O adaptador recebe o padrão e, depois, cada exemplo por cima dele.
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
