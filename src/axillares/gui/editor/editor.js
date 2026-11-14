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
                 editor: null, fila: [], decoracoes: new Map() };

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
    let modelo = estado.modelos.get(caminho);
    if (!modelo) {
      modelo = monaco.editor.createModel(texto, linguagemDe(caminho), monaco.Uri.file(caminho));
      modelo.updateOptions({ tabSize: 4, insertSpaces: true });
      estado.modelos.set(caminho, modelo);
      estado.salvos.set(caminho, modelo.getAlternativeVersionId());
      modelo.onDidChangeContent(() => avisarSujo(caminho));
    }
    mostrar(caminho);
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

  problemas(caminho, lista) {   // [{linha, coluna, mensagem, gravidade}]
    if (this._ou_fila("problemas", [caminho, lista])) return;
    const modelo = estado.modelos.get(caminho);
    if (!modelo) { estado.pendentes = estado.pendentes || new Map(); estado.pendentes.set(caminho, lista); return; }
    const S = monaco.MarkerSeverity;
    // linha inteira tingida + ponto na margem: o erro se vê de longe, mesmo no fim da linha
    const antigas = estado.decoracoes.get(caminho) || [];
    estado.decoracoes.set(caminho, modelo.deltaDecorations(antigas, lista.map(p => ({
      range: new monaco.Range(p.linha, 1, p.linha, 1),
      options: { isWholeLine: true,
                 className: p.gravidade === "erro" ? "linha-erro" : "linha-aviso",
                 glyphMarginClassName: p.gravidade === "erro" ? "glifo-erro" : "glifo-aviso",
                 glyphMarginHoverMessage: { value: p.mensagem },
                 overviewRuler: { position: monaco.editor.OverviewRulerLane.Full,
                                  color: getComputedStyle(document.documentElement).getPropertyValue(
                                    p.gravidade === "erro" ? "--falha" : "--aviso").trim() } } }))));
    monaco.editor.setModelMarkers(modelo, "axillares", lista.map(p => {
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
      marcadores: m ? monaco.editor.getModelMarkers({ resource: m.uri }).length : 0 });
  },
};

function mostrar(caminho) {
  if (estado.atual && estado.editor.getModel()) estado.visoes.set(estado.atual, estado.editor.saveViewState());
  estado.atual = caminho;
  estado.editor.setModel(estado.modelos.get(caminho));
  const visao = estado.visoes.get(caminho);
  if (visao) estado.editor.restoreViewState(visao);
  document.getElementById("editor").classList.add("ativo");
  if (estado.pendentes && estado.pendentes.has(caminho)) {
    const lista = estado.pendentes.get(caminho); estado.pendentes.delete(caminho);
    window.axil.problemas(caminho, lista);
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
    });
    estado.editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => window.axil.pedirSalvar());
    estado.editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => estado.ponte.acao("sintese"));
    estado.editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.Enter,
                             () => estado.ponte.acao("gds"));
    estado.editor.onDidChangeCursorPosition(avisarCursor);
    const fila = estado.fila; estado.fila = [];
    for (const [nome, args] of fila) window.axil[nome](...args);
    estado.ponte.pronto();
  });
});
