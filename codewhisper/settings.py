"""The CodeWhisper window: home, AI models, shortcuts, preferences, history."""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLineEdit,
                               QMainWindow, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
                               QStackedWidget, QVBoxLayout, QWidget)

from . import audio, hotkeys, theme, winutil
from .config import (DATA_DIR, DEFAULT_CLEANUP_PROMPT, LANG_LABELS, LANGUAGES, LLM_PROVIDERS,
                     LOCAL_MODELS, STT_PROVIDERS)
from .engines import LocalWhisper, list_remote_models
from .widgets import (BrandMark, Dot, Keycaps, ModelTile, Panel, Segmented, Toggle, hbox, label,
                      run_async)


def _page(title: str, lead: str = ""):
    """A scrollable page with a heading. Returns (scroll_area, content_layout)."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    body = QWidget()
    body.setObjectName("Page")
    outer = QHBoxLayout(body)
    outer.setContentsMargins(40, 34, 40, 40)
    col = QWidget()
    col.setMaximumWidth(760)
    lay = QVBoxLayout(col)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    lay.addWidget(label(title, "H1"))
    if lead:
        lay.addWidget(label(lead, "Lead", wrap=True))
    lay.addSpacing(14)
    outer.addWidget(col, 1)
    scroll.setWidget(body)
    return scroll, lay


def _section(lay, title: str, desc: str = ""):
    lay.addSpacing(14)
    lay.addWidget(label(title, "H2"))
    if desc:
        lay.addWidget(label(desc, "Small", wrap=True))
    lay.addSpacing(4)


def _combo(items: list[tuple[str, str]], current: str, editable=False) -> QComboBox:
    c = QComboBox()
    c.setEditable(editable)
    for key, text in items:
        c.addItem(text, key)
    idx = c.findData(current)
    if idx >= 0:
        c.setCurrentIndex(idx)
    elif editable:
        c.setEditText(current)
    c.setMinimumWidth(200)
    return c


def _when(ts: float) -> str:
    d = dt.datetime.fromtimestamp(ts)
    today = dt.date.today()
    if d.date() == today:
        return f"Aujourd'hui, {d:%H:%M}"
    if d.date() == today - dt.timedelta(days=1):
        return f"Hier, {d:%H:%M}"
    return f"{d:%d/%m/%Y, %H:%M}"


def _copy_button(get_text) -> QPushButton:
    b = QPushButton("Copier")
    b.setObjectName("Ghost")
    b.setCursor(Qt.PointingHandCursor)

    def _do():
        QGuiApplication.clipboard().setText(get_text())
        b.setText("Copié")
        QTimer.singleShot(1200, lambda: b.setText("Copier"))
    b.clicked.connect(_do)
    return b


class SettingsWindow(QMainWindow):
    PAGES = [("home", "Accueil"), ("models", "Modèles IA"), ("shortcuts", "Raccourcis"),
             ("prefs", "Préférences"), ("history", "Historique")]

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.cfg = app.config
        self.setWindowTitle("CodeWhisper")
        self.resize(1000, 720)
        self.setMinimumSize(860, 560)

        root = QWidget()
        root.setObjectName("Root")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._build_sidebar())
        self.stack = QStackedWidget()
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.pages = {}
        self._rebuild_pages()
        self.apply_theme()

        self.cfg.on_change(self._on_cfg)
        app.status_changed.connect(self._on_status)
        app.history_changed.connect(self._refresh_history_views)
        self._on_status(*app.status)

    # ── chrome ────────────────────────────────────────────────────────────────
    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(212)
        v = QVBoxLayout(side)
        v.setContentsMargins(14, 20, 14, 16)
        v.setSpacing(4)
        brand = hbox(BrandMark(), label("CodeWhisper", "Brand"), spacing=10, stretch_last=True)
        v.addWidget(brand)
        v.addSpacing(22)
        self.nav = {}
        for key, text in self.PAGES:
            b = QPushButton(text)
            b.setObjectName("NavButton")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            v.addWidget(b)
            self.nav[key] = b
        v.addStretch(1)
        self.side_dot = Dot()
        self.side_status = label("", "SideStatus", wrap=True)
        v.addWidget(hbox(self.side_dot, self.side_status, spacing=8))
        return side

    def show_page(self, key: str):
        self.nav[key].setChecked(True)
        self.stack.setCurrentWidget(self.pages[key])
        if key == "models":
            self._check_downloads()

    def apply_theme(self):
        t = theme.tokens(self.cfg.get("theme"))
        self.setProperty("tokens", t)
        self.setStyleSheet(theme.stylesheet(t))
        winutil.set_dark_title_bar(self, theme.is_dark(self.cfg.get("theme")))
        self.update()
        for w in self.findChildren(QWidget):
            w.update()

    def _rebuild_pages(self):
        current = next((k for k, b in self.nav.items() if b.isChecked()), "home")
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        builders = {"home": self._build_home, "models": self._build_models,
                    "shortcuts": self._build_shortcuts, "prefs": self._build_prefs,
                    "history": self._build_history}
        for key, _ in self.PAGES:
            self.pages[key] = builders[key]()
            self.stack.addWidget(self.pages[key])
        self.show_page(current)

    def _on_cfg(self, path: str):
        if path == "theme":
            self.apply_theme()
        elif path in ("shortcuts", "mode", "cancel_hotkey"):
            self._refresh_home_later()

    # ── status ────────────────────────────────────────────────────────────────
    def _on_status(self, kind: str, text: str):
        t = theme.tokens(self.cfg.get("theme"))
        color, msg = {
            "ready": (t["ok"], f"Prêt avec {text}"),
            "loading": (t["warn"], f"Chargement de {text}…"),
            "downloading": (t["warn"], f"Téléchargement de {text}…"),
            "error": (t["bad"], text),
        }.get(kind, (t["muted"], text))
        self.side_dot.set_color(color)
        self.side_status.setText(msg)
        if hasattr(self, "home_dot"):
            self.home_dot.set_color(color)
            self.home_status.setText(msg)
        self._refresh_tiles()

    # ══ Home ═════════════════════════════════════════════════════════════════
    def _build_home(self):
        page, lay = _page("Dicte n'importe où.",
                          "Place ton curseur dans n'importe quelle application, appuie sur un raccourci "
                          "et parle. Appuie à nouveau pour arrêter : le texte est collé à l'endroit du curseur.")
        self.home_dot = Dot()
        self.home_status = label("", "Muted")
        lay.addWidget(hbox(self.home_dot, self.home_status, spacing=8, stretch_last=True))
        lay.addSpacing(8)

        panel = Panel()
        for sc in self.cfg.get("shortcuts"):
            panel.add_row(LANG_LABELS.get(sc["language"], sc["language"]),
                          "Dicter dans cette langue", Keycaps(sc["hotkey"]))
        mode_desc = ("Maintiens le raccourci pendant que tu parles, relâche pour coller."
                     if self.cfg.get("mode") == "hold" else
                     "Ou clique sur la petite barre en bas de l'écran.")
        panel.add_row("Annuler", mode_desc, Keycaps(self.cfg.get("cancel_hotkey")))
        lay.addWidget(panel)

        _section(lay, "Ton rythme")
        self.stats_row = QWidget()
        self.stats_lay = QHBoxLayout(self.stats_row)
        self.stats_lay.setContentsMargins(0, 0, 0, 0)
        self.stats_lay.setSpacing(36)
        lay.addWidget(self.stats_row)

        _section(lay, "Dernières dictées")
        self.recent_box = QVBoxLayout()
        self.recent_box.setContentsMargins(0, 0, 0, 0)
        self.recent_box.setSpacing(0)
        holder = QWidget()
        holder.setLayout(self.recent_box)
        lay.addWidget(holder)
        lay.addStretch(1)
        self._fill_home()
        return page

    def _fill_home(self):
        while self.stats_lay.count():
            it = self.stats_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        s = self.app.history.stats()
        for value, caption in ((f"{s['week_words']:,}".replace(",", " "), "mots dictés cette semaine"),
                               (str(s["wpm"]) if s["wpm"] else "—", "mots par minute à l'oral"),
                               (str(s["saved_min"]), "minutes gagnées sur la frappe")):
            col = QWidget()
            v = QVBoxLayout(col)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)
            v.addWidget(label(value, "Figure"))
            v.addWidget(label(caption, "Small"))
            self.stats_lay.addWidget(col)
        self.stats_lay.addStretch(1)

        while self.recent_box.count():
            it = self.recent_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        items = self.app.history.items[:5]
        if not items:
            self.recent_box.addWidget(label("Tes dictées apparaîtront ici.", "Muted"))
            return
        panel = Panel()
        for item in items:
            panel.add(self._history_row(item, compact=True))
        self.recent_box.addWidget(panel)

    # ══ Models ═══════════════════════════════════════════════════════════════
    def _build_models(self):
        page, lay = _page("Modèles IA",
                          "Choisis qui transcrit ta voix, et si une IA doit remettre le texte au propre "
                          "avant de le coller. Les changements s'appliquent tout de suite.")

        # ── Transcription ──
        _section(lay, "Transcription")
        provider = self.cfg.get("stt.provider")
        seg = Segmented([(k, v["label"]) for k, v in STT_PROVIDERS.items()], provider)
        lay.addWidget(seg)
        hint = label(STT_PROVIDERS[provider]["hint"], "Small", wrap=True)
        lay.addWidget(hint)

        self.stt_stack = QStackedWidget()
        self.stt_stack.addWidget(self._local_models_panel())
        self._stt_api_widgets = {}
        for name in ("groq", "openai", "custom"):
            self.stt_stack.addWidget(self._stt_api_panel(name))
        lay.addWidget(self.stt_stack)
        order = ["local", "groq", "openai", "custom"]
        self.stt_stack.setCurrentIndex(order.index(provider))

        def on_provider(key):
            self.cfg.set("stt.provider", key)
            hint.setText(STT_PROVIDERS[key]["hint"])
            self.stt_stack.setCurrentIndex(order.index(key))
        seg.changed.connect(on_provider)

        # ── Vocabulary ──
        _section(lay, "Vocabulaire",
                 "Noms propres, jargon, termes techniques : la transcription respectera leur orthographe. "
                 "Sépare-les par des virgules.")
        vocab = QPlainTextEdit(self.cfg.get("vocabulary"))
        vocab.setPlaceholderText("Spring Boot, Kubernetes, JVM, Voiron, ἀγάπη…")
        vocab.setFixedHeight(76)
        vocab.textChanged.connect(lambda: self.cfg.set("vocabulary", vocab.toPlainText()))
        lay.addWidget(vocab)

        # ── Clean-up ──
        _section(lay, "Mise en forme IA",
                 "Après la transcription, un modèle de langage corrige la ponctuation, retire les "
                 "« euh » et les répétitions. Ajoute une à quelques secondes.")
        lay.addWidget(self._llm_panel())
        lay.addStretch(1)
        return page

    def _local_models_panel(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(12)
        grid = QGridLayout()
        grid.setSpacing(12)
        self.tiles = {}
        current = self.cfg.get("stt.local_model") if not self.cfg.get("stt.custom_local_model") else None
        for i, m in enumerate(LOCAL_MODELS):
            tile = ModelTile(m)
            tile.setChecked(m["id"] == current)
            tile.clicked.connect(lambda _=False, mid=m["id"]: self._pick_local(mid))
            grid.addWidget(tile, i // 2, i % 2)
            self.tiles[m["id"]] = tile
        v.addLayout(grid)

        panel = Panel()
        device = _combo([("cpu", "Processeur (CPU)"), ("cuda", "Carte NVIDIA (CUDA)"), ("auto", "Automatique")],
                        self.cfg.get("stt.device"))
        device.currentIndexChanged.connect(lambda: self.cfg.set("stt.device", device.currentData()))
        panel.add_row("Calcul", "Les cartes AMD ne sont pas prises en charge par faster-whisper : "
                                "garde le CPU.", device)
        custom = QLineEdit(self.cfg.get("stt.custom_local_model"))
        custom.setPlaceholderText("ex. bofenghuang/whisper-large-v3-french-distil-dec16")
        custom.setMinimumWidth(320)

        def apply_custom():
            self.cfg.set("stt.custom_local_model", custom.text().strip())
            self._refresh_tiles()
        custom.editingFinished.connect(apply_custom)
        panel.add_row("Autre modèle", "Identifiant Hugging Face (format CTranslate2) ou dossier local. "
                                      "Prend le pas sur la sélection ci-dessus.", custom, stacked=True)
        self.custom_model_edit = custom
        v.addWidget(panel)
        return w

    def _pick_local(self, mid: str):
        self.custom_model_edit.clear()
        self.cfg.set("stt.custom_local_model", "")
        self.cfg.set("stt.local_model", mid)
        self._refresh_tiles()

    def _refresh_tiles(self):
        if not getattr(self, "tiles", None):
            return
        kind, _ = self.app.status
        active = self.cfg.local_model_id() if self.cfg.get("stt.provider") == "local" else None
        for mid, tile in self.tiles.items():
            try:
                tile.setChecked(mid == active)
                tile.status = ("loading" if kind in ("loading", "downloading") else "active") \
                    if mid == active and kind != "error" else ""
                tile.update()
            except RuntimeError:  # tile deleted during a rebuild
                return

    def _check_downloads(self):
        def scan():
            return {m["id"]: LocalWhisper.is_downloaded(m["id"]) for m in LOCAL_MODELS}

        def done(res):
            if isinstance(res, Exception) or not getattr(self, "tiles", None):
                return
            for mid, ok in res.items():
                try:
                    self.tiles[mid].downloaded = ok
                    self.tiles[mid].update()
                except (KeyError, RuntimeError):
                    pass
        run_async(scan, done)

    def _key_field(self, path: str, key_url: str | None):
        edit = QLineEdit(self.cfg.get(path))
        edit.setEchoMode(QLineEdit.Password)
        edit.setPlaceholderText("Colle ta clé ici")
        edit.setMinimumWidth(260)
        edit.textChanged.connect(lambda txt: self.cfg.set(path, txt.strip()))
        show = QPushButton("Afficher")
        show.setObjectName("Ghost")
        show.setCheckable(True)
        show.toggled.connect(lambda on: (edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password),
                                         show.setText("Masquer" if on else "Afficher")))
        parts = [edit, show]
        if key_url:
            get = QPushButton("Obtenir une clé")
            get.setObjectName("Ghost")
            get.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(key_url)))
            parts.append(get)
        return hbox(*parts, spacing=4)

    def _model_field(self, path: str, suggestions: list[str], base_url_fn, key_fn):
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems(suggestions)
        combo.setEditText(self.cfg.get(path) or "")
        combo.setMinimumWidth(260)
        combo.currentTextChanged.connect(lambda txt: self.cfg.set(path, txt.strip()))
        fetch = QPushButton("Lister")
        fetch.setToolTip("Récupérer les modèles disponibles sur le serveur")
        status = label("", "Small")

        def do_fetch():
            fetch.setEnabled(False)
            status.setText("Recherche…")

            def done(res):
                fetch.setEnabled(True)
                if isinstance(res, Exception):
                    status.setText(str(res))
                    status.setObjectName("Bad")
                else:
                    current = combo.currentText()
                    combo.blockSignals(True)
                    combo.clear()
                    combo.addItems(res)
                    combo.setEditText(current)
                    combo.blockSignals(False)
                    status.setText(f"{len(res)} modèles trouvés")
                    status.setObjectName("Small")
                status.style().unpolish(status)
                status.style().polish(status)
            run_async(lambda: list_remote_models(base_url_fn(), key_fn()), done)
        fetch.clicked.connect(do_fetch)
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        v.addWidget(hbox(combo, fetch, spacing=6))
        v.addWidget(status, 0, Qt.AlignRight)
        return box

    def _stt_api_panel(self, name: str):
        preset = STT_PROVIDERS[name]
        base = f"stt.providers.{name}"
        panel = Panel()
        if name == "custom":
            url = QLineEdit(self.cfg.get(f"{base}.base_url"))
            url.setMinimumWidth(300)
            url.textChanged.connect(lambda t: self.cfg.set(f"{base}.base_url", t.strip()))
            panel.add_row("Adresse du serveur", "Doit exposer /audio/transcriptions.", url)
        panel.add_row("Clé API", "Stockée uniquement sur ce PC, dans data/settings.json.",
                      self._key_field(f"{base}.key", preset.get("key_url")))
        panel.add_row("Modèle", "", self._model_field(
            f"{base}.model", preset.get("models", []),
            lambda: self.cfg.stt_api_settings()["base_url"] if self.cfg.get("stt.provider") == name
            else (self.cfg.get(f"{base}.base_url") or preset["base_url"]),
            lambda: self.cfg.get(f"{base}.key")))
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 8, 0, 0)
        v.addWidget(panel)
        return w

    def _llm_panel(self):
        panel = Panel()
        enabled = Toggle(self.cfg.get("llm.enabled"))
        panel.add_row("Activer la mise en forme", "Si le modèle ne répond pas, le texte brut est collé.", enabled)

        provider = _combo([(k, v["label"]) for k, v in LLM_PROVIDERS.items()], self.cfg.get("llm.provider"))
        panel.add_row("Fournisseur", "llama.cpp et Ollama tournent sur ton PC ; les autres passent par une API.",
                      provider)

        details = QWidget()
        dlay = QVBoxLayout(details)
        dlay.setContentsMargins(0, 0, 0, 0)
        dlay.setSpacing(0)
        subs = {}
        for name, preset in LLM_PROVIDERS.items():
            base = f"llm.providers.{name}"
            sub = Panel()
            sub.setObjectName("")  # flat inside the parent panel
            url = QLineEdit(self.cfg.get(f"{base}.base_url") or preset["base_url"])
            url.setMinimumWidth(300)
            url.textChanged.connect(lambda t, b=base: self.cfg.set(f"{b}.base_url", t.strip()))
            sub.add_row("Adresse", "", url)
            if preset.get("needs_key"):
                sub.add_row("Clé API", "Stockée uniquement sur ce PC.",
                            self._key_field(f"{base}.key", preset.get("key_url")))
            sub.add_row("Modèle", "Pour llama.cpp, laisse vide : le modèle chargé par llama-server est utilisé."
                        if name == "llamacpp" else "",
                        self._model_field(f"{base}.model", preset["models"],
                                          lambda b=base: self.cfg.get(f"{b}.base_url"),
                                          lambda b=base: self.cfg.get(f"{b}.key")))
            dlay.addWidget(sub)
            subs[name] = sub
        panel.add(details)

        def show_sub():
            for n, sub in subs.items():
                sub.setVisible(n == self.cfg.get("llm.provider"))

        def on_provider():
            self.cfg.set("llm.provider", provider.currentData())
            show_sub()
        provider.currentIndexChanged.connect(on_provider)
        show_sub()

        prompt = QPlainTextEdit(self.cfg.get("llm.prompt"))
        prompt.setFixedHeight(150)
        prompt.textChanged.connect(lambda: self.cfg.set("llm.prompt", prompt.toPlainText()))
        reset = QPushButton("Rétablir")
        reset.setObjectName("Ghost")
        reset.clicked.connect(lambda: prompt.setPlainText(DEFAULT_CLEANUP_PROMPT))
        prow = panel.add_row("Consignes", "Ce que l'IA doit faire du texte. Tu peux par exemple lui demander "
                                          "d'écrire en Markdown ou de tutoyer.", prompt, stacked=True)
        prow.layout().addWidget(reset, 0, Qt.AlignRight)

        sample = QLineEdit("euh donc en fait je voulais dire que euh le build passe pas non plutôt les tests passent pas")
        try_btn = QPushButton("Essayer")
        result = label("", "Muted", wrap=True)
        result.setTextInteractionFlags(Qt.TextSelectableByMouse)

        def run_try():
            try_btn.setEnabled(False)
            result.setText("Mise en forme…")

            def done(res):
                try_btn.setEnabled(True)
                result.setText(f"Erreur : {res}" if isinstance(res, Exception) else res)
            run_async(lambda: self.app.engine.cleanup(sample.text()), done)
        try_btn.clicked.connect(run_try)
        trow = panel.add_row("Essai", "Écris une phrase comme tu la dirais, et vois ce que l'IA en fait.",
                             hbox(sample, try_btn, spacing=6), stacked=True)
        trow.layout().addWidget(result)

        def on_enabled(on):
            self.cfg.set("llm.enabled", on)
            for w in (provider, details, prompt, sample, try_btn):
                w.setEnabled(on)
        enabled.toggled.connect(on_enabled)
        on_enabled(enabled.isChecked())
        return panel

    # ══ Shortcuts ════════════════════════════════════════════════════════════
    def _build_shortcuts(self):
        page, lay = _page("Raccourcis",
                          "Un raccourci par langue. Forcer la langue rend Whisper plus rapide et plus fiable "
                          "que la détection automatique.")
        if not hotkeys.available():
            lay.addWidget(label("Les raccourcis globaux ne sont pas disponibles sur ce système.", "Bad", wrap=True))

        _section(lay, "Comportement")
        mode = Segmented([("toggle", "Appuyer pour démarrer et arrêter"), ("hold", "Maintenir pour parler")],
                         self.cfg.get("mode"))
        mode.changed.connect(lambda k: self.cfg.set("mode", k))
        lay.addWidget(mode)

        _section(lay, "Dicter")
        panel = Panel()
        shortcuts = self.cfg.get("shortcuts")
        for i, sc in enumerate(shortcuts):
            panel.add(self._shortcut_row(i, sc, len(shortcuts) > 1))
        lay.addWidget(panel)
        add = QPushButton("Ajouter un raccourci")
        add.clicked.connect(self._add_shortcut)
        lay.addWidget(add, 0, Qt.AlignLeft)

        _section(lay, "Annuler")
        panel2 = Panel()
        caps = Keycaps(self.cfg.get("cancel_hotkey"))
        change = QPushButton("Modifier")
        change.clicked.connect(lambda: self._capture(change, caps, lambda hk: self.cfg.set("cancel_hotkey", hk)))
        panel2.add_row("Annuler la dictée en cours", "Le texte n'est ni transcrit ni collé.",
                       hbox(caps, change, spacing=12))
        lay.addWidget(panel2)
        lay.addStretch(1)
        return page

    def _shortcut_row(self, i: int, sc: dict, removable: bool):
        caps = Keycaps(sc["hotkey"])
        lang = _combo(LANGUAGES, sc["language"])
        lang.setMinimumWidth(160)
        change = QPushButton("Modifier")
        remove = QPushButton("Supprimer")
        remove.setObjectName("Ghost")
        remove.setVisible(removable)

        def update(field, value):
            items = self.cfg.get("shortcuts")
            items[i][field] = value
            self.cfg.set("shortcuts", items)
        lang.currentIndexChanged.connect(lambda: update("language", lang.currentData()))
        change.clicked.connect(lambda: self._capture(change, caps, lambda hk: update("hotkey", hk)))

        def do_remove():
            items = self.cfg.get("shortcuts")
            items.pop(i)
            self.cfg.set("shortcuts", items)
            self._rebuild_pages()
        remove.clicked.connect(do_remove)

        row = QWidget()
        row.setObjectName("Row")
        h = QHBoxLayout(row)
        h.setContentsMargins(16, 12, 16, 12)
        h.setSpacing(12)
        h.addWidget(caps)
        h.addStretch(1)
        h.addWidget(lang)
        h.addWidget(change)
        h.addWidget(remove)
        return row

    def _add_shortcut(self):
        items = self.cfg.get("shortcuts")
        items.append({"hotkey": "", "language": "auto"})
        self.cfg.set("shortcuts", items)
        self._rebuild_pages()

    def _capture(self, button: QPushButton, caps: Keycaps, on_value):
        button.setText("Appuie sur les touches…")
        button.setEnabled(False)

        def done(combo):
            button.setText("Modifier")
            button.setEnabled(True)
            if combo:
                caps.set_hotkey(combo)
                on_value(combo)

        self.app.hotkeys.capture(lambda combo: run_async(lambda: combo, done))

    def _refresh_home_later(self):
        QTimer.singleShot(0, lambda: self._replace_page("home", self._build_home))

    def _replace_page(self, key, builder):
        old = self.pages[key]
        idx = self.stack.indexOf(old)
        new = builder()
        self.stack.insertWidget(idx, new)
        self.pages[key] = new
        if self.stack.currentWidget() is old:
            self.stack.setCurrentWidget(new)
        self.stack.removeWidget(old)
        old.deleteLater()

    # ══ Preferences ══════════════════════════════════════════════════════════
    def _build_prefs(self):
        page, lay = _page("Préférences")

        _section(lay, "Micro et collage")
        panel = Panel()
        mics = [("", "Micro par défaut de Windows")] + [(m, m) for m in audio.list_microphones()]
        mic = _combo(mics, self.cfg.get("microphone"))
        mic.setMinimumWidth(280)
        mic.currentIndexChanged.connect(lambda: self.cfg.set("microphone", mic.currentData()))
        panel.add_row("Micro", "", mic)
        self._toggle_row(panel, "auto_paste", "Coller automatiquement",
                         "Sinon le texte est seulement copié dans le presse-papiers.")
        self._toggle_row(panel, "restore_clipboard", "Restaurer le presse-papiers",
                         "Après le collage, remet ce que tu avais copié avant la dictée.")
        dur = QSpinBox()
        dur.setRange(10, 900)
        dur.setSuffix(" s")
        dur.setValue(self.cfg.get("max_record"))
        dur.setMinimumWidth(100)
        dur.valueChanged.connect(lambda v: self.cfg.set("max_record", v))
        panel.add_row("Durée maximale", "La dictée s'arrête seule au-delà.", dur)
        lay.addWidget(panel)

        _section(lay, "Apparence")
        panel = Panel()
        self._toggle_row(panel, "idle_pill", "Barre visible au repos",
                         "Une fine barre reste en bas de l'écran ; clique dessus pour dicter.")
        self._toggle_row(panel, "sounds", "Sons", "Un petit son au début et à la fin de la dictée.")
        pos = _combo([("bottom-center", "En bas, au centre"), ("bottom-right", "En bas, à droite"),
                      ("top-center", "En haut, au centre")], self.cfg.get("position"))
        pos.currentIndexChanged.connect(lambda: self.cfg.set("position", pos.currentData()))
        panel.add_row("Position de la barre", "", pos)
        th = _combo([("system", "Comme Windows"), ("light", "Clair"), ("dark", "Sombre")], self.cfg.get("theme"))
        th.currentIndexChanged.connect(lambda: self.cfg.set("theme", th.currentData()))
        panel.add_row("Thème de cette fenêtre", "", th)
        lay.addWidget(panel)

        _section(lay, "Système")
        panel = Panel()
        login = Toggle(winutil.launch_at_login_enabled())
        login.setEnabled(winutil.IS_WIN)
        login.toggled.connect(lambda on: winutil.set_launch_at_login(on))
        panel.add_row("Lancer au démarrage de Windows", "CodeWhisper démarre en arrière-plan, sans fenêtre.", login)
        folder = QPushButton("Ouvrir le dossier")
        folder.clicked.connect(lambda: winutil.open_folder(DATA_DIR))
        panel.add_row("Réglages, historique et journal", "Tout est rangé dans le dossier data de l'application.",
                      folder)
        lay.addWidget(panel)
        lay.addStretch(1)
        return page

    def _toggle_row(self, panel: Panel, key: str, title: str, desc: str):
        tg = Toggle(self.cfg.get(key))
        tg.toggled.connect(lambda on: self.cfg.set(key, on))
        panel.add_row(title, desc, tg)
        return tg

    # ══ History ══════════════════════════════════════════════════════════════
    def _build_history(self):
        page, lay = _page("Historique", "Tout ce que tu as dicté, du plus récent au plus ancien.")
        search = QLineEdit()
        search.setPlaceholderText("Rechercher dans tes dictées")
        clear = QPushButton("Tout effacer")
        clear.setObjectName("Danger")

        def do_clear():
            if clear.text() == "Tout effacer":
                clear.setText("Confirmer l'effacement")
                QTimer.singleShot(3000, lambda: clear.setText("Tout effacer"))
                return
            self.app.history.clear()
            self.app.history_changed.emit()
        clear.clicked.connect(do_clear)
        bar = QWidget()
        hb = QHBoxLayout(bar)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.addWidget(search, 1)
        hb.addWidget(clear)
        lay.addWidget(bar)
        lay.addSpacing(6)
        self.history_box = QVBoxLayout()
        self.history_box.setContentsMargins(0, 0, 0, 0)
        holder = QWidget()
        holder.setLayout(self.history_box)
        lay.addWidget(holder)
        lay.addStretch(1)
        self.history_search = search
        search.textChanged.connect(lambda _: self._fill_history())
        self._fill_history()
        return page

    def _fill_history(self):
        while self.history_box.count():
            it = self.history_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        q = self.history_search.text().strip().lower()
        items = [i for i in self.app.history.items if not q or q in i["text"].lower()][:200]
        if not items:
            self.history_box.addWidget(label(
                "Aucune dictée ne correspond." if q else
                "Rien pour l'instant. Appuie sur ton raccourci et parle : la transcription s'affichera ici.",
                "Muted", wrap=True))
            return
        panel = Panel()
        for item in items:
            panel.add(self._history_row(item))
        self.history_box.addWidget(panel)

    def _history_row(self, item: dict, compact=False):
        row = QWidget()
        row.setObjectName("Row")
        v = QVBoxLayout(row)
        v.setContentsMargins(16, 10, 10, 10)
        v.setSpacing(4)
        meta = f"{_when(item['ts'])}    {LANG_LABELS.get(item.get('language') or 'auto', '')}"
        if not compact and item.get("engine"):
            meta += f"    {item['engine']}"
        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(label(meta, "Small"), 1)
        top.addWidget(_copy_button(lambda: item["text"]))
        if not compact:
            if item.get("raw"):
                raw = QPushButton("Texte brut")
                raw.setObjectName("Ghost")
                raw.setToolTip(item["raw"])
                raw.clicked.connect(lambda: QGuiApplication.clipboard().setText(item["raw"]))
                top.addWidget(raw)
            delete = QPushButton("Supprimer")
            delete.setObjectName("Ghost")
            delete.clicked.connect(lambda: (self.app.history.delete(item["id"]), self.app.history_changed.emit()))
            top.addWidget(delete)
        v.addLayout(top)
        text = item["text"]
        if compact and len(text) > 220:
            text = text[:220] + "…"
        body = label(text, "", wrap=True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(body)
        return row

    def _refresh_history_views(self):
        if hasattr(self, "stats_lay"):
            self._fill_home()
        if hasattr(self, "history_box"):
            self._fill_history()

    # ── window behaviour ──────────────────────────────────────────────────────
    def closeEvent(self, e):
        # closing the window keeps the app running in the tray
        if getattr(self.app, "quitting", False):
            e.accept()
            return
        e.ignore()
        self.hide()

    def present(self, page: str | None = None):
        if page:
            self.show_page(page)
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()
