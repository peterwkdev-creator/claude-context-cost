"""Build the showcase: the page that runs the library in the browser (Pyodide).

Lives in `vitrine/` at the
library root, next to `index.html`, `vitrine.json` and `vitrine.py`.

    python vitrine/montar.py              check and build into _site/
    python vitrine/montar.py --conferir   check only (configuration and adapter)
    python vitrine/montar.py --saida X    build into X

Check = the configuration has what the page reads, and the adapter, run here in
plain Python with each field's example (and with each of the extra `exemplos`),
returns the format the page draws. The page never receives what this script has not approved.

Build = `index.html` with the title, description and language from the configuration baked in
(the page without JS shows the project), `vitrine.json` copied, and `pacote.zip` with the package
(without `__pycache__`) plus `vitrine.py` at the zip root. A single file for the
browser to download, and the zip comes out byte for byte identical from the same tree.
"""
import argparse
import html
import importlib.util
import json
import shutil
import sys
import zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
TIPOS = {"textarea", "texto", "arquivo"}
CHAVES_CAMPO = {"nome", "rotulo", "tipo", "exemplo"}
OBRIGATORIAS = {"titulo", "descricao", "pacote", "campos", "botao", "repositorio"}
OPCIONAIS = {"lang", "campo_marcado", "textos", "rodape", "links", "exemplos"}
CHAVES_RESULTADO = {"resumo", "aviso", "marcas", "tabela"}
DATA_FIXA = (2020, 1, 1, 0, 0, 0)


def conferir_config(cfg):
    """Configuration errors (empty list = valid)."""
    erros = []
    if not isinstance(cfg, dict):
        return ["vitrine.json is not an object"]
    for k in sorted(OBRIGATORIAS - cfg.keys()):
        erros.append(f"missing key {k!r}")
    for k in sorted(cfg.keys() - OBRIGATORIAS - OPCIONAIS):
        erros.append(f"unknown key {k!r}")
    # written into the HTML by montar: empty or non-text would break the page
    for k in ("titulo", "descricao", "lang"):
        if k in cfg and (not isinstance(cfg[k], str) or not cfg[k].strip()):
            erros.append(f"{k!r} must be non-empty text")
    campos = cfg.get("campos")
    if not isinstance(campos, list) or not campos:
        return erros + ["'campos' must be a list with at least one field"]
    nomes = []
    for i, c in enumerate(campos):
        for k in ("nome", "rotulo", "tipo", "exemplo"):
            if not isinstance(c.get(k), str):
                erros.append(f"campos[{i}]: {k!r} must be text")
        if c.get("tipo") not in TIPOS:
            erros.append(f"campos[{i}]: tipo {c.get('tipo')!r} not in {sorted(TIPOS)}")
        # "aceita" (e.g. ".jsonl") filters the file picker; it only exists on the file field.
        permitidas = CHAVES_CAMPO | ({"aceita"} if c.get("tipo") == "arquivo" else set())
        for k in sorted(c.keys() - permitidas):
            erros.append(f"campos[{i}]: unknown key {k!r}")
        if "aceita" in c and not isinstance(c["aceita"], str):
            erros.append(f"campos[{i}]: 'aceita' must be text")
        nomes.append(c.get("nome"))
    if len(set(nomes)) != len(nomes):
        erros.append("duplicate field name")
    marcado = cfg.get("campo_marcado")
    if marcado is not None:
        tipo = next((c.get("tipo") for c in campos if c.get("nome") == marcado), None)
        if tipo is None:
            erros.append(f"campo_marcado {marcado!r} is not one of the fields")
        elif tipo == "arquivo":
            erros.append("campo_marcado cannot be of type 'arquivo' (the page does not show it)")
    # package name, not a path: "../outro" would take what is outside the library into the public zip
    if not str(cfg.get("pacote", "")).isidentifier():
        erros.append("'pacote' must be the package name (letters, digits and _), not a path")
    if not str(cfg.get("repositorio", "")).startswith("https://"):
        erros.append("'repositorio' must start with https://")
    # footer links (the waiting list in an issue, for example): https:// only,
    # so a javascript: in vitrine.json does not become a link on the page.
    links = cfg.get("links", [])
    if not isinstance(links, list):
        erros.append("'links' must be a list")
        links = []
    for i, l in enumerate(links):
        if not isinstance(l, dict):
            erros.append(f"links[{i}] is not an object")
            continue
        for k in sorted(l.keys() - {"texto", "href"}):
            erros.append(f"links[{i}]: unknown key {k!r}")
        if not isinstance(l.get("texto"), str) or not l.get("texto"):
            erros.append(f"links[{i}]: 'texto' must be non-empty text")
        if not str(l.get("href", "")).startswith("https://"):
            erros.append(f"links[{i}]: 'href' must start with https://")
    # extra examples (text and HTML in the same field, for example): each one replaces
    # the example of some fields; the file field is left out, because the
    # page keeps no value in it (empty, it runs with the field's "exemplo").
    exemplos = cfg.get("exemplos", [])
    if not isinstance(exemplos, list):
        erros.append("'exemplos' must be a list")
        exemplos = []
    de_texto = {c.get("nome") for c in campos if c.get("tipo") != "arquivo"}
    for i, e in enumerate(exemplos):
        if not isinstance(e, dict):
            erros.append(f"exemplos[{i}] is not an object")
            continue
        for k in sorted(e.keys() - {"rotulo", "valores"}):
            erros.append(f"exemplos[{i}]: unknown key {k!r}")
        if not isinstance(e.get("rotulo"), str) or not e.get("rotulo"):
            erros.append(f"exemplos[{i}]: 'rotulo' must be non-empty text")
        valores = e.get("valores")
        if not isinstance(valores, dict) or not valores:
            erros.append(f"exemplos[{i}]: 'valores' must be an object with at least one field")
            continue
        for k, v in valores.items():
            if k not in de_texto:
                erros.append(f"exemplos[{i}]: {k!r} is not a text field")
            if not isinstance(v, str):
                erros.append(f"exemplos[{i}]: the value of {k!r} must be text")
    return erros


