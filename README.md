# CodeWhisper

Dictée vocale pour Windows. Appuie sur un raccourci, parle, appuie à nouveau : le texte est collé à l'endroit du curseur, dans n'importe quelle application.

Whisper tourne en local par défaut (gratuit, privé, hors ligne). Tu peux aussi passer en un clic sur Groq, OpenAI ou ton propre serveur, et ajouter une mise en forme du texte par IA (llama.cpp, Ollama, Groq, OpenAI, DeepSeek, Claude…).

---

## Installation

1. Double-clique sur `install.bat` (relance-le après une mise à jour : il installe les nouvelles dépendances).
2. Lance CodeWhisper avec le raccourci du Bureau ou `run.bat`.

Au premier lancement, la fenêtre CodeWhisper s'ouvre. Ensuite, l'application vit dans la zone de notification : clique sur son icône pour rouvrir la fenêtre. Relancer `run.bat` alors qu'elle tourne déjà ouvre simplement la fenêtre.

`run_debug.bat` lance la même chose avec une console visible, pratique en cas de souci.

---

## Utilisation

| Action | Résultat |
|--------|----------|
| `Ctrl + Espace` | Dicter en anglais |
| `Ctrl + Maj + Espace` | Dicter en français |
| Même raccourci à nouveau | Arrête, transcrit et colle |
| `Échap` | Annule la dictée en cours |
| Clic sur la barre en bas de l'écran | Démarre ou arrête une dictée |
| Clic droit sur la barre | Ouvre la fenêtre CodeWhisper |

Les raccourcis, les langues et le mode « maintenir pour parler » se règlent dans l'onglet **Raccourcis**.

---

## La fenêtre CodeWhisper

- **Accueil** : raccourcis actifs, statistiques (mots par semaine, vitesse, temps gagné), dernières dictées.
- **Modèles IA** :
  - *Transcription* : modèles Whisper locaux (Tiny → Large v3, Turbo recommandé), ou Groq / OpenAI / serveur compatible OpenAI. Le changement est immédiat, le nouveau modèle se charge en arrière-plan.
  - *Vocabulaire* : mots que Whisper doit bien orthographier (Spring Boot, JVM, noms propres…).
  - *Mise en forme IA* : un LLM nettoie la transcription (ponctuation, « euh », auto-corrections). Les consignes sont modifiables et il y a une zone d'essai.
- **Préférences** : micro, collage automatique, restauration du presse-papiers, sons, position de la barre, thème clair/sombre, lancement au démarrage de Windows.
- **Historique** : toutes les dictées, avec recherche, copie et texte brut avant mise en forme.

Le menu de l'icône de notification permet aussi de changer de modèle ou d'activer la mise en forme sans ouvrir la fenêtre.

---

## Où sont les données

Tout est dans le dossier `data/` de l'application : `settings.json` (réglages et clés API), `history.json` et `codewhisper.log`. Les clés API y sont en clair : ne partage pas ce dossier.

---

## Choisir un modèle local

| Modèle | Taille | Vitesse | Qualité | Remarque |
|--------|--------|---------|---------|----------|
| Tiny | 75 Mo | ★★★★★ | ★ | |
| Base | 145 Mo | ★★★★ | ★★ | |
| Small | 480 Mo | ★★★★ | ★★★ | |
| Medium | 1,5 Go | ★★ | ★★★★ | |
| Large v3 Turbo | 1,6 Go | ★★★ | ★★★★★ | Recommandé |
| Large v3 | 3 Go | ★ | ★★★★★ | |
| Distil Large v3 | 1,5 Go | ★★★★ | ★★★★ | Anglais seulement |

faster-whisper n'utilise le GPU qu'avec une carte NVIDIA (CUDA). Avec une carte AMD, reste sur le CPU ; pour aller plus vite, passe sur Groq (gratuit avec une limite quotidienne) ou sur un modèle plus léger.

---

## Technique

| Composant | Bibliothèque | Rôle |
|-----------|--------------|------|
| Interface | PySide6 (Qt) | Barre flottante translucide, fenêtre de réglages, icône de notification |
| Reconnaissance locale | faster-whisper | Whisper quantifié int8 sur CPU, filtre VAD |
| Reconnaissance cloud / mise en forme | requests | API compatibles OpenAI (`/audio/transcriptions`, `/chat/completions`, `/models`) |
| Audio | sounddevice | Capture micro + niveau en direct pour la forme d'onde |
| Raccourcis globaux | keyboard | Hook clavier Win32 |
| Collage | ctypes + `SendInput` | Ctrl+V simulé, fiable partout |

Code dans `codewhisper/` : `main.py` (contrôleur), `overlay.py` (barre flottante), `settings.py` (fenêtre), `engines.py` (moteurs IA), `config.py` (réglages et préréglages des fournisseurs). L'ancienne version est conservée dans `app_old.py`.
