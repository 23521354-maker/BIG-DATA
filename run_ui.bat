@echo off
title VN30 Text-to-SQL UI
cd /d "%~dp0text2sql"
if not exist app.py (
  echo Khong thay text2sql\app.py - hay chuyen thu muc du an vao day truoc.
  pause
  exit /b 1
)
if "%OPENAI_BASE_URL%"=="" set OPENAI_BASE_URL=https://api.deepseek.com
if "%OPENAI_API_KEY%"=="" echo [Luu y] Chua co OPENAI_API_KEY - hay nhap key o o "API key" ben trai trang web.
echo Dang mo giao dien tai http://localhost:8501 ...
python -m streamlit run app.py
pause