def conferir_resultado(res, entradas, campo_marcado=None):
    """Errors in what the adapter returned (empty list = the page draws it)."""
    if not isinstance(res, dict):
        return [f"the adapter returned {type(res).__name__}, not dict"]
    erros = [f"unknown key {k!r}" for k in sorted(res.keys() - CHAVES_RESULTADO)]
    if not isinstance(res.get("resumo"), str) or not res.get("resumo"):
        erros.append("'resumo' must be non-empty text")
    if "aviso" in res and not isinstance(res["aviso"], str):
        erros.append("'aviso' must be text")
    marcas = res.get("marcas", [])
    if marcas and campo_marcado is None:
        erros.append("there are 'marcas', but the configuration does not name the campo_marcado")
    if not isinstance(marcas, list):
        erros.append("'marcas' must be a list")
        marcas = []
    # Positions in Python characters (code points), as the page
    # counts with Array.from: an emoji counts 1 on both sides.
    tamanho = len(entradas.get(campo_marcado, "")) if campo_marcado else 0
    for i, m in enumerate(marcas):
        if not isinstance(m, dict):
            erros.append(f"marcas[{i}] is not an object")
            continue
        ini, fim = m.get("inicio"), m.get("fim")
        if not (type(ini) is int and type(fim) is int and 0 <= ini < fim <= tamanho):
            erros.append(f"marcas[{i}]: needs 0 <= inicio < fim <= {tamanho}; got {ini!r}..{fim!r}")
        if not isinstance(m.get("rotulo"), str) or not m.get("rotulo"):
            erros.append(f"marcas[{i}]: 'rotulo' must be non-empty text")
        if "detalhe" in m and not isinstance(m["detalhe"], str):
            erros.append(f"marcas[{i}]: 'detalhe' must be text")
        for k in sorted(m.keys() - {"inicio", "fim", "rotulo", "detalhe"}):
            erros.append(f"marcas[{i}]: unknown key {k!r}")
    if "tabela" in res:
        t = res["tabela"]
        colunas = t.get("colunas") if isinstance(t, dict) else None
        linhas = t.get("linhas") if isinstance(t, dict) else None
        if isinstance(t, dict) and "titulo" in t and not isinstance(t["titulo"], str):
            erros.append("tabela: 'titulo' must be text")
        if isinstance(t, dict):
            erros += [f"tabela: unknown key {k!r}" for k in sorted(t.keys() - {"titulo", "colunas", "linhas"})]
        if not (isinstance(colunas, list) and colunas and all(isinstance(c, str) for c in colunas)):
            erros.append("tabela: 'colunas' must be a list of text")
        elif not isinstance(linhas, list):
            erros.append("tabela: 'linhas' must be a list")
        else:
            for i, linha in enumerate(linhas):
                if not isinstance(linha, list) or len(linha) != len(colunas):
                    erros.append(f"tabela: row {i} does not have {len(colunas)} cells")
                elif not all(isinstance(c, (str, int, float)) for c in linha):
                    erros.append(f"tabela: row {i} has a cell that is neither text nor a number")
    try:
        # NaN and Infinity become JSON that the page's JSON.parse rejects
        json.dumps(res, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as e:
        erros.append(f"does not become JSON: {e}")
    return erros


def carregar_adaptador(raiz):
    """Import vitrine/vitrine.py with the library root on the path."""
    sys.path.insert(0, str(raiz))
    try:
        spec = importlib.util.spec_from_file_location("vitrine", raiz / "vitrine" / "vitrine.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(raiz))
    return mod


def conferir(raiz):
    """Configuration errors and adapter errors when run with the examples."""
    cfg = json.loads((raiz / "vitrine" / "vitrine.json").read_text(encoding="utf-8"))
    erros = conferir_config(cfg)
    if erros:
        return erros
    if not (raiz / cfg["pacote"] / "__init__.py").is_file():
        return [f"package {cfg['pacote']!r} not found in {raiz}"]
    padrao = {c["nome"]: c["exemplo"] for c in cfg["campos"]}
    adaptador = carregar_adaptador(raiz)
    erros = []
    for rotulo, valores in [("the example", {})] + [(f"the example {e['rotulo']!r}", e["valores"])
                                                     for e in cfg.get("exemplos", [])]:
        entradas = {**padrao, **valores}
        res = adaptador.executar(entradas)
        erros += [f"adapter, with {rotulo}: {e}" for e in conferir_resultado(res, entradas, cfg.get("campo_marcado"))]
    return erros


def arquivos_do_pacote(raiz, pacote):
    base = raiz / pacote
    # order by path text: Windows Path sorts case-insensitively, Linux's
    # case-sensitively, and the zip would change from one machine to another
    return sorted((p for p in base.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"),
                  key=lambda p: p.relative_to(raiz).as_posix())


SAIDA = {"index.html", "vitrine.json", "pacote.zip"}
TITULO = "<title>Vitrine</title>"
LANG = '<html lang="pt-BR">'


def pagina(raiz, cfg):
    """The index.html with title, description and language baked in: the link preview
    and the indexer without JS used to read "Vitrine" and no sentence about the project."""
    texto = (raiz / "vitrine" / "index.html").read_bytes().decode("utf-8")
    for marca in (TITULO, LANG):
        if texto.count(marca) != 1:
            raise SystemExit(f"vitrine: index.html without {marca!r} exactly once; refused")
    titulo = html.escape(cfg["titulo"])
    descricao = html.escape(cfg["descricao"], quote=True)
    fim = "\r\n" if "\r\n" in texto else "\n"
    texto = texto.replace(TITULO, f'<title>{titulo}</title>{fim}<meta name="description" content="{descricao}">')
    # the same default as the JS (cfg.lang || "pt-BR")
    texto = texto.replace(LANG, f'<html lang="{html.escape(cfg.get("lang") or "pt-BR", quote=True)}">')
    return texto.encode("utf-8")


def montar(raiz, saida):
    cfg = json.loads((raiz / "vitrine" / "vitrine.json").read_text(encoding="utf-8"))
    # It only rewrites what it writes itself: a folder with anything else (the
    # root, the package, a typo in --saida) is refused, never emptied.
    if saida.exists():
        alheios = sorted(p.name for p in saida.iterdir() if p.name not in SAIDA)
        if alheios:
            raise SystemExit(f"vitrine: {saida} has what montar did not write ({', '.join(alheios[:5])}); refused")
    indice = pagina(raiz, cfg)  # before mkdir: if refused, it leaves no empty folder
    saida.mkdir(parents=True, exist_ok=True)
    (saida / "index.html").write_bytes(indice)
    shutil.copyfile(raiz / "vitrine" / "vitrine.json", saida / "vitrine.json")
    entradas = [(p, p.relative_to(raiz).as_posix()) for p in arquivos_do_pacote(raiz, cfg["pacote"])]
    entradas.append((raiz / "vitrine" / "vitrine.py", "vitrine.py"))
    with zipfile.ZipFile(saida / "pacote.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for origem, nome in entradas:
            info = zipfile.ZipInfo(nome, DATA_FIXA)
            info.compress_type = zipfile.ZIP_DEFLATED
            # Always Unix: the default is the system doing the build (0 on
            # Windows, 3 on the CI's Linux), and the zip would change from one machine to another
            info.create_system = 3
            info.external_attr = 0o644 << 16
            z.writestr(info, origem.read_bytes())
    return [nome for _, nome in entradas]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--conferir", action="store_true", help="check only, do not build")
    ap.add_argument("--saida", default="_site", help="output folder (default: _site)")
    args = ap.parse_args(argv)
    raiz = AQUI.parent
    erros = conferir(raiz)
    for e in erros:
        print("vitrine:", e, file=sys.stderr)
    if erros:
        return 1
    if args.conferir:
        print("vitrine: configuration and adapter checked")
        return 0
    nomes = montar(raiz, (raiz / args.saida).resolve())
    print(f"vitrine: {len(nomes)} files in {args.saida}/pacote.zip")
    return 0


if __name__ == "__main__":
    sys.exit(main())
