@echo off
rem Startet das Programm unter Windows. Beim ersten Mal wird alles installiert (einmal Internet).
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo Erster Start: Installiere, was das Programm braucht ...
    py -3 -m venv .venv || (echo Python 3 fehlt. Siehe README.md. & pause & exit /b 1)
    .venv\Scripts\pip install --quiet -r requirements.txt || (pause & exit /b 1)
    .venv\Scripts\pip install --quiet aubio || echo Hinweis: aubio fehlt, das Programm nimmt die eigene Beat-Erkennung.
)
.venv\Scripts\python start.py %*
pause
