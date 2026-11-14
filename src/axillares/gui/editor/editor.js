// Editor do Axillares. Só edita: ler e gravar arquivos é com o Python (ponte QWebChannel).
"use strict";

// Workers do Monaco a partir de file://: um bootstrap em data: URL importa o worker local.
const BASE_MONACO = new URL("monaco/", location.href).href;
window.MonacoEnvironment = {
  getWorkerUrl() {
    return "data:text/javascript;charset=utf-8," + encodeURIComponent(
      `self.MonacoEnvironment = { baseUrl: "${BASE_MONACO}" };` +
      `importScripts("${BASE_MONACO}vs/base/worker/workerMain.js");`);
  },
};

const estado = { ponte: null, modelos: new Map(), visoes: new Map(), atual: null, salvos: new Map(),
                 editor: null, fila: [], decoracoes: new Map(), caminhoDe: new WeakMap(),
                 mudancas: new Map(), respostas: new Map(), proximo: 1 };
const ESPERA_MUDANCA_MS = 250;   // digitar rápido não inunda o servidor de linguagem
const LIMITE_RESPOSTA_MS = 8000;

const LINGUAGENS = { ".v": "systemverilog", ".sv": "systemverilog", ".vh": "systemverilog",
  ".svh": "systemverilog", ".sdc": "tcl", ".tcl": "tcl", ".xdc": "tcl", ".py": "python",
  ".md": "markdown", ".sh": "shell", ".toml": "ini", ".ini": "ini", ".pcf": "ini", ".lpf": "ini",
  ".cst": "ini" };

function linguagemDe(caminho) {
  const i = caminho.lastIndexOf(".");
  return i >= 0 ? (LINGUAGENS[caminho.slice(i).toLowerCase()] || "plaintext") : "plaintext";
}

