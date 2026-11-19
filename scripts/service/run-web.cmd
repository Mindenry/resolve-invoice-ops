@echo off
copy /Y "E:\Code\AI project\infrastructure\nginx\resolve-lan.conf" "C:\tools\nginx-1.31.8\conf\resolve-lan.conf" >nul
cd /d "C:\tools\nginx-1.31.8"
nginx.exe -p "C:/tools/nginx-1.31.8" -c "C:/tools/nginx-1.31.8/conf/resolve-lan.conf" -g "daemon off;"
