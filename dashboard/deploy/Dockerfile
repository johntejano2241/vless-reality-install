FROM php:8.4-fpm-bookworm AS app
RUN apt-get update && apt-get install -y --no-install-recommends libicu-dev libzip-dev libonig-dev libsqlite3-dev libxml2-dev unzip git \
    && docker-php-ext-install intl mbstring pdo_sqlite zip bcmath pcntl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=composer:2 /usr/bin/composer /usr/local/bin/composer
WORKDIR /app
COPY . /app
RUN mkdir -p storage/framework/cache/data storage/framework/sessions storage/framework/views storage/logs storage/app/private bootstrap/cache \
    && composer install --no-dev --no-interaction --prefer-dist --optimize-autoloader \
    && php artisan filament:assets \
    && chmod -R a=rX /app
ENV APP_ENV=production APP_DEBUG=false
CMD ["php-fpm", "-F"]

FROM nginxinc/nginx-unprivileged:stable-alpine AS web
COPY --from=app /app/public /app/public
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