// Comandos vindos do Python chegam como chamadas a window.axil.<nome>(...).
window.axil = {
  // Antes de o Monaco carregar, os comandos esperam na fila.
  _ou_fila(nome, args) { if (!estado.editor) { estado.fila.push([nome, args]); return true; } return false; },

  tema(t) {
    const r = document.documentElement.style;
    for (const [k, v] of Object.entries(t.css)) r.setProperty(k, v);
    if (window.monaco) { monaco.editor.defineTheme("axillares", t.monaco); monaco.editor.setTheme("axillares"); }
    else estado.tema = t;
  },

  abrir(caminho, texto) {
    if (this._ou_fila("abrir", [caminho, texto])) return;
    criarModelo(caminho, texto);
    mostrar(caminho);
  },

  // Arquivos citados por definição/referências/renomear, ainda não abertos em aba: o Monaco
  // precisa do modelo para espiar e editar. Viram aba se forem alterados.
  garantirModelos(textos) {
    if (this._ou_fila("garantirModelos", [textos])) return;
    for (const [caminho, texto] of Object.entries(textos || {})) criarModelo(caminho, texto);
  },

  resposta(id, dados) {
    const resolver = estado.respostas.get(id);
    if (!resolver) return;
    estado.respostas.delete(id);
    if (dados && dados.textos) window.axil.garantirModelos(dados.textos);
    resolver(dados ? dados.resultado : null);
  },

  acao(nome) {   // ação do Monaco pelo id: formatar, estrutura, renomear…
    if (this._ou_fila("acao", [nome])) return;
    const a = estado.editor.getAction(nome);
    if (a) { estado.editor.focus(); a.run(); }
  },

  recarregar(caminho, texto) {   // o arquivo mudou no disco e não havia alteração pendente
    const modelo = estado.modelos.get(caminho);
    if (!modelo) return;
    modelo.pushEditOperations([], [{ range: modelo.getFullModelRange(), text: texto }], () => null);
    estado.salvos.set(caminho, modelo.getAlternativeVersionId());
    avisarSujo(caminho);
  },

  fechar(caminho) {
    const modelo = estado.modelos.get(caminho);
    clearTimeout(estado.mudancas.get(caminho)); estado.mudancas.delete(caminho);
    if (modelo) modelo.dispose();
    estado.modelos.delete(caminho); estado.visoes.delete(caminho); estado.salvos.delete(caminho);
    if (estado.atual === caminho) { estado.atual = null; estado.editor.setModel(null);
      document.getElementById("editor").classList.remove("ativo"); }
  },

  salvo(caminho, versao) { estado.salvos.set(caminho, versao); avisarSujo(caminho); },

  pedirSalvar(caminho) {
    const alvo = caminho || estado.atual;
    const modelo = estado.modelos.get(alvo);
    if (modelo) estado.ponte.salvar(alvo, modelo.getValue(), modelo.getAlternativeVersionId());
  },

  pedirSalvarTodos() {
    for (const [caminho, modelo] of estado.modelos)
      if (modelo.getAlternativeVersionId() !== estado.salvos.get(caminho))
        estado.ponte.salvar(caminho, modelo.getValue(), modelo.getAlternativeVersionId());
  },

  // dono: "fluxo" (a execução falhou), "verible" (ao digitar) ou "verilator" (lint ao salvar).
  problemas(caminho, lista, dono) {   // [{linha, coluna, mensagem, gravidade, origem}]
    dono = dono || "fluxo";
    if (this._ou_fila("problemas", [caminho, lista, dono])) return;
    const modelo = estado.modelos.get(caminho);
    if (!modelo) { estado.pendentes = estado.pendentes || new Map();
                   estado.pendentes.set(caminho + "\u0000" + dono, [caminho, lista, dono]); return; }
    const S = monaco.MarkerSeverity;
    // Falha do fluxo: linha inteira tingida + ponto na margem — se vê de longe. Ao digitar, só o
    // sublinhado e o ponto: tingir a linha a cada tecla seria um pisca-pisca.
    const chave = caminho + "\u0000" + dono;
    const inteira = dono === "fluxo";
    const antigas = estado.decoracoes.get(chave) || [];
    estado.decoracoes.set(chave, modelo.deltaDecorations(antigas, lista.map(p => ({
      range: new monaco.Range(p.linha, 1, p.linha, 1),
      options: { isWholeLine: true,
                 className: !inteira ? null : p.gravidade === "erro" ? "linha-erro" : "linha-aviso",
                 glyphMarginClassName: p.gravidade === "erro" ? "glifo-erro" : "glifo-aviso",
                 glyphMarginHoverMessage: { value: p.mensagem },
                 overviewRuler: { position: monaco.editor.OverviewRulerLane.Full,
                                  color: getComputedStyle(document.documentElement).getPropertyValue(
                                    p.gravidade === "erro" ? "--falha" : "--aviso").trim() } } }))));
    monaco.editor.setModelMarkers(modelo, dono, lista.map(p => {
      const fim = modelo.getWordAtPosition({ lineNumber: p.linha, column: Math.max(1, p.coluna) });
      return { startLineNumber: p.linha, startColumn: Math.max(1, p.coluna),
               endLineNumber: p.linha, endColumn: fim ? fim.endColumn : Math.max(1, p.coluna) + 1,
               message: p.mensagem, severity: p.gravidade === "erro" ? S.Error : S.Warning,
               source: p.origem || "" };
    }));
  },

  irPara(caminho, linha, coluna) {
    if (this._ou_fila("irPara", [caminho, linha, coluna])) return;
    if (caminho !== estado.atual) mostrar(caminho);
    const pos = { lineNumber: linha, column: Math.max(1, coluna || 1) };
    estado.editor.setPosition(pos);
    estado.editor.revealPositionInCenter(pos, monaco.editor.ScrollType.Smooth);
    estado.editor.focus();
  },

  // Para testes: estado observável.
  _sonda() {
    const m = estado.atual && estado.modelos.get(estado.atual);
    return JSON.stringify({ atual: estado.atual, linguagem: m ? m.getLanguageId() : null,
      linhas: m ? m.getLineCount() : 0, abertos: [...estado.modelos.keys()],
      marcadores: m ? monaco.editor.getModelMarkers({ resource: m.uri }).length : 0,
      texto: m ? m.getValue() : "" });
  },
};

function criarModelo(caminho, texto) {
  let modelo = estado.modelos.get(caminho);
  if (modelo) return modelo;
  modelo = monaco.editor.createModel(texto, linguagemDe(caminho), monaco.Uri.file(caminho));
  modelo.updateOptions({ tabSize: 4, insertSpaces: true });
  estado.modelos.set(caminho, modelo);
  estado.caminhoDe.set(modelo, caminho);
  estado.salvos.set(caminho, modelo.getAlternativeVersionId());
  modelo.onDidChangeContent(() => { avisarSujo(caminho); agendarMudanca(caminho); });
  return modelo;
}

function agendarMudanca(caminho) {
  clearTimeout(estado.mudancas.get(caminho));
  estado.mudancas.set(caminho, setTimeout(() => enviarMudanca(caminho), ESPERA_MUDANCA_MS));
}

function enviarMudanca(caminho) {   // manda já o que estiver pendente (antes de um pedido)
  if (!estado.mudancas.has(caminho)) return;
  clearTimeout(estado.mudancas.get(caminho)); estado.mudancas.delete(caminho);
  const modelo = estado.modelos.get(caminho);
  if (modelo && estado.ponte) estado.ponte.mudou(caminho, modelo.getValue());
}

