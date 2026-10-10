"""Monta a vitrine: a página que roda a biblioteca no navegador (Pyodide).

Modelo da Coordenação (`modelo/vitrine/LEIA-ME.md`). Mora em `vitrine/` na
raiz da biblioteca, ao lado de `index.html`, `vitrine.json` e `vitrine.py`.

    python vitrine/montar.py              confere e monta em _site/
    python vitrine/montar.py --conferir   só confere (configuração e adaptador)
    python vitrine/montar.py --saida X    monta em X

Conferir = a configuração tem o que a página lê, e o adaptador, rodado aqui em
Python normal com o exemplo de cada campo (e com cada um dos `exemplos` a
mais), devolve o formato que a página desenha. A página nunca recebe o que este script não aprovou.

Montar = `index.html` e `vitrine.json` copiados, e `pacote.zip` com o pacote
(sem `__pycache__`) mais `vitrine.py` na raiz do zip. Um arquivo só para o
navegador baixar, e o zip sai igual byte a byte da mesma árvore.
"""
import argparse
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
    """Erros da configuração (lista vazia = certa)."""
    erros = []
    if not isinstance(cfg, dict):
        return ["vitrine.json não é um objeto"]
    for k in sorted(OBRIGATORIAS - cfg.keys()):
        erros.append(f"falta a chave {k!r}")
    for k in sorted(cfg.keys() - OBRIGATORIAS - OPCIONAIS):
        erros.append(f"chave desconhecida {k!r}")
    campos = cfg.get("campos")
    if not isinstance(campos, list) or not campos:
        return erros + ["'campos' precisa ser lista com ao menos um campo"]
    nomes = []
    for i, c in enumerate(campos):
        for k in ("nome", "rotulo", "tipo", "exemplo"):
            if not isinstance(c.get(k), str):
                erros.append(f"campos[{i}]: {k!r} precisa ser texto")
        if c.get("tipo") not in TIPOS:
            erros.append(f"campos[{i}]: tipo {c.get('tipo')!r} fora de {sorted(TIPOS)}")
        # "aceita" (ex.: ".jsonl") filtra o seletor; só existe no campo de arquivo.
        permitidas = CHAVES_CAMPO | ({"aceita"} if c.get("tipo") == "arquivo" else set())
        for k in sorted(c.keys() - permitidas):
            erros.append(f"campos[{i}]: chave desconhecida {k!r}")
        if "aceita" in c and not isinstance(c["aceita"], str):
            erros.append(f"campos[{i}]: 'aceita' precisa ser texto")
        nomes.append(c.get("nome"))
    if len(set(nomes)) != len(nomes):
        erros.append("nome de campo repetido")
    marcado = cfg.get("campo_marcado")
    if marcado is not None:
        tipo = next((c.get("tipo") for c in campos if c.get("nome") == marcado), None)
        if tipo is None:
            erros.append(f"campo_marcado {marcado!r} não é um dos campos")
        elif tipo == "arquivo":
            erros.append("campo_marcado não pode ser do tipo 'arquivo' (a página não o mostra)")
    # nome de pacote, não caminho: "../outro" levaria ao zip público o que está fora da biblioteca
    if not str(cfg.get("pacote", "")).isidentifier():
        erros.append("'pacote' precisa ser o nome do pacote (letras, números e _), não um caminho")
    if not str(cfg.get("repositorio", "")).startswith("https://"):
        erros.append("'repositorio' precisa começar com https://")
    # links do rodapé (SN, 10/10: a lista de espera numa issue): só https://,
    # para um javascript: no vitrine.json não virar link na página.
    links = cfg.get("links", [])
    if not isinstance(links, list):
        erros.append("'links' precisa ser lista")
        links = []
    for i, l in enumerate(links):
        if not isinstance(l, dict):
            erros.append(f"links[{i}] não é objeto")
            continue
        for k in sorted(l.keys() - {"texto", "href"}):
            erros.append(f"links[{i}]: chave desconhecida {k!r}")
        if not isinstance(l.get("texto"), str) or not l.get("texto"):
            erros.append(f"links[{i}]: 'texto' precisa ser texto não vazio")
        if not str(l.get("href", "")).startswith("https://"):
            erros.append(f"links[{i}]: 'href' precisa começar com https://")
    # exemplos a mais (LS, 10/10: texto e HTML no mesmo campo): cada um troca
    # o exemplo de alguns campos; o campo de arquivo fica de fora, porque a
    # página não guarda valor nele (vazio, roda com o "exemplo" do campo).
    exemplos = cfg.get("exemplos", [])
    if not isinstance(exemplos, list):
        erros.append("'exemplos' precisa ser lista")
        exemplos = []
    de_texto = {c.get("nome") for c in campos if c.get("tipo") != "arquivo"}
    for i, e in enumerate(exemplos):
        if not isinstance(e, dict):
            erros.append(f"exemplos[{i}] não é objeto")
            continue
        for k in sorted(e.keys() - {"rotulo", "valores"}):
            erros.append(f"exemplos[{i}]: chave desconhecida {k!r}")
        if not isinstance(e.get("rotulo"), str) or not e.get("rotulo"):
            erros.append(f"exemplos[{i}]: 'rotulo' precisa ser texto não vazio")
        valores = e.get("valores")
        if not isinstance(valores, dict) or not valores:
            erros.append(f"exemplos[{i}]: 'valores' precisa ser objeto com ao menos um campo")
            continue
        for k, v in valores.items():
            if k not in de_texto:
                erros.append(f"exemplos[{i}]: {k!r} não é campo de texto")
            if not isinstance(v, str):
                erros.append(f"exemplos[{i}]: o valor de {k!r} precisa ser texto")
    return erros


