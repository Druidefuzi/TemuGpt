@echo off
call "%~dp0env\Scripts\activate"
python "%~dp0server.py"
pause