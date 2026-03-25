@echo off
echo ================================
echo    TemuGPT - Server starten
echo ================================
echo.

echo Aktiviere virtuelle Umgebung...
call .\env\Scripts\activate

echo Starte Python Server...
start "TemuGPT - Python" cmd /k "call .\env\Scripts\activate && python server.py"

echo Starte Node Server...
start "TemuGPT - Node" cmd /k "node index.js"

echo.
echo ================================
echo    Beide Server laufen!
echo ================================
timeout /t 3
