# References: makefile-generator/docs/{patterns-guide,security-guide}.md
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DELETE_ON_ERROR:
.SUFFIXES:
.NOTPARALLEL:
MAKEFLAGS += --no-builtin-rules --warn-undefined-variables
.DEFAULT_GOAL := help

ENV ?= local
SERVICES ?= postgres mariadb redis minio
export ENV SERVICES

.PHONY: all help init check config network build pull up deploy ps logs stop down test
all: help
help: ## Tampilkan perintah dan pilihan environment
	@printf '%s\n' 'make TARGET ENV=local|staging|production SERVICES="postgres redis"' 'Default: local; layanan: postgres mariadb redis minio' 'Staging/production wajib server Docker terpisah.'
	@awk 'BEGIN {FS=":.*## "} /^[a-z-]+:.*## / {printf "  %-12s %s\n", $$1, $$2}' Makefile
init: ## Buat .env contoh tanpa menimpa file existing
	@python3 scripts/manage.py init
check: ## Preflight credential, storage dan Compose tanpa mencetak secret
	@python3 scripts/manage.py check
config: ## Validasi Compose secara quiet
	@python3 scripts/manage.py config
network: ## Buat shared-network jika belum ada
	@python3 scripts/manage.py network
build: ## Build image PostgreSQL jika dipilih
	@python3 scripts/manage.py build
pull: ## Tarik image layanan yang dipilih
	@python3 scripts/manage.py pull
up: ## Preflight lalu jalankan dan tunggu healthcheck
	@python3 scripts/manage.py up
deploy: ## Pull, build, lalu up; jalankan di host tujuan
	@python3 scripts/manage.py deploy
ps: ## Status layanan
	@python3 scripts/manage.py ps
logs: ## Tampilkan 100 baris log per layanan (dapat mengandung data aplikasi)
	@python3 scripts/manage.py logs
stop: ## Hentikan container tanpa menghapusnya
	@python3 scripts/manage.py stop
down: ## Hapus container; volume dan external network dipertahankan
	@python3 scripts/manage.py down
test: ## Jalankan tes preflight dan kontrak Compose
	@python3 -m unittest discover -s tests -v
	@python3 -m unittest discover -s minio -p 'test_*.py' -v