def conferir_resultado(res, entradas, campo_marcado=None):
    """Erros do que o adaptador devolveu (lista vazia = a página desenha)."""
    if not isinstance(res, dict):
        return [f"o adaptador devolveu {type(res).__name__}, não dict"]
    erros = [f"chave desconhecida {k!r}" for k in sorted(res.keys() - CHAVES_RESULTADO)]
    if not isinstance(res.get("resumo"), str) or not res.get("resumo"):
        erros.append("'resumo' precisa ser texto não vazio")
    if "aviso" in res and not isinstance(res["aviso"], str):
        erros.append("'aviso' precisa ser texto")
    marcas = res.get("marcas", [])
    if marcas and campo_marcado is None:
        erros.append("há 'marcas', mas a configuração não diz o campo_marcado")
    if not isinstance(marcas, list):
        erros.append("'marcas' precisa ser lista")
        marcas = []
    # Posições em caracteres do Python (pontos de código), como a página
    # conta com Array.from: emoji conta 1 nos dois lados.
    tamanho = len(entradas.get(campo_marcado, "")) if campo_marcado else 0
    for i, m in enumerate(marcas):
        if not isinstance(m, dict):
            erros.append(f"marcas[{i}] não é objeto")
            continue
        ini, fim = m.get("inicio"), m.get("fim")
        if not (type(ini) is int and type(fim) is int and 0 <= ini < fim <= tamanho):
            erros.append(f"marcas[{i}]: precisa 0 <= inicio < fim <= {tamanho}; veio {ini!r}..{fim!r}")
        if not isinstance(m.get("rotulo"), str) or not m.get("rotulo"):
            erros.append(f"marcas[{i}]: 'rotulo' precisa ser texto não vazio")
        if "detalhe" in m and not isinstance(m["detalhe"], str):
            erros.append(f"marcas[{i}]: 'detalhe' precisa ser texto")
        for k in sorted(m.keys() - {"inicio", "fim", "rotulo", "detalhe"}):
            erros.append(f"marcas[{i}]: chave desconhecida {k!r}")
    if "tabela" in res:
        t = res["tabela"]
        colunas = t.get("colunas") if isinstance(t, dict) else None
        linhas = t.get("linhas") if isinstance(t, dict) else None
        if isinstance(t, dict) and "titulo" in t and not isinstance(t["titulo"], str):
            erros.append("tabela: 'titulo' precisa ser texto")
        if isinstance(t, dict):
            erros += [f"tabela: chave desconhecida {k!r}" for k in sorted(t.keys() - {"titulo", "colunas", "linhas"})]
        if not (isinstance(colunas, list) and colunas and all(isinstance(c, str) for c in colunas)):
            erros.append("tabela: 'colunas' precisa ser lista de textos")
        elif not isinstance(linhas, list):
            erros.append("tabela: 'linhas' precisa ser lista")
        else:
            for i, linha in enumerate(linhas):
                if not isinstance(linha, list) or len(linha) != len(colunas):
                    erros.append(f"tabela: linha {i} não tem {len(colunas)} células")
                elif not all(isinstance(c, (str, int, float)) for c in linha):
                    erros.append(f"tabela: linha {i} tem célula que não é texto nem número")
    try:
        # NaN e Infinity viram JSON que o JSON.parse da página recusa
        json.dumps(res, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as e:
        erros.append(f"não vira JSON: {e}")
    return erros


def carregar_adaptador(raiz):
    """Importa vitrine/vitrine.py com a raiz da biblioteca no caminho."""
    sys.path.insert(0, str(raiz))
    try:
        spec = importlib.util.spec_from_file_location("vitrine", raiz / "vitrine" / "vitrine.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(raiz))
    return mod


def conferir(raiz):
    """Erros de configuração e do adaptador rodado com os exemplos."""
    cfg = json.loads((raiz / "vitrine" / "vitrine.json").read_text(encoding="utf-8"))
    erros = conferir_config(cfg)
    if erros:
        return erros
    if not (raiz / cfg["pacote"] / "__init__.py").is_file():
        return [f"pacote {cfg['pacote']!r} não encontrado em {raiz}"]
    padrao = {c["nome"]: c["exemplo"] for c in cfg["campos"]}
    adaptador = carregar_adaptador(raiz)
    erros = []
    for rotulo, valores in [("o exemplo", {})] + [(f"o exemplo {e['rotulo']!r}", e["valores"])
                                                   for e in cfg.get("exemplos", [])]:
        entradas = {**padrao, **valores}
        res = adaptador.executar(entradas)
        erros += [f"adaptador, com {rotulo}: {e}" for e in conferir_resultado(res, entradas, cfg.get("campo_marcado"))]
    return erros


def arquivos_do_pacote(raiz, pacote):
    base = raiz / pacote
    # ordem pelo texto do caminho: o Path do Windows ordena sem caixa, o do
    # Linux com, e o zip mudaria de uma máquina para outra
    return sorted((p for p in base.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"),
                  key=lambda p: p.relative_to(raiz).as_posix())


SAIDA = {"index.html", "vitrine.json", "pacote.zip"}


def montar(raiz, saida):
    cfg = json.loads((raiz / "vitrine" / "vitrine.json").read_text(encoding="utf-8"))
    # Só regrava o que ela mesma escreve: pasta com outra coisa (a raiz, o
    # pacote, um erro de digitação em --saida) é recusada, nunca esvaziada.
    if saida.exists():
        alheios = sorted(p.name for p in saida.iterdir() if p.name not in SAIDA)
        if alheios:
            raise SystemExit(f"vitrine: {saida} tem o que o montar não escreveu ({', '.join(alheios[:5])}); recusado")
    saida.mkdir(parents=True, exist_ok=True)
    for nome in ("index.html", "vitrine.json"):
        shutil.copyfile(raiz / "vitrine" / nome, saida / nome)
    entradas = [(p, p.relative_to(raiz).as_posix()) for p in arquivos_do_pacote(raiz, cfg["pacote"])]
    entradas.append((raiz / "vitrine" / "vitrine.py", "vitrine.py"))
    with zipfile.ZipFile(saida / "pacote.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for origem, nome in entradas:
            info = zipfile.ZipInfo(nome, DATA_FIXA)
            info.compress_type = zipfile.ZIP_DEFLATED
            # Unix sempre (SN, 10/10): o padrão é o sistema que monta (0 no
            # Windows, 3 no Linux do CI), e o zip mudaria de uma máquina para outra
            info.create_system = 3
            info.external_attr = 0o644 << 16
            z.writestr(info, origem.read_bytes())
    return [nome for _, nome in entradas]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--conferir", action="store_true", help="só confere, não monta")
    ap.add_argument("--saida", default="_site", help="pasta de saída (padrão: _site)")
    args = ap.parse_args(argv)
    raiz = AQUI.parent
    erros = conferir(raiz)
    for e in erros:
        print("vitrine:", e, file=sys.stderr)
    if erros:
        return 1
    if args.conferir:
        print("vitrine: configuração e adaptador conferidos")
        return 0
    nomes = montar(raiz, (raiz / args.saida).resolve())
    print(f"vitrine: {len(nomes)} arquivos em {args.saida}/pacote.zip")
    return 0


if __name__ == "__main__":
    sys.exit(main())
