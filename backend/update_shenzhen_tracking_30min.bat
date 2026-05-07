@echo off
cd /d "%~dp0"
docker-compose exec -T web python manage.py update_shenzhen_tracking --shop=kidstoylover.myshopify.com
exit /b %errorlevel%
