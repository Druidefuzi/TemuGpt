@echo off
echo ================================
echo    TemuGPT - Setup
echo ================================
echo.

echo [1/3] Erstelle virtuelle Umgebung...
python -m venv env
if errorlevel 1 (
    echo FEHLER: Python nicht gefunden! Bitte Python installieren.
    pause
    exit /b 1
)

echo [2/3] Aktiviere venv und installiere Python-Pakete...
call .\env\Scripts\activate
pip install -r requirements.txt
if errorlevel 1 (
    echo FEHLER: pip install fehlgeschlagen!
    pause
    exit /b 1
)

echo [3/3] Installiere Node-Pakete...
npm install
if errorlevel 1 (
    echo FEHLER: npm install fehlgeschlagen! Bitte Node.js installieren.
    pause
    exit /b 1
)

echo.
echo ================================
echo    Setup abgeschlossen!
echo    Starte jetzt start.bat
echo ================================
pause
