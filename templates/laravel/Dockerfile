# syntax=docker/dockerfile:1
# All four arguments MUST be supplied as approved name:version@sha256:digest.
# PHP_IMAGE must already contain the extensions required by composer.lock.
ARG PHP_IMAGE
ARG COMPOSER_IMAGE
ARG NODE_IMAGE
ARG NGINX_IMAGE
FROM ${COMPOSER_IMAGE} AS composer-tool
FROM ${NODE_IMAGE} AS assets
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM ${PHP_IMAGE} AS dependencies
WORKDIR /var/www/html
COPY --from=composer-tool /usr/bin/composer /usr/local/bin/composer
COPY composer.json composer.lock ./
RUN composer install --no-dev --no-scripts --no-autoloader --prefer-dist --no-interaction
COPY . .
COPY --from=assets /build/public/build ./public/build
RUN composer dump-autoload --no-dev --classmap-authoritative --no-scripts \
    && composer check-platform-reqs --no-dev

FROM ${PHP_IMAGE} AS php
WORKDIR /var/www/html
COPY --from=dependencies --chown=1000:1000 /var/www/html ./
COPY docker/php-fpm.conf /usr/local/etc/php-fpm.d/zz-app.conf
COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/app-entrypoint
RUN mkdir -p storage/app/public storage/framework/cache/data storage/framework/sessions \
    storage/framework/views storage/logs bootstrap/cache \
    && chown -R 1000:1000 storage bootstrap/cache \
    && chmod -R u=rwX,g=rX,o= storage bootstrap/cache
USER 1000:1000
ENTRYPOINT ["/usr/local/bin/app-entrypoint"]
CMD ["php-fpm", "-F"]

FROM ${NGINX_IMAGE} AS web
COPY --from=dependencies /var/www/html/public /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/nginx.conf
# This target uses the official nginx image's existing nginx identity.
USER 101:101
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
