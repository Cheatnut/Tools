@echo off
set "__pdf2png_dir=%~dp0"
python "%__pdf2png_dir%pdf2png\pdf2png.py" %*
