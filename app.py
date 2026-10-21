#!/usr/bin/env python3
"""
CodeWhisper — dictée vocale pour Windows.

Appuie sur un raccourci (Ctrl+Espace par défaut), parle, appuie à nouveau :
le texte est transcrit puis collé à l'endroit du curseur.
Tous les réglages se font dans la fenêtre CodeWhisper (icône dans la barre des tâches).
"""

import sys

from codewhisper.main import main

if __name__ == "__main__":
    sys.exit(main())