// Pedido ao servidor de linguagem, pelo Python. Resolve com null se não houver resposta.
function pedir(tipo, modelo, dados) {
  const caminho = estado.caminhoDe.get(modelo);
  if (!caminho || !estado.ponte) return Promise.resolve(null);
  enviarMudanca(caminho);
  return new Promise(resolver => {
    const id = estado.proximo++;
    estado.respostas.set(id, resolver);
    estado.ponte.pedir(id, tipo, caminho, JSON.stringify(dados || {}));
    setTimeout(() => window.axil.resposta(id, null), LIMITE_RESPOSTA_MS);
  });
}

function faixa(f) { return new monaco.Range(f.linha, f.coluna, f.linha_fim, f.coluna_fim); }
function posicao(p) { return { linha: p.lineNumber, coluna: p.column }; }
function lugares(lista) {
  return (lista || []).map(l => ({ uri: monaco.Uri.file(l.caminho), range: faixa(l) }));
}

function registrarLinguagem() {
  const L = monaco.languages, id = "systemverilog";
  const simbolo = s => ({ name: s.nome, detail: s.tipo, kind: Math.max(0, (s.codigo || 13) - 1),
    tags: [], range: faixa(s), selectionRange: faixa(s), children: (s.filhos || []).map(simbolo) });
  L.registerDocumentFormattingEditProvider(id, { displayName: "Verible",
    async provideDocumentFormattingEdits(m) {
      return ((await pedir("formatar", m)) || []).map(e => ({ range: faixa(e), text: e.texto }));
    } });
  L.registerDefinitionProvider(id, {
    async provideDefinition(m, p) { return lugares(await pedir("definicao", m, posicao(p))); } });
  L.registerReferenceProvider(id, {
    async provideReferences(m, p) { return lugares(await pedir("referencias", m, posicao(p))); } });
  L.registerDocumentHighlightProvider(id, {
    async provideDocumentHighlights(m, p) {
      return ((await pedir("destaques", m, posicao(p))) || []).map(f => ({ range: faixa(f),
        kind: L.DocumentHighlightKind.Text }));
    } });
  L.registerDocumentSymbolProvider(id, { displayName: "Verible",
    async provideDocumentSymbols(m) { return ((await pedir("simbolos", m)) || []).map(simbolo); } });
  L.registerHoverProvider(id, {
    async provideHover(m, p) {
      const texto = await pedir("dica", m, posicao(p));
      return texto ? { contents: [{ value: texto }] } : null;
    } });
  L.registerRenameProvider(id, {
    async provideRenameEdits(m, p, novo) {
      const r = await pedir("renomear", m, { ...posicao(p), novo });
      if (!r) return { edits: [], rejectReason: "O servidor de linguagem não respondeu." };
      return { edits: r.flatMap(a => a.edicoes.map(e => ({ resource: monaco.Uri.file(a.caminho),
        versionId: undefined, textEdit: { range: faixa(e), text: e.texto } }))) };
    } });
  // Ir à definição em outro arquivo: quem abre a aba é o Python.
  monaco.editor.registerEditorOpener({
    openCodeEditor(_fonte, recurso, selecao) {
      let linha = 1, coluna = 1;
      if (selecao && "startLineNumber" in selecao) { linha = selecao.startLineNumber; coluna = selecao.startColumn; }
      else if (selecao && "lineNumber" in selecao) { linha = selecao.lineNumber; coluna = selecao.column; }
      estado.ponte.abrirEm(recurso.path, linha, coluna);
      return true;
    } });
}

function mostrar(caminho) {
  if (estado.atual && estado.editor.getModel()) estado.visoes.set(estado.atual, estado.editor.saveViewState());
  estado.atual = caminho;
  estado.editor.setModel(estado.modelos.get(caminho));
  const visao = estado.visoes.get(caminho);
  if (visao) estado.editor.restoreViewState(visao);
  document.getElementById("editor").classList.add("ativo");
  if (estado.pendentes) {
    for (const [chave, args] of [...estado.pendentes]) {
      if (args[0] !== caminho) continue;
      estado.pendentes.delete(chave);
      window.axil.problemas(...args);
    }
  }
  estado.editor.focus();
  avisarCursor();
}

function avisarSujo(caminho) {
  const modelo = estado.modelos.get(caminho);
  if (!modelo || !estado.ponte) return;
  estado.ponte.sujo(caminho, modelo.getAlternativeVersionId() !== estado.salvos.get(caminho));
}

