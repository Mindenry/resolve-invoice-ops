@echo off
if "%NGINX_HOME%"=="" set "NGINX_HOME=C:\nginx"
set "REPO=%~dp0..\.."
copy /Y "%REPO%\infrastructure\nginx\resolve-lan.conf" "%NGINX_HOME%\conf\resolve-lan.conf" >nul
pushd "%NGINX_HOME%"
nginx.exe -p "%NGINX_HOME%" -c "%NGINX_HOME%/conf/resolve-lan.conf" -g "daemon off;"
