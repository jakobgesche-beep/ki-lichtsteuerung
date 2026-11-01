#!/bin/sh
# Startet das Programm auf dem Mac oder unter Linux (Doppelklick oder im Terminal).
# Beim ersten Mal wird alles Nötige installiert, dafür braucht es einmal Internet.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
    echo "Erster Start: Installiere, was das Programm braucht ..."
    python3 -m venv .venv || { echo "Python 3 fehlt. Siehe README.md."; exit 1; }
    .venv/bin/pip install --quiet -r requirements.txt || exit 1
    # aubio ist die bessere Beat-Erkennung. Klappt es nicht, springt die eigene ein.
    CFLAGS="-Wno-incompatible-function-pointer-types" .venv/bin/pip install --quiet aubio \
        || echo "Hinweis: aubio ließ sich nicht installieren, das Programm nimmt die eigene Beat-Erkennung."
fi
exec .venv/bin/python start.py "$@"