function avisarCursor() {
  if (!estado.ponte || !estado.atual) return;
  const p = estado.editor.getPosition();
  const m = estado.editor.getModel();
  if (p && m) estado.ponte.cursor(p.lineNumber, p.column, m.getLanguageId());
}

// Didática: dicas em português ao passar o mouse e trechos prontos (verilog-pt.json).
function registrarDidatica() {
  const dados = window.DIDATICA;
  if (!dados) return;
  monaco.languages.registerHoverProvider("systemverilog", {
    provideHover(modelo, posicao) {
      const linha = modelo.getLineContent(posicao.lineNumber);
      for (const [op, texto] of Object.entries(dados.operadores)) {
        const i = linha.indexOf(op, Math.max(0, posicao.column - 1 - op.length));
        if (i >= 0 && posicao.column - 1 >= i && posicao.column - 1 < i + op.length
            && (op !== "=" || !"<>=!".includes(linha[i - 1] || "") && linha[i + 1] !== "=")) {
          return { range: new monaco.Range(posicao.lineNumber, i + 1, posicao.lineNumber, i + 1 + op.length),
                   contents: [{ value: texto }] };
        }
      }
      const palavra = modelo.getWordAtPosition(posicao);
      if (!palavra) return null;
      const texto = dados.dicas[palavra.word];
      if (!texto) return null;
      return { range: new monaco.Range(posicao.lineNumber, palavra.startColumn, posicao.lineNumber, palavra.endColumn),
               contents: [{ value: texto }] };
    },
  });
  monaco.languages.registerCompletionItemProvider("systemverilog", {
    provideCompletionItems(modelo, posicao) {
      const palavra = modelo.getWordUntilPosition(posicao);
      const faixa = new monaco.Range(posicao.lineNumber, palavra.startColumn, posicao.lineNumber, palavra.endColumn);
      const K = monaco.languages.CompletionItemKind;
      const R = monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet;
      const trechos = dados.trechos.map(t => ({ label: t.rotulo, detail: t.detalhe, kind: K.Snippet,
        insertText: t.texto, insertTextRules: R, range: faixa, documentation: { value: "```verilog\n" + t.texto.replace(/\$\{\d+:([^}]*)\}/g, "$1").replace(/\$\d/g, "") + "\n```" } }));
      const palavras = Object.entries(dados.dicas).map(([p, d]) => ({ label: p, kind: K.Keyword,
        insertText: p, range: faixa, documentation: { value: d } }));
      return { suggestions: [...trechos, ...palavras] };
    },
  });
}

new QWebChannel(qt.webChannelTransport, canal => {
  estado.ponte = canal.objects.ponte;
  require.config({ paths: { vs: "monaco/vs" } });
  require(["vs/editor/editor.main"], () => {
    if (estado.tema) { monaco.editor.defineTheme("axillares", estado.tema.monaco); }
    estado.editor = monaco.editor.create(document.getElementById("editor"), {
      model: null, theme: estado.tema ? "axillares" : "vs-dark", automaticLayout: true,
      fontFamily: "Geist Mono", fontSize: 13.5, lineHeight: 22, letterSpacing: 0.2,
      fontLigatures: false, minimap: { enabled: true, renderCharacters: false, scale: 2 },
      smoothScrolling: true, cursorSmoothCaretAnimation: "on", cursorBlinking: "phase",
      cursorWidth: 2, renderLineHighlight: "all", roundedSelection: true, glyphMargin: true,
      lineDecorationsWidth: 6,
      bracketPairColorization: { enabled: true }, guides: { bracketPairs: "active", indentation: true },
      stickyScroll: { enabled: true }, padding: { top: 14, bottom: 14 }, scrollBeyondLastLine: false,
      overviewRulerBorder: false, hideCursorInOverviewRuler: true, fixedOverflowWidgets: true,
      scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10, useShadows: false },
      unicodeHighlight: { ambiguousCharacters: false }, wordWrap: "off", tabSize: 4,
      hover: { delay: 350 }, quickSuggestions: { other: true, comments: false, strings: false },
      suggest: { showWords: false, preview: true }, snippetSuggestions: "top",
    });
    estado.editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => window.axil.pedirSalvar());
    estado.editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => estado.ponte.acao("sintese"));
    estado.editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.Enter,
                             () => estado.ponte.acao("gds"));
    estado.editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyMod.Alt | monaco.KeyCode.Enter,
                             () => estado.ponte.acao("fpga"));
    estado.editor.onDidChangeCursorPosition(avisarCursor);
    registrarDidatica();
    registrarLinguagem();
    const fila = estado.fila; estado.fila = [];
    for (const [nome, args] of fila) window.axil[nome](...args);
    estado.ponte.pronto();
  });
});
