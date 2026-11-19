@echo off
set OLLAMA_HOST=0.0.0.0:11434
set OLLAMA_MODELS=%USERPROFILE%\.ollama\models
"%USERPROFILE%\AppData\Local\Programs\Ollama\ollama.exe" serve
