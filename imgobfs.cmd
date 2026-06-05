@echo off
set "__imgobfs_dir=%~dp0"
python "%__imgobfs_dir%imgobfs\imgobfs.py" %*
